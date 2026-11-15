"""Backend API v1 (Doc 04 §9.1). Ejecutar: uvicorn nexus.api.app:app --host 127.0.0.1"""
import json
import logging
import mimetypes
import secrets
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from fastapi import (BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Query, Response,
                     UploadFile)
from fastapi.responses import FileResponse, StreamingResponse

from nexus.config import env
from nexus.contracts import (ApprovalDecision, AssistantResponse, ChatAccepted, FeedbackIn, ChatRequest, CoreEvent, DocumentIn,
                             DocumentIngested, EpisodeView, FileIngested, FolderSourceIn, KnowledgeHit,
                             TaskView)
from nexus.core import approvals, classifier, hardware, pipeline, task_store
from nexus.core.state import TaskStatus as S
from nexus.gateway import connectors, internal_tools
from nexus.gateway.registry import SqlToolRegistry
from nexus.knowledge import extract, sources
from nexus.knowledge import store as knowledge_store
from nexus.learning import registry
from nexus.learning import service as learning_service
from nexus.knowledge.sanitize import redact
from nexus.memory import episodes

OWNER = "owner"  # ponytail: un único propietario por token; perfiles/roles en Fase 4 (Doc 04 §11)
STREAM_END = {"completed", "partial", "failed", "cancelled", "expired", "needs_input", "awaiting_approval"}
FINISHED = {"completed", "partial", "failed", "cancelled", "expired"}
STREAM_MAX_S = 120
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # ponytail: límite fijo; por tipo/propietario cuando haya cuotas
SYNC_TICK_S = 60
FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


AUTO = object()


def _start_sync_scheduler(engine, embedder) -> None:
    """Revisa cada SYNC_TICK_S qué carpetas cumplieron su intervalo y las sincroniza.
    ponytail: un hilo y pasadas secuenciales (no APScheduler como Primitivo); el advisory lock
    evita solaparse con una pasada manual. Subir a cola de trabajos si hay muchas fuentes."""
    def loop():
        while True:
            time.sleep(SYNC_TICK_S)
            try:
                for sid in sources.due_sources(engine, datetime.now(timezone.utc)):
                    sources.sync_folder(engine, sid, embedder, trigger="schedule")
            except Exception:
                logging.getLogger("nexus.scheduler").exception("scheduled sync failed")
    threading.Thread(target=loop, name="nexus-sync", daemon=True).start()


def create_app(engine=None, model=None, api_token: str | None = None, adapters=None,
               embedder=AUTO, start_scheduler: bool = False) -> FastAPI:
    if embedder is AUTO:
        from nexus.knowledge.embeddings import get_embedder
        embedder = get_embedder()  # None => RAG solo full-text
    if engine is None:
        from nexus.db import get_engine
        engine = get_engine()
    if model is None:
        from nexus.core.models import get_model
        model = get_model()
    token = api_token or env("NEXUS_API_TOKEN")
    if not token:
        raise RuntimeError("Define NEXUS_API_TOKEN (.env)")

    with engine.begin() as c:
        internal_tools.seed(c)                    # internas: revisadas como código -> aprobadas
        external_adapters = connectors.seed(c)    # externas: quedan en `review` hasta que el propietario apruebe
    if adapters is None:
        adapters = {**internal_tools.build_adapters(engine, embedder), **external_adapters}
    if start_scheduler:
        _start_sync_scheduler(engine, embedder)
        registry.activate_intent(engine, embedder)  # IA propia promovida, si la hay; si no, reglas

    app = FastAPI(title="NEXUS API", version="0.2.0")

    def auth(authorization: str = Header(default="")) -> str:
        scheme, _, given = authorization.partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(given.encode(), token.encode()):
            raise HTTPException(401, "AUTH_REQUIRED", headers={"WWW-Authenticate": "Bearer"})
        return OWNER

    def owned_task(conn, task_id: str, owner: str):
        row = conn.execute(sa.text("SELECT id, status, correlation_id, request_class FROM tasks "
                                   "WHERE id=:i AND owner_id=:o"), {"i": task_id, "o": owner}).first()
        if row is None:
            raise HTTPException(404, "TASK_NOT_FOUND")
        return row

    @app.post("/api/v1/chat/messages", status_code=202, response_model=ChatAccepted)
    def post_message(req: ChatRequest, bg: BackgroundTasks, response: Response,
                     owner: str = Depends(auth)):
        corr = f"corr_{uuid.uuid4().hex}"
        with engine.begin() as c:
            conv = req.conversation_id
            if conv is None:
                conv = f"conv_{uuid.uuid4().hex}"
                c.execute(sa.text("INSERT INTO conversations (id, owner_id) VALUES (:i, :o)"),
                          {"i": conv, "o": owner})
            elif not c.scalar(sa.text("SELECT 1 FROM conversations WHERE id=:i AND owner_id=:o"),
                              {"i": conv, "o": owner}):
                raise HTTPException(404, "CONVERSATION_NOT_FOUND")
            task_id = task_store.create_task(c, owner_id=owner, goal=req.message[:200],
                                             correlation_id=corr)
            c.execute(sa.text("INSERT INTO messages (conversation_id, role, content, task_id) "
                              "VALUES (:c, 'user', :t, :k)"), {"c": conv, "t": req.message, "k": task_id})
        bg.add_task(pipeline.run, engine, model, adapters, task_id, conv, req.message, corr, embedder)
        response.headers["X-Correlation-ID"] = corr
        return ChatAccepted(task_id=task_id, conversation_id=conv, correlation_id=corr)

    @app.get("/api/v1/tasks/{task_id}", response_model=TaskView)
    def get_task(task_id: str, owner: str = Depends(auth)):
        with engine.connect() as c:
            t = owned_task(c, task_id, owner)
            msg = c.execute(sa.text("SELECT content, metadata FROM messages WHERE task_id=:i "
                                    "AND role='assistant' ORDER BY id DESC LIMIT 1"), {"i": task_id}).first()
        resp = msg and AssistantResponse(text=msg.content, task_status=t.status,
                                         warnings=msg.metadata.get("warnings", []),
                                         sources=msg.metadata.get("sources", []))
        return TaskView(task_id=t.id, status=t.status, correlation_id=t.correlation_id, response=resp,
                        request_class=t.request_class)

    @app.post("/api/v1/tasks/{task_id}/cancel")
    def cancel_task(task_id: str, owner: str = Depends(auth)):
        """Doc 02 §11.2: cooperativa. En espera -> cancelada ya; en marcha -> se corta en el próximo paso."""
        with engine.connect() as c:
            status = owned_task(c, task_id, owner).status
        if status in FINISHED:
            raise HTTPException(409, "TASK_FINISHED")
        if status in ("awaiting_approval", "needs_input"):
            pipeline.abort(engine, task_id, S.cancelled, "Tarea cancelada; no se ha ejecutado nada.", "CANCELLED")
            return {"task_id": task_id, "status": "cancelled"}
        with engine.begin() as c:
            task_store.set_status(c, task_id, S.cancel_requested)
        return {"task_id": task_id, "status": "cancel_requested",
                "note": "Una acción ya enviada a un sistema externo puede no ser reversible."}

    # --- Aprobaciones (Doc 05 §11) ---
    @app.get("/api/v1/approvals")
    def list_approvals(status: str | None = Query(None, pattern="^(pending|approved|rejected|expired|consumed)$"),
                       owner: str = Depends(auth)):
        with engine.connect() as c:
            return {"approvals": approvals.list_for_owner(c, owner, status)}

    @app.post("/api/v1/approvals/{approval_id}/decision")
    def decide_approval(approval_id: str, body: ApprovalDecision, bg: BackgroundTasks, owner: str = Depends(auth)):
        try:
            with engine.begin() as c:
                task_id = approvals.decide(c, approval_id, owner, body.decision)
                state = approvals.task_state(c, task_id)
        except approvals.ApprovalError as e:
            if e.code == "APPROVAL_EXPIRED":
                pipeline.abort(engine, e.task_id, S.expired, "La aprobación caducó; no se ha ejecutado nada.",
                               "APPROVAL_EXPIRED")
            raise HTTPException(404 if e.code == "APPROVAL_NOT_FOUND" else 409, e.code)
        if state == "rejected":
            pipeline.abort(engine, task_id, S.cancelled, "Has rechazado la acción; no se ha ejecutado nada.",
                           "APPROVAL_REJECTED")
        elif state == "approved":
            bg.add_task(pipeline.resume, engine, model, adapters, task_id, embedder)
        return {"approval_id": approval_id, "decision": body.decision, "task_state": state}

    @app.get("/api/v1/tasks/{task_id}/events")
    def task_events(task_id: str, owner: str = Depends(auth),
                    last_event_id: int = Header(default=0, alias="Last-Event-ID")):
        with engine.connect() as c:
            owned_task(c, task_id, owner)

        def stream():
            # ponytail: polling a la tabla cada 0,5 s (techo: 1 query/cliente/0,5 s);
            # pasar a LISTEN/NOTIFY si hay muchos clientes simultáneos.
            last, deadline = last_event_id, time.monotonic() + STREAM_MAX_S
            while time.monotonic() < deadline:
                with engine.connect() as c:
                    rows = c.execute(sa.text(
                        "SELECT id, event_id, event_type, occurred_at, correlation_id, entity_id, "
                        "schema_version, payload FROM execution_events "
                        "WHERE entity_id=:t AND id>:l ORDER BY id"), {"t": task_id, "l": last}).all()
                    status = c.scalar(sa.text("SELECT status FROM tasks WHERE id=:t"), {"t": task_id})
                for r in rows:
                    ev = CoreEvent(**{k: v for k, v in r._asdict().items() if k != "id"})
                    last = r.id
                    yield (f"id: {r.id}\nevent: {r.event_type}\n"
                           f"data: {json.dumps(ev.model_dump(mode='json'))}\n\n")
                if not rows and status in STREAM_END:
                    return
                if not rows:
                    time.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    # --- Memory & Knowledge (Doc 03 §14, Doc 04 §9.1) ---
    @app.post("/api/v1/knowledge/documents", status_code=201, response_model=DocumentIngested)
    def ingest(doc: DocumentIn, owner: str = Depends(auth)):
        # ponytail: síncrono; cola de ingesta (Doc 03 §4) cuando haya documentos grandes o conectores
        r = knowledge_store.ingest_document(engine, owner, title=doc.title, text=doc.text, embedder=embedder,
                                            uri_ref=doc.uri_ref, mime_type=doc.mime_type)
        return DocumentIngested(**vars(r))

    @app.post("/api/v1/knowledge/files", status_code=201, response_model=FileIngested)
    def ingest_file(file: UploadFile = File(...), title: str | None = Form(None, max_length=300),
                    owner: str = Depends(auth)):
        name = Path(file.filename or "archivo").name
        suffix = Path(name).suffix.lower()
        if suffix not in extract.SUPPORTED_EXT:
            raise HTTPException(415, "UNSUPPORTED_TYPE")
        data = file.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "FILE_TOO_LARGE")
        # Archivo temporal propio con la extensión validada; nunca se usa el nombre del cliente como ruta.
        with tempfile.TemporaryDirectory(prefix="nexus_upload_") as tmp:
            path = Path(tmp) / f"upload{suffix}"
            path.write_bytes(data)
            mime = file.content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
            got = extract.extract(path, mime, name)
        if got.error:
            raise HTTPException(422, got.error)
        r = knowledge_store.ingest_document(engine, owner, title=title or name, text=got.text,
                                            embedder=embedder, uri_ref=f"upload://{name}", mime_type=mime,
                                            source_type="file_upload")
        return FileIngested(**vars(r), ocr_used=got.ocr_used)

    # --- Carpetas sincronizadas (Doc 03 §4–5) ---
    @app.post("/api/v1/knowledge/sources", status_code=201)
    def add_source(src: FolderSourceIn, owner: str = Depends(auth)):
        try:
            sid = sources.register_folder(engine, owner, src.path, interval_minutes=src.interval_minutes,
                                          ocr=src.ocr, display_name=src.display_name)
        except sources.SourceError as e:
            raise HTTPException({"PATH_NOT_ALLOWED": 403, "ALREADY_REGISTERED": 409}.get(e.code, 422), e.code)
        return {"source_id": sid}

    @app.get("/api/v1/knowledge/sources")
    def list_sources(owner: str = Depends(auth)):
        with engine.connect() as c:
            return {"sources": sources.list_folders(c, owner)}

    def owned_source(source_id: str, owner: str) -> None:
        with engine.connect() as c:
            if not sources.owned(c, owner, source_id):
                raise HTTPException(404, "SOURCE_NOT_FOUND")

    @app.post("/api/v1/knowledge/sources/{source_id}/sync", status_code=202)
    def sync_source(source_id: str, bg: BackgroundTasks, force: bool = False, owner: str = Depends(auth)):
        owned_source(source_id, owner)
        bg.add_task(sources.sync_folder, engine, source_id, embedder, "manual", force)
        return {"source_id": source_id, "status": "queued"}

    @app.get("/api/v1/knowledge/sources/{source_id}/runs")
    def source_runs(source_id: str, owner: str = Depends(auth)):
        owned_source(source_id, owner)
        with engine.connect() as c:
            return {"runs": sources.runs(c, source_id)}

    @app.get("/api/v1/knowledge/search")
    def knowledge_search(q: str = Query(min_length=1, max_length=500), k: int = Query(5, ge=1, le=20),
                         owner: str = Depends(auth)):
        with engine.connect() as c:
            hits = knowledge_store.search(c, owner, q, embedder, k=k)
        return {"hits": [KnowledgeHit(source_ref=h.source_ref, **{f: getattr(h, f) for f in (
            "document_id", "title", "heading", "text", "uri_ref", "char_start", "char_end", "score")})
            for h in hits]}

    @app.get("/api/v1/memory/episodes")
    def list_episodes(event_type: str | None = None, since: datetime | None = None,
                      until: datetime | None = None, limit: int = Query(50, ge=1, le=100),
                      owner: str = Depends(auth)):
        with engine.connect() as c:
            rows = episodes.search(c, owner, event_type=event_type, since=since, until=until, limit=limit)
        return {"episodes": [EpisodeView(**{k: getattr(r, k) for k in EpisodeView.model_fields}) for r in rows]}

    # --- Conectores y herramientas (Doc 05 §13) ---
    @app.get("/api/v1/connectors")
    def list_connectors(owner: str = Depends(auth)):
        with engine.connect() as c:
            return {"tools": SqlToolRegistry(c).list_all()}

    @app.post("/api/v1/connectors/tools/{tool_id}/approve")
    def approve_tool(tool_id: str, owner: str = Depends(auth)):
        # ponytail: el token único es el propietario; sesión administrativa reforzada (Doc 05 §6.2 admin) en Fase 4
        with engine.begin() as c:
            if not SqlToolRegistry(c).approve(tool_id):
                raise HTTPException(404, "TOOL_NOT_FOUND")
            audit(c, owner, "tool.approved", tool_id)
        return {"tool_id": tool_id, "status": "enabled"}

    @app.post("/api/v1/connectors/tools/{tool_id}/disable")
    def disable_tool(tool_id: str, owner: str = Depends(auth)):
        with engine.begin() as c:
            if not SqlToolRegistry(c).disable(tool_id):
                raise HTTPException(404, "TOOL_NOT_FOUND")
            audit(c, owner, "tool.disabled", tool_id)
        return {"tool_id": tool_id, "status": "disabled"}

    def audit(c, actor: str, action: str, tool_id: str) -> None:
        c.execute(sa.text("INSERT INTO audit_events (actor_type, actor_id, action, entity_type, entity_id) "
                          "VALUES ('owner', :a, :ac, 'tool', :t)"), {"a": actor, "ac": action, "t": tool_id})

    @app.get("/api/v1/system/health")
    def health():
        # Doc 04 §12: estados reales, nunca métricas inventadas.
        try:
            with engine.connect() as c:
                c.execute(sa.text("SELECT 1"))
            db = "ok"
        except Exception:
            db = "unavailable"
        model_status = model.health()
        ok = db == "ok" and model_status in ("ok", "stub")
        emb = ({"name": embedder.model_name, "status": "configured"} if embedder is not None
               else {"name": None, "status": "not_configured"})  # sin embedder el RAG es solo full-text
        model_info = {"name": model.name, "status": model_status}
        if details := getattr(model, "details", None):  # cadena GGUF: activo, candidatos, capas en GPU
            model_info.update(details())
        return {"status": "ok" if ok else "degraded",
                "components": {"database": db, "model": model_info, "embeddings": emb,
                               "hardware": hardware.get_hardware_info()}}

    # --- IA propia: modelos entrenados (Text Learning §8, §11; Learning Center Doc 04 §10) ---
    @app.get("/api/v1/learning/models")
    def learning_models(owner: str = Depends(auth)):
        with engine.connect() as c:
            return {"models": registry.list_models(c), "active_intent": bool(classifier.active_model())}

    @app.post("/api/v1/learning/models/{model_id}/promote")
    def promote_model(model_id: str, owner: str = Depends(auth)):
        try:
            with engine.begin() as c:
                registry.promote(c, model_id)
                c.execute(sa.text("INSERT INTO audit_events (actor_type, actor_id, action, entity_type, entity_id) "
                                  "VALUES ('owner', :o, 'model.promoted', 'model', :m)"), {"o": owner, "m": model_id})
        except registry.RegistryError as e:
            raise HTTPException(404 if e.code == "MODEL_NOT_FOUND" else 409, e.code)
        loaded = registry.activate_intent(engine, embedder)
        return {"model_id": model_id, "status": "active", "loaded": loaded}

    # --- T5: correcciones del propietario -> revisión -> reentrenamiento (Text Learning §8) ---
    @app.post("/api/v1/tasks/{task_id}/feedback", status_code=201)
    def task_feedback(task_id: str, body: FeedbackIn, owner: str = Depends(auth)):
        with engine.begin() as c:
            t = owned_task(c, task_id, owner)
            if t.request_class == body.correct_label:
                raise HTTPException(422, "SAME_LABEL")
            text = c.scalar(sa.text("SELECT content FROM messages WHERE task_id=:t AND role='user'"), {"t": task_id})
            if redact(text or "")[1]:  # TL §5.5: un secreto nunca entra en un dataset
                raise HTTPException(422, "SECRET_DETECTED")
            if c.scalar(sa.text("SELECT 1 FROM feedback_events WHERE task_id=:t"), {"t": task_id}):
                raise HTTPException(409, "FEEDBACK_EXISTS")
            fid = f"fb_{uuid.uuid4().hex}"
            c.execute(sa.text("INSERT INTO feedback_events (id, owner_id, task_id, text, predicted_label, "
                              "corrected_label) VALUES (:i, :o, :t, :x, :p, :c)"),
                      {"i": fid, "o": owner, "t": task_id, "x": text, "p": t.request_class, "c": body.correct_label})
        return {"feedback_id": fid, "status": "pending"}

    @app.get("/api/v1/learning/feedback")
    def list_feedback(status: str | None = Query(None, pattern="^(pending|approved|rejected)$"),
                      owner: str = Depends(auth)):
        with engine.connect() as c:
            rows = c.execute(sa.text(
                "SELECT id, task_id, text, predicted_label, corrected_label, status, created_at, reviewed_at "
                "FROM feedback_events WHERE owner_id=:o AND (CAST(:s AS text) IS NULL OR status=:s) "
                "ORDER BY created_at DESC LIMIT 200"), {"o": owner, "s": status}).all()
        return {"feedback": [{"feedback_id": r.id, **{k: v for k, v in r._asdict().items() if k != "id"}}
                             for r in rows]}

    @app.post("/api/v1/learning/feedback/{feedback_id}/review")
    def review_feedback(feedback_id: str, body: ApprovalDecision, owner: str = Depends(auth)):
        """El propietario confirma que la corrección pasa a ser una etiqueta permanente (TL §8 paso 2)."""
        with engine.begin() as c:
            status = c.scalar(sa.text("SELECT status FROM feedback_events WHERE id=:i AND owner_id=:o FOR UPDATE"),
                              {"i": feedback_id, "o": owner})
            if status is None:
                raise HTTPException(404, "FEEDBACK_NOT_FOUND")
            if status != "pending":
                raise HTTPException(409, "FEEDBACK_ALREADY_REVIEWED")
            new = "approved" if body.decision == "approve" else "rejected"
            c.execute(sa.text("UPDATE feedback_events SET status=:s, reviewed_at=now(), reviewed_by=:o WHERE id=:i"),
                      {"s": new, "o": owner, "i": feedback_id})
        return {"feedback_id": feedback_id, "status": new}

    @app.post("/api/v1/learning/train", status_code=202)
    def retrain(bg: BackgroundTasks, owner: str = Depends(auth)):
        """Entrena offline en segundo plano y registra un CANDIDATO (nunca lo promueve)."""
        def job():
            try:
                learning_service.train_and_register(engine, encoder=embedder)
            except learning_service.Busy:
                logging.getLogger("nexus.learning").info("entrenamiento ya en curso")
        bg.add_task(job)
        return {"status": "training"}

    # --- Conversaciones (Doc 04 §9.1) ---
    @app.get("/api/v1/chat/conversations")
    def list_conversations(owner: str = Depends(auth)):
        with engine.connect() as c:
            rows = c.execute(sa.text(
                "SELECT c.id, c.created_at, (SELECT content FROM messages WHERE conversation_id=c.id AND role='user' "
                "ORDER BY id LIMIT 1) AS title, (SELECT count(*) FROM messages WHERE conversation_id=c.id) AS n, "
                "(SELECT max(created_at) FROM messages WHERE conversation_id=c.id) AS last_at "
                "FROM conversations c WHERE c.owner_id=:o ORDER BY last_at DESC NULLS LAST LIMIT 50"), {"o": owner}).all()
        return {"conversations": [{"conversation_id": r.id, "title": (r.title or "")[:80], "messages": r.n,
                                   "created_at": r.created_at, "last_at": r.last_at} for r in rows]}

    @app.get("/api/v1/chat/conversations/{conversation_id}")
    def get_conversation(conversation_id: str, owner: str = Depends(auth)):
        with engine.connect() as c:
            if not c.scalar(sa.text("SELECT 1 FROM conversations WHERE id=:i AND owner_id=:o"),
                            {"i": conversation_id, "o": owner}):
                raise HTTPException(404, "CONVERSATION_NOT_FOUND")
            rows = c.execute(sa.text(
                "SELECT m.id, m.role, m.content, m.task_id, m.metadata, m.created_at, t.status AS task_status, "
                "t.request_class "
                "FROM messages m LEFT JOIN tasks t ON t.id = m.task_id WHERE m.conversation_id=:i ORDER BY m.id"),
                {"i": conversation_id}).all()
        return {"conversation_id": conversation_id, "messages": [
            {"id": r.id, "role": r.role, "content": r.content, "task_id": r.task_id, "task_status": r.task_status,
             "warnings": (r.metadata or {}).get("warnings", []), "sources": (r.metadata or {}).get("sources", []),
             "request_class": r.request_class,
             "created_at": r.created_at} for r in rows]}

    _serve_frontend(app)
    return app


def _serve_frontend(app: FastAPI) -> None:
    """Sirve el build de la interfaz (frontend/dist) en el mismo proceso: un solo puerto en producción,
    sin CORS. Las rutas del cliente devuelven index.html; /api/* nunca queda tapado."""
    dist = Path(env("NEXUS_FRONTEND_DIST") or FRONTEND_DIST).resolve()
    if not (dist / "index.html").is_file():
        return

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "NOT_FOUND")
        target = (dist / path).resolve()
        if path and target.is_file() and target.is_relative_to(dist):  # sin salir de dist (../)
            return FileResponse(target)
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})


def __getattr__(name):  # `uvicorn nexus.api.app:app` sin crear la app al importar el módulo
    if name == "app":
        return create_app(start_scheduler=True)
    raise AttributeError(name)
