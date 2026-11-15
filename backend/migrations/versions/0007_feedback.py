"""T5: clase de cada petición y correcciones del propietario (Text Learning §8, §11 `feedback_events`).

Revision ID: 0007
"""
from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade():
    op.execute("""
    ALTER TABLE tasks ADD COLUMN request_class text;   -- lo que decidió el clasificador (señal, no autorización)

    CREATE TABLE feedback_events (
        id              text PRIMARY KEY,
        owner_id        text NOT NULL,
        task_id         text NOT NULL UNIQUE REFERENCES tasks(id),  -- una corrección por petición
        kind            text NOT NULL DEFAULT 'intent_correction',
        text            text NOT NULL,                 -- mensaje original (sin secretos: se rechaza si los hay)
        predicted_label text,
        corrected_label text NOT NULL,
        status          text NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
        created_at      timestamptz NOT NULL DEFAULT now(),
        reviewed_at     timestamptz,
        reviewed_by     text
    );
    CREATE INDEX ON feedback_events (owner_id, status);
    """)


def downgrade():
    op.execute("DROP TABLE feedback_events; ALTER TABLE tasks DROP COLUMN request_class;")
