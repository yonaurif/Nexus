"""Configuración desde el entorno, con ../.env (raíz del repo) como respaldo local."""
import os
from functools import cache
from pathlib import Path

ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


@cache
def _dotenv() -> dict[str, str]:
    if not ROOT_ENV.exists():  # ponytail: parser mínimo KEY=VALUE, sin python-dotenv
        return {}
    return dict(l.strip().split("=", 1) for l in ROOT_ENV.read_text().splitlines()
                if "=" in l and not l.lstrip().startswith("#"))


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name) or _dotenv().get(name) or default
