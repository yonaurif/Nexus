"""Plan Validator (Doc 02 §6.2). Rechaza antes de ejecutar: límites, deps, ciclos, tools, riesgo, input."""
from graphlib import CycleError, TopologicalSorter

from nexus.contracts import Plan
from nexus.gateway.registry import GatewayError

# Techo global: ningún plan (venga del LLM o no) puede superarlo (Doc 02 §11).
CEILING = {"max_steps": 8, "max_duration_s": 60}


class PlanRejected(ValueError):
    pass


def validate_plan(plan: Plan, registry) -> None:
    for k, cap in CEILING.items():
        if getattr(plan.limits, k) > cap:
            raise PlanRejected(f"global ceiling: {k} > {cap}")
    if len(plan.steps) > plan.limits.max_steps:
        raise PlanRejected(f"max_steps exceeded ({len(plan.steps)}>{plan.limits.max_steps})")

    ids = [s.step_id for s in plan.steps]
    if len(ids) != len(set(ids)):
        raise PlanRejected("duplicate step_id")

    for s in plan.steps:
        for d in s.depends_on:
            if d not in ids:
                raise PlanRejected(f"unknown dependency {d!r} in {s.step_id}")
    try:
        TopologicalSorter({s.step_id: s.depends_on for s in plan.steps}).prepare()
    except CycleError as e:
        raise PlanRejected(f"dependency cycle: {e.args[1]}") from None

    for s in plan.steps:
        if s.kind != "tool_call":
            continue
        try:
            m = registry.resolve(s.tool_id or "")
        except GatewayError as e:
            raise PlanRejected(f"{e.code}: {s.tool_id}") from None
        # Doc 05 §6.2: `admin` nunca está disponible para el Core ni para agentes ordinarios.
        # Escrituras sí, pero el pipeline pide aprobación y el Executor la consume al ejecutar (C5).
        if m.risk_level == "admin":
            raise PlanRejected(f"POLICY_DENIED: {s.tool_id} (admin)")
        # ponytail: solo 'required'; validación JSON Schema completa (jsonschema) en G1
        missing = set(m.input_schema.get("required", [])) - s.input.keys()
        if missing:
            raise PlanRejected(f"INPUT_INVALID: {s.step_id} missing {sorted(missing)}")
