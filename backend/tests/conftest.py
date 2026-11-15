import pytest


@pytest.fixture(scope="session")
def engine():
    from alembic import command
    from alembic.config import Config
    from nexus.db import get_engine

    eng = get_engine()
    try:
        eng.connect().close()
    except Exception as e:  # ponytail: sin DB levantada, se saltan; los unitarios siguen
        pytest.skip(f"PostgreSQL no disponible: {type(e).__name__}")
    command.upgrade(Config("alembic.ini"), "head")
    return eng


@pytest.fixture
def conn(engine):
    with engine.connect() as c:
        tx = c.begin()
        yield c
        tx.rollback()
