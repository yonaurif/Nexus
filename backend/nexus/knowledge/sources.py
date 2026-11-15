"""Carpetas como fuentes sincronizadas (Doc 03 §4 Source Registry, §5 ciclo de vida, §6.1, §12).

Portado de Primitivo-f25 `gala/kb_service.py`: señal de cambio (mtime, size) con margen de 1 s,
manifiesto por archivo, pasadas registradas con contadores, un fallo no corta la pasada y lo
que desaparece del origen se retira del índice. Endurecido para NEXUS:
- solo raíces autorizadas (NEXUS_FOLDER_ROOTS), sin seguir enlaces simbólicos (Doc 02 §16);
- se omiten carpetas de ruido/secretos (.git, node_modules, .venv...) y temporales de Office;
- versión modificada -> `superseded`, borrada -> `deleted`, con sus chunks y vectores borrados;
- una sola pasada a la vez por fuente (advisory lock de Postgres).

ponytail: mtime+size, no hash de cada archivo en cada pasada. Techo: dos contenidos distintos con
idéntico mtime y tamaño no se detectan; subir a hash si pasa (Primitivo tiene la misma nota).
"""
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa

from nexus.config import env
from nexus.knowledge import store
from nexus.knowledge.extract import SUPPORTED_EXT, extract

log = logging.getLogger("nexus.sources")
MAX_FILE_BYTES = 50 * 1024 * 1024  # Primitivo: un PDF escaneado enorme monopoliza OCR y memoria
EXCLUDED_DIRS = {"node_modules", "__pycache__", "venv", "dist", "build", "$recycle.bin",
                 "system volume information"}
COUNTERS = ("files_total", "n_indexed", "n_unchanged", "n_skipped", "n_failed", "n_removed")
# Nombres que anuncian secretos en texto libre (p. ej. "credenciales_manager.txt", visto en una carpeta
# real): redact() solo reconoce formatos conocidos, así que estos archivos no se leen nunca.
SENSITIVE_NAME = re.compile(r"(?i)(credencial|credential|contrase|password|passwd|secret|token|"
                            r"api[_-]?key|private[_-]?key|id_rsa|\.env\b|\.pem$|\.key$|\.kdbx$)")


class SourceError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class SyncResult:
    status: str
    run_id: int | None = None
    error: str | None = None
    counts: dict = field(default_factory=lambda: dict.fromkeys(COUNTERS, 0))

    def __getattr__(self, name):  # r.n_indexed, r.files_total...
        if name in COUNTERS and "counts" in self.__dict__:
            return self.__dict__["counts"][name]
        raise AttributeError(name)


# --- Rutas autorizadas -------------------------------------------------------------------------
def allowed_roots() -> list[Path]:
    raw = env("NEXUS_FOLDER_ROOTS") or ""
    return [Path(r).resolve() for r in raw.split(";") if r.strip()]


def check_path(path: str) -> Path:
    p = Path(path).resolve()
    if not any(p == r or p.is_relative_to(r) for r in allowed_roots()):
        raise SourceError("PATH_NOT_ALLOWED")
    if not p.is_dir():
        raise SourceError("NOT_A_DIRECTORY")
    return p


def register_folder(engine, owner_id: str, path: str, *, interval_minutes: int | None = None,
                    ocr: bool = True, display_name: str | None = None) -> str:
    root = check_path(path)
    policy = {"interval_minutes": interval_minutes, "ocr": ocr}
    with engine.begin() as c:
        # Una carpeta, una fuente: dos manifiestos sobre los mismos archivos dejarían versiones viejas activas.
        if c.scalar(sa.text("SELECT 1 FROM memory_sources WHERE owner_id=:o AND source_type='folder' "
                            "AND status='active' AND lower(uri_ref)=lower(:u)"), {"o": owner_id, "u": str(root)}):
            raise SourceError("ALREADY_REGISTERED")
        return str(c.scalar(sa.text(
            "INSERT INTO memory_sources (owner_id, source_type, display_name, uri_ref, permission_scope, "
            "status, sync_policy) VALUES (:o, 'folder', :n, :u, 'owner', 'active', CAST(:p AS jsonb)) RETURNING id"),
            {"o": owner_id, "n": display_name or root.name, "u": str(root), "p": json.dumps(policy)}))


# --- Recorrido ---------------------------------------------------------------------------------
def scan(root: Path) -> list[tuple[str, Path, int, datetime]]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d.lower() not in EXCLUDED_DIRS]
        for name in filenames:
            p = Path(dirpath) / name
            if name.startswith(("~$", ".")) or p.suffix.lower() not in SUPPORTED_EXT or p.is_symlink():
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            out.append((p.relative_to(root).as_posix(), p, st.st_size,
                        datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)))
    return out


def _same_mtime(a: datetime, b: datetime) -> bool:
    return abs((a - b).total_seconds()) < 1.0


# --- Ciclo de vida de documentos (Doc 03 §6.1, §12) --------------------------------------------
def _retire(c, source_id: str, document_id: str | None, status: str) -> None:
    """Retira un documento de esta fuente si ningún otro archivo del manifiesto lo usa:
    estado `superseded`/`deleted` y borrado de chunks (vectores en cascada)."""
    if document_id is None:
        return
    still_used = c.scalar(sa.text(
        "SELECT count(*) FROM source_files WHERE document_id=:d AND status='indexed'"), {"d": document_id})
    owned = c.scalar(sa.text("SELECT source_id FROM documents WHERE id=:d"), {"d": document_id})
    if still_used == 0 and str(owned) == source_id:
        c.execute(sa.text("UPDATE documents SET status=:s WHERE id=:d"), {"s": status, "d": document_id})
        c.execute(sa.text("DELETE FROM document_chunks WHERE document_id=:d"), {"d": document_id})


def _mark(c, source_id, rel, size, mtime, status, error=None, document_id=None) -> None:
    c.execute(sa.text(
        "INSERT INTO source_files (source_id, rel_path, size_bytes, mtime, document_id, status, error, indexed_at) "
        "VALUES (:s, :r, :z, :m, :d, :st, :e, now()) ON CONFLICT (source_id, rel_path) DO UPDATE SET "
        "size_bytes=EXCLUDED.size_bytes, mtime=EXCLUDED.mtime, document_id=EXCLUDED.document_id, "
        "status=EXCLUDED.status, error=EXCLUDED.error, indexed_at=now()"),
        {"s": source_id, "r": rel, "z": size, "m": mtime, "d": document_id, "st": status, "e": error})


# --- Pasada ------------------------------------------------------------------------------------
def sync_folder(engine, source_id: str, embedder, trigger: str = "manual", force: bool = False) -> SyncResult:
    """`force`: reindexa todo aunque no haya cambiado (tras mejorar chunking/OCR)."""
    lock_key = f"sync:{source_id}"
    with engine.connect() as lock_conn:
        if not lock_conn.scalar(sa.text("SELECT pg_try_advisory_lock(hashtext(:k))"), {"k": lock_key}):
            return SyncResult("busy")
        lock_conn.commit()
        try:
            return _sync(engine, source_id, embedder, trigger, force)
        finally:
            lock_conn.execute(sa.text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": lock_key})
            lock_conn.commit()


def _sync(engine, source_id: str, embedder, trigger: str, force: bool) -> SyncResult:
    with engine.begin() as c:
        src = c.execute(sa.text("SELECT owner_id, uri_ref, sync_policy FROM memory_sources "
                                "WHERE id=:i AND source_type='folder' AND status='active'"), {"i": source_id}).first()
        if src is None:
            return SyncResult("failed", error="SOURCE_NOT_FOUND")
        run_id = c.scalar(sa.text("INSERT INTO sync_runs (source_id, trigger, status) VALUES (:s, :t, 'running') "
                                  "RETURNING id"), {"s": source_id, "t": trigger})
    res = SyncResult("running", run_id)
    k = res.counts
    try:
        root = check_path(src.uri_ref)  # la lista de raíces puede haber cambiado desde el registro
        files = scan(root)
        k["files_total"] = len(files)
        with engine.connect() as c:
            manifest = {r.rel_path: r for r in c.execute(sa.text(
                "SELECT rel_path, size_bytes, mtime, document_id, status FROM source_files WHERE source_id=:s"),
                {"s": source_id})}
        ocr = bool((src.sync_policy or {}).get("ocr", True))
        seen = set()
        for rel, path, size, mtime in files:
            seen.add(rel)
            prev = manifest.get(rel)
            if not force and prev and prev.status in ("indexed", "skipped") and prev.size_bytes == size \
                    and _same_mtime(prev.mtime, mtime):
                k["n_unchanged"] += 1
                continue
            _index_one(engine, source_id, src.owner_id, rel, path, size, mtime, prev, ocr, embedder, k, force)
        with engine.begin() as c:
            for rel, prev in manifest.items():
                if rel not in seen and prev.status != "removed":
                    _mark(c, source_id, rel, prev.size_bytes, prev.mtime, "removed")
                    _retire(c, source_id, prev.document_id, "deleted")
                    k["n_removed"] += 1
        res.status = "success" if k["n_failed"] == 0 else "partial"
    except SourceError as e:
        res.status, res.error = "failed", e.code
    except Exception as e:  # fallo inesperado: la pasada queda registrada como fallida
        log.exception("sync failure source=%s", source_id)
        res.status, res.error = "failed", type(e).__name__
    with engine.begin() as c:
        c.execute(sa.text(
            "UPDATE sync_runs SET status=:st, error=:e, finished_at=now(), files_total=:files_total, "
            "n_indexed=:n_indexed, n_unchanged=:n_unchanged, n_skipped=:n_skipped, n_failed=:n_failed, "
            "n_removed=:n_removed WHERE id=:id"), {"st": res.status, "e": res.error, "id": run_id, **k})
    return res


def _index_one(engine, source_id, owner_id, rel, path, size, mtime, prev, ocr, embedder, k, force=False) -> None:
    prev_doc = prev.document_id if prev else None
    if SENSITIVE_NAME.search(path.name):
        with engine.begin() as c:
            _mark(c, source_id, rel, size, mtime, "skipped", "SENSITIVE_FILENAME")
            _retire(c, source_id, prev_doc, "deleted")
        k["n_skipped"] += 1
        return
    if size > MAX_FILE_BYTES:
        with engine.begin() as c:
            _mark(c, source_id, rel, size, mtime, "skipped", "FILE_TOO_LARGE")
            _retire(c, source_id, prev_doc, "superseded")
        k["n_skipped"] += 1
        return
    got = extract(path, "", path.name, ocr=ocr)
    if got.error:
        status = "skipped" if got.error in ("NO_TEXT", "UNSUPPORTED_TYPE") else "failed"
        with engine.begin() as c:
            _mark(c, source_id, rel, size, mtime, status, got.error)
            _retire(c, source_id, prev_doc, "superseded")
        k["n_skipped" if status == "skipped" else "n_failed"] += 1
        return
    r = store.ingest_document(engine, owner_id, title=rel, text=got.text, embedder=embedder,
                              uri_ref=path.resolve().as_uri(), source_id=source_id, source_type="folder",
                              refresh=force)
    with engine.begin() as c:
        _mark(c, source_id, rel, size, mtime, "indexed", document_id=r.document_id)
        if prev_doc != r.document_id:
            _retire(c, source_id, prev_doc, "superseded")
    k["n_indexed"] += 1


# --- Consulta y planificación ------------------------------------------------------------------
def list_folders(conn, owner_id: str) -> list[dict]:
    rows = conn.execute(sa.text(
        "SELECT s.id, s.display_name, s.uri_ref, s.sync_policy, s.status, s.created_at, "
        "(SELECT count(*) FROM source_files f WHERE f.source_id=s.id AND f.status='indexed') AS files_indexed "
        "FROM memory_sources s WHERE s.owner_id=:o AND s.source_type='folder' ORDER BY s.created_at"),
        {"o": owner_id}).all()
    out = []
    for r in rows:
        last = runs(conn, str(r.id), limit=1)
        out.append({"source_id": str(r.id), "display_name": r.display_name, "path": r.uri_ref,
                    "sync_policy": r.sync_policy, "status": r.status, "files_indexed": r.files_indexed,
                    "last_run": last[0] if last else None})
    return out


def runs(conn, source_id: str, limit: int = 20) -> list[dict]:
    rows = conn.execute(sa.text(
        "SELECT id, trigger, status, started_at, finished_at, error, " + ", ".join(COUNTERS) +
        " FROM sync_runs WHERE source_id=:s ORDER BY id DESC LIMIT :n"), {"s": source_id, "n": limit}).all()
    return [r._asdict() for r in rows]


def owned(conn, owner_id: str, source_id: str) -> bool:
    try:
        uuid.UUID(source_id)
    except ValueError:
        return False
    return bool(conn.scalar(sa.text("SELECT 1 FROM memory_sources WHERE id=:i AND owner_id=:o AND "
                                    "source_type='folder'"), {"i": source_id, "o": owner_id}))


def due_sources(engine, now: datetime) -> list[str]:
    """Fuentes con intervalo cuya última pasada empezó hace al menos ese intervalo (o nunca)."""
    with engine.connect() as c:
        return [str(i) for i in c.scalars(sa.text(
            "SELECT s.id FROM memory_sources s WHERE s.source_type='folder' AND s.status='active' "
            "AND (s.sync_policy->>'interval_minutes') IS NOT NULL AND NOT EXISTS ("
            "  SELECT 1 FROM sync_runs r WHERE r.source_id=s.id AND r.started_at > "
            "  :now - make_interval(mins => (s.sync_policy->>'interval_minutes')::int))"), {"now": now})]
