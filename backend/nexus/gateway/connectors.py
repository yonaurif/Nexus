"""Conectores externos definidos en código (Doc 05 §5–6). A diferencia de las herramientas internas,
se registran en estado `review`: el propietario debe aprobarlos (POST /api/v1/connectors/tools/{id}/approve).

GitHub de solo lectura (fase G1/G2, primer conector previsto en la documentación).
Token opcional: NEXUS_GITHUB_TOKEN (fine-grained, solo lectura). Sin token: repos públicos, 60 peticiones/h.
"""
from nexus.contracts import ToolManifest
from nexus.gateway.registry import SqlToolRegistry
from nexus.gateway.rest import RestConnector, RestTool

_NAME = {"type": "string", "pattern": "^[A-Za-z0-9._-]{1,100}$"}


def _m(tool_id, description, input_props, required, output_required):
    return ToolManifest(tool_id=tool_id, connector_id="github_readonly", version="1.0.0", description=description,
                        input_schema={"type": "object", "properties": input_props, "required": required},
                        output_schema={"type": "object", "required": output_required},
                        risk_level="read", required_scopes=["github.metadata.read"], timeout_ms=10_000,
                        max_response_bytes=50_000)


def github(transport=None) -> RestConnector:
    return RestConnector(
        "github_readonly", "https://api.github.com", [
            RestTool(_m("github.repository.get", "Metadatos de un repositorio de GitHub (owner/repo): descripción, "
                        "lenguaje, rama principal, visibilidad, último push.",
                        {"owner": _NAME, "repo": _NAME}, ["owner", "repo"], ["full_name"]),
                     path="/repos/{owner}/{repo}",
                     fields=["full_name", "description", "default_branch", "visibility", "language",
                             "stargazers_count", "open_issues_count", "pushed_at", "html_url"]),
            RestTool(_m("github.user.repos", "Repositorios públicos de un usuario de GitHub, del más reciente "
                        "al más antiguo (máx. 20).", {"user": _NAME}, ["user"], ["items"]),
                     path="/users/{user}/repos", static_query={"sort": "pushed", "per_page": "20"},
                     fields=["full_name", "description", "language", "pushed_at", "visibility"], list_items=True),
        ],
        token_env="NEXUS_GITHUB_TOKEN", transport=transport,
        headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                 "User-Agent": "NEXUS"})


CONNECTORS = [github]


def seed(conn) -> dict:
    """Registra las definiciones (quedan en `review` o conservan su aprobación si el hash no cambió)
    y devuelve los adaptadores por connector_id."""
    reg, adapters = SqlToolRegistry(conn), {}
    for factory in CONNECTORS:
        c = factory()
        for m in c.manifests():
            reg.register(m)
        adapters[c.connector_id] = c.adapter
    return adapters
