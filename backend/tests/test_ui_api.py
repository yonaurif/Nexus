"""Endpoints que necesita la interfaz (Doc 04 §9.1) y servido del build estático."""
import pytest
from fastapi.testclient import TestClient

from tests.test_c1_api import FakeModel

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(engine):
    from nexus.api.app import create_app
    return TestClient(create_app(engine=engine, model=FakeModel("Respuesta de prueba."), api_token=TOKEN, embedder=None))


def test_conversations_list_and_detail(client):
    first = client.post("/api/v1/chat/messages", headers=AUTH, json={"message": "hola, primera pregunta"}).json()
    client.post("/api/v1/chat/messages", headers=AUTH,
                json={"message": "segunda", "conversation_id": first["conversation_id"]})
    convs = client.get("/api/v1/chat/conversations", headers=AUTH).json()["conversations"]
    mine = next(c for c in convs if c["conversation_id"] == first["conversation_id"])
    assert mine["title"] == "hola, primera pregunta" and mine["messages"] == 4

    detail = client.get(f"/api/v1/chat/conversations/{first['conversation_id']}", headers=AUTH).json()
    roles = [m["role"] for m in detail["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"]
    reply = detail["messages"][1]
    assert reply["content"] == "Respuesta de prueba." and reply["task_status"] == "completed"
    assert reply["warnings"] == [] and reply["sources"] == [] and reply["task_id"] == first["task_id"]


def test_conversation_access_is_owner_scoped(client):
    assert client.get("/api/v1/chat/conversations").status_code == 401
    assert client.get("/api/v1/chat/conversations/conv_nope", headers=AUTH).status_code == 404


def test_frontend_is_served_when_built(engine, tmp_path, monkeypatch):
    from nexus.api import app as app_module
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>NEXUS</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setattr(app_module, "FRONTEND_DIST", dist)
    c = TestClient(app_module.create_app(engine=engine, model=FakeModel(), api_token=TOKEN, embedder=None))
    assert "NEXUS" in c.get("/").text
    assert c.get("/assets/app.js").text == "console.log(1)"
    assert "NEXUS" in c.get("/conversaciones/abc").text  # SPA: rutas del cliente devuelven index.html
    assert c.get("/api/v1/no-existe").status_code == 404   # la API no queda tapada por el SPA
    assert c.get("/api/v1/system/health").status_code == 200
