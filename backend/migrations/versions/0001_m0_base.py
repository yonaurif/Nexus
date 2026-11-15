"""M0: pgvector, tareas/planes/ejecuciones (Doc 02 §13), fuentes (Doc 03 §7.1), tools (Doc 05 §6).

Revision ID: 0001
"""
from alembic import op

revision = "0001"
down_revision = None

UP = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE memory_sources (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id         text NOT NULL,
    source_type      text NOT NULL,
    display_name     text NOT NULL,
    uri_ref          text,
    auth_ref         text,            -- referencia al secret store, nunca el secreto
    permission_scope text NOT NULL,
    license          text,
    status           text NOT NULL DEFAULT 'staged',
    sync_policy      jsonb NOT NULL DEFAULT '{}',
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON memory_sources (owner_id, status);

CREATE TABLE tasks (
    id             text PRIMARY KEY,
    owner_id       text NOT NULL,
    goal           text NOT NULL,
    status         text NOT NULL,
    correlation_id text NOT NULL,
    deadline       timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON tasks (owner_id, status);

CREATE TABLE plans (
    id         text PRIMARY KEY,
    task_id    text NOT NULL REFERENCES tasks(id),
    version    int  NOT NULL,
    summary    text NOT NULL,
    limits     jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (task_id, version)
);

CREATE TABLE plan_steps (
    plan_id          text NOT NULL REFERENCES plans(id),
    step_id          text NOT NULL,
    kind             text NOT NULL,
    tool_id          text,
    depends_on       jsonb NOT NULL DEFAULT '[]',
    input            jsonb NOT NULL DEFAULT '{}',
    success_criteria jsonb NOT NULL,
    status           text NOT NULL DEFAULT 'pending',
    PRIMARY KEY (plan_id, step_id)
);

CREATE TABLE tools (
    tool_id         text PRIMARY KEY,
    connector_id    text NOT NULL,
    manifest        jsonb NOT NULL,
    definition_hash text NOT NULL,
    approved_hash   text,             -- NULL = nunca aprobada
    status          text NOT NULL,    -- review | enabled | disabled
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE tool_executions (
    id              text PRIMARY KEY,
    task_id         text NOT NULL REFERENCES tasks(id),
    step_id         text NOT NULL,
    tool_id         text NOT NULL,
    definition_hash text NOT NULL,
    arguments_hash  text NOT NULL,    -- argumentos redactados: solo hash (Doc 05 §18)
    status          text NOT NULL,
    result          jsonb,
    error           jsonb,
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    duration_ms     int,
    correlation_id  text NOT NULL
);
CREATE INDEX ON tool_executions (task_id);

CREATE TABLE execution_events (
    id             bigserial PRIMARY KEY,
    event_id       text NOT NULL UNIQUE,
    event_type     text NOT NULL,
    occurred_at    timestamptz NOT NULL DEFAULT now(),
    correlation_id text NOT NULL,
    entity_id      text NOT NULL,
    schema_version text NOT NULL DEFAULT '1.0',
    payload        jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX ON execution_events (entity_id);
CREATE INDEX ON execution_events (correlation_id);

CREATE TABLE audit_events (
    id             bigserial PRIMARY KEY,
    occurred_at    timestamptz NOT NULL DEFAULT now(),
    actor_type     text NOT NULL,
    actor_id       text NOT NULL,
    action         text NOT NULL,
    entity_type    text NOT NULL,
    entity_id      text NOT NULL,
    correlation_id text,
    details        jsonb NOT NULL DEFAULT '{}'
);

-- Append-only a nivel de DB (Doc 03 §3.1): las correcciones son eventos nuevos.
CREATE FUNCTION forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END $$;
CREATE TRIGGER execution_events_append_only BEFORE UPDATE OR DELETE ON execution_events
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
"""

DOWN = """
DROP TABLE audit_events, execution_events, tool_executions, tools, plan_steps, plans,
           tasks, memory_sources;
DROP FUNCTION forbid_mutation();
"""


def upgrade():
    op.execute(UP)


def downgrade():
    op.execute(DOWN)
