"""Tool Registry (Doc 05 §6, §8.5). Solo herramientas aprobadas con hash sin cambios se resuelven."""
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
        m = self._tools.get(tool_id)
        if m is None or tool_id not in self._approved_hash:
            raise GatewayError("TOOL_NOT_ALLOWED", tool_id)
        if m.definition_hash != self._approved_hash[tool_id]:
            raise GatewayError("TOOL_DEFINITION_CHANGED", tool_id)
        return m
