"""Memoria episódica (Doc 03 §3.1, §7.2): qué ocurrió. Append-only (trigger en la DB);
el resumen se sanitiza antes de guardarse."""
import uuid
from datetime import datetime

import sqlalchemy as sa

from nexus.knowledge.sanitize import redact

MAX_LIMIT = 100


def record(conn, *, owner_id: str, event_type: str, summary: str, actor_type: str, actor_id: str,
           correlation_id: str | None = None, conversation_id: str | None = None,
           task_id: str | None = None, payload_ref: str | None = None) -> str:
    clean, found = redact(summary[:500])
    episode_id = f"ep_{uuid.uuid4().hex}"
    conn.execute(sa.text(
        "INSERT INTO memory_episodes (episode_id, owner_id, conversation_id, task_id, event_type, "
        "actor_type, actor_id, summary, payload_ref, sensitivity, correlation_id) VALUES "
        "(:e, :o, :cv, :t, :ty, :at, :ai, :s, :p, :sens, :c)"),
        {"e": episode_id, "o": owner_id, "cv": conversation_id, "t": task_id, "ty": event_type,
         "at": actor_type, "ai": actor_id, "s": clean, "p": payload_ref,
         "sens": "redacted" if found else "normal", "c": correlation_id})
    return episode_id


def search(conn, owner_id: str, *, event_type: str | None = None, since: datetime | None = None,
           until: datetime | None = None, limit: int = 50):
    return conn.execute(sa.text(
        "SELECT episode_id, conversation_id, task_id, event_type, actor_type, actor_id, occurred_at, "
        "summary, sensitivity, correlation_id, status FROM memory_episodes "
        "WHERE owner_id = :o AND status = 'active' "
        "AND (CAST(:t AS text) IS NULL OR event_type = :t) "
        "AND (CAST(:s AS timestamptz) IS NULL OR occurred_at >= :s) "
        "AND (CAST(:u AS timestamptz) IS NULL OR occurred_at < :u) "
        "ORDER BY id DESC LIMIT :n"),
        {"o": owner_id, "t": event_type, "s": since, "u": until, "n": min(limit, MAX_LIMIT)}).all()
