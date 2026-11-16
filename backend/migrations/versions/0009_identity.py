"""Identidad y perfil (Doc 03 §3.5): almacén propio, separado de la memoria. Solo lo cambia el propietario
autenticado por la API; ninguna inferencia ni mensaje del chat lo toca.

Revision ID: 0009
"""
from alembic import op

revision = "0009"
down_revision = "0008"


def upgrade():
    op.execute("""
    CREATE TABLE identity (
        owner_id text PRIMARY KEY,
        assistant_name text NOT NULL DEFAULT 'NEXUS',
        owner_name text,
        updated_at timestamptz NOT NULL DEFAULT now()
    );
    """)


def downgrade():
    op.execute("DROP TABLE identity;")
