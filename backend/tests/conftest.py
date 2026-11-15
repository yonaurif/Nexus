import os

import pytest
import sqlalchemy as sa

TEST_DB = "nexus_test"  # nunca la base de desarrollo: los tests registran herramientas y datos


@pytest.fixture(scope="session")
def engine():
    from alembic import command
    from alembic.config import Config
    from nexus.db import database_url, get_engine

    base = sa.make_url(database_url())
    try:
        admin = sa.create_engine(base, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3})
        with admin.connect() as c:
            if not c.scalar(sa.text("SELECT 1 FROM pg_database WHERE datname=:d"), {"d": TEST_DB}):
                c.execute(sa.text(f'CREATE DATABASE "{TEST_DB}"'))
        admin.dispose()
    except Exception as e:  # ponytail: sin DB levantada, se saltan; los unitarios siguen
        pytest.skip(f"PostgreSQL no disponible: {type(e).__name__}")
    os.environ["NEXUS_DATABASE_URL"] = base.set(database=TEST_DB).render_as_string(hide_password=False)
    command.upgrade(Config("alembic.ini"), "head")  # migrations/env.py usa get_engine()
    eng = get_engine()
    assert eng.url.database == TEST_DB
    return eng


@pytest.fixture
def conn(engine):
    with engine.connect() as c:
        tx = c.begin()
        yield c
        tx.rollback()
