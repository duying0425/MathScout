from typing import Literal

from pydantic import BaseModel, Field

OrchestrationActionType = Literal[
    "discover_sources",
    "create_crawl_job",
    "create_extraction_job",
    "create_reconciliation_job",
    "reprioritize_source",
    "pause_source",
    "resume_source",
    "adjust_strategy",
    "request_login",
    "request_review",
    "stop_session",
]


class OrchestrationContext(BaseModel):
    session_id: str | None = None
    objective: str
    target_scope: dict = Field(default_factory=dict)
    budgets: dict = Field(default_factory=dict)
    stop_conditions: dict = Field(default_factory=dict)
    quality_snapshot: dict = Field(default_factory=dict)
    active_sources: list[dict] = Field(default_factory=list)
    blocked_sources: list[dict] = Field(default_factory=list)


class NaturalLanguageDirective(BaseModel):
    raw_text: str
    interpreted_intent: str
    target_scope: dict = Field(default_factory=dict)
    strategy_preferences: dict = Field(default_factory=dict)
    budgets: dict = Field(default_factory=dict)
    stop_conditions: dict = Field(default_factory=dict)
    review_policy: dict = Field(default_factory=dict)


class OrchestrationAction(BaseModel):
    action_type: OrchestrationActionType
    rationale: str
    payload: dict = Field(default_factory=dict)
    priority: int = Field(default=100, ge=0, le=1000)
    confidence: float = Field(ge=0.0, le=1.0)
    requires_policy_check: bool = True


class OrchestrationPlan(BaseModel):
    directive: NaturalLanguageDirective
    actions: list[OrchestrationAction]
    expected_outcomes: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    stop_conditions: dict = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
