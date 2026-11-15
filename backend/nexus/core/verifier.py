"""Verifier (Doc 02 §7.2–7.3). Contrasta estado y evidencia de cada paso; no declara éxito
porque algo parezca plausible.

ponytail: los `success_criteria` son texto libre; se verifican estado + evidencia. Criterios
estructurados (campo/condición) cuando haya herramientas que los necesiten.
"""
from dataclasses import dataclass, field
from typing import Literal

from nexus.contracts import Plan, ToolResult

RETRIABLE = {"TIMEOUT", "CONNECTOR_UNAVAILABLE", "RATE_LIMITED"}


@dataclass
class Verdict:
    status: Literal["completed", "partial", "failed"]
    warnings: list[str] = field(default_factory=list)
    retriable: bool = False


def verify(plan: Plan, results: dict[str, ToolResult]) -> Verdict:
    tool_steps = [s.step_id for s in plan.steps if s.kind == "tool_call"]
    if not tool_steps:
        return Verdict("completed")
    warnings, codes, good, failed = [], set(), 0, 0
    for sid in tool_steps:
        r = results.get(sid)
        if r is None or r.status != "succeeded":
            code = (r.error or {}).get("code", "NOT_EXECUTED") if r else "NOT_EXECUTED"
            warnings.append(f"{sid}:{code}")
            codes.add(code)
            failed += 1
        elif not r.evidence:
            warnings.append(f"{sid}:NO_EVIDENCE")  # ejecutó, pero sin evidencia no hay éxito pleno
        else:
            good += 1
    n = len(tool_steps)
    status = "completed" if good == n else "failed" if failed == n else "partial"
    return Verdict(status, warnings, retriable=bool(codes & RETRIABLE))
