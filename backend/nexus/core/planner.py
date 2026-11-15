"""Planner (Doc 02 §6). El modelo solo propone `summary_for_user` y `steps`; IDs, versión y
límites los fija el sistema, así el LLM no puede ampliarse el presupuesto."""
import json

import sqlalchemy as sa
from pydantic import ValidationError

from nexus.contracts import Plan, PlanStep, Strict, ToolManifest
from nexus.core.plan_validator import PlanRejected

DEFAULT_LIMITS = {"max_steps": 6, "max_duration_s": 30}

PLANNER_PROMPT = """Eres el Planner de NEXUS. Devuelve SOLO un objeto JSON, sin texto alrededor:
{{"summary_for_user": "<frase corta>", "steps": [{{"step_id": "s1", "kind": "tool_call",
"tool_id": "<id>", "depends_on": [], "input": {{}}, "success_criteria": ["<criterio>"]}}]}}
Usa únicamente estas herramientas (JSON): {tools}
Si ninguna sirve, devuelve "steps": []. No inventes IDs, rutas ni datos que no tengas."""


class _Proposal(Strict):
    summary_for_user: str
    steps: list[PlanStep]


def synthesis_plan(task_id: str, goal: str, version: int) -> Plan:
    return Plan(plan_id=f"plan_{task_id}_{version}", task_id=task_id, goal=goal[:200],
                summary_for_user="Responder en la conversación.", plan_version=version,
                steps=[PlanStep(step_id="respond", kind="synthesis", success_criteria=["respuesta no vacía"])],
                limits=DEFAULT_LIMITS)


def propose(model, task_id: str, message: str, tools: list[ToolManifest], version: int,
            feedback: list[str] | None = None) -> Plan:
    catalog = json.dumps([{"tool_id": t.tool_id, "description": t.description,
                           "input_schema": t.input_schema} for t in tools], ensure_ascii=False)
    user = message if not feedback else f"{message}\n\nEl intento anterior falló: {feedback}"
    try:
        gen = getattr(model, "generate_json", None) or model.generate  # JSON por gramática si el modelo lo admite
        raw = gen([{"role": "system", "content": PLANNER_PROMPT.format(tools=catalog)},
                              {"role": "user", "content": user}])
    except Exception:
        raise PlanRejected("MODEL_UNAVAILABLE") from None
    start, end = raw.find("{"), raw.rfind("}")
    try:
        p = _Proposal.model_validate_json(raw[start:end + 1] if start >= 0 else raw)
    except ValidationError:
        raise PlanRejected("PLAN_UNPARSEABLE") from None
    if not p.steps:
        return synthesis_plan(task_id, message, version)
    return Plan(plan_id=f"plan_{task_id}_{version}", task_id=task_id, goal=message[:200],
                summary_for_user=p.summary_for_user, steps=p.steps, limits=DEFAULT_LIMITS,
                plan_version=version)


def load_plan(engine, task_id: str) -> Plan:
    """Última versión del plan guardado de una tarea (para reanudar tras una aprobación)."""
    with engine.connect() as c:
        p = c.execute(sa.text("SELECT p.id, p.version, p.summary, p.limits, t.goal FROM plans p "
                              "JOIN tasks t ON t.id = p.task_id WHERE p.task_id=:t ORDER BY p.version DESC LIMIT 1"),
                      {"t": task_id}).one()
        steps = c.execute(sa.text("SELECT step_id, kind, tool_id, depends_on, input, success_criteria "
                                  "FROM plan_steps WHERE plan_id=:p ORDER BY step_id"), {"p": p.id}).all()
    return Plan(plan_id=p.id, task_id=task_id, goal=p.goal, summary_for_user=p.summary, limits=p.limits,
                plan_version=p.version, steps=[PlanStep(**s._asdict()) for s in steps])


def save_plan(engine, plan: Plan) -> None:
    with engine.begin() as c:
        c.execute(sa.text("INSERT INTO plans (id, task_id, version, summary, limits) "
                          "VALUES (:i, :t, :v, :s, CAST(:l AS jsonb))"),
                  {"i": plan.plan_id, "t": plan.task_id, "v": plan.plan_version,
                   "s": plan.summary_for_user, "l": plan.limits.model_dump_json()})
        for s in plan.steps:
            c.execute(sa.text(
                "INSERT INTO plan_steps (plan_id, step_id, kind, tool_id, depends_on, input, success_criteria) "
                "VALUES (:p, :s, :k, :t, CAST(:d AS jsonb), CAST(:i AS jsonb), CAST(:c AS jsonb))"),
                {"p": plan.plan_id, "s": s.step_id, "k": s.kind, "t": s.tool_id,
                 "d": json.dumps(s.depends_on), "i": json.dumps(s.input), "c": json.dumps(s.success_criteria)})
