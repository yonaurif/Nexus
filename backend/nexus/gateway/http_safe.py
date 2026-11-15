"""HTTP saliente seguro para todos los adaptadores REST (Doc 05 §7.1, §14, §17).

Portado de Primitivo_Worker `updater.py` (H-12, la versión más fuerte del ecosistema):
- host canónico: fuera 2130706433, 0x7f000001, 127.1, localhost, .local/.lan/.internal..., nombres sin punto;
- TODAS las IP que devuelve el DNS deben ser unicast globales (fuera loopback, privadas, link-local,
  metadatos 169.254.169.254, CGNAT 100.64/10, 192.0.0/24; IPv4 mapeada/6to4/Teredo se juzgan por la que esconden);
- se conecta a la IP ya validada con Host + SNI del nombre original (cierra el DNS rebinding que
  Primitivo `websearch` dejaba documentado como TOCTOU);
- redirecciones a mano, revalidadas en cada salto (máx. 3), solo https y dentro de `allowed_hosts`.
Además para NEXUS: lista de hosts por conector, límite de tamaño leído en streaming y errores con
los códigos normalizados del Doc 05 §14.
"""
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlsplit

import httpx

from nexus.gateway.registry import GatewayError

BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".corp", ".intranet",
                    ".localdomain", ".home.arpa")
REDIRECT_CODES = (301, 302, 303, 307, 308)
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_IETF = ipaddress.ip_network("192.0.0.0/24")
STATUS_CODES = {401: "AUTH_REQUIRED", 403: "SCOPE_MISSING", 404: "RESOURCE_NOT_FOUND", 429: "RATE_LIMITED"}


def _assert_public_ip(ip) -> None:
    if ip.version == 6:
        inner = ip.ipv4_mapped or ip.sixtofour or (ip.teredo[1] if ip.teredo else None)
        if inner is not None:
            ip = inner
    if not ip.is_global or ip.is_multicast or ip in _CGNAT or ip in _IETF:
        raise GatewayError("POLICY_DENIED", "destino no público")


def check_host(host: str):
    """Valida un host sin red. Devuelve la IP si es un literal público, None si es un nombre."""
    h = host.strip("[]").rstrip(".").lower()
    if not h or not h.isascii() or "%" in h:
        raise GatewayError("POLICY_DENIED", "host inválido")
    if h == "localhost" or h.endswith(BLOCKED_SUFFIXES):
        raise GatewayError("POLICY_DENIED", "host interno")
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        ip = None
    if ip is not None:
        _assert_public_ip(ip)
        return ip
    if re.fullmatch(r"[0-9a-fx.]+", h) or "." not in h:  # el SO resolvería formas que Python no reconoce
        raise GatewayError("POLICY_DENIED", "host numérico no canónico o sin dominio")
    return None


def _resolve_public(host: str, port: int) -> list[str]:
    if (ip := check_host(host)) is not None:
        return [str(ip)]
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise GatewayError("CONNECTOR_UNAVAILABLE", "el host no resuelve") from None
    addrs = list(dict.fromkeys(i[4][0].split("%")[0] for i in infos))
    if not addrs:
        raise GatewayError("CONNECTOR_UNAVAILABLE", "el host no resuelve")
    for a in addrs:  # un nombre que mezcla IP pública y privada se rechaza entero
        _assert_public_ip(ipaddress.ip_address(a))
    return addrs


def _check_url(url: str, allowed_hosts: set[str] | None):
    u = urlsplit(url)
    if u.scheme != "https" or not u.hostname or "@" in u.netloc or "\\" in url:
        raise GatewayError("POLICY_DENIED", "solo https sin credenciales en la URL")
    if allowed_hosts is not None and u.hostname.lower() not in allowed_hosts:
        raise GatewayError("POLICY_DENIED", f"host fuera de la lista del conector: {u.hostname}")
    return u


def request(method: str, url: str, *, params: dict | None = None, headers: dict | None = None,
            allowed_hosts: set[str] | None = None, max_bytes: int = 2_000_000, timeout: float = 10.0,
            max_redirects: int = 3, transport: httpx.BaseTransport | None = None) -> httpx.Response:
    allowed = {h.lower() for h in allowed_hosts} if allowed_hosts is not None else None
    current, first = url, True
    with httpx.Client(transport=transport, follow_redirects=False, timeout=timeout) as client:
        for _ in range(max_redirects + 1):
            u = _check_url(current, allowed)
            addrs = _resolve_public(u.hostname, u.port or 443)
            host_hdr = u.hostname if not u.port else f"{u.hostname}:{u.port}"
            target, last_exc = None, None
            for ip in addrs:
                pinned = httpx.URL(current).copy_with(host=ip)
                try:
                    with client.stream(method, pinned, params=params if first else None,
                                       headers={**(headers or {}), "Host": host_hdr},
                                       extensions={"sni_hostname": u.hostname}) as resp:
                        if resp.status_code in REDIRECT_CODES:
                            if not (loc := resp.headers.get("location")):
                                raise GatewayError("OUTPUT_INVALID", "redirección sin Location")
                            target = urljoin(current, loc)
                            break
                        body = bytearray()
                        for chunk in resp.iter_bytes():
                            body += chunk
                            if len(body) > max_bytes:
                                raise GatewayError("RESPONSE_TOO_LARGE", f"> {max_bytes} bytes")
                        if resp.status_code >= 400:
                            raise GatewayError(STATUS_CODES.get(resp.status_code, "CONNECTOR_UNAVAILABLE"),
                                               f"HTTP {resp.status_code}")
                        # iter_bytes() ya descomprime (y el límite cuenta bytes descomprimidos: protege de
                        # bombas gzip). Sin quitar Content-Encoding, httpx volvía a descomprimir -> zlib.error
                        # (visto contra api.github.com real; los mocks no usaban gzip).
                        hdrs = {k: v for k, v in resp.headers.items()
                                if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")}
                        return httpx.Response(resp.status_code, headers=hdrs, content=bytes(body),
                                              request=resp.request)
                except httpx.TimeoutException:
                    raise GatewayError("TIMEOUT", u.hostname) from None
                except httpx.TransportError as e:  # probar la siguiente IP del mismo nombre
                    last_exc = e
            else:
                raise GatewayError("CONNECTOR_UNAVAILABLE", type(last_exc).__name__ if last_exc else "sin IP")
            current, first = target, False
    raise GatewayError("TOO_MANY_REDIRECTS", str(max_redirects))
