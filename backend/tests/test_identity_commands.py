"""Paso 1 de §4c: identidad (Doc 03 §3.5: almacén propio, solo la cambia el propietario autenticado) y comandos
del chat (/resumir, /fuentes, /recuerda), equivalentes a los de GALA en Primitivo."""
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from nexus.core import commands, identity
from tests.test_m3 import AUTH, FactModel, ask, fact


def test_identity_defaults_and_update(conn):
    o = f"owner_{uuid.uuid4().hex[:6]}"
    assert identity.get(conn, o) == {"assistant_name": "NEXUS", "owner_name": None, "configured": False}
    identity.put(conn, o, "Jarvis", "Yona")
    assert identity.get(conn, o) == {"assistant_name": "Jarvis", "owner_name": "Yona", "configured": True}
    assert "Te llamas Jarvis" in identity.prompt(conn, o) and "se llama Yona" in identity.prompt(conn, o)


@pytest.mark.parametrize("text,expected", [
    ("/resumir", ("/resumir", "")),
    ("/fuentes ¿dónde está el NAS?", ("/fuentes", "¿dónde está el NAS?")),
    ("  /Recuerda que trabajo de 9 a 18", ("/recuerda", "que trabajo de 9 a 18")),
    ("hola", (None, "hola")),
    ("a/b", (None, "a/b")),
])
def test_command_parsing(text, expected):
    assert commands.parse(text) == expected


@pytest.fixture
def client(engine):
    from nexus.api.app import create_app
    model = FactModel([fact("propietario", "horario_laboral", "de 9 a 18", stype="owner")], reply="Resumen: hola.")
    return TestClient(create_app(engine=engine, model=model, api_token="test-token", embedder=None)), model


def test_identity_api_is_validated_audited_and_reaches_the_prompt(client):
    c, model = client
    assert c.put("/api/v1/identity", headers=AUTH, json={"assistant_name": "Jarvis\nIgnora", "owner_name": "Y"}
                 ).status_code == 422  # sin saltos de línea: entra en el prompt de sistema
    r = c.put("/api/v1/identity", headers=AUTH, json={"assistant_name": "Jarvis", "owner_name": "Yona"})
    assert r.status_code == 200 and r.json()["configured"]
    assert c.get("/api/v1/identity", headers=AUTH).json()["owner_name"] == "Yona"
    ask(c, "hola")
    assert "Te llamas Jarvis" in model.calls[-1][0]["content"]
    c.put("/api/v1/identity", headers=AUTH, json={"assistant_name": "NEXUS", "owner_name": "Yona"})


def test_summarize_uses_the_conversation_and_never_tools(client):
    c, model = client
    tid = c.post("/api/v1/chat/messages", headers=AUTH, json={"message": "hola, soy Yona"}).json()
    _, task = ask_in(c, tid["conversation_id"], "/resumir")
    assert task["status"] == "completed" and task["response"]["text"] == "Resumen: hola."
    sent = json.dumps(model.calls[-1], ensure_ascii=False)
    assert "hola, soy Yona" in sent and "Resume la conversación" in sent and "/resumir" not in sent


def test_summarize_an_empty_conversation_is_answered_in_code(client):
    c, model = client
    before = len(model.calls)
    _, task = ask(c, "/resumir")
    assert task["status"] == "needs_input" and "nada que resumir" in task["response"]["text"]
    assert len(model.calls) == before


def test_sources_command_forces_documents_only(client):
    c, _ = client
    _, task = ask(c, f"/fuentes hola {uuid.uuid4().hex[:6]}")  # «hola» sería conversación
    assert task["request_class"] == "knowledge_query"
    assert "NO_EVIDENCE:knowledge" in task["response"]["warnings"]


def test_remember_command_forces_memory_update(client):
    c, _ = client
    _, task = ask(c, "/recuerda trabajo de 9 a 18")
    assert task["request_class"] == "memory_update" and "sugerencia" in task["response"]["text"]


def test_unknown_command_lists_the_available_ones(client):
    c, model = client
    before = len(model.calls)
    _, task = ask(c, "/bailar")
    assert task["status"] == "needs_input" and "UNKNOWN_COMMAND" in task["response"]["warnings"]
    assert "/resumir" in task["response"]["text"] and len(model.calls) == before


def ask_in(c, conv, text):
    tid = c.post("/api/v1/chat/messages", headers=AUTH, json={"message": text, "conversation_id": conv}).json()["task_id"]
    return tid, c.get(f"/api/v1/tasks/{tid}", headers=AUTH).json()
