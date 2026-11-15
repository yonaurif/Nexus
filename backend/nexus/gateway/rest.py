"""Adaptador REST (Doc 05 §7): traduce una herramienta interna a una petición HTTP concreta.

Por herramienta: método (solo GET en G1), ruta fija con plantilla, parámetros de consulta permitidos,
campos de salida declarados. Nunca acepta URL del LLM: host fijo del conector, argumentos de ruta
validados (sin `/`, sin `..`), credencial desde el entorno y fuera de datos, evidencia y logs.
"""
import string
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

from nexus.config import env
from nexus.contracts import ToolManifest
from nexus.gateway import http_safe
from nexus.gateway.registry import GatewayError

import re

PATH_ARG = re.compile(r"(?!\.{1,2}$)[A-Za-z0-9._-]{1,100}")


@dataclass
class RestTool:
    manifest: ToolManifest
    path: str
    method: str = "GET"
    query: dict[str, str] = field(default_factory=dict)         # argumento -> parámetro de consulta
    static_query: dict[str, str] = field(default_factory=dict)  # fijos (p. ej. per_page)
    fields: list[str] = field(default_factory=list)             # campos de salida permitidos
    list_items: bool = False                                    # la respuesta es una lista -> {"items": [...]}
    max_items: int = 20

    def __post_init__(self):
        if self.method != "GET":
            raise ValueError("solo GET en esta fase (G1: conectores de lectura)")
        self.path_args = {f for _, f, _, _ in string.Formatter().parse(self.path) if f}


class RestConnector:
    def __init__(self, connector_id: str, base_url: str, tools: list[RestTool], *, token_env: str | None = None,
                 headers: dict | None = None, transport=None, max_bytes: int = 500_000, timeout: float = 10.0):
        u = urlsplit(base_url)
        if u.scheme != "https" or not u.hostname:
            raise ValueError("el conector REST debe usar https")
        self.connector_id, self.base_url, self.host = connector_id, base_url.rstrip("/"), u.hostname.lower()
        self._tools = {t.manifest.tool_id: t for t in tools}
        self.token_env, self.headers = token_env, headers or {}
        self.transport, self.max_bytes, self.timeout = transport, max_bytes, timeout

    def manifests(self) -> list[ToolManifest]:
        return [t.manifest for t in self._tools.values()]

    def _headers(self) -> dict:
        h = dict(self.headers)
        if self.token_env and (token := env(self.token_env)):  # Doc 05 §7.2: el token nunca llega al LLM
            h["Authorization"] = f"Bearer {token}"
        return h

    def adapter(self, tool_id: str, args: dict) -> dict:
        tool = self._tools.get(tool_id)
        if tool is None:
            raise GatewayError("TOOL_NOT_ALLOWED", tool_id)
        allowed = tool.path_args | set(tool.query)
        if set(args) - allowed or tool.path_args - set(args):
            raise GatewayError("INPUT_INVALID", f"argumentos esperados: {sorted(allowed)}")
        for a in tool.path_args:
            if not isinstance(args[a], str) or not PATH_ARG.fullmatch(args[a]):
                raise GatewayError("INPUT_INVALID", f"{a} no válido")
        path = tool.path.format(**{a: quote(args[a], safe="") for a in tool.path_args})
        params = {**tool.static_query, **{p: str(args[a]) for a, p in tool.query.items() if a in args}}
        resp = http_safe.request("GET", self.base_url + path, params=params or None, headers=self._headers(),
                                 allowed_hosts={self.host}, max_bytes=self.max_bytes, timeout=self.timeout,
                                 transport=self.transport)
        try:
            body = resp.json()
        except ValueError:
            raise GatewayError("OUTPUT_INVALID", "la respuesta no es JSON") from None
        pick = lambda obj: {f: obj.get(f) for f in tool.fields} if isinstance(obj, dict) else None  # noqa: E731
        if tool.list_items:
            if not isinstance(body, list):
                raise GatewayError("OUTPUT_INVALID", "se esperaba una lista")
            data = {"items": [pick(x) for x in body[:tool.max_items]]}
        else:
            if not isinstance(body, dict):
                raise GatewayError("OUTPUT_INVALID", "se esperaba un objeto")
            data = pick(body)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return {"data": data, "evidence": [{"source_ref": f"{self.connector_id}:GET {path}", "retrieved_at": now}]}
