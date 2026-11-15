"""Aprobaciones (Doc 05 §6.2, §11; Doc 02 §7.1 `awaiting_approval`).

Patrón de Primitivo `gala/actions.py` (el chat solo PROPONE; la ejecución pasa por una decisión
explícita que se re-valida en servidor), endurecido según el Doc 05:
- los argumentos se guardan en servidor con su hash; el cliente solo dice approve/reject;
- caduca (TTL), se decide una vez y se CONSUME una vez en el instante de ejecutar;
- si el paso cambia después de pedirla, el hash no coincide y no autoriza nada.
"""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from nexus.contracts import Plan, PlanStep, ToolManifest

TTL_S = 15 * 60
REVERSIBLE = {"read", "write_reversible"}


class ApprovalError(Exception):
    def __init__(self, code: str, task_id: str | None = None):
        super().__init__(code)
        self.code, self.task_id = code, task_id


def needs_approval(m: ToolManifest) -> bool:
    return m.risk_level != "read" or m.requires_approval


def args_hash(args: dict) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(args, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def summarize(m: ToolManifest, args: dict) -> str:
    shown = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)[:120]}" for k, v in args.items())
    return f"{m.tool_id} ({m.risk_level}): {m.description} — {shown}"


def create(conn, plan: Plan, step: PlanStep, m: ToolManifest, correlation_id: str) -> str:
    approval_id = f"apr_{uuid.uuid4().hex}"
    conn.execute(sa.text(
        "INSERT INTO approvals (id, task_id, plan_id, step_id, tool_id, connector_id, risk_level, arguments, "
        "arguments_hash, summary, expires_at, correlation_id) VALUES (:i, :t, :p, :s, :tool, :c, :r, "
        "CAST(:a AS jsonb), :h, :sum, :exp, :corr)"),
        {"i": approval_id, "t": plan.task_id, "p": plan.plan_id, "s": step.step_id, "tool": m.tool_id,
         "c": m.connector_id, "r": m.risk_level, "a": json.dumps(step.input), "h": args_hash(step.input),
         "sum": summarize(m, step.input), "corr": correlation_id,
         "exp": datetime.now(timezone.utc) + timedelta(seconds=TTL_S)})
    return approval_id


def list_for_owner(conn, owner_id: str, status: str | None = None) -> list[dict]:
    rows = conn.execute(sa.text(
        "SELECT a.id, a.task_id, a.step_id, a.tool_id, a.connector_id, a.risk_level, a.arguments, a.summary, "
        "a.status, a.created_at, a.expires_at, a.decided_at FROM approvals a JOIN tasks t ON t.id = a.task_id "
        "WHERE t.owner_id = :o AND (CAST(:s AS text) IS NULL OR a.status = :s) ORDER BY a.created_at DESC LIMIT 100"),
        {"o": owner_id, "s": status}).all()
    return [{"approval_id": r.id, "task_id": r.task_id, "step_id": r.step_id, "tool_id": r.tool_id,
             "connector_id": r.connector_id, "risk_level": r.risk_level, "reversible": r.risk_level in REVERSIBLE,
             "arguments": r.arguments, "summary": r.summary, "status": r.status, "created_at": r.created_at,
             "expires_at": r.expires_at, "decided_at": r.decided_at} for r in rows]


def decide(conn, approval_id: str, owner_id: str, decision: str) -> str:
    """Registra la decisión. Devuelve el task_id. ApprovalError: NOT_FOUND | ALREADY_DECIDED | EXPIRED."""
    row = conn.execute(sa.text(
        "SELECT a.task_id, a.status, a.expires_at < now() AS expired FROM approvals a JOIN tasks t ON t.id = a.task_id "
        "WHERE a.id = :i AND t.owner_id = :o FOR UPDATE OF a"), {"i": approval_id, "o": owner_id}).first()
    if row is None:
        raise ApprovalError("APPROVAL_NOT_FOUND")
    if row.status != "pending":
        raise ApprovalError("APPROVAL_ALREADY_DECIDED", row.task_id)
    if row.expired:
        raise ApprovalError("APPROVAL_EXPIRED", row.task_id)
    conn.execute(sa.text("UPDATE approvals SET status=:s, decided_at=now(), decided_by=:o WHERE id=:i"),
                 {"s": "approved" if decision == "approve" else "rejected", "o": owner_id, "i": approval_id})
    conn.execute(sa.text("INSERT INTO audit_events (actor_type, actor_id, action, entity_type, entity_id, "
                         "correlation_id) SELECT 'owner', :o, :a, 'approval', id, correlation_id FROM approvals "
                         "WHERE id = :i"),
                 {"o": owner_id, "a": f"approval.{'approved' if decision == 'approve' else 'rejected'}",
                  "i": approval_id})
    return row.task_id


def task_state(conn, task_id: str) -> str:
    """'rejected' si alguna se rechazó; 'pending' si queda alguna; 'approved' si todas lo están."""
    statuses = set(conn.scalars(sa.text("SELECT status FROM approvals WHERE task_id=:t AND status IN "
                                        "('pending', 'approved', 'rejected')"), {"t": task_id}))
    return "rejected" if "rejected" in statuses else "pending" if "pending" in statuses else "approved"


def expire_open(conn, task_id: str) -> None:
    conn.execute(sa.text("UPDATE approvals SET status='expired' WHERE task_id=:t AND status IN ('pending', 'approved')"),
                 {"t": task_id})


def consume(conn, task_id: str, step_id: str, arguments: dict) -> bool:
    """Doc 05 §10.7: justo antes de invocar, la aprobación debe existir, estar vigente y casar con
    los argumentos EXACTOS. Se consume (un solo uso: un reintento no duplica la escritura)."""
    return conn.execute(sa.text(
        "UPDATE approvals SET status='consumed' WHERE task_id=:t AND step_id=:s AND arguments_hash=:h "
        "AND status='approved' AND expires_at > now() RETURNING id"),
        {"t": task_id, "s": step_id, "h": args_hash(arguments)}).first() is not None
