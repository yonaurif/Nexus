"""Executor (Doc 02 §8, Doc 05 §10). Solo invoca herramientas resueltas en el registro en el
momento de ejecutar; normaliza todo resultado a ToolResult y lo registra sin argumentos en claro."""
import hashlib
import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from graphlib import TopologicalSorter

import sqlalchemy as sa
from pydantic import ValidationError

from nexus.contracts import Evidence, Plan, PlanStep, ToolResult
from nexus.gateway.registry import GatewayError, SqlToolRegistry

log = logging.getLogger("nexus.executor")
# ponytail: un hilo que excede su timeout sigue vivo hasta acabar; aislar en proceso/contenedor
# por conector cuando haya adaptadores de red reales (Doc 02 §9.2, fase C6).
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="nexus-tool")


def _hash(args: dict) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()


def _invoke(engine, adapters, step: PlanStep, inv: str, corr: str, budget_s: float):
    """Devuelve (ToolResult, definition_hash)."""
    def fail(code, ms=0, h=""):
        return ToolResult(invocation_id=inv, status="failed", error={"code": code}, duration_ms=ms,
                          correlation_id=corr), h

    try:  # re-autorización en el instante de ejecución (Doc 02 aceptación #4)
        with engine.connect() as c:
            m = SqlToolRegistry(c).resolve(step.tool_id or "")
    except GatewayError as e:
        return fail(e.code)
    adapter = adapters.get(m.connector_id)
    if adapter is None:
        return fail("CONNECTOR_NOT_FOUND", h=m.definition_hash)

    t0 = time.monotonic()
    ms = lambda: int((time.monotonic() - t0) * 1000)
    try:
        out = _pool.submit(adapter, m.tool_id, dict(step.input)).result(timeout=min(m.timeout_ms / 1000, budget_s))
    except FutureTimeout:
        return fail("TIMEOUT", ms(), m.definition_hash)
    except GatewayError as e:  # el adaptador ya normalizó el error (Doc 05 §14)
        return fail(e.code, ms(), m.definition_hash)
    except Exception:
        log.exception("adapter failure tool=%s inv=%s", m.tool_id, inv)
        return fail("CONNECTOR_UNAVAILABLE", ms(), m.definition_hash)

    # Validación de salida (Doc 05 §10.10): tamaño, forma, campos requeridos, evidencia tipada.
    try:
        size = len(json.dumps(out))
    except (TypeError, ValueError):
        return fail("OUTPUT_INVALID", ms(), m.definition_hash)
    if size > m.max_response_bytes:
        return fail("RESPONSE_TOO_LARGE", ms(), m.definition_hash)
    data = out.get("data") if isinstance(out, dict) else None
    if not isinstance(data, dict) or set(m.output_schema.get("required", [])) - data.keys():
        return fail("OUTPUT_INVALID", ms(), m.definition_hash)
    try:
        evidence = [Evidence(**e) for e in out.get("evidence", [])]
    except (TypeError, ValidationError):
        return fail("OUTPUT_INVALID", ms(), m.definition_hash)
    return ToolResult(invocation_id=inv, status="succeeded", data=data, evidence=evidence,
                      duration_ms=ms(), correlation_id=corr), m.definition_hash


def _record(engine, plan: Plan, step: PlanStep, r: ToolResult, definition_hash: str) -> None:
    with engine.begin() as c:
        c.execute(sa.text(
            "INSERT INTO tool_executions (id, task_id, step_id, tool_id, definition_hash, arguments_hash, "
            "status, result, error, finished_at, duration_ms, correlation_id) VALUES (:i, :t, :s, :tool, :h, "
            ":a, :st, CAST(:res AS jsonb), CAST(:err AS jsonb), now(), :ms, :c)"),
            {"i": r.invocation_id, "t": plan.task_id, "s": step.step_id, "tool": step.tool_id or "",
             "h": definition_hash, "a": _hash(step.input), "st": r.status,
             "res": json.dumps(r.model_dump(mode="json", include={"data", "evidence"})),
             "err": json.dumps(r.error), "ms": r.duration_ms, "c": r.correlation_id})
        c.execute(sa.text("UPDATE plan_steps SET status=:st WHERE plan_id=:p AND step_id=:s"),
                  {"st": r.status, "p": plan.plan_id, "s": step.step_id})


def execute(engine, adapters: dict, plan: Plan, correlation_id: str) -> dict[str, ToolResult]:
    steps = {s.step_id: s for s in plan.steps}
    deadline = time.monotonic() + plan.limits.max_duration_s
    results: dict[str, ToolResult] = {}
    # ponytail: secuencial en orden topológico; paralelismo solo tras validar idempotencia (C6)
    for sid in TopologicalSorter({s.step_id: s.depends_on for s in plan.steps}).static_order():
        step = steps[sid]
        if step.kind != "tool_call":
            continue
        inv = f"inv_{uuid.uuid4().hex}"
        left = deadline - time.monotonic()
        if any(d in results and results[d].status != "succeeded" for d in step.depends_on):
            r, h = ToolResult(invocation_id=inv, status="failed", error={"code": "DEPENDENCY_FAILED"},
                              duration_ms=0, correlation_id=correlation_id), ""
        elif left <= 0:
            r, h = ToolResult(invocation_id=inv, status="failed", error={"code": "BUDGET_EXCEEDED"},
                              duration_ms=0, correlation_id=correlation_id), ""
        else:
            r, h = _invoke(engine, adapters, step, inv, correlation_id, left)
        results[sid] = r
        _record(engine, plan, step, r, h)
    return results
