"""M5 (parcial): carpetas como fuentes sincronizadas (Doc 03 §4 Source Registry, §5, §6.1).
Portado de Primitivo-f25 gala/kb_service.py (manifiesto por mtime+size, pasadas registradas).

Revision ID: 0004
"""
from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade():
    op.execute("""
    -- Dedupe solo entre documentos activos: un archivo que vuelve a un contenido anterior
    -- (A -> B -> A) no debe chocar con su versión `superseded`.
    ALTER TABLE documents DROP CONSTRAINT documents_owner_id_content_hash_key;
    CREATE UNIQUE INDEX documents_active_content ON documents (owner_id, content_hash) WHERE status = 'active';
    -- Ubicación propia del documento (archivo dentro de una carpeta); si es NULL se usa la de la fuente.
    ALTER TABLE documents ADD COLUMN uri_ref text;

    CREATE TABLE source_files (
        id          bigserial PRIMARY KEY,
        source_id   uuid NOT NULL REFERENCES memory_sources(id),
        rel_path    text NOT NULL,
        size_bytes  bigint NOT NULL,
        mtime       timestamptz NOT NULL,
        document_id text REFERENCES documents(id),
        status      text NOT NULL,  -- indexed | skipped | failed | removed
        error       text,
        indexed_at  timestamptz,
        UNIQUE (source_id, rel_path)
    );

    CREATE TABLE sync_runs (
        id          bigserial PRIMARY KEY,
        source_id   uuid NOT NULL REFERENCES memory_sources(id),
        trigger     text NOT NULL,  -- manual | schedule
        status      text NOT NULL,  -- running | success | partial | failed
        started_at  timestamptz NOT NULL DEFAULT now(),
        finished_at timestamptz,
        files_total int NOT NULL DEFAULT 0,
        n_indexed   int NOT NULL DEFAULT 0,
        n_unchanged int NOT NULL DEFAULT 0,
        n_skipped   int NOT NULL DEFAULT 0,
        n_failed    int NOT NULL DEFAULT 0,
        n_removed   int NOT NULL DEFAULT 0,
        error       text
    );
    CREATE INDEX ON sync_runs (source_id, id DESC);
    """)


def downgrade():
    op.execute("""
    DROP TABLE sync_runs, source_files;
    ALTER TABLE documents DROP COLUMN IF EXISTS uri_ref;
    DROP INDEX documents_active_content;
    -- Las versiones retiradas solo existen por esta revisión (y ya no tienen chunks): sin borrarlas,
    -- la restricción única antigua no se puede restaurar.
    DELETE FROM documents WHERE status IN ('superseded', 'deleted');
    ALTER TABLE documents ADD CONSTRAINT documents_owner_id_content_hash_key UNIQUE (owner_id, content_hash);
    """)
