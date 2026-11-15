"""Conexión a PostgreSQL. URL desde NEXUS_DATABASE_URL o, en local, desde ../.env (compose)."""
import os
from pathlib import Path

import sqlalchemy as sa

ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


def database_url() -> str:
    if url := os.environ.get("NEXUS_DATABASE_URL"):
        return url
    pw = os.environ.get("NEXUS_DB_PASSWORD")
    if pw is None and ROOT_ENV.exists():  # ponytail: parser mínimo KEY=VALUE, sin python-dotenv
        env = dict(l.split("=", 1) for l in ROOT_ENV.read_text().splitlines() if "=" in l)
        pw = env.get("NEXUS_DB_PASSWORD")
    if not pw:
        raise RuntimeError("Define NEXUS_DATABASE_URL o NEXUS_DB_PASSWORD (.env)")
    return f"postgresql+psycopg://nexus:{pw}@127.0.0.1:5432/nexus"


def get_engine() -> sa.Engine:
    return sa.create_engine(database_url(), pool_pre_ping=True)
