"""C5: aprobaciones ligadas a acción y parámetros exactos (Doc 02 §13 `approvals`, Doc 05 §11).

Revision ID: 0005
"""
from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade():
    op.execute("""
    CREATE TABLE approvals (
        id             text PRIMARY KEY,
        task_id        text NOT NULL REFERENCES tasks(id),
        plan_id        text NOT NULL REFERENCES plans(id),
        step_id        text NOT NULL,
        tool_id        text NOT NULL,
        connector_id   text NOT NULL,
        risk_level     text NOT NULL,
        arguments      jsonb NOT NULL,   -- en servidor: el cliente nunca reenvía los parámetros
        arguments_hash text NOT NULL,
        summary        text NOT NULL,
        status         text NOT NULL DEFAULT 'pending',  -- pending | approved | rejected | expired | consumed
        created_at     timestamptz NOT NULL DEFAULT now(),
        expires_at     timestamptz NOT NULL,
        decided_at     timestamptz,
        decided_by     text,
        correlation_id text NOT NULL,
        UNIQUE (plan_id, step_id)
    );
    CREATE INDEX ON approvals (task_id);
    CREATE INDEX ON approvals (status);
    """)


def downgrade():
    op.execute("DROP TABLE approvals;")
