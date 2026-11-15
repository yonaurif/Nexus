"""Máquina de estados de tarea (Doc 02 §7.1). Transiciones explícitas; terminales no vuelven."""
from enum import Enum


class TaskStatus(str, Enum):
    created = "created"
    classifying = "classifying"
    context_building = "context_building"
    planning = "planning"
    plan_validating = "plan_validating"
    awaiting_approval = "awaiting_approval"
    queued = "queued"
    running = "running"
    verifying = "verifying"
    completed = "completed"
    needs_input = "needs_input"
    partial = "partial"
    failed = "failed"
    cancel_requested = "cancel_requested"
    cancelled = "cancelled"
    expired = "expired"


S = TaskStatus
_ABORT = {S.failed, S.cancel_requested}
ALLOWED: dict[S, set[S]] = {
    S.created: {S.classifying} | _ABORT,
    S.classifying: {S.context_building, S.needs_input} | _ABORT,
    S.context_building: {S.planning} | _ABORT,
    S.planning: {S.plan_validating, S.needs_input} | _ABORT,
    S.plan_validating: {S.queued, S.awaiting_approval} | _ABORT,
    S.awaiting_approval: {S.queued, S.expired} | _ABORT,
    S.queued: {S.running} | _ABORT,
    S.running: {S.verifying} | _ABORT,
    S.verifying: {S.completed, S.partial, S.planning} | _ABORT,  # planning = replanificación limitada
    S.needs_input: {S.planning, S.expired} | _ABORT,
    S.cancel_requested: {S.cancelled},
    # terminales: completed, partial, failed, cancelled, expired -> nuevo intento = nueva tarea
}


class InvalidTransition(ValueError):
    pass


def transition(current: S, target: S) -> S:
    if target not in ALLOWED.get(current, set()):
        raise InvalidTransition(f"{current.value} -> {target.value}")
    return target
