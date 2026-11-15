"""C1: conversations / messages (Doc 02 §13, Doc 04 Fase 1).

Revision ID: 0002
"""
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade():
    op.execute("""
    CREATE TABLE conversations (
        id         text PRIMARY KEY,
        owner_id   text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON conversations (owner_id);

    CREATE TABLE messages (
        id              bigserial PRIMARY KEY,
        conversation_id text NOT NULL REFERENCES conversations(id),
        role            text NOT NULL CHECK (role IN ('user', 'assistant')),
        content         text NOT NULL,
        task_id         text REFERENCES tasks(id),
        metadata        jsonb NOT NULL DEFAULT '{}',
        created_at      timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON messages (conversation_id, id);
    CREATE INDEX ON messages (task_id);
    """)


def downgrade():
    op.execute("DROP TABLE messages, conversations;")
