"""Contratos internos (Doc 02 §14, Doc 05 §6.1/§12). extra=forbid en todos."""
import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

RiskLevel = Literal["read", "write_reversible", "write_external", "destructive", "admin"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanStep(Strict):
    step_id: str
    kind: Literal["tool_call", "agent_call", "synthesis", "needs_user_input"]
    tool_id: str | None = None
    depends_on: list[str] = []
    input: dict[str, Any] = {}
    success_criteria: list[str] = Field(min_length=1)
    risk_level: RiskLevel | None = None  # ponytail: informativo; el riesgo real lo decide el registro


class PlanLimits(Strict):
    max_steps: int = Field(gt=0)
    max_duration_s: int = Field(gt=0)


class Plan(Strict):
    plan_id: str
    task_id: str
    goal: str
    summary_for_user: str
    steps: list[PlanStep]
    limits: PlanLimits
    plan_version: int = 1


class ToolManifest(Strict):
    tool_id: str
    connector_id: str
    version: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    risk_level: RiskLevel
    required_scopes: list[str]
    timeout_ms: int = 10000
    max_response_bytes: int = 200_000
    idempotent: bool = True
    requires_approval: bool = False

    @computed_field
    @property
    def definition_hash(self) -> str:
        # Doc 05 §8.5: hash de la definición completa (todo menos el propio hash).
        body = self.model_dump(exclude={"definition_hash"})
        return "sha256:" + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


class Evidence(Strict):
    source_ref: str
    retrieved_at: datetime


class ToolResult(Strict):
    invocation_id: str
    status: Literal["succeeded", "failed", "partial"]
    data: dict[str, Any] | None = None
    evidence: list[Evidence] = []
    warnings: list[str] = []
    error: dict[str, Any] | None = None
    duration_ms: int
    schema_version: str = "1.0"
    correlation_id: str
