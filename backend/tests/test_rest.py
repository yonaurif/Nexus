"""Adaptador REST y conector GitHub de solo lectura (Doc 05 §6–7, §10–11, §14; fases G1/G2)."""
import json
import socket

import httpx
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from nexus.contracts import ToolManifest
from nexus.gateway import connectors
from nexus.gateway.registry import GatewayError, SqlToolRegistry
from nexus.gateway.rest import RestConnector, RestTool

REPO = {"name": "Nexus", "full_name": "yonaurif/Nexus", "description": "IA personal", "default_branch": "main",
        "visibility": "public", "language": "Python", "stargazers_count": 3, "open_issues_count": 1,
        "pushed_at": "2026-11-15T18:00:00Z", "html_url": "https://github.com/yonaurif/Nexus",
        "owner": {"login": "yonaurif", "id": 1}, "private": False}


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("140.82.112.6", port))])


def github(handler, calls=None):
    def wrapped(request):
        if calls is not None:
            calls.append(request)
        return handler(request)
    return connectors.github(transport=httpx.MockTransport(wrapped))


def test_repository_get_maps_fields_and_adds_evidence(monkeypatch):
    monkeypatch.setenv("NEXUS_GITHUB_TOKEN", "ghp_secreto_de_prueba")
    calls = []
    gh = github(lambda r: httpx.Response(200, json=REPO), calls)
    out = gh.adapter("github.repository.get", {"owner": "yonaurif", "repo": "Nexus"})
    assert out["data"]["full_name"] == "yonaurif/Nexus" and out["data"]["default_branch"] == "main"
    assert "owner" not in out["data"]  # solo los campos declarados en la salida
    assert out["evidence"][0]["source_ref"] == "github_readonly:GET /repos/yonaurif/Nexus"
    assert calls[0].headers["authorization"] == "Bearer ghp_secreto_de_prueba"
    assert "ghp_secreto" not in json.dumps(out)  # el token nunca vuelve en datos ni evidencia


def test_list_responses_are_capped(monkeypatch):
    repos = [dict(REPO, name=f"r{i}", full_name=f"yonaurif/r{i}") for i in range(50)]
    gh = github(lambda r: httpx.Response(200, json=repos))
    out = gh.adapter("github.user.repos", {"user": "yonaurif"})
    assert len(out["data"]["items"]) == 20 and out["data"]["items"][0] == {
        "full_name": "yonaurif/r0", "description": "IA personal", "language": "Python", "pushed_at": REPO["pushed_at"],
        "visibility": "public"}


@pytest.mark.parametrize("args", [{"owner": "../../admin", "repo": "x"}, {"owner": "a/b", "repo": "x"},
                                  {"owner": "yonaurif"}, {"owner": "x", "repo": "y", "extra": "z"},
                                  {"owner": "x" * 101, "repo": "y"}, {"owner": "..", "repo": "y"}])
def test_path_arguments_cannot_inject(args):
    calls = []
    gh = github(lambda r: httpx.Response(200, json=REPO), calls)
    with pytest.raises(GatewayError, match="INPUT_INVALID"):
        gh.adapter("github.repository.get", args)
    assert calls == []


def test_unknown_tool_and_http_errors():
    gh = github(lambda r: httpx.Response(404))
    with pytest.raises(GatewayError, match="TOOL_NOT_ALLOWED"):
        gh.adapter("github.repository.delete", {})
    with pytest.raises(GatewayError, match="RESOURCE_NOT_FOUND"):
        gh.adapter("github.repository.get", {"owner": "nadie", "repo": "nada"})


def test_rest_tools_are_read_only_by_construction():
    tool = ToolManifest(tool_id="x.y", connector_id="c", version="1", description="d", input_schema={},
                        output_schema={}, risk_level="read", required_scopes=[])
    with pytest.raises(ValueError, match="solo GET"):
        RestTool(tool, method="POST", path="/x")
    with pytest.raises(ValueError, match="https"):
        RestConnector("c", "http://api.example.com", [])


# --- Integración con el Core (Doc 05 §10: flujo de invocación) ---
TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class PlanThenAnswer:
    name, configured = "scripted", True

    def __init__(self):
        self.calls = []

    def generate(self, messages):
        self.calls.append(messages)
        if "Planner de NEXUS" in messages[0]["content"]:
            return json.dumps({"summary_for_user": "Consultar el repositorio.", "steps": [{
                "step_id": "s1", "kind": "tool_call", "tool_id": "github.repository.get", "depends_on": [],
                "input": {"owner": "yonaurif", "repo": "Nexus"}, "success_criteria": ["datos del repo"]}]})
        return "El repositorio yonaurif/Nexus usa Python y su rama principal es main."

    def health(self):
        return "ok"


@pytest.fixture
def api(engine):
    from nexus.api.app import create_app
    from nexus.gateway.internal_tools import ADAPTERS
    with engine.begin() as c:  # cada test parte con el conector sin aprobar
        c.execute(sa.text("DELETE FROM tools WHERE connector_id='github_readonly'"))
    gh = github(lambda r: httpx.Response(200, json=REPO))

    def make(model):
        return TestClient(create_app(engine=engine, model=model, api_token=TOKEN, embedder=None,
                                     adapters={**ADAPTERS, gh.connector_id: gh.adapter}))
    return make


def ask(client, text):
    tid = client.post("/api/v1/chat/messages", headers=AUTH, json={"message": text}).json()["task_id"]
    return client.get(f"/api/v1/tasks/{tid}", headers=AUTH).json()


def test_external_connector_starts_in_review_and_needs_owner_approval(api, engine):
    client = api(PlanThenAnswer())
    tools = {t["tool_id"]: t for t in client.get("/api/v1/connectors", headers=AUTH).json()["tools"]}
    assert tools["github.repository.get"]["status"] == "review"
    assert tools["system.time.now"]["status"] == "enabled"  # interna, revisada como código

    before = ask(client, "revisa mi repositorio de github yonaurif/Nexus")
    assert before["status"] == "partial"
    assert any(w.startswith("PLAN_REJECTED:TOOL_NOT_ALLOWED") for w in before["response"]["warnings"])

    assert client.post("/api/v1/connectors/tools/github.repository.get/approve").status_code == 401
    assert client.post("/api/v1/connectors/tools/github.repository.get/approve", headers=AUTH).status_code == 200
    after = ask(client, "revisa mi repositorio de github yonaurif/Nexus")
    assert after["status"] == "completed", after
    assert after["response"]["sources"][0]["source_ref"] == "github_readonly:GET /repos/yonaurif/Nexus"
    with engine.connect() as c:
        row = c.execute(sa.text("SELECT status, arguments_hash FROM tool_executions WHERE tool_id='github.repository.get' "
                                "ORDER BY started_at DESC LIMIT 1")).one()
    assert row.status == "succeeded" and "yonaurif" not in row.arguments_hash


def test_disabled_tool_stops_working_without_redeploy(api):
    client = api(PlanThenAnswer())
    client.post("/api/v1/connectors/tools/github.repository.get/approve", headers=AUTH)
    assert client.post("/api/v1/connectors/tools/github.repository.get/disable", headers=AUTH).status_code == 200
    t = ask(client, "revisa mi repositorio de github yonaurif/Nexus")
    assert t["status"] == "partial"  # Doc 05 aceptación #15: revocar sin desplegar
    assert client.post("/api/v1/connectors/tools/no.existe/approve", headers=AUTH).status_code == 404


def test_executor_keeps_gateway_error_codes(engine):
    from nexus.core.executor import execute
    from nexus.core import planner, task_store
    from tests.test_c0_g0 import make_plan
    from nexus.contracts import PlanStep
    gh = github(lambda r: httpx.Response(429))
    with engine.begin() as c:
        reg = SqlToolRegistry(c)
        for m in gh.manifests():
            reg.register(m)
            reg.approve(m.tool_id)
        tid = task_store.create_task(c, owner_id="test", goal="gh", correlation_id="corr_gh")
    plan = make_plan([PlanStep(step_id="s", kind="tool_call", tool_id="github.repository.get",
                               input={"owner": "a", "repo": "b"}, success_criteria=["ok"])])
    plan = plan.model_copy(update={"task_id": tid, "plan_id": f"plan_{tid}"})
    planner.save_plan(engine, plan)
    r = execute(engine, {gh.connector_id: gh.adapter}, plan, "corr_gh")["s"]
    assert r.status == "failed" and r.error == {"code": "RATE_LIMITED"}  # reintentable (Verifier)


def test_failed_tools_never_get_an_invented_answer(api, engine):
    """Regresión real: con GitHub caído, Qwen inventó el lenguaje, la rama y una lista vacía de repos."""
    from nexus.api.app import create_app
    from nexus.gateway.internal_tools import ADAPTERS
    model = PlanThenAnswer()
    gh = github(lambda r: httpx.Response(404))
    client = TestClient(create_app(engine=engine, model=model, api_token=TOKEN, embedder=None,
                                   adapters={**ADAPTERS, gh.connector_id: gh.adapter}))
    client.post("/api/v1/connectors/tools/github.repository.get/approve", headers=AUTH)
    t = ask(client, "revisa mi repositorio de github yonaurif/Nexus")
    assert t["status"] == "failed" and "s1:RESOURCE_NOT_FOUND" in t["response"]["warnings"]
    assert "no voy a suponer" in t["response"]["text"] and "Python" not in t["response"]["text"]
    assert all("Planner de NEXUS" in call[0]["content"] for call in model.calls)  # solo el Planner usó el LLM
