"""Ingesta de documentos y búsqueda híbrida (Doc 03 §5, §7.1, §8.3–8.4).

Ingesta: sanitizar -> hash/dedupe por propietario -> source + document -> chunks -> embeddings.
Búsqueda: filtro por propietario/estado ANTES del ranking -> full-text (OR de términos) +
vectorial (mismo perfil) -> Reciprocal Rank Fusion -> máximo N chunks por documento.
"""
import hashlib
import uuid
from dataclasses import dataclass

import sqlalchemy as sa

from nexus.config import env
from nexus.knowledge.chunking import chunk_text
from nexus.knowledge.sanitize import redact

CANDIDATES = 20
RRF_K = 60
MAX_PER_DOCUMENT = 2
MIN_TERMS = 2
# ponytail: umbral fijo para que la búsqueda vectorial no "encuentre" siempre algo;
# calibrar con datos reales (Recall@k/MRR, Doc 03 §16).
MAX_VECTOR_DISTANCE = float(env("NEXUS_RAG_MAX_DISTANCE", "0.6"))


@dataclass
class IngestResult:
    document_id: str
    chunks: int
    deduplicated: bool
    redactions: list[str]


@dataclass
class Hit:
    document_id: str
    chunk_index: int
    title: str
    heading: str | None
    text: str
    uri_ref: str | None
    char_start: int
    char_end: int
    score: float

    @property
    def source_ref(self) -> str:
        return f"doc:{self.document_id}#{self.chunk_index}"


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def ensure_profile(conn, embedder) -> int:
    key = {"p": embedder.provider, "n": embedder.model_name, "v": embedder.model_version, "d": embedder.dimensions}
    conn.execute(sa.text(
        "INSERT INTO embedding_profiles (provider, model_name, model_version, dimensions) "
        "VALUES (:p, :n, :v, :d) ON CONFLICT DO NOTHING"), key)
    return conn.scalar(sa.text(
        "SELECT id FROM embedding_profiles WHERE provider=:p AND model_name=:n AND model_version=:v "
        "AND dimensions=:d"), key)


def ingest_document(engine, owner_id: str, *, title: str, text: str, embedder, uri_ref: str | None = None,
                    mime_type: str = "text/plain", source_type: str = "manual_upload",
                    max_chars: int = 1200) -> IngestResult:
    clean, found = redact(text)
    content_hash = "sha256:" + hashlib.sha256(clean.encode()).hexdigest()
    with engine.begin() as c:
        existing = c.scalar(sa.text("SELECT id FROM documents WHERE owner_id=:o AND content_hash=:h"),
                            {"o": owner_id, "h": content_hash})
        if existing:
            n = c.scalar(sa.text("SELECT count(*) FROM document_chunks WHERE document_id=:d"), {"d": existing})
            return IngestResult(existing, n, True, found)

        source_id = c.scalar(sa.text(
            "INSERT INTO memory_sources (owner_id, source_type, display_name, uri_ref, permission_scope, "
            "status) VALUES (:o, :t, :n, :u, 'owner', 'active') RETURNING id"),
            {"o": owner_id, "t": source_type, "n": title, "u": uri_ref})
        doc_id = f"doc_{uuid.uuid4().hex}"
        c.execute(sa.text(
            "INSERT INTO documents (id, owner_id, source_id, title, mime_type, sensitivity, content_hash, "
            "char_count) VALUES (:i, :o, :s, :t, :m, :sens, :h, :n)"),
            {"i": doc_id, "o": owner_id, "s": source_id, "t": title, "m": mime_type,
             "sens": "redacted" if found else "normal", "h": content_hash, "n": len(clean)})

        chunks = chunk_text(clean, max_chars=max_chars)
        ids = [c.scalar(sa.text(
            "INSERT INTO document_chunks (document_id, chunk_index, heading, text, char_start, char_end) "
            "VALUES (:d, :i, :h, :t, :s, :e) RETURNING id"),
            {"d": doc_id, "i": ch.index, "h": ch.heading, "t": ch.text, "s": ch.start, "e": ch.end})
            for ch in chunks]

        if embedder is not None and chunks:
            profile = ensure_profile(c, embedder)
            vectors = embedder.embed([f"{ch.heading or ''}\n{ch.text}".strip() for ch in chunks])
            for cid, v in zip(ids, vectors):
                c.execute(sa.text("INSERT INTO chunk_embeddings (chunk_id, profile_id, embedding) "
                                  "VALUES (:c, :p, CAST(:v AS vector))"), {"c": cid, "p": profile, "v": _vec(v)})
    return IngestResult(doc_id, len(chunks), False, found)


_SCOPE = "d.owner_id = :o AND d.status = 'active' AND c.status = 'active'"


def search(conn, owner_id: str, query: str, embedder, k: int = 5) -> list[Hit]:
    ranked: list[list[int]] = []
    # Full-text: un chunk cuenta si contiene al menos MIN_TERMS lexemas distintos de la consulta
    # (o todos si hay menos). AND puro pierde recall en preguntas naturales; OR puro acepta
    # cualquier chunk con una sola palabra común (medido: 95 falsos positivos con "documentos").
    ranked.append(conn.scalars(sa.text(
        f"WITH lex AS (SELECT DISTINCT unnest(tsvector_to_array(to_tsvector('spanish', :q))) AS l) "
        f"SELECT c.id FROM document_chunks c JOIN documents d ON d.id = c.document_id "
        f"JOIN lex ON c.tsv @@ CAST(quote_literal(lex.l) AS tsquery) "
        f"WHERE {_SCOPE} GROUP BY c.id "
        f"HAVING count(*) >= LEAST(:min_terms, (SELECT count(*) FROM lex)) "
        f"ORDER BY count(*) DESC, c.id LIMIT :n"),
        {"o": owner_id, "q": query, "n": CANDIDATES, "min_terms": MIN_TERMS}).all())
    if embedder is not None:
        profile = ensure_profile(conn, embedder)
        qv = _vec(embedder.embed([query])[0])
        ranked.append(conn.scalars(sa.text(
            f"SELECT c.id FROM chunk_embeddings e JOIN document_chunks c ON c.id = e.chunk_id "
            f"JOIN documents d ON d.id = c.document_id "
            f"WHERE {_SCOPE} AND e.profile_id = :p AND (e.embedding <=> CAST(:v AS vector)) < :maxd "
            f"ORDER BY e.embedding <=> CAST(:v AS vector) LIMIT :n"),
            {"o": owner_id, "p": profile, "v": qv, "maxd": MAX_VECTOR_DISTANCE, "n": CANDIDATES}).all())

    scores: dict[int, float] = {}
    for ids in ranked:
        for rank, cid in enumerate(ids):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
    if not scores:
        return []
    rows = {r.id: r for r in conn.execute(sa.text(
        "SELECT c.id, c.document_id, c.chunk_index, c.heading, c.text, c.char_start, c.char_end, "
        "d.title, s.uri_ref FROM document_chunks c JOIN documents d ON d.id = c.document_id "
        "JOIN memory_sources s ON s.id = d.source_id WHERE c.id = ANY(:ids) AND d.owner_id = :o"),
        {"ids": list(scores), "o": owner_id})}

    hits, per_doc = [], {}
    for cid in sorted(scores, key=lambda i: (-scores[i], i)):
        r = rows.get(cid)
        if r is None or per_doc.get(r.document_id, 0) >= MAX_PER_DOCUMENT:
            continue
        per_doc[r.document_id] = per_doc.get(r.document_id, 0) + 1
        hits.append(Hit(r.document_id, r.chunk_index, r.title, r.heading, r.text, r.uri_ref,
                        r.char_start, r.char_end, round(scores[cid], 6)))
        if len(hits) == k:
            break
    return hits
