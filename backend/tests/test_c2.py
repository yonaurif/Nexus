"""Fase C2 (Doc 02 §6–8, §11, §17.2): Planner, Executor, Verifier, presupuestos y replanificación."""
import json
import time

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from nexus.contracts import Evidence, PlanStep, ToolManifest, ToolResult
from nexus.core import planner, task_store
from nexus.core.executor import execute
from nexus.core.plan_validator import PlanRejected, validate_plan
from nexus.core.verifier import verify
from nexus.gateway.internal_tools import ADAPTERS
from nexus.gateway.registry import SqlToolRegistry, ToolRegistry

from tests.test_c0_g0 import MANIFEST, make_plan, tool_step

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
NOW = "2026-11-15T12:00:00+00:00"


def ok(sid, evidence=True):
    return ToolResult(invocation_id=sid, status="succeeded", data={}, duration_ms=1, correlation_id="c",
                      evidence=[Evidence(source_ref="x", retrieved_at=NOW)] if evidence else [])


def failed(sid, code="TIMEOUT"):
    return ToolResult(invocation_id=sid, status="failed", error={"code": code}, duration_ms=1,
                      correlation_id="c")


# --- Verifier (Doc 02 §7.2–7.3): nunca éxito sin evidencia ---
def test_verifier_states():
    plan = make_plan([tool_step("a"), tool_step("b")])
    assert verify(plan, {"a": ok("a"), "b": ok("b")}).status == "completed"
    v = verify(plan, {"a": ok("a"), "b": failed("b")})
    assert v.status == "partial" and "b:TIMEOUT" in v.warnings and v.retriable
    assert verify(plan, {"a": failed("a", "INPUT_INVALID"), "b": failed("b", "INPUT_INVALID")}).status == "failed"
    assert not verify(plan, {"a": failed("a", "INPUT_INVALID"), "b": ok("b")}).retriable
    v = verify(plan, {"a": ok("a"), "b": ok("b", evidence=False)})
    assert v.status == "partial" and "b:NO_EVIDENCE" in v.warnings


def test_verifier_synthesis_only_plan_is_completed():
    assert verify(planner.synthesis_plan("t", "g", 1), {}).status == "completed"


# --- Validator: techo global y riesgo (Doc 02 §11, Doc 05 §6.2) ---
def reg_with(**over):
    reg = ToolRegistry()
    reg.register(ToolManifest(**{**MANIFEST, **over}))
    reg.approve(MANIFEST["tool_id"])
    return reg


def test_validator_enforces_global_ceiling():
    plan = make_plan([tool_step("a")]).model_copy(update={"limits": {"max_steps": 50, "max_duration_s": 60}})
    plan = plan.model_validate(plan.model_dump())
    with pytest.raises(PlanRejected, match="ceiling"):
        validate_plan(plan, reg_with())


def test_validator_blocks_non_read_tools_until_approvals_exist():
    with pytest.raises(PlanRejected, match="APPROVAL_REQUIRED"):
        validate_plan(make_plan([tool_step("a")]), reg_with(risk_level="write_external"))


# --- Planner (Doc 02 §6): el modelo propone; el sistema fija límites e IDs ---
class ScriptedModel:
    name, configured = "scripted", True

    def __init__(self, plans, answer="Son las 12:00 UTC."):
        self.plans, self.answer, self.calls = list(plans), answer, []

    def generate(self, messages):
        self.calls.append(messages)
        if "Planner de NEXUS" in messages[0]["content"]:
            return self.plans.pop(0)
        return self.answer

    def health(self):
        return "ok"


def steps_json(*steps, **extra):
    return "```json\n" + json.dumps({"summary_for_user": "Consultar la hora.", "steps": list(steps),
                                     **extra}) + "\n```"


TIME_STEP = {"step_id": "s1", "kind": "tool_call", "tool_id": "system.time.now", "depends_on": [],
             "input": {}, "success_criteria": ["Se devuelve la hora"]}


def test_planner_parses_fenced_json_and_sets_limits():
    plan = planner.propose(ScriptedModel([steps_json(TIME_STEP)]), "task_x", "¿hora?", [], 1)
    assert plan.task_id == "task_x" and plan.steps[0].tool_id == "system.time.now"
    assert plan.limits.max_steps == planner.DEFAULT_LIMITS["max_steps"]


@pytest.mark.parametrize("raw", ["no es json", steps_json(TIME_STEP, limits={"max_steps": 99})])
def test_planner_rejects_unparseable_or_self_set_limits(raw):
    with pytest.raises(PlanRejected, match="PLAN_UNPARSEABLE"):
        planner.propose(ScriptedModel([raw]), "t", "m", [], 1)


def test_planner_empty_steps_means_synthesis():
    plan = planner.propose(ScriptedModel([steps_json()]), "t", "m", [], 1)
    assert [s.kind for s in plan.steps] == ["synthesis"]


# --- Executor (Doc 02 §8, §11; Doc 05 §10) ---
def tool(tid, **over):
    base = dict(tool_id=tid, connector_id="test_c2", version="1", description=tid,
                input_schema={"type": "object"}, output_schema={"type": "object", "required": ["v"]},
                risk_level="read", required_scopes=[])
    return ToolManifest(**{**base, **over})


def fake_adapter(tool_id, args):
    if tool_id == "test.c2.slow":
        time.sleep(1)
    if tool_id == "test.c2.boom":
        raise ConnectionError("caído")
    if tool_id == "test.c2.big":
        return {"data": {"v": "x" * 500}, "evidence": []}
    if tool_id == "test.c2.badout":
        return {"data": {"otro": 1}, "evidence": []}
    return {"data": {"v": args.get("n", 0)}, "evidence": [{"source_ref": f"test:{tool_id}", "retrieved_at": NOW}]}


@pytest.fixture
def c2_tools(engine):
    with engine.begin() as c:
        reg = SqlToolRegistry(c)
        for m in [tool("test.c2.ok"), tool("test.c2.slow", timeout_ms=100), tool("test.c2.boom"),
                  tool("test.c2.big", max_response_bytes=50), tool("test.c2.badout"), tool("test.c2.unapproved")]:
            reg.register(m)
            if m.tool_id != "test.c2.unapproved":
                reg.approve(m.tool_id)
        tid = task_store.create_task(c, owner_id="test", goal="c2", correlation_id="corr_c2")
    return tid


def step(sid, tid, deps=(), **inp):
    return PlanStep(step_id=sid, kind="tool_call", tool_id=tid, depends_on=list(deps), input=inp,
                    success_criteria=["ok"])


def run_plan(engine, task_id, steps):
    plan = make_plan(steps).model_copy(update={"task_id": task_id, "plan_id": f"plan_{task_id}_{len(steps)}"})
    planner.save_plan(engine, plan)
    return execute(engine, {"test_c2": fake_adapter}, plan, "corr_c2")


def test_executor_normalizes_every_outcome(engine, c2_tools):
    r = run_plan(engine, c2_tools, [
        step("ok", "test.c2.ok", n=7), step("slow", "test.c2.slow"), step("boom", "test.c2.boom"),
        step("big", "test.c2.big"), step("badout", "test.c2.badout"), step("unapproved", "test.c2.unapproved"),
        step("child", "test.c2.ok", deps=["boom"]),
    ])
    assert r["ok"].status == "succeeded" and r["ok"].data == {"v": 7} and r["ok"].evidence
    codes = {k: v.error["code"] for k, v in r.items() if v.status == "failed"}
    assert codes == {"slow": "TIMEOUT", "boom": "CONNECTOR_UNAVAILABLE", "big": "RESPONSE_TOO_LARGE",
                     "badout": "OUTPUT_INVALID", "unapproved": "TOOL_NOT_ALLOWED", "child": "DEPENDENCY_FAILED"}


def test_executor_records_executions_without_raw_arguments(engine, c2_tools):
    run_plan(engine, c2_tools, [step("ok", "test.c2.ok", n=12345)])
    with engine.connect() as c:
        rows = c.execute(sa.text("SELECT arguments_hash, status, step_id FROM tool_executions WHERE task_id=:t"),
                         {"t": c2_tools}).all()
        step_status = c.scalar(sa.text("SELECT status FROM plan_steps WHERE plan_id=:p AND step_id='ok'"),
                               {"p": f"plan_{c2_tools}_1"})
    assert rows[0].status == "succeeded" and rows[0].arguments_hash.startswith("sha256:")
    assert "12345" not in rows[0].arguments_hash and step_status == "succeeded"


def test_internal_time_tool_returns_evidence():
    out = ADAPTERS["internal"]("system.time.now", {})
    assert out["data"]["utc_iso"].endswith("+00:00") and out["evidence"][0]["source_ref"] == "internal:system_clock"


# --- Flujo completo por la API (Doc 02 §17.2) ---
@pytest.fixture
def api(engine):
    from nexus.api.app import create_app

    def make(model, adapters=None):
        return TestClient(create_app(engine=engine, model=model, api_token=TOKEN, adapters=adapters))
    return make


def ask(client, text):
    tid = client.post("/api/v1/chat/messages", json={"message": text}, headers=AUTH).json()["task_id"]
    return tid, client.get(f"/api/v1/tasks/{tid}", headers=AUTH).json()


def test_e2e_tool_plan_completes_with_sources(api):
    model = ScriptedModel([steps_json(TIME_STEP)])
    tid, t = ask(api(model), "¿qué hora es?")
    assert t["status"] == "completed", t
    assert t["response"]["text"] == "Son las 12:00 UTC."
    assert t["response"]["sources"][0]["source_ref"] == "internal:system_clock"
    synthesis_ctx = json.dumps(model.calls[-1], ensure_ascii=False)
    assert "DATOS NO CONFIABLES" in synthesis_ctx and "utc_iso" in synthesis_ctx


def test_e2e_unknown_tool_is_rejected_but_answered(api):
    bad = {**TIME_STEP, "tool_id": "shell.run"}
    tid, t = ask(api(ScriptedModel([steps_json(bad)])), "¿qué hora es?")
    assert t["status"] == "partial"
    assert any(w.startswith("PLAN_REJECTED:TOOL_NOT_ALLOWED") for w in t["response"]["warnings"])


def test_e2e_replans_once_after_retriable_failure(api, engine):
    calls = {"n": 0}

    def flaky(tool_id, args):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("transitorio")
        return ADAPTERS["internal"](tool_id, args)

    model = ScriptedModel([steps_json(TIME_STEP), steps_json(TIME_STEP)])
    client = api(model, adapters={"internal": flaky})
    tid, t = ask(client, "¿qué hora es?")
    assert t["status"] == "completed" and calls["n"] == 2
    events = client.get(f"/api/v1/tasks/{tid}/events", headers=AUTH).text
    payloads = [json.loads(l[6:])["payload"] for l in events.splitlines() if l.startswith("data: ")]
    assert {"from": "verifying", "to": "planning"} in payloads
    with engine.connect() as c:
        assert c.scalar(sa.text("SELECT count(*) FROM plans WHERE task_id=:t"), {"t": tid}) == 2
    assert "CONNECTOR_UNAVAILABLE" in json.dumps(model.calls[1], ensure_ascii=False)  # el Planner recibe el fallo
