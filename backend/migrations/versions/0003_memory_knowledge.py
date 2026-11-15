"""M1/M2: episodios, documentos, chunks con FTS, perfiles de embedding y vectores (Doc 03 §7.1–7.2).

Revision ID: 0003
"""
from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade():
    op.execute("""
    CREATE TABLE memory_episodes (
        id              bigserial PRIMARY KEY,
        episode_id      text NOT NULL UNIQUE,
        owner_id        text NOT NULL,
        conversation_id text,
        task_id         text,
        event_type      text NOT NULL,
        actor_type      text NOT NULL,
        actor_id        text NOT NULL,
        occurred_at     timestamptz NOT NULL DEFAULT now(),
        recorded_at     timestamptz NOT NULL DEFAULT now(),
        summary         text NOT NULL,
        payload_ref     text,
        sensitivity     text NOT NULL DEFAULT 'normal',
        visibility      text NOT NULL DEFAULT 'private',
        source_id       uuid REFERENCES memory_sources(id),
        correlation_id  text,
        status          text NOT NULL DEFAULT 'active'
    );
    CREATE INDEX ON memory_episodes (owner_id, occurred_at);
    CREATE INDEX ON memory_episodes (owner_id, event_type);
    CREATE TRIGGER memory_episodes_append_only BEFORE UPDATE OR DELETE ON memory_episodes
        FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

    CREATE TABLE documents (
        id           text PRIMARY KEY,
        owner_id     text NOT NULL,
        source_id    uuid NOT NULL REFERENCES memory_sources(id),
        title        text NOT NULL,
        mime_type    text NOT NULL DEFAULT 'text/plain',
        language     text NOT NULL DEFAULT 'es',
        sensitivity  text NOT NULL DEFAULT 'normal',
        status       text NOT NULL DEFAULT 'active',
        content_hash text NOT NULL,
        char_count   int  NOT NULL,
        created_at   timestamptz NOT NULL DEFAULT now(),
        UNIQUE (owner_id, content_hash)
    );

    CREATE TABLE document_chunks (
        id          bigserial PRIMARY KEY,
        document_id text NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        chunk_index int  NOT NULL,
        heading     text,
        text        text NOT NULL,
        char_start  int  NOT NULL,
        char_end    int  NOT NULL,
        status      text NOT NULL DEFAULT 'active',
        tsv         tsvector GENERATED ALWAYS AS
                    (to_tsvector('spanish', coalesce(heading, '') || ' ' || text)) STORED,
        UNIQUE (document_id, chunk_index)
    );
    CREATE INDEX ON document_chunks USING gin (tsv);

    CREATE TABLE embedding_profiles (
        id            serial PRIMARY KEY,
        provider      text NOT NULL,
        model_name    text NOT NULL,
        model_version text NOT NULL,
        dimensions    int  NOT NULL,
        normalization text NOT NULL DEFAULT 'l2',
        created_at    timestamptz NOT NULL DEFAULT now(),
        UNIQUE (provider, model_name, model_version, dimensions)
    );

    -- Sin dimensión fija: cada perfil tiene la suya y nunca se comparan vectores de perfiles distintos.
    -- ponytail: búsqueda exacta (sin índice ANN); índice HNSW parcial por perfil cuando haya >100k chunks.
    CREATE TABLE chunk_embeddings (
        chunk_id   bigint NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
        profile_id int    NOT NULL REFERENCES embedding_profiles(id),
        embedding  vector NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (chunk_id, profile_id)
    );
    """)


def downgrade():
    op.execute("DROP TABLE chunk_embeddings, embedding_profiles, document_chunks, documents, memory_episodes;")
