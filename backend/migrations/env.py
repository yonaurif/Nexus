from alembic import context

from nexus.db import get_engine

with get_engine().connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
