"""Fase C0 (Doc 02) + G0 (Doc 05): contratos, estados, validación de plan y registro de herramientas."""
import pytest
from pydantic import ValidationError

from nexus.contracts import Plan, PlanStep, ToolManifest, ToolResult
from nexus.core.state import TaskStatus, InvalidTransition, transition
from nexus.core.plan_validator import PlanRejected, validate_plan
from nexus.gateway.registry import GatewayError, ToolRegistry

MANIFEST = dict(
    tool_id="github.repository.get",
    connector_id="github_primary",
    version="1.0.0",
    description="Obtiene metadatos de un repositorio permitido",
    input_schema={"type": "object", "required": ["repository_ref"]},
    output_schema={"type": "object"},
    risk_level="read",
    required_scopes=["github.repository.read"],
)


def make_plan(steps):
    return Plan(plan_id="plan_1", task_id="task_1", goal="g", summary_for_user="s",
                steps=steps, limits={"max_steps": 8, "max_duration_s": 60})


def tool_step(sid, deps=(), tool="github.repository.get"):
    return PlanStep(step_id=sid, kind="tool_call", tool_id=tool, depends_on=list(deps),
                    input={"repository_ref": "r"}, success_criteria=["ok"])


# --- Contratos (Doc 02 §14: extra=forbid) ---
def test_contracts_reject_unknown_fields():
    with pytest.raises(ValidationError):
        PlanStep(step_id="s", kind="synthesis", success_criteria=["x"], sneaky=True)


def test_tool_result_shape():
    r = ToolResult(invocation_id="inv", status="succeeded", data={}, correlation_id="c",
                   duration_ms=1)
    assert r.error is None and r.schema_version == "1.0"


# --- Máquina de estados (Doc 02 §7.1) ---
def test_happy_path_transitions():
    s = TaskStatus.created
    for nxt in ["classifying", "context_building", "planning", "plan_validating",
                "queued", "running", "verifying", "completed"]:
        s = transition(s, TaskStatus(nxt))
    assert s is TaskStatus.completed


def test_completed_cannot_return_to_running():
    with pytest.raises(InvalidTransition):
        transition(TaskStatus.completed, TaskStatus.running)


def test_approval_branch():
    s = transition(TaskStatus.plan_validating, TaskStatus.awaiting_approval)
    assert transition(s, TaskStatus.queued) is TaskStatus.queued


# --- Validador de plan (Doc 02 §6.2, criterio aceptación 2) ---
def registry():
    reg = ToolRegistry()
    reg.register(ToolManifest(**MANIFEST))
    reg.approve("github.repository.get")
    return reg


def test_valid_plan_passes():
    plan = make_plan([tool_step("a"), PlanStep(step_id="b", kind="synthesis",
                                               depends_on=["a"], success_criteria=["x"])])
    validate_plan(plan, registry())


def test_unknown_tool_rejected():
    with pytest.raises(PlanRejected, match="TOOL_NOT_ALLOWED"):
        validate_plan(make_plan([tool_step("a", tool="shell.run")]), registry())


def test_cycle_rejected():
    with pytest.raises(PlanRejected, match="cycle"):
        validate_plan(make_plan([tool_step("a", ["b"]), tool_step("b", ["a"])]), registry())


def test_missing_dependency_rejected():
    with pytest.raises(PlanRejected, match="unknown dependency"):
        validate_plan(make_plan([tool_step("a", ["zzz"])]), registry())


def test_too_many_steps_rejected():
    plan = make_plan([tool_step(f"s{i}") for i in range(9)])
    with pytest.raises(PlanRejected, match="max_steps"):
        validate_plan(plan, registry())


def test_missing_required_input_rejected():
    step = PlanStep(step_id="a", kind="tool_call", tool_id="github.repository.get",
                    input={}, success_criteria=["ok"])
    with pytest.raises(PlanRejected, match="INPUT_INVALID"):
        validate_plan(make_plan([step]), registry())


# --- Tool Registry (Doc 05 §6, §8.5, aceptación 4) ---
def test_unapproved_tool_not_resolvable():
    reg = ToolRegistry()
    reg.register(ToolManifest(**MANIFEST))
    with pytest.raises(GatewayError, match="TOOL_NOT_ALLOWED"):
        reg.resolve("github.repository.get")


def test_definition_change_requires_new_review():
    reg = registry()
    changed = ToolManifest(**{**MANIFEST, "description": "ahora también borra"})
    reg.register(changed)
    with pytest.raises(GatewayError, match="TOOL_DEFINITION_CHANGED"):
        reg.resolve("github.repository.get")


def test_hash_is_stable():
    assert ToolManifest(**MANIFEST).definition_hash == ToolManifest(**MANIFEST).definition_hash
