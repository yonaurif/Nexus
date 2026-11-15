"""Tool Registry (Doc 05 §6, §8.5). Solo herramientas aprobadas con hash sin cambios se resuelven."""
import sqlalchemy as sa

from nexus.contracts import ToolManifest


class GatewayError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code = code


class ToolRegistry:
    # ponytail: en memoria; pasa a tabla PostgreSQL en M0
    def __init__(self):
        self._tools: dict[str, ToolManifest] = {}
        self._approved_hash: dict[str, str] = {}

    def register(self, manifest: ToolManifest) -> None:
        self._tools[manifest.tool_id] = manifest  # queda en review hasta approve()

    def approve(self, tool_id: str) -> None:
        self._approved_hash[tool_id] = self._tools[tool_id].definition_hash

    def resolve(self, tool_id: str) -> ToolManifest:
        return _checked(tool_id, self._tools.get(tool_id), self._approved_hash.get(tool_id))


def _checked(tool_id: str, m: ToolManifest | None, approved_hash: str | None) -> ToolManifest:
    if m is None or approved_hash is None:
        raise GatewayError("TOOL_NOT_ALLOWED", tool_id)
    if m.definition_hash != approved_hash:
        raise GatewayError("TOOL_DEFINITION_CHANGED", tool_id)
    return m


class SqlToolRegistry:
    """Misma interfaz que ToolRegistry sobre la tabla `tools` (M0)."""

    def __init__(self, conn):
        self.conn = conn

    def register(self, manifest: ToolManifest) -> None:
        # Re-registrar conserva approved_hash: si la definición cambió, queda en review.
        self.conn.execute(sa.text("""
            INSERT INTO tools (tool_id, connector_id, manifest, definition_hash, status)
            VALUES (:t, :c, CAST(:m AS jsonb), :h, 'review')
            ON CONFLICT (tool_id) DO UPDATE SET
                connector_id = EXCLUDED.connector_id, manifest = EXCLUDED.manifest,
                definition_hash = EXCLUDED.definition_hash, updated_at = now(),
                status = CASE WHEN tools.approved_hash = EXCLUDED.definition_hash
                              THEN tools.status ELSE 'review' END"""),
            {"t": manifest.tool_id, "c": manifest.connector_id,
             "m": manifest.model_dump_json(exclude={"definition_hash"}), "h": manifest.definition_hash})

    def approve(self, tool_id: str) -> bool:
        return self.conn.execute(sa.text(
            "UPDATE tools SET approved_hash = definition_hash, status = 'enabled', updated_at = now() "
            "WHERE tool_id = :t"), {"t": tool_id}).rowcount > 0

    def disable(self, tool_id: str) -> bool:
        """Doc 05 aceptación #15: revocar sin desplegar. Re-registrar no la reactiva."""
        return self.conn.execute(sa.text("UPDATE tools SET status = 'disabled', updated_at = now() "
                                         "WHERE tool_id = :t"), {"t": tool_id}).rowcount > 0

    def list_all(self) -> list[dict]:
        rows = self.conn.execute(sa.text(
            "SELECT tool_id, connector_id, status, definition_hash, approved_hash, manifest, updated_at "
            "FROM tools ORDER BY connector_id, tool_id")).all()
        return [{"tool_id": r.tool_id, "connector_id": r.connector_id, "status": r.status,
                 "risk_level": r.manifest.get("risk_level"), "description": r.manifest.get("description"),
                 "definition_hash": r.definition_hash, "approved": r.approved_hash == r.definition_hash,
                 "updated_at": r.updated_at} for r in rows]

    def list_enabled(self) -> list[ToolManifest]:
        """Herramientas aprobadas y sin cambios: lo único que se ofrece al Planner."""
        rows = self.conn.execute(sa.text(
            "SELECT manifest, approved_hash FROM tools WHERE status = 'enabled' ORDER BY tool_id")).all()
        tools = [ToolManifest(**r.manifest) for r in rows]
        return [m for m, r in zip(tools, rows) if m.definition_hash == r.approved_hash]

    def resolve(self, tool_id: str) -> ToolManifest:
        row = self.conn.execute(sa.text(
            "SELECT manifest, approved_hash, status FROM tools WHERE tool_id = :t"), {"t": tool_id}).first()
        if row is None or row.status == "disabled":
            raise GatewayError("TOOL_NOT_ALLOWED", tool_id)
        # El hash se recalcula desde el manifest guardado, no se confía en la columna.
        return _checked(tool_id, ToolManifest(**row.manifest), row.approved_hash)
