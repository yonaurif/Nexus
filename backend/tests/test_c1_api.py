"""Fase C1 (Doc 02 §18, Doc 04 Fase 1/§9): API, clasificador simple, Model Router, chat persistido, SSE."""
import pytest
from fastapi.testclient import TestClient

from nexus.core.classifier import classify

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakeModel:
    name = "fake"

    def __init__(self, reply="Hola, soy NEXUS."):
        self.reply, self.calls = reply, []

    def generate(self, messages):
        self.calls.append(messages)
        return self.reply

    def health(self):
        return "ok"


class BrokenModel(FakeModel):
    def generate(self, messages):
        raise ConnectionError("modelo caído")


@pytest.fixture
def client_for(engine):
    from nexus.api.app import create_app

    def make(model):
        return TestClient(create_app(engine=engine, model=model, api_token=TOKEN, embedder=None))
    return make


# --- Clasificador simple (Doc 02 §4): señal de enrutamiento, con abstención ---
@pytest.mark.parametrize("text,label", [
    ("hola, ¿qué tal?", "conversation"),
    ("revisa mi repositorio de github", "agent_request"),
    ("recuérdame revisar el repositorio mañana", "task_request"),
    ("¿qué hora es?", "task_request"),
    ("recuerda que prefiero respuestas cortas", "memory_update"),
    ("cada vez que publique un vídeo pídeme aprobación", "rule_proposal"),
    ("?!", "unknown"),
])
def test_classifier(text, label):
    assert classify(text) == label


# --- Auth y validación en la frontera ---
def test_requires_token(client_for):
    c = client_for(FakeModel())
    assert c.post("/api/v1/chat/messages", json={"message": "hola"}).status_code == 401
    assert c.post("/api/v1/chat/messages", json={"message": "hola"},
                  headers={"Authorization": "Bearer otro"}).status_code == 401


@pytest.mark.parametrize("body", [{"message": ""}, {"message": "x" * 8001},
                                  {"message": "hola", "role": "system"}])
def test_rejects_invalid_body(client_for, body):
    assert client_for(FakeModel()).post("/api/v1/chat/messages", json=body,
                                        headers=AUTH).status_code == 422


# --- Flujo completo: mensaje -> tarea -> modelo -> respuesta ---
def test_chat_message_completes_task(client_for):
    model = FakeModel()
    c = client_for(model)
    r = c.post("/api/v1/chat/messages", json={"message": "hola"}, headers=AUTH)
    assert r.status_code == 202
    body = r.json()
    assert r.headers["X-Correlation-ID"] == body["correlation_id"]

    t = c.get(f"/api/v1/tasks/{body['task_id']}", headers=AUTH).json()
    assert t["status"] == "completed"
    assert t["response"]["text"] == "Hola, soy NEXUS."
    assert t["response"]["warnings"] == []
    # el system prompt va primero y el mensaje del usuario al final
    assert model.calls[0][0]["role"] == "system" and model.calls[0][-1]["content"] == "hola"


def test_conversation_keeps_history(client_for):
    model = FakeModel()
    c = client_for(model)
    conv = c.post("/api/v1/chat/messages", json={"message": "me llamo Ana"},
                  headers=AUTH).json()["conversation_id"]
    c.post("/api/v1/chat/messages", json={"message": "¿cómo me llamo?",
                                          "conversation_id": conv}, headers=AUTH)
    contents = [m["content"] for m in model.calls[1]]
    assert "me llamo Ana" in contents and contents[-1] == "¿cómo me llamo?"


def test_unknown_conversation_is_404(client_for):
    r = client_for(FakeModel()).post("/api/v1/chat/messages", headers=AUTH,
                                     json={"message": "hola", "conversation_id": "conv_nope"})
    assert r.status_code == 404


def test_unsupported_capability_is_partial_not_success(client_for):
    c = client_for(FakeModel())
    tid = c.post("/api/v1/chat/messages", json={"message": "revisa mi repositorio de github"},
                 headers=AUTH).json()["task_id"]
    t = c.get(f"/api/v1/tasks/{tid}", headers=AUTH).json()
    assert t["status"] == "partial"
    assert t["response"]["warnings"]


def test_ambiguous_message_asks_for_input_without_model(client_for):
    model = FakeModel()
    c = client_for(model)
    tid = c.post("/api/v1/chat/messages", json={"message": "?!"}, headers=AUTH).json()["task_id"]
    assert c.get(f"/api/v1/tasks/{tid}", headers=AUTH).json()["status"] == "needs_input"
    assert model.calls == []


def test_model_failure_marks_task_failed(client_for):
    """Doc 02 aceptación #8: el fallo no bloquea ni se convierte en éxito aparente."""
    c = client_for(BrokenModel())
    r = c.post("/api/v1/chat/messages", json={"message": "hola"}, headers=AUTH)
    assert r.status_code == 202
    t = c.get(f"/api/v1/tasks/{r.json()['task_id']}", headers=AUTH).json()
    assert t["status"] == "failed"
    assert "modelo caído" not in str(t)  # sin detalles internos al cliente
    assert t["response"]["warnings"] == ["MODEL_UNAVAILABLE"]


def test_unknown_task_is_404(client_for):
    assert client_for(FakeModel()).get("/api/v1/tasks/task_nope", headers=AUTH).status_code == 404


# --- SSE (Doc 04 §9.2): eventos con id para reconexión ---
def test_task_events_stream_and_resume(client_for):
    c = client_for(FakeModel())
    tid = c.post("/api/v1/chat/messages", json={"message": "hola"}, headers=AUTH).json()["task_id"]
    r = c.get(f"/api/v1/tasks/{tid}/events", headers=AUTH)
    assert r.headers["content-type"].startswith("text/event-stream")
    ids = [int(l[4:]) for l in r.text.splitlines() if l.startswith("id: ")]
    assert len(ids) == 9 and '"to": "completed"' in r.text  # created ... completed

    resumed = c.get(f"/api/v1/tasks/{tid}/events", headers={**AUTH, "Last-Event-ID": str(ids[-2])})
    assert [int(l[4:]) for l in resumed.text.splitlines() if l.startswith("id: ")] == [ids[-1]]


# --- Health (Doc 04 §12): sin métricas inventadas ---
def test_health_reports_components(client_for):
    h = client_for(FakeModel()).get("/api/v1/system/health").json()
    assert h["status"] == "ok"
    comp = h["components"]
    assert comp["database"] == "ok" and comp["model"] == {"name": "fake", "status": "ok"}
    assert comp["embeddings"] == {"name": None, "status": "not_configured"}
    assert comp["hardware"]["ram_total_gb"] > 0 and "vram_free_gb" in comp["hardware"]  # real, no inventado


def test_stub_model_is_partial_not_completed(client_for):
    from nexus.core.models import StubModel
    c = client_for(StubModel())
    tid = c.post("/api/v1/chat/messages", json={"message": "hola"}, headers=AUTH).json()["task_id"]
    t = c.get(f"/api/v1/tasks/{tid}", headers=AUTH).json()
    assert t["status"] == "partial" and t["response"]["warnings"] == ["MODEL_NOT_CONFIGURED"]
