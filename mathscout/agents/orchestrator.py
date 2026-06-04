from mathscout.agents.base import AgentResult, AgentStatus
from mathscout.crawler.registry import DEFAULT_SEED_SOURCES
from mathscout.extraction.schemas import (
    CandidateKnowledgeItemSchema,
    CandidateMatchSchema,
    ReconciliationDecisionSchema,
)
from mathscout.orchestration.schemas import (
    NaturalLanguageDirective,
    OrchestrationAction,
    OrchestrationContext,
    OrchestrationPlan,
)


class SourceDiscoveryAgent:
    def run(self) -> AgentResult:
        payload = {
            "seed_sources": [
                {
                    "name": source.name,
                    "base_url": source.base_url,
                    "category": source.category,
                    "notes": source.notes,
                }
                for source in DEFAULT_SEED_SOURCES
            ]
        }
        return AgentResult(status=AgentStatus.succeeded, payload=payload)


class AIOrchestratorAgent:
    """Creates executable plans from human direction and current run state.

    This is intentionally deterministic for the skeleton. A later LLM-backed
    implementation should keep the same input/output contracts and write every
    action to `agent_decisions`.
    """

    def plan(
        self,
        directive: NaturalLanguageDirective,
        context: OrchestrationContext,
    ) -> OrchestrationPlan:
        actions: list[OrchestrationAction] = []

        target_scope = directive.target_scope or context.target_scope
        budgets = directive.budgets or context.budgets
        stop_conditions = directive.stop_conditions or context.stop_conditions

        actions.append(
            OrchestrationAction(
                action_type="create_crawl_job",
                rationale=(
                    "Start or continue crawling sources that match the requested "
                    "textbook scope."
                ),
                payload={
                    "target_scope": target_scope,
                    "strategy_preferences": directive.strategy_preferences,
                    "budgets": budgets,
                },
                priority=100,
                confidence=0.72,
            )
        )
        actions.append(
            OrchestrationAction(
                action_type="create_extraction_job",
                rationale="Parse newly fetched documents and extract candidate knowledge items.",
                payload={"target_scope": target_scope},
                priority=120,
                confidence=0.7,
            )
        )
        actions.append(
            OrchestrationAction(
                action_type="create_reconciliation_job",
                rationale=(
                    "Compare extracted candidates with canonical records before "
                    "updating the database."
                ),
                payload={
                    "target_scope": target_scope,
                    "review_policy": directive.review_policy,
                },
                priority=130,
                confidence=0.74,
            )
        )

        if context.blocked_sources:
            actions.append(
                OrchestrationAction(
                    action_type="request_login",
                    rationale=(
                        "Some useful sources are blocked by login and require "
                        "user-provided access."
                    ),
                    payload={"blocked_sources": context.blocked_sources},
                    priority=80,
                    confidence=0.86,
                )
            )

        return OrchestrationPlan(
            directive=directive,
            actions=actions,
            expected_outcomes=[
                "Fetch source documents within the requested scope.",
                "Create candidate knowledge items instead of writing directly to canonical tables.",
                "Reconcile candidates against existing knowledge records.",
            ],
            risk_notes=[
                "PolicyGuard must approve crawl scope, source access, and budget before execution.",
                "Conflicts and low-confidence creates should remain visible in the review queue.",
            ],
            stop_conditions=stop_conditions,
            confidence=0.74,
        )


class ReconciliationAgent:
    """Decides how a newly extracted candidate should affect the canonical DB.

    The real implementation will retrieve similar canonical records from SQL and
    vector search. This skeleton keeps the decision contract stable for the UI,
    worker tasks, and future model prompts.
    """

    high_similarity_threshold = 0.92
    review_similarity_threshold = 0.78

    def decide(
        self,
        candidate: CandidateKnowledgeItemSchema,
        matches: list[CandidateMatchSchema],
    ) -> ReconciliationDecisionSchema:
        if not matches:
            return ReconciliationDecisionSchema(
                candidate=candidate,
                action="create",
                matched_records=[],
                rationale="No existing canonical record matched this candidate.",
                proposed_patch={"create": candidate.model_dump()},
                confidence=candidate.confidence,
                requires_human_review=candidate.confidence < 0.9,
            )

        best_match = max(matches, key=lambda match: match.similarity)
        if best_match.similarity >= self.high_similarity_threshold:
            if candidate.item_type in {"teaching_method", "teaching_method_variant"}:
                return ReconciliationDecisionSchema(
                    candidate=candidate,
                    action="create_variant",
                    matched_records=[best_match],
                    rationale=(
                        "Candidate matches an existing canonical teaching method, "
                        "but teacher techniques should preserve meaningful "
                        "source-specific variants."
                    ),
                    proposed_patch={
                        "matched_table": best_match.table,
                        "matched_id": best_match.record_id,
                        "create_variant": candidate.model_dump(),
                        "increment_source_count": True,
                        "update_last_seen_at": True,
                    },
                    confidence=min(candidate.confidence, best_match.confidence),
                    requires_human_review=candidate.confidence < 0.88,
                )

            return ReconciliationDecisionSchema(
                candidate=candidate,
                action="skip",
                matched_records=[best_match],
                rationale=(
                    "Candidate appears to duplicate an existing canonical record; "
                    "only source counters and last-seen metadata should be updated."
                ),
                proposed_patch={
                    "matched_table": best_match.table,
                    "matched_id": best_match.record_id,
                    "increment_source_count": True,
                    "update_last_seen_at": True,
                },
                confidence=min(candidate.confidence, best_match.confidence),
                requires_human_review=False,
            )

        if best_match.similarity >= self.review_similarity_threshold:
            return ReconciliationDecisionSchema(
                candidate=candidate,
                action="review",
                matched_records=[best_match],
                rationale=(
                    "Candidate is similar to an existing record but not close enough "
                    "for automatic skip or update."
                ),
                proposed_patch={},
                confidence=min(candidate.confidence, best_match.confidence),
                requires_human_review=True,
            )

        return ReconciliationDecisionSchema(
            candidate=candidate,
            action="create",
            matched_records=matches[:3],
            rationale="Candidate is materially different from retrieved records.",
            proposed_patch={"create": candidate.model_dump()},
            confidence=candidate.confidence,
            requires_human_review=candidate.confidence < 0.9,
        )
