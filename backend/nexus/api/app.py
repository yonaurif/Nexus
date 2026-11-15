"""Backend API v1 (Doc 04 §9.1). Ejecutar: uvicorn nexus.api.app:app --host 127.0.0.1"""
import json
import secrets
import time
import uuid

import sqlalchemy as sa
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from nexus.config import env
from nexus.contracts import AssistantResponse, ChatAccepted, ChatRequest, CoreEvent, TaskView
from nexus.core import pipeline, task_store
from nexus.gateway import internal_tools

OWNER = "owner"  # ponytail: un único propietario por token; perfiles/roles en Fase 4 (Doc 04 §11)
STREAM_END = {"completed", "partial", "failed", "cancelled", "expired", "needs_input"}
STREAM_MAX_S = 120


def create_app(engine=None, model=None, api_token: str | None = None, adapters=None) -> FastAPI:
    if adapters is None:
        adapters = internal_tools.ADAPTERS
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
        internal_tools.seed(c)

    app = FastAPI(title="NEXUS API", version="0.2.0")

    def auth(authorization: str = Header(default="")) -> str:
        scheme, _, given = authorization.partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(given.encode(), token.encode()):
            raise HTTPException(401, "AUTH_REQUIRED", headers={"WWW-Authenticate": "Bearer"})
        return OWNER

    def owned_task(conn, task_id: str, owner: str):
        row = conn.execute(sa.text("SELECT id, status, correlation_id FROM tasks "
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
        bg.add_task(pipeline.run, engine, model, adapters, task_id, conv, req.message, corr)
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
        return TaskView(task_id=t.id, status=t.status, correlation_id=t.correlation_id, response=resp)

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
        return {"status": "ok" if ok else "degraded",
                "components": {"database": db, "model": {"name": model.name, "status": model_status}}}

    return app


def __getattr__(name):  # `uvicorn nexus.api.app:app` sin crear la app al importar el módulo
    if name == "app":
        return create_app()
    raise AttributeError(name)
