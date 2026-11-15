"""M3: memoria semántica relacional (Doc 03 §3.2, §6.1, §7.3, §9).

Entidades con alias, hechos atómicos y temporales con evidencia, y conflictos sin resolver.
ponytail: sin tabla `relations` aparte: un hecho con `object_entity_id` ES la arista del grafo.
Separarla si el grafo pasa a un motor dedicado (Doc 03 §19).

Revision ID: 0008
"""
from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade():
    op.execute("""
    CREATE TABLE entities (
        id             text PRIMARY KEY,
        owner_id       text NOT NULL,
        entity_type    text NOT NULL,          -- owner | person | project | repository | technology | ...
        canonical_name text NOT NULL,
        norm_name      text NOT NULL,          -- minúsculas sin tildes: no crear una entidad por mención
        description    text,
        status         text NOT NULL DEFAULT 'active',
        created_at     timestamptz NOT NULL DEFAULT now(),
        updated_at     timestamptz NOT NULL DEFAULT now(),
        UNIQUE (owner_id, norm_name)
    );

    CREATE TABLE entity_aliases (
        id          text PRIMARY KEY,
        entity_id   text NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
        alias       text NOT NULL,
        norm_alias  text NOT NULL,
        source_ref  text,
        confidence  real,
        UNIQUE (entity_id, alias)
    );
    CREATE INDEX ON entity_aliases (norm_alias);

    CREATE TABLE facts (
        id                 text PRIMARY KEY,
        owner_id           text NOT NULL,
        subject_entity_id  text NOT NULL REFERENCES entities(id),
        predicate          text NOT NULL,
        object_entity_id   text REFERENCES entities(id),
        object_value       text,
        value_type         text NOT NULL,      -- entity | text
        status             text NOT NULL DEFAULT 'suggested'
            CHECK (status IN ('suggested', 'confirmed', 'rejected', 'superseded', 'expired', 'deleted')),
        confidence         real,
        observed_at        timestamptz NOT NULL DEFAULT now(),
        recorded_at        timestamptz NOT NULL DEFAULT now(),
        valid_from         timestamptz,
        valid_to           timestamptz,
        supersedes_fact_id text REFERENCES facts(id),
        reviewed_at        timestamptz,
        reviewed_by        text,
        CHECK ((object_entity_id IS NULL) <> (object_value IS NULL))  -- exactamente un objeto
    );
    CREATE INDEX ON facts (owner_id, status);
    CREATE INDEX ON facts (subject_entity_id, predicate);
    CREATE INDEX ON facts (object_entity_id);

    CREATE TABLE fact_evidence (
        id            text PRIMARY KEY,
        fact_id       text NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
        source_ref    text NOT NULL,           -- task:<id>, doc:<id>#<chunk>, ...
        task_id       text,
        episode_id    text,
        document_id   text,
        chunk_id      text,
        quote         text,                    -- texto que lo respalda (redactado)
        evidence_role text NOT NULL DEFAULT 'stated_by_owner',
        created_at    timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON fact_evidence (fact_id);

    CREATE TABLE knowledge_conflicts (
        id            text PRIMARY KEY,
        owner_id      text NOT NULL,
        fact_a_id     text NOT NULL REFERENCES facts(id) ON DELETE CASCADE,  -- el confirmado
        fact_b_id     text NOT NULL REFERENCES facts(id) ON DELETE CASCADE,  -- el nuevo
        conflict_type text NOT NULL,           -- same_predicate
        status        text NOT NULL DEFAULT 'open',  -- open | resolved
        resolution    text,                    -- replaced | coexist | rejected
        created_at    timestamptz NOT NULL DEFAULT now(),
        resolved_at   timestamptz
    );
    CREATE INDEX ON knowledge_conflicts (owner_id, status);
    """)


def downgrade():
    op.execute("DROP TABLE knowledge_conflicts, fact_evidence, facts, entity_aliases, entities;")
