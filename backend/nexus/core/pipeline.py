"""Pipeline conversacional de C1 (Doc 02 §3, §7): classify -> context -> plan -> validate ->
run -> verify -> responder. Cada transición se confirma por separado para que el SSE la vea.

ponytail: Planner/Executor/Verifier triviales (un paso `synthesis`); los reales llegan en C2.
"""
import json
import logging
from contextlib import suppress

import sqlalchemy as sa

from nexus.contracts import Plan, PlanStep
from nexus.core import task_store
from nexus.core.classifier import classify
from nexus.core.models import SYSTEM_PROMPT
from nexus.core.plan_validator import validate_plan
from nexus.core.state import TaskStatus as S
from nexus.gateway.registry import ToolRegistry

log = logging.getLogger("nexus.pipeline")
HISTORY_LIMIT = 10  # ponytail: por nº de mensajes; presupuesto por tokens cuando haya tokenizador
NOT_YET = {  # clase -> fase en la que se habilita
    "agent_request": "C4/G2", "task_request": "C2", "memory_update": "M1",
    "rule_proposal": "C5", "feedback": "T5", "system_admin": "G3", "knowledge_query": "M2",
}


def _step(engine, task_id: str, target: S) -> None:
    with engine.begin() as c:
        task_store.set_status(c, task_id, target)


def _reply(engine, task_id: str, conversation_id: str, text: str, warnings: list[str]) -> None:
    with engine.begin() as c:
        c.execute(sa.text(
            "INSERT INTO messages (conversation_id, role, content, task_id, metadata) "
            "VALUES (:c, 'assistant', :t, :k, CAST(:m AS jsonb))"),
            {"c": conversation_id, "t": text, "k": task_id, "m": json.dumps({"warnings": warnings})})


def _context(engine, conversation_id: str) -> list[dict]:
    with engine.connect() as c:
        rows = c.execute(sa.text(
            "SELECT role, content FROM messages WHERE conversation_id=:c "
            "ORDER BY id DESC LIMIT :n"), {"c": conversation_id, "n": HISTORY_LIMIT}).all()
    return [{"role": "system", "content": SYSTEM_PROMPT}] + [
        {"role": r.role, "content": r.content} for r in reversed(rows)]


def run(engine, model, task_id: str, conversation_id: str, message: str) -> None:
    try:
        _step(engine, task_id, S.classifying)
        label = classify(message)
        if label == "unknown":
            _step(engine, task_id, S.needs_input)
            _reply(engine, task_id, conversation_id,
                   "No he entendido la petición. ¿Puedes concretar qué necesitas?", ["NEEDS_INPUT"])
            return

        _step(engine, task_id, S.context_building)
        messages = _context(engine, conversation_id)

        _step(engine, task_id, S.planning)
        plan = Plan(plan_id=f"plan_{task_id}", task_id=task_id, goal=message[:200],
                    summary_for_user="Responder en la conversación.",
                    steps=[PlanStep(step_id="respond", kind="synthesis",
                                    success_criteria=["respuesta no vacía"])],
                    limits={"max_steps": 1, "max_duration_s": 120})
        _step(engine, task_id, S.plan_validating)
        validate_plan(plan, ToolRegistry())  # sin herramientas en C1

        _step(engine, task_id, S.queued)
        _step(engine, task_id, S.running)
        warnings = []
        if not getattr(model, "configured", True):
            warnings.append("MODEL_NOT_CONFIGURED")
        if label in NOT_YET:
            warnings.append(f"CAPABILITY_UNAVAILABLE:{label} (fase {NOT_YET[label]})")
        try:
            text = model.generate(messages).strip()
        except Exception:
            log.exception("model failure task=%s", task_id)  # detalle solo en logs
            _step(engine, task_id, S.failed)
            _reply(engine, task_id, conversation_id,
                   "No he podido generar una respuesta: el modelo no está disponible.",
                   ["MODEL_UNAVAILABLE"])
            return

        _step(engine, task_id, S.verifying)
        if not text:
            _step(engine, task_id, S.failed)
            _reply(engine, task_id, conversation_id, "El modelo devolvió una respuesta vacía.",
                   ["EMPTY_RESPONSE"])
            return
        _step(engine, task_id, S.partial if warnings else S.completed)
        _reply(engine, task_id, conversation_id, text, warnings)
    except Exception:
        log.exception("pipeline failure task=%s", task_id)
        with suppress(Exception):  # puede estar ya en estado terminal
            _step(engine, task_id, S.failed)
