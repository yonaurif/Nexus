"""Herramientas internas de confianza (Doc 02 §8: cálculo exacto fuera del LLM).

Adaptador = función (tool_id, arguments) -> {"data": dict, "evidence": [{source_ref, retrieved_at}]}.
"""
from datetime import datetime, timezone

from nexus.contracts import ToolManifest
from nexus.gateway.registry import SqlToolRegistry

TIME_NOW = ToolManifest(
    tool_id="system.time.now", connector_id="internal", version="1.0.0",
    description="Devuelve la fecha y hora actuales en UTC (ISO 8601). Determinista, sin red.",
    input_schema={"type": "object", "properties": {}},
    output_schema={"type": "object", "required": ["utc_iso"]},
    risk_level="read", required_scopes=["system.time.read"], timeout_ms=1000,
)
NOTES_CREATE = ToolManifest(
    tool_id="notes.create", connector_id="internal", version="1.0.0",
    # La descripción entra en el prompt: sin "requiere aprobación", que el modelo repetía en su respuesta.
    description="Guarda una nota del propietario (título y texto) en su base de conocimiento (escritura reversible).",
    input_schema={"type": "object", "properties": {"title": {"type": "string"}, "text": {"type": "string"}},
                  "required": ["title", "text"]},
    output_schema={"type": "object", "required": ["document_id"]},
    risk_level="write_reversible", required_scopes=["notes.write"], timeout_ms=30_000, idempotent=True,
)
INTERNAL_TOOLS = [TIME_NOW, NOTES_CREATE]


def internal_adapter(tool_id: str, arguments: dict) -> dict:
    if tool_id == "system.time.now":
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return {"data": {"utc_iso": now},
                "evidence": [{"source_ref": "internal:system_clock", "retrieved_at": now}]}
    raise KeyError(tool_id)


ADAPTERS = {"internal": internal_adapter}  # solo herramientas sin estado (tests y arranque mínimo)


def build_adapters(engine, embedder) -> dict:
    """Adaptadores internos que necesitan la base de datos (notes.create)."""
    from nexus.gateway.registry import GatewayError
    from nexus.knowledge import store

    def internal(tool_id: str, arguments: dict, ctx: dict | None = None) -> dict:
        if tool_id != "notes.create":
            return internal_adapter(tool_id, arguments)
        title, text = arguments.get("title"), arguments.get("text")
        if not (isinstance(title, str) and isinstance(text, str) and title.strip() and text.strip()):
            raise GatewayError("INPUT_INVALID", "title y text deben ser texto no vacío")
        # Idempotente: mismo contenido -> mismo documento (dedupe por hash); la clave queda en uri_ref.
        r = store.ingest_document(engine, ctx["owner_id"], title=title[:300], text=text[:20_000], embedder=embedder,
                                  uri_ref=f"note://{ctx['idempotency_key']}", source_type="note")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return {"data": {"document_id": r.document_id, "chunks": r.chunks, "deduplicated": r.deduplicated},
                "evidence": [{"source_ref": f"doc:{r.document_id}#0", "retrieved_at": now}]}
    return {"internal": internal}


def seed(conn) -> None:
    # Las herramientas internas se revisan como código (git), por eso se aprueban al arrancar.
    # Conectores externos nunca se auto-aprueban (Doc 05 §8.1).
    reg = SqlToolRegistry(conn)
    for m in INTERNAL_TOOLS:
        reg.register(m)
        reg.approve(m.tool_id)
