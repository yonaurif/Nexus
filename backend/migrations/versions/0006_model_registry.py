"""T1: registro de modelos propios (Text Learning §11 `model_registry`, Doc 03 §7.5).

Revision ID: 0006
"""
from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade():
    op.execute("""
    CREATE TABLE model_registry (
        id              text PRIMARY KEY,
        task            text NOT NULL,         -- intent_es, ...
        version         text NOT NULL,
        dataset_version text NOT NULL,
        metrics         jsonb NOT NULL,        -- informe completo (test bloqueado, línea base, umbral)
        threshold       double precision NOT NULL,
        artifact_path   text NOT NULL,         -- en disco, fuera de la DB (TL §11)
        artifact_sha256 text NOT NULL,         -- solo se deserializa si coincide
        status          text NOT NULL DEFAULT 'candidate',  -- candidate | active | retired
        created_at      timestamptz NOT NULL DEFAULT now(),
        promoted_at     timestamptz
    );
    CREATE UNIQUE INDEX model_registry_one_active ON model_registry (task) WHERE status = 'active';
    """)


def downgrade():
    op.execute("DROP TABLE model_registry;")
