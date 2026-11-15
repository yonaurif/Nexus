"""Conexión a PostgreSQL. URL desde NEXUS_DATABASE_URL o NEXUS_DB_PASSWORD (compose local)."""
import sqlalchemy as sa

from nexus.config import env


def database_url() -> str:
    if url := env("NEXUS_DATABASE_URL"):
        return url
    if not (pw := env("NEXUS_DB_PASSWORD")):
        raise RuntimeError("Define NEXUS_DATABASE_URL o NEXUS_DB_PASSWORD (.env)")
    return f"postgresql+psycopg://nexus:{pw}@127.0.0.1:5432/nexus"


def get_engine() -> sa.Engine:
    return sa.create_engine(database_url(), pool_pre_ping=True, connect_args={"connect_timeout": 3})
