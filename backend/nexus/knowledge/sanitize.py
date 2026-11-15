"""Detección y redacción de secretos antes de indexar o guardar (Doc 03 §5.5, §11).

ponytail: expresiones regulares para los formatos más comunes; detección de PII (correos,
teléfonos, nombres) con NER cuando llegue el Text Learning (T0).
"""
import re

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{20,}=*")),
]
# "password: x", "token=x", "api_key = x"... conserva la clave y redacta el valor.
ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|pwd|contraseña|secret|token|api[_-]?key)(\s*[:=]\s*)(?!\[REDACTED\])\S+")


def redact(text: str) -> tuple[str, list[str]]:
    found: list[str] = []
    for kind, rx in PATTERNS:
        text, n = rx.subn("[REDACTED]", text)
        if n:
            found.append(kind)
    text, n = ASSIGNMENT.subn(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)
    if n:
        found.append("credential_assignment")
    return text, found
