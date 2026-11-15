"""Fases M1 (episodios) y M2 (documentos + RAG híbrido) — Doc 03 §3, §5, §7–8, §11, §14, §17."""
import hashlib
import json
import math
import re
import uuid

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from nexus.knowledge import store
from nexus.knowledge.chunking import chunk_text
from nexus.knowledge.sanitize import redact
from nexus.memory import episodes

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class HashEmbedder:
    """Embedder determinista para tests (bolsa de palabras con hashing, normalizado)."""
    provider, model_name, model_version = "test", "hash-bow", "1"

    def __init__(self, dimensions=64):
        self.dimensions = dimensions

    def embed(self, texts):
        out = []
        for t in texts:
            v = [0.0] * self.dimensions
            for tok in re.findall(r"\w+", t.lower()):
                v[int(hashlib.md5(tok.encode()).hexdigest()[:8], 16) % self.dimensions] += 1
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


def owner():
    return f"owner_{uuid.uuid4().hex[:8]}"  # aislamiento entre tests sin borrar filas


# --- Chunking (Doc 03 §8.2): límites semánticos y offsets exactos ---
DOC = """# Proyecto Atlas

Atlas es un servicio de automatización escrito en Python.
Usa PostgreSQL para guardar el estado.

## Despliegue

Se despliega con Docker Compose en el homelab.

""" + ("Párrafo largo de relleno. " * 120)


def test_chunks_keep_exact_offsets_and_headings():
    chunks = chunk_text(DOC, max_chars=400)
    assert len(chunks) >= 3
    for c in chunks:
        assert DOC[c.start:c.end] == c.text and len(c.text) <= 400
    assert chunks[0].heading == "Proyecto Atlas"
    assert any(c.heading == "Despliegue" and "Docker" in c.text for c in chunks)
    assert [c.index for c in chunks] == list(range(len(chunks)))


# --- Sanitización (Doc 03 §5.5, §11): secretos nunca entran al índice ---
def test_redacts_secrets_and_reports_kinds():
    text = ("token ghp_" + "a" * 36 + " y clave AKIAABCDEFGHIJKLMNOP\npassword: hunter2\n"
            "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----")
    clean, found = redact(text)
    assert "ghp_" not in clean and "AKIA" not in clean and "hunter2" not in clean and "MIIabc" not in clean
    assert "password: [REDACTED]" in clean
    assert set(found) >= {"github_token", "aws_access_key", "credential_assignment", "private_key"}


def test_clean_text_is_untouched():
    assert redact("Atlas usa Python y Docker.") == ("Atlas usa Python y Docker.", [])


# --- Ingesta + búsqueda híbrida (Doc 03 §8.3) ---
@pytest.fixture
def emb():
    return HashEmbedder()


def test_ingest_dedupes_and_registers_profile(engine, emb):
    o = owner()
    a = store.ingest_document(engine, o, title="Atlas", text=DOC, embedder=emb)
    b = store.ingest_document(engine, o, title="Atlas copia", text=DOC, embedder=emb)
    assert b.document_id == a.document_id and b.deduplicated and a.chunks >= 3
    with engine.connect() as c:
        dims = c.scalar(sa.text("SELECT dimensions FROM embedding_profiles WHERE model_name='hash-bow'"))
        n = c.scalar(sa.text("SELECT count(*) FROM chunk_embeddings e JOIN document_chunks d ON d.id=e.chunk_id "
                             "WHERE d.document_id=:d"), {"d": a.document_id})
    assert dims == 64 and n == a.chunks


def test_secrets_are_not_stored(engine, emb):
    o = owner()
    r = store.ingest_document(engine, o, title="notas", text="La clave es password=superSecreta123", embedder=emb)
    with engine.connect() as c:
        text = c.scalar(sa.text("SELECT string_agg(text, ' ') FROM document_chunks WHERE document_id=:d"),
                        {"d": r.document_id})
        sens = c.scalar(sa.text("SELECT sensitivity FROM documents WHERE id=:d"), {"d": r.document_id})
    assert "superSecreta123" not in text and r.redactions == ["credential_assignment"] and sens == "redacted"


def test_search_finds_relevant_chunk_with_citation(engine, emb):
    o = owner()
    doc = store.ingest_document(engine, o, title="Atlas", text=DOC, embedder=emb, uri_ref="file://atlas.md")
    store.ingest_document(engine, o, title="Cocina", text="Receta de tortilla de patatas con cebolla.", embedder=emb)
    with engine.connect() as c:
        hits = store.search(c, o, "¿cómo se despliega Atlas con Docker?", emb)
    assert hits and hits[0].document_id == doc.document_id and "Docker" in hits[0].text
    assert hits[0].title == "Atlas" and hits[0].uri_ref == "file://atlas.md" and hits[0].heading == "Despliegue"


def test_search_never_crosses_owners(engine, emb):
    a, b = owner(), owner()
    store.ingest_document(engine, b, title="Privado", text="El proyecto Zeta usa Rust.", embedder=emb)
    with engine.connect() as c:
        assert store.search(c, a, "proyecto Zeta Rust", emb) == []
        assert store.search(c, b, "proyecto Zeta Rust", emb)


def test_search_without_embedder_uses_full_text_only(engine):
    o = owner()
    store.ingest_document(engine, o, title="Atlas", text=DOC, embedder=None)
    with engine.connect() as c:
        assert store.search(c, o, "Docker Compose homelab", None)[0].title == "Atlas"
        assert store.search(c, o, "astronomía cuántica", None) == []


def test_search_limits_chunks_per_document(engine, emb):
    o = owner()
    store.ingest_document(engine, o, title="Repetido", text="\n\n".join(["Docker Docker Docker"] * 6),
                          embedder=emb, max_chars=30)
    with engine.connect() as c:
        hits = store.search(c, o, "Docker", emb)
    assert len(hits) == store.MAX_PER_DOCUMENT


# --- Episodios (M1, Doc 03 §3.1, §7.2): append-only, consulta por tiempo/tipo ---
def test_episodes_record_search_and_are_append_only(engine):
    o = owner()
    with engine.begin() as c:
        episodes.record(c, owner_id=o, event_type="chat.turn", summary="[conversation] hola",
                        correlation_id="corr_ep", actor_type="owner", actor_id=o)
        episodes.record(c, owner_id=o, event_type="tool.call", summary="hora", actor_type="system",
                        actor_id="core")
    with engine.connect() as c:
        assert [e.event_type for e in episodes.search(c, o)] == ["tool.call", "chat.turn"]
        assert [e.summary for e in episodes.search(c, o, event_type="chat.turn")] == ["[conversation] hola"]
        assert episodes.search(c, owner()) == []
    with pytest.raises(DBAPIError, match="append-only"):
        with engine.begin() as c:
            c.execute(sa.text("UPDATE memory_episodes SET summary='x' WHERE owner_id=:o"), {"o": o})


def test_episode_summary_is_sanitized(engine):
    o = owner()
    with engine.begin() as c:
        episodes.record(c, owner_id=o, event_type="chat.turn", summary="mi token=abc123456789",
                        actor_type="owner", actor_id=o)
    with engine.connect() as c:
        e = episodes.search(c, o)[0]
    assert "abc123456789" not in e.summary and e.sensitivity == "redacted"


# --- API y Core (Doc 04 §9.1, Doc 02 §5) ---
class RagModel:
    name, configured = "rag", True

    def __init__(self):
        self.calls = []

    def generate(self, messages):
        self.calls.append(messages)
        return "Según tus documentos, Atlas se despliega con Docker Compose [1]."

    def health(self):
        return "ok"


@pytest.fixture
def api(engine, emb):
    from nexus.api.app import create_app

    def make(model):
        return TestClient(create_app(engine=engine, model=model, api_token=TOKEN, embedder=emb))
    return make


def test_api_ingest_and_search(api):
    c = api(RagModel())
    assert c.post("/api/v1/knowledge/documents", json={"title": "x", "text": "y"}).status_code == 401
    r = c.post("/api/v1/knowledge/documents", headers=AUTH,
               json={"title": "Atlas", "text": DOC, "uri_ref": "file://atlas.md"})
    assert r.status_code == 201 and r.json()["chunks"] >= 3
    hits = c.get("/api/v1/knowledge/search", params={"q": "despliegue Docker"}, headers=AUTH).json()["hits"]
    assert hits[0]["title"] == "Atlas" and hits[0]["source_ref"].startswith("doc:")
    assert c.post("/api/v1/knowledge/documents", headers=AUTH,
                  json={"title": "x", "text": "y", "role": "system"}).status_code == 422


def test_chat_knowledge_query_uses_rag_with_sources(api):
    model = RagModel()
    c = api(model)
    c.post("/api/v1/knowledge/documents", headers=AUTH, json={"title": "Atlas", "text": DOC})
    tid = c.post("/api/v1/chat/messages", headers=AUTH,
                 json={"message": "según mis documentos, ¿cómo se despliega Atlas con Docker?"}).json()["task_id"]
    t = c.get(f"/api/v1/tasks/{tid}", headers=AUTH).json()
    assert t["status"] == "completed", t
    assert t["response"]["sources"] and t["response"]["sources"][0]["source_ref"].startswith("doc:")
    ctx = json.dumps(model.calls[-1], ensure_ascii=False)
    assert "DATOS NO CONFIABLES" in ctx and "Docker Compose" in ctx
    eps = c.get("/api/v1/memory/episodes", headers=AUTH, params={"event_type": "chat.turn"}).json()["episodes"]
    assert any(e["task_id"] == tid for e in eps)


def test_chat_knowledge_query_without_evidence_abstains(api):
    model = RagModel()
    c = api(model)
    tid = c.post("/api/v1/chat/messages", headers=AUTH,
                 json={"message": "según mis documentos, ¿qué es Kryptonita-9000?"}).json()["task_id"]
    t = c.get(f"/api/v1/tasks/{tid}", headers=AUTH).json()
    assert t["status"] == "needs_input" and "NO_EVIDENCE:knowledge" in t["response"]["warnings"]
    assert t["response"]["text"].startswith("No he encontrado información")
    assert model.calls == []  # sin evidencia no se llama al modelo: no puede inventar


def test_real_onnx_embedder_if_configured():
    from nexus.knowledge.embeddings import get_embedder
    e = get_embedder()
    if e is None:
        pytest.skip("NEXUS_EMBED_MODEL_DIR no configurado")
    q, rel, unrel = e.embed(["¿Cómo pongo en marcha el servicio?",
                             "El servicio se arranca con Docker Compose.",
                             "Receta de tortilla de patatas."])
    dot = lambda a, b: sum(x * y for x, y in zip(a, b))
    assert e.dimensions == 384 and abs(dot(q, q) - 1) < 1e-4
    assert dot(q, rel) > dot(q, unrel)  # semántico: sin palabras en común con la relevante


def test_routing_phrase_alone_is_not_evidence(api):
    """Regresión: 'según mis documentos' casaba con cualquier documento que dijera 'documentos'."""
    model = RagModel()
    c = api(model)
    c.post("/api/v1/knowledge/documents", headers=AUTH,
           json={"title": "Arquitectura", "text": "Estos documentos describen la arquitectura del sistema."})
    tid = c.post("/api/v1/chat/messages", headers=AUTH,
                 json={"message": "según mis documentos, ¿cuál es la receta de la paella?"}).json()["task_id"]
    t = c.get(f"/api/v1/tasks/{tid}", headers=AUTH).json()
    assert t["status"] == "needs_input" and t["response"]["sources"] == [] and model.calls == []
    assert "NO_EVIDENCE:knowledge" in t["response"]["warnings"]


def test_strip_routing():
    from nexus.core.classifier import strip_routing
    assert strip_routing("Según mis documentos, ¿qué es Atlas?") == "¿qué es Atlas?"
    assert strip_routing("qué sabes de Atlas") == "Atlas"
    assert strip_routing("hola") == "hola"
