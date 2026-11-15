"""Sincronización incremental de carpetas (Doc 03 §5, §6.1, §12; Doc 02 §16 rutas autorizadas).
Comportamiento portado de Primitivo-f25 gala/kb_service.py y endurecido."""
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from nexus.knowledge import sources, store
from tests.test_m1m2 import HashEmbedder, RagModel

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def root(tmp_path, monkeypatch):
    allowed = tmp_path / "permitido"
    allowed.mkdir()
    monkeypatch.setenv("NEXUS_FOLDER_ROOTS", str(allowed))
    return allowed


@pytest.fixture
def emb():
    return HashEmbedder()


def owner():
    return f"owner_{uuid.uuid4().hex[:8]}"


def touch(path, text, bump=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if bump:  # mtime distinto aunque el test vaya más rápido que la resolución del FS
        t = time.time() + bump
        os.utime(path, (t, t))


def search(engine, o, q, emb):
    with engine.connect() as c:
        return store.search(c, o, q, emb)


# --- Registro con rutas autorizadas (Doc 02 §16, Doc 04 §11) ---
def test_register_requires_allowed_existing_directory(engine, root, tmp_path):
    o = owner()
    with pytest.raises(sources.SourceError, match="PATH_NOT_ALLOWED"):
        sources.register_folder(engine, o, str(tmp_path))  # padre de la raíz permitida
    with pytest.raises(sources.SourceError, match="PATH_NOT_ALLOWED"):
        sources.register_folder(engine, o, str(root / ".." / ".." ))  # escape con ..
    with pytest.raises(sources.SourceError, match="NOT_A_DIRECTORY"):
        sources.register_folder(engine, o, str(root / "no_existe"))
    sid = sources.register_folder(engine, o, str(root), interval_minutes=30)
    with pytest.raises(sources.SourceError, match="ALREADY_REGISTERED"):
        sources.register_folder(engine, o, str(root).upper())  # misma carpeta (Windows no distingue mayúsculas)
    with engine.connect() as c:
        row = c.execute(sa.text("SELECT source_type, uri_ref, sync_policy FROM memory_sources WHERE id=:i"),
                        {"i": sid}).one()
    assert row.source_type == "folder" and row.sync_policy["interval_minutes"] == 30


def test_no_roots_configured_means_feature_off(engine, monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUS_FOLDER_ROOTS", "")
    monkeypatch.setattr("nexus.config._dotenv", lambda: {})
    with pytest.raises(sources.SourceError, match="PATH_NOT_ALLOWED"):
        sources.register_folder(engine, owner(), str(tmp_path))


# --- Pasadas incrementales ---
def test_first_sync_indexes_supported_files_and_skips_noise(engine, root, emb):
    o = owner()
    touch(root / "proyecto" / "atlas.md", "# Atlas\n\nAtlas se despliega con Docker Compose.")
    touch(root / "notas.txt", "La reunión del lunes trata el presupuesto de Orion.")
    touch(root / ".git" / "config", "token secreto de git")
    touch(root / "node_modules" / "lib" / "readme.md", "librería de terceros con Docker")
    touch(root / "programa.exe", "MZ binario")
    sid = sources.register_folder(engine, o, str(root))
    r = sources.sync_folder(engine, sid, emb)
    assert (r.status, r.files_total, r.n_indexed, r.n_failed) == ("success", 2, 2, 0)
    titles = {h.title for h in search(engine, o, "Docker Compose despliega", emb)}
    assert titles == {"proyecto/atlas.md"}  # node_modules nunca se indexa


def test_second_sync_without_changes_reads_nothing(engine, root, emb):
    o = owner()
    touch(root / "a.txt", "Contenido estable del archivo A.")
    sid = sources.register_folder(engine, o, str(root))
    sources.sync_folder(engine, sid, emb)
    r = sources.sync_folder(engine, sid, emb)
    assert (r.n_indexed, r.n_unchanged) == (0, 1)


def test_modified_file_supersedes_previous_version(engine, root, emb):
    o = owner()
    f = root / "plan.txt"
    touch(f, "El servidor usa MariaDB como base de datos.")
    sid = sources.register_folder(engine, o, str(root))
    sources.sync_folder(engine, sid, emb)
    touch(f, "El servidor usa PostgreSQL como base de datos.", bump=10)
    r = sources.sync_folder(engine, sid, emb)
    assert r.n_indexed == 1
    texts = " ".join(h.text for h in search(engine, o, "servidor base de datos", emb))
    assert "PostgreSQL" in texts and "MariaDB" not in texts
    with engine.connect() as c:
        st = dict(c.execute(sa.text("SELECT status, count(*) FROM documents WHERE source_id=:s GROUP BY status"),
                            {"s": sid}).all())
        orphan_chunks = c.scalar(sa.text(
            "SELECT count(*) FROM document_chunks ch JOIN documents d ON d.id=ch.document_id "
            "WHERE d.source_id=:s AND d.status<>'active'"), {"s": sid})
    assert st == {"active": 1, "superseded": 1} and orphan_chunks == 0  # Doc 03 §12: sin derivados huérfanos


def test_content_can_return_to_a_previous_version(engine, root, emb):
    o = owner()
    f = root / "v.txt"
    touch(f, "Versión A del documento.")
    sid = sources.register_folder(engine, o, str(root))
    sources.sync_folder(engine, sid, emb)
    touch(f, "Versión B del documento.", bump=10)
    sources.sync_folder(engine, sid, emb)
    touch(f, "Versión A del documento.", bump=20)
    assert sources.sync_folder(engine, sid, emb).status == "success"


def test_deleted_file_is_retired_from_index(engine, root, emb):
    o = owner()
    f = root / "temporal.txt"
    touch(f, "Documento temporal sobre Kryptonita.")
    sid = sources.register_folder(engine, o, str(root))
    sources.sync_folder(engine, sid, emb)
    assert search(engine, o, "Documento temporal Kryptonita", emb)
    f.unlink()
    r = sources.sync_folder(engine, sid, emb)
    assert r.n_removed == 1 and search(engine, o, "Documento temporal Kryptonita", emb) == []


def test_bad_files_do_not_stop_the_run(engine, root, emb, monkeypatch):
    o = owner()
    touch(root / "bueno.txt", "Archivo correcto sobre Helios.")
    touch(root / "vacio.txt", "   ")
    (root / "roto.pdf").write_bytes(b"%PDF-1.4 roto")
    touch(root / "enorme.txt", "x" * 200)
    monkeypatch.setattr(sources, "MAX_FILE_BYTES", 100)
    sid = sources.register_folder(engine, o, str(root))
    r = sources.sync_folder(engine, sid, emb)
    assert (r.status, r.n_indexed, r.n_skipped, r.n_failed) == ("partial", 1, 2, 1)
    with engine.connect() as c:
        errors = dict(c.execute(sa.text("SELECT rel_path, error FROM source_files WHERE source_id=:s"), {"s": sid}).all())
    assert errors == {"bueno.txt": None, "vacio.txt": "NO_TEXT", "roto.pdf": "EXTRACTION_FAILED",
                      "enorme.txt": "FILE_TOO_LARGE"}


def test_concurrent_sync_of_same_source_is_refused(engine, root, emb):
    o = owner()
    touch(root / "a.txt", "contenido")
    sid = sources.register_folder(engine, o, str(root))
    with engine.connect() as c:
        assert c.scalar(sa.text("SELECT pg_try_advisory_lock(hashtext(:s))"), {"s": f"sync:{sid}"})
        assert sources.sync_folder(engine, sid, emb).status == "busy"
        c.execute(sa.text("SELECT pg_advisory_unlock(hashtext(:s))"), {"s": f"sync:{sid}"})
    assert sources.sync_folder(engine, sid, emb).status == "success"


def test_root_removed_from_allowlist_fails_the_run(engine, root, emb, monkeypatch, tmp_path):
    sid = sources.register_folder(engine, owner(), str(root))
    monkeypatch.setenv("NEXUS_FOLDER_ROOTS", str(tmp_path / "otra"))
    r = sources.sync_folder(engine, sid, emb)
    assert r.status == "failed" and r.error == "PATH_NOT_ALLOWED"


# --- Planificador (Doc 03 §13 calendario de sincronización) ---
def test_due_sources_respects_interval(engine, root, emb):
    o = owner()
    touch(root / "a.txt", "contenido")
    sid = sources.register_folder(engine, o, str(root), interval_minutes=15)
    (root / "otra").mkdir()
    manual = sources.register_folder(engine, o, str(root / "otra"))  # sin intervalo: solo manual
    now = datetime.now(timezone.utc)
    assert sid in sources.due_sources(engine, now) and manual not in sources.due_sources(engine, now)
    sources.sync_folder(engine, sid, emb, trigger="schedule")
    assert sid not in sources.due_sources(engine, now)
    assert sid in sources.due_sources(engine, now + timedelta(minutes=16))


# --- API ---
@pytest.fixture
def client(engine):
    from nexus.api.app import create_app
    return TestClient(create_app(engine=engine, model=RagModel(), api_token="test-token", embedder=HashEmbedder()))


def test_api_register_sync_and_inspect(client, root, tmp_path):
    # contenido único por ejecución: el propietario de la API es fijo y el dedupe reutilizaría otro documento
    touch(root / "manual.md", f"# Manual\n\nEl equipo Vega usa Grafana para monitorizar. ref-{uuid.uuid4().hex}")
    assert client.post("/api/v1/knowledge/sources", json={"path": str(root)}).status_code == 401
    assert client.post("/api/v1/knowledge/sources", headers=AUTH, json={"path": str(tmp_path)}).status_code == 403
    r = client.post("/api/v1/knowledge/sources", headers=AUTH, json={"path": str(root), "interval_minutes": 60})
    assert r.status_code == 201, r.text
    assert client.post("/api/v1/knowledge/sources", headers=AUTH, json={"path": str(root)}).status_code == 409
    sid = r.json()["source_id"]
    assert client.post(f"/api/v1/knowledge/sources/{sid}/sync", headers=AUTH).status_code == 202
    listed = {s["source_id"]: s for s in client.get("/api/v1/knowledge/sources", headers=AUTH).json()["sources"]}
    assert listed[sid]["last_run"]["status"] == "success" and listed[sid]["last_run"]["n_indexed"] == 1
    runs = client.get(f"/api/v1/knowledge/sources/{sid}/runs", headers=AUTH).json()["runs"]
    assert runs[0]["trigger"] == "manual"
    hits = client.get("/api/v1/knowledge/search", headers=AUTH, params={"q": "Vega Grafana"}).json()["hits"]
    mine = [h for h in hits if h["uri_ref"] and h["uri_ref"].startswith("file://") and "manual.md" in h["uri_ref"]]
    assert mine and mine[0]["title"] == "manual.md"  # ubicación del archivo, no de la carpeta
    assert client.post("/api/v1/knowledge/sources/00000000-0000-0000-0000-000000000000/sync",
                       headers=AUTH).status_code == 404


def test_files_named_like_secrets_are_never_read(engine, root, emb):
    """Visto en una carpeta real: credenciales_manager.txt en texto libre, sin formato que redact() detecte."""
    o = owner()
    touch(root / "credenciales_manager.txt", "usuario admin clave Primavera2026")
    touch(root / "config" / ".env.local", "DB=postgres")
    touch(root / "notas.txt", "Notas normales sobre el proyecto Lyra.")
    sid = sources.register_folder(engine, o, str(root))
    r = sources.sync_folder(engine, sid, emb)
    assert (r.n_indexed, r.n_skipped) == (1, 1)  # .env.local ni se escanea (archivo oculto)
    assert search(engine, o, "usuario admin clave Primavera2026", emb) == []
    with engine.connect() as c:
        assert c.scalar(sa.text("SELECT error FROM source_files WHERE source_id=:s AND rel_path LIKE 'credenciales%'"),
                        {"s": sid}) == "SENSITIVE_FILENAME"


def test_force_sync_regenerates_chunks_of_unchanged_files(engine, root, emb):
    o = owner()
    touch(root / "guia.md", "\n\n".join(["# Guía", "## Instalación", "Se instala con el asistente."]))
    sid = sources.register_folder(engine, o, str(root))
    sources.sync_folder(engine, sid, emb)
    with engine.begin() as c:  # simula chunks hechos con un chunking anterior
        c.execute(sa.text("UPDATE document_chunks SET heading='viejo' WHERE document_id IN "
                          "(SELECT id FROM documents WHERE source_id=:s)"), {"s": sid})
    assert sources.sync_folder(engine, sid, emb).n_unchanged == 1
    r = sources.sync_folder(engine, sid, emb, force=True)
    assert (r.n_indexed, r.n_unchanged) == (1, 0)
    with engine.connect() as c:
        headings = c.scalars(sa.text("SELECT ch.heading FROM document_chunks ch JOIN documents d ON d.id=ch.document_id "
                                     "WHERE d.source_id=:s AND d.status='active'"), {"s": sid}).all()
        docs = c.scalar(sa.text("SELECT count(*) FROM documents WHERE source_id=:s"), {"s": sid})
    assert headings == ["Guía › Instalación"] and docs == 1  # mismo documento, chunks nuevos
