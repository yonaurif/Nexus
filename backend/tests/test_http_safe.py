"""HTTP seguro hacia fuera (Doc 05 §7.1, §14, §17). Casos portados de Primitivo_Worker tests/test_ssrf.py
y Primitivo tests/test_websearch.py: host canónico, DNS validado, IP fijada, redirecciones revalidadas."""
import socket

import httpx
import pytest

from nexus.gateway import http_safe
from nexus.gateway.registry import GatewayError

BAD_HOSTS = [
    "2130706433", "0x7f000001", "0177.0.0.1", "127.1", "0", "2852039166", "0xa9.0xfe.0xa9.0xfe", "127.0.0.1",
    "10.1.2.3", "169.254.169.254", "100.64.0.1", "100.100.100.200", "192.0.0.192", "::1", "::ffff:127.0.0.1",
    "fd00:ec2::254", "localhost", "LOCALHOST.", "foo.localhost", "printer.local", "metadata.google.internal",
    "nas.lan", "intranet", "2002:7f00:1::",
]


@pytest.mark.parametrize("host", BAD_HOSTS)
def test_check_host_rejects_internal_and_noncanonical(host):
    with pytest.raises(GatewayError, match="POLICY_DENIED"):
        http_safe.check_host(host)


@pytest.mark.parametrize("host", ["api.github.com", "8.8.8.8", "2606:4700:4700::1111"])
def test_check_host_accepts_public(host):
    http_safe.check_host(host)


# --- Peticiones con DNS y transporte simulados ---
def dns(monkeypatch, table):
    def fake(host, port, *a, **k):
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))
                for ip in table[host]]
    monkeypatch.setattr(socket, "getaddrinfo", fake)


def transport(handler):
    calls = []

    def wrapped(request):
        calls.append(request)
        return handler(request)
    return httpx.MockTransport(wrapped), calls


def test_connects_to_validated_ip_with_host_and_sni(monkeypatch):
    dns(monkeypatch, {"api.example.com": ["93.184.216.34"]})
    t, calls = transport(lambda r: httpx.Response(200, json={"ok": True}))
    r = http_safe.request("GET", "https://api.example.com/v1/x?a=1", transport=t)
    assert r.json() == {"ok": True}
    req = calls[0]
    assert req.url.host == "93.184.216.34" and req.headers["host"] == "api.example.com"  # IP fijada (anti rebinding)
    assert req.extensions["sni_hostname"] == "api.example.com"


def test_dns_answer_mixing_public_and_private_is_rejected(monkeypatch):
    dns(monkeypatch, {"rebind.example.com": ["93.184.216.34", "127.0.0.1"]})
    t, calls = transport(lambda r: httpx.Response(200))
    with pytest.raises(GatewayError, match="POLICY_DENIED"):
        http_safe.request("GET", "https://rebind.example.com/", transport=t)
    assert calls == []


@pytest.mark.parametrize("url", ["http://api.example.com/", "file:///etc/passwd", "https://user:pw@api.example.com/",
                                 "ftp://api.example.com/"])
def test_only_https_without_credentials(monkeypatch, url):
    dns(monkeypatch, {"api.example.com": ["93.184.216.34"]})
    with pytest.raises(GatewayError, match="POLICY_DENIED"):
        http_safe.request("GET", url, transport=transport(lambda r: httpx.Response(200))[0])


def test_redirect_to_internal_host_is_not_followed(monkeypatch):
    dns(monkeypatch, {"cdn.example.com": ["93.184.216.34"], "evil.example.com": ["10.0.0.5"]})
    t, calls = transport(lambda r: httpx.Response(302, headers={"location": "https://evil.example.com/admin"}))
    with pytest.raises(GatewayError, match="POLICY_DENIED"):
        http_safe.request("GET", "https://cdn.example.com/a", transport=t)
    assert len(calls) == 1  # nunca se conectó al destino interno


def test_redirect_outside_allowlist_is_rejected_and_inside_is_followed(monkeypatch):
    dns(monkeypatch, {"api.example.com": ["93.184.216.34"], "other.example.com": ["93.184.216.35"]})
    hops = iter([httpx.Response(301, headers={"location": "/v2/x"}), httpx.Response(200, json={"v": 2})])
    t, calls = transport(lambda r: next(hops))
    r = http_safe.request("GET", "https://api.example.com/v1/x", allowed_hosts={"api.example.com"}, transport=t)
    assert r.json() == {"v": 2} and calls[1].url.path == "/v2/x"
    t2, _ = transport(lambda r: httpx.Response(302, headers={"location": "https://other.example.com/"}))
    with pytest.raises(GatewayError, match="POLICY_DENIED"):
        http_safe.request("GET", "https://api.example.com/", allowed_hosts={"api.example.com"}, transport=t2)
    with pytest.raises(GatewayError, match="POLICY_DENIED"):
        http_safe.request("GET", "https://other.example.com/", allowed_hosts={"api.example.com"}, transport=t2)


def test_too_many_redirects(monkeypatch):
    dns(monkeypatch, {"api.example.com": ["93.184.216.34"]})
    t, _ = transport(lambda r: httpx.Response(302, headers={"location": "/otra"}))
    with pytest.raises(GatewayError, match="TOO_MANY_REDIRECTS"):
        http_safe.request("GET", "https://api.example.com/", transport=t)


def test_response_size_limit(monkeypatch):
    dns(monkeypatch, {"api.example.com": ["93.184.216.34"]})
    t, _ = transport(lambda r: httpx.Response(200, content=b"x" * 5000))
    with pytest.raises(GatewayError, match="RESPONSE_TOO_LARGE"):
        http_safe.request("GET", "https://api.example.com/", max_bytes=1000, transport=t)


@pytest.mark.parametrize("status,code", [(401, "AUTH_REQUIRED"), (403, "SCOPE_MISSING"), (404, "RESOURCE_NOT_FOUND"),
                                         (429, "RATE_LIMITED"), (500, "CONNECTOR_UNAVAILABLE"),
                                         (503, "CONNECTOR_UNAVAILABLE")])
def test_http_errors_are_normalized(monkeypatch, status, code):
    dns(monkeypatch, {"api.example.com": ["93.184.216.34"]})
    t, _ = transport(lambda r: httpx.Response(status))
    with pytest.raises(GatewayError, match=code):
        http_safe.request("GET", "https://api.example.com/", transport=t)


def test_timeout_is_normalized(monkeypatch):
    dns(monkeypatch, {"api.example.com": ["93.184.216.34"]})

    def slow(request):
        raise httpx.ReadTimeout("lento", request=request)
    with pytest.raises(GatewayError, match="TIMEOUT"):
        http_safe.request("GET", "https://api.example.com/", transport=httpx.MockTransport(slow))


def test_gzip_responses_are_decoded_once_and_limited_after_decompression(monkeypatch):
    """Regresión real (api.github.com): el cuerpo ya descomprimido se volvía a descomprimir."""
    import gzip
    import json as _json
    dns(monkeypatch, {"api.example.com": ["93.184.216.34"]})
    payload = _json.dumps({"full_name": "yonaurif/Nexus"}).encode()
    gz = lambda r: httpx.Response(200, content=gzip.compress(payload),
                                  headers={"content-encoding": "gzip", "content-type": "application/json"})
    assert http_safe.request("GET", "https://api.example.com/", transport=transport(gz)[0]).json() == {
        "full_name": "yonaurif/Nexus"}
    bomb = lambda r: httpx.Response(200, content=gzip.compress(b"0" * 5_000_000), headers={"content-encoding": "gzip"})
    with pytest.raises(GatewayError, match="RESPONSE_TOO_LARGE"):  # 5 MB descomprimidos, pocos KB por la red
        http_safe.request("GET", "https://api.example.com/", max_bytes=100_000, transport=transport(bomb)[0])
