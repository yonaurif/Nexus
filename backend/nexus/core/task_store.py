"""Persistencia de tareas (Doc 02 §7.1, §13). Todo cambio de estado pasa por state.transition
y emite un execution_event en la misma transacción."""
import uuid

import sqlalchemy as sa

from nexus.core.state import TaskStatus, transition


def _emit(conn, task_id: str, correlation_id: str, frm: str | None, to: str) -> None:
    conn.execute(sa.text(
        "INSERT INTO execution_events (event_id, event_type, correlation_id, entity_id, payload) "
        "VALUES (:e, 'task.status.changed', :c, :t, jsonb_build_object('from', CAST(:f AS text), 'to', CAST(:to AS text)))"),
        {"e": f"evt_{uuid.uuid4().hex}", "c": correlation_id, "t": task_id, "f": frm, "to": to})


def create_task(conn, *, owner_id: str, goal: str, correlation_id: str) -> str:
    task_id = f"task_{uuid.uuid4().hex}"
    conn.execute(sa.text(
        "INSERT INTO tasks (id, owner_id, goal, status, correlation_id) VALUES (:i, :o, :g, :s, :c)"),
        {"i": task_id, "o": owner_id, "g": goal, "s": TaskStatus.created.value, "c": correlation_id})
    _emit(conn, task_id, correlation_id, None, TaskStatus.created.value)
    return task_id


def get_status(conn, task_id: str) -> TaskStatus:
    return TaskStatus(conn.scalar(sa.text("SELECT status FROM tasks WHERE id=:i"), {"i": task_id}))


def set_status(conn, task_id: str, target: TaskStatus) -> TaskStatus:
    row = conn.execute(sa.text(
        "SELECT status, correlation_id FROM tasks WHERE id=:i FOR UPDATE"), {"i": task_id}).one()
    new = transition(TaskStatus(row.status), target)  # lanza InvalidTransition antes de escribir
    conn.execute(sa.text("UPDATE tasks SET status=:s, updated_at=now() WHERE id=:i"),
                 {"s": new.value, "i": task_id})
    _emit(conn, task_id, row.correlation_id, row.status, new.value)
    return new
