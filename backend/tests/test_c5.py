"""Fase C5 (Doc 02 §11, §18; Doc 05 §6.2, §11): aprobaciones ligadas a parámetros exactos,
caducidad, consumo único, cancelación cooperativa. Patrón proponer -> confirmar -> re-validar
tomado de Primitivo gala/actions.py, endurecido (argumentos en servidor + hash)."""
import json
import uuid

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from nexus.contracts import ToolManifest
from nexus.core import approvals
from nexus.core.plan_validator import PlanRejected, validate_plan
from nexus.gateway.registry import ToolRegistry

from tests.test_c0_g0 import make_plan, tool_step

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def manifest(risk, **over):
    return ToolManifest(**{"tool_id": "example.repository.get", "connector_id": "x", "version": "1",
                           "description": "d", "input_schema": {"type": "object", "required": ["repository_ref"]},
                           "output_schema": {}, "risk_level": risk, "required_scopes": [], **over})


def reg(m):
    r = ToolRegistry()
    r.register(m)
    r.approve(m.tool_id)
    return r


# --- Política (Doc 05 §6.2) ---
def test_risk_policy():
    assert not approvals.needs_approval(manifest("read"))
    assert approvals.needs_approval(manifest("read", requires_approval=True))
    for risk in ("write_reversible", "write_external", "destructive"):
        assert approvals.needs_approval(manifest(risk))
        validate_plan(make_plan([tool_step("a", tool="example.repository.get")]), reg(manifest(risk)))
    with pytest.raises(PlanRejected, match="POLICY_DENIED"):  # admin: nunca para el Core/agentes
        validate_plan(make_plan([tool_step("a", tool="example.repository.get")]), reg(manifest("admin")))


def test_arguments_hash_is_order_independent_and_sensitive():
    assert approvals.args_hash({"a": 1, "b": 2}) == approvals.args_hash({"b": 2, "a": 1})
    assert approvals.args_hash({"a": 1}) != approvals.args_hash({"a": 2})


# --- Flujo completo por la API ---
class NoteModel:
    name, configured = "scripted", True

    def __init__(self, title):
        self.title, self.calls = title, []

    def generate(self, messages):
        self.calls.append(messages)
        if "Planner de NEXUS" in messages[0]["content"]:
            return json.dumps({"summary_for_user": "Guardar la nota.", "steps": [{
                "step_id": "s1", "kind": "tool_call", "tool_id": "notes.create", "depends_on": [],
                "input": {"title": self.title, "text": f"Contenido de {self.title}: el NAS se migra en marzo."},
                "success_criteria": ["nota guardada"]}]})
        return f"He guardado la nota «{self.title}»."

    def health(self):
        return "ok"


@pytest.fixture
def run(engine):
    from nexus.api.app import create_app
    from tests.test_m1m2 import HashEmbedder

    def make():
        title = f"Nota {uuid.uuid4().hex[:8]}"
        client = TestClient(create_app(engine=engine, model=NoteModel(title), api_token=TOKEN,
                                       embedder=HashEmbedder()))
        tid = client.post("/api/v1/chat/messages", headers=AUTH,
                          json={"message": f"crea una nota titulada {title}"}).json()["task_id"]
        return client, tid, title
    return make


def task(client, tid):
    return client.get(f"/api/v1/tasks/{tid}", headers=AUTH).json()


def pending(client, tid):
    return [a for a in client.get("/api/v1/approvals", headers=AUTH, params={"status": "pending"}).json()["approvals"]
            if a["task_id"] == tid]


def note_exists(engine, title):
    with engine.connect() as c:
        return bool(c.scalar(sa.text("SELECT 1 FROM documents WHERE title=:t AND status='active'"), {"t": title}))


def test_write_tool_pauses_for_approval_and_shows_exact_action(run, engine):
    client, tid, title = run()
    t = task(client, tid)
    assert t["status"] == "awaiting_approval" and "APPROVAL_REQUIRED" in t["response"]["warnings"]
    assert title in t["response"]["text"]  # la tarjeta dice qué se va a hacer
    [a] = pending(client, tid)
    assert a["tool_id"] == "notes.create" and a["risk_level"] == "write_reversible" and a["reversible"]
    assert a["arguments"]["title"] == title and a["expires_at"]
    assert not note_exists(engine, title)  # nada se escribe antes de aprobar


def test_approve_executes_once(run, engine):
    client, tid, title = run()
    [a] = pending(client, tid)
    assert client.post(f"/api/v1/approvals/{a['approval_id']}/decision", json={"decision": "approve"}).status_code == 401
    r = client.post(f"/api/v1/approvals/{a['approval_id']}/decision", headers=AUTH, json={"decision": "approve"})
    assert r.status_code == 200, r.text
    t = task(client, tid)
    assert t["status"] == "completed", t and note_exists(engine, title)
    assert note_exists(engine, title)
    assert t["response"]["sources"][0]["source_ref"].startswith("doc:")
    again = client.post(f"/api/v1/approvals/{a['approval_id']}/decision", headers=AUTH, json={"decision": "approve"})
    assert again.status_code == 409 and again.json()["detail"] == "APPROVAL_ALREADY_DECIDED"
    with engine.connect() as c:
        assert c.scalar(sa.text("SELECT status FROM approvals WHERE id=:i"), {"i": a["approval_id"]}) == "consumed"
        assert c.scalar(sa.text("SELECT count(*) FROM audit_events WHERE action='approval.approved' AND entity_id=:i"),
                        {"i": a["approval_id"]}) == 1


def test_reject_cancels_without_writing(run, engine):
    client, tid, title = run()
    [a] = pending(client, tid)
    client.post(f"/api/v1/approvals/{a['approval_id']}/decision", headers=AUTH, json={"decision": "reject"})
    t = task(client, tid)
    assert t["status"] == "cancelled" and not note_exists(engine, title)


def test_expired_approval_cannot_be_used(run, engine):
    client, tid, title = run()
    [a] = pending(client, tid)
    with engine.begin() as c:
        c.execute(sa.text("UPDATE approvals SET expires_at = now() - interval '1 minute' WHERE id=:i"),
                  {"i": a["approval_id"]})
    r = client.post(f"/api/v1/approvals/{a['approval_id']}/decision", headers=AUTH, json={"decision": "approve"})
    assert r.status_code == 409 and r.json()["detail"] == "APPROVAL_EXPIRED"
    assert task(client, tid)["status"] == "expired" and not note_exists(engine, title)


def test_changed_arguments_invalidate_the_approval(run, engine):
    """Doc 05 §11: si cambia cualquier parámetro, la aprobación anterior no autoriza la llamada."""
    client, tid, title = run()
    [a] = pending(client, tid)
    with engine.begin() as c:  # alguien altera el paso después de pedir la aprobación
        c.execute(sa.text("UPDATE plan_steps SET input = jsonb_set(input, '{title}', '\"Otra cosa\"') "
                          "WHERE plan_id IN (SELECT id FROM plans WHERE task_id=:t)"), {"t": tid})
    client.post(f"/api/v1/approvals/{a['approval_id']}/decision", headers=AUTH, json={"decision": "approve"})
    t = task(client, tid)
    assert t["status"] == "failed" and "s1:APPROVAL_REQUIRED" in t["response"]["warnings"]
    assert not note_exists(engine, title) and not note_exists(engine, "Otra cosa")


def test_cancel_task_waiting_for_approval(run, engine):
    client, tid, title = run()
    [a] = pending(client, tid)
    r = client.post(f"/api/v1/tasks/{tid}/cancel", headers=AUTH)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert pending(client, tid) == []
    r = client.post(f"/api/v1/approvals/{a['approval_id']}/decision", headers=AUTH, json={"decision": "approve"})
    assert r.status_code == 409 and not note_exists(engine, title)
    assert client.post(f"/api/v1/tasks/{tid}/cancel", headers=AUTH).status_code == 409  # ya terminada


def test_executor_stops_between_steps_when_cancelled(engine):
    from nexus.core import planner, task_store
    from nexus.core.executor import execute
    from nexus.contracts import PlanStep
    from nexus.gateway.internal_tools import ADAPTERS, seed
    with engine.begin() as c:
        seed(c)
        tid = task_store.create_task(c, owner_id="test", goal="g", correlation_id="corr_cancel")
    steps = [PlanStep(step_id=f"s{i}", kind="tool_call", tool_id="system.time.now", success_criteria=["ok"])
             for i in range(3)]
    plan = make_plan(steps).model_copy(update={"task_id": tid, "plan_id": f"plan_{tid}"})
    planner.save_plan(engine, plan)
    calls = iter([False, True, True])
    r = execute(engine, ADAPTERS, plan, "corr_cancel", should_stop=lambda: next(calls))
    assert r["s0"].status == "succeeded" and r["s1"].error == {"code": "CANCELLED"} and r["s2"].error == {"code": "CANCELLED"}


class LyingModel(NoteModel):
    """Planner que devuelve basura y síntesis que afirma haber actuado (visto con Qwen real)."""

    def generate(self, messages):
        self.calls.append(messages)
        if "Planner de NEXUS" in messages[0]["content"]:
            return "Claro, voy a crear la nota «X»: título y texto…"
        return "He creado la nota con el título indicado."


def test_never_claims_an_action_that_did_not_run(engine):
    from nexus.api.app import create_app
    model = LyingModel("Nota inexistente")
    client = TestClient(create_app(engine=engine, model=model, api_token=TOKEN, embedder=None))
    tid = client.post("/api/v1/chat/messages", headers=AUTH, json={"message": "crea una nota titulada X"}).json()["task_id"]
    t = task(client, tid)
    assert t["status"] == "partial" and "no se ha hecho ningún cambio" in t["response"]["text"]
    assert "He creado" not in t["response"]["text"] and len(model.calls) == 1  # solo el Planner


def test_synthesis_without_tools_is_told_not_to_claim_actions(engine):
    from nexus.api.app import create_app

    class EmptyPlan(NoteModel):
        def generate(self, messages):
            self.calls.append(messages)
            if "Planner de NEXUS" in messages[0]["content"]:
                return '{"summary_for_user": "nada", "steps": []}'
            return "No tengo una herramienta para eso."
    model = EmptyPlan("x")
    client = TestClient(create_app(engine=engine, model=model, api_token=TOKEN, embedder=None))
    client.post("/api/v1/chat/messages", headers=AUTH, json={"message": "recuérdame llamar a Ana mañana"})
    assert "no afirmes haber creado" in json.dumps(model.calls[-1], ensure_ascii=False)
