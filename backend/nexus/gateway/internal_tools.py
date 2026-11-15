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
INTERNAL_TOOLS = [TIME_NOW]


def internal_adapter(tool_id: str, arguments: dict) -> dict:
    if tool_id == "system.time.now":
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return {"data": {"utc_iso": now},
                "evidence": [{"source_ref": "internal:system_clock", "retrieved_at": now}]}
    raise KeyError(tool_id)


ADAPTERS = {"internal": internal_adapter}


def seed(conn) -> None:
    # Las herramientas internas se revisan como código (git), por eso se aprueban al arrancar.
    # Conectores externos nunca se auto-aprueban (Doc 05 §8.1).
    reg = SqlToolRegistry(conn)
    for m in INTERNAL_TOOLS:
        reg.register(m)
        reg.approve(m.tool_id)
