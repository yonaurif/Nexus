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


RequestClass = Literal["conversation", "knowledge_query", "task_request", "agent_request",
                       "memory_update", "feedback", "rule_proposal", "system_admin", "unknown"]


class ChatRequest(Strict):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None
    locale: str = "es"


class ChatAccepted(Strict):
    task_id: str
    conversation_id: str
    correlation_id: str


class AssistantResponse(Strict):
    text: str
    task_status: str
    warnings: list[str] = []
    sources: list[Evidence] = []


class TaskView(Strict):
    task_id: str
    status: str
    correlation_id: str
    request_class: str | None = None
    response: AssistantResponse | None = None


class DocumentIn(Strict):
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=200_000)
    uri_ref: str | None = Field(default=None, max_length=2000)
    mime_type: Literal["text/plain", "text/markdown"] = "text/plain"


class DocumentIngested(Strict):
    document_id: str
    chunks: int
    deduplicated: bool
    redactions: list[str]


class ApprovalDecision(Strict):
    decision: Literal["approve", "reject"]


class IdentityIn(Strict):
    # Entra en el prompt de sistema: una línea corta, sin saltos (no se cuela texto de instrucciones).
    assistant_name: str = Field(min_length=1, max_length=40, pattern=r"^[^\r\n]+$")
    owner_name: str = Field(min_length=1, max_length=60, pattern=r"^[^\r\n]+$")


class FactReview(Strict):
    """Doc 03 §14 `facts/{id}/review`. replace=True: el hecho sustituye a los confirmados que contradice."""
    decision: Literal["confirm", "reject"]
    replace: bool = False


class FeedbackIn(Strict):
    correct_label: Literal["conversation", "knowledge_query", "task_request", "agent_request", "memory_update",
                           "feedback", "rule_proposal", "system_admin"]


class FolderSourceIn(Strict):
    path: str = Field(min_length=1, max_length=1000)
    interval_minutes: int | None = Field(default=None, ge=5, le=10_080)  # None = solo manual
    ocr: bool = True
    display_name: str | None = Field(default=None, max_length=200)


class FileIngested(DocumentIngested):
    ocr_used: bool


class KnowledgeHit(Strict):
    source_ref: str
    document_id: str
    title: str
    heading: str | None
    text: str
    uri_ref: str | None
    char_start: int
    char_end: int
    score: float


class EpisodeView(Strict):
    episode_id: str
    event_type: str
    occurred_at: datetime
    summary: str
    sensitivity: str
    conversation_id: str | None
    task_id: str | None
    correlation_id: str | None


class CoreEvent(Strict):
    event_id: str
    event_type: str
    occurred_at: datetime
    correlation_id: str
    entity_id: str
    schema_version: str
    payload: dict[str, Any]


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
