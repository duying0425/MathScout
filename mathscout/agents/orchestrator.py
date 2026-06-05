from __future__ import annotations

from pydantic import BaseModel, Field

from mathscout.agents.base import AgentResult, AgentStatus
from mathscout.agents.control_plane import (
    ChatJsonClient,
    LLMBackedAgent,
    OrchestratorPlanningAgent,
)
from mathscout.config import Settings
from mathscout.crawler.registry import DEFAULT_SEED_SOURCES
from mathscout.extraction.schemas import (
    CandidateKnowledgeItemSchema,
    CandidateMatchSchema,
    ReconciliationAction,
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
    """LLM-led planner with a deterministic fallback for local/offline runs."""

    def __init__(
        self,
        client: ChatJsonClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.planning_agent = OrchestratorPlanningAgent(client=client, settings=settings)

    def plan(
        self,
        directive: NaturalLanguageDirective,
        context: OrchestrationContext,
    ) -> OrchestrationPlan:
        ai_plan = self.planning_agent.plan(directive, context)
        if ai_plan is not None:
            return _ensure_required_actions(ai_plan)
        return _deterministic_plan(directive, context)


class ReconciliationDecisionPayload(BaseModel):
    action: ReconciliationAction
    matched_record_ids: list[str] = Field(default_factory=list)
    rationale: str
    proposed_patch: dict = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    requires_human_review: bool = True


class ReconciliationAgent(LLMBackedAgent):
    """AI-first candidate reconciliation with threshold fallback."""

    agent_name = "ReconciliationAgent"

    high_similarity_threshold = 0.92
    review_similarity_threshold = 0.78

    def decide(
        self,
        candidate: CandidateKnowledgeItemSchema,
        matches: list[CandidateMatchSchema],
    ) -> ReconciliationDecisionSchema:
        ai_decision = self._decide_with_ai(candidate, matches)
        if ai_decision is not None:
            return ai_decision
        return self._decide_with_thresholds(candidate, matches)

    def _decide_with_ai(
        self,
        candidate: CandidateKnowledgeItemSchema,
        matches: list[CandidateMatchSchema],
    ) -> ReconciliationDecisionSchema | None:
        if not self.ai_enabled and self._client is None:
            return None
        try:
            payload = self.call_model(
                system_prompt=RECONCILIATION_AGENT_PROMPT,
                payload={
                    "candidate": candidate.model_dump(mode="json"),
                    "matches": [match.model_dump(mode="json") for match in matches],
                    "allowed_actions": [
                        "skip",
                        "update",
                        "create_variant",
                        "create",
                        "conflict",
                        "review",
                    ],
                },
                output_model=ReconciliationDecisionPayload,
            )
        except Exception:
            return None

        matched_records = _matches_by_ids(matches, payload.matched_record_ids)
        return ReconciliationDecisionSchema(
            candidate=candidate,
            action=payload.action,
            matched_records=matched_records,
            rationale=payload.rationale,
            proposed_patch=payload.proposed_patch,
            confidence=payload.confidence,
            requires_human_review=payload.requires_human_review,
        )

    def _decide_with_thresholds(
        self,
        candidate: CandidateKnowledgeItemSchema,
        matches: list[CandidateMatchSchema],
    ) -> ReconciliationDecisionSchema:
        if not matches:
            return ReconciliationDecisionSchema(
                candidate=candidate,
                action="create",
                matched_records=[],
                rationale="没有找到与该候选项匹配的已有主知识库记录。",
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
                        "候选项与已有主知识库教学方法相近，"
                        "但教师方法需要保留有意义的来源差异，因此创建变体。"
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
                    "候选项看起来重复已有主知识库记录，"
                    "只需要更新来源计数和最后出现时间。"
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
                    "候选项与已有记录相似，但相似度不足以自动跳过或更新，"
                    "需要人工复核。"
                ),
                proposed_patch={},
                confidence=min(candidate.confidence, best_match.confidence),
                requires_human_review=True,
            )

        return ReconciliationDecisionSchema(
            candidate=candidate,
            action="create",
            matched_records=matches[:3],
            rationale="候选项与检索到的记录存在实质差异，建议创建新记录。",
            proposed_patch={"create": candidate.model_dump()},
            confidence=candidate.confidence,
            requires_human_review=candidate.confidence < 0.9,
        )


def _ensure_required_actions(plan: OrchestrationPlan) -> OrchestrationPlan:
    action_types = {action.action_type for action in plan.actions}
    actions = list(plan.actions)
    if "create_crawl_job" not in action_types:
        actions.append(
            OrchestrationAction(
                action_type="create_crawl_job",
                rationale="补齐执行入口：需要持久化爬取任务承载后续 Agent 工具调用。",
                payload={
                    "target_scope": plan.directive.target_scope,
                    "strategy_preferences": plan.directive.strategy_preferences,
                    "budgets": plan.directive.budgets,
                },
                priority=100,
                confidence=min(plan.confidence, 0.7),
            )
        )
    if "create_extraction_job" not in action_types:
        actions.append(
            OrchestrationAction(
                action_type="create_extraction_job",
                rationale="补齐抽取阶段：爬取结果需要交给 MethodAgent 生成结构化候选项。",
                payload={"target_scope": plan.directive.target_scope},
                priority=120,
                confidence=min(plan.confidence, 0.7),
            )
        )
    if "create_reconciliation_job" not in action_types:
        actions.append(
            OrchestrationAction(
                action_type="create_reconciliation_job",
                rationale="补齐调和阶段：候选项必须先经 ReconciliationAgent 决策再进入主知识库。",
                payload={"review_policy": plan.directive.review_policy},
                priority=130,
                confidence=min(plan.confidence, 0.7),
            )
        )
    actions.sort(key=lambda action: (action.priority, action.action_type))
    plan.actions = actions
    return plan


def _deterministic_plan(
    directive: NaturalLanguageDirective,
    context: OrchestrationContext,
) -> OrchestrationPlan:
    actions: list[OrchestrationAction] = []

    target_scope = directive.target_scope or context.target_scope
    budgets = directive.budgets or context.budgets
    stop_conditions = directive.stop_conditions or context.stop_conditions

    if directive.strategy_preferences.get("discover_links", True):
        actions.append(
            OrchestrationAction(
                action_type="discover_sources",
                rationale=(
                    "SourceSelectionAgent 未启用时，先用本地候选提取器检查种子页，"
                    "再用确定性兜底排序创建候选抓取任务。"
                ),
                payload={
                    "target_scope": target_scope,
                    "max_links_per_seed": directive.strategy_preferences.get(
                        "discovery_max_links", 12
                    ),
                    "policy": "只允许同域公开 HTTP(S) 链接",
                },
                priority=90,
                confidence=0.68,
            )
        )

    actions.extend(
        [
            OrchestrationAction(
                action_type="create_crawl_job",
                rationale="创建或继续爬取与目标教材范围匹配的公开来源任务。",
                payload={
                    "target_scope": target_scope,
                    "strategy_preferences": directive.strategy_preferences,
                    "budgets": budgets,
                },
                priority=100,
                confidence=0.72,
            ),
            OrchestrationAction(
                action_type="create_extraction_job",
                rationale="解析新抓取文档，并调用 MethodAgent 抽取候选知识项和教师方法。",
                payload={"target_scope": target_scope},
                priority=120,
                confidence=0.7,
            ),
            OrchestrationAction(
                action_type="create_reconciliation_job",
                rationale=(
                    "候选项入库前交给 ReconciliationAgent 与主知识库比较，"
                    "避免重复、误合并或覆盖人工整理内容。"
                ),
                payload={
                    "target_scope": target_scope,
                    "review_policy": directive.review_policy,
                },
                priority=130,
                confidence=0.74,
            ),
        ]
    )

    if context.blocked_sources:
        actions.append(
            OrchestrationAction(
                action_type="request_login",
                rationale="部分有价值来源需要登录授权，必须等待用户提供合法访问信息。",
                payload={"blocked_sources": context.blocked_sources},
                priority=80,
                confidence=0.86,
            )
        )

    return OrchestrationPlan(
        directive=directive,
        actions=actions,
        expected_outcomes=[
            "在用户指定范围内抓取公开来源文档。",
            "通过 MethodAgent 创建候选知识项，不直接依赖规则写入主知识库。",
            "通过 ReconciliationAgent 将候选项与已有知识记录调和后再决定创建、更新或复核。",
        ],
        risk_notes=[
            "PolicyGuard 必须先检查爬取范围、来源权限和预算。",
            "冲突项和低置信度创建项必须进入人工复核队列。",
        ],
        stop_conditions=stop_conditions,
        confidence=0.74,
    )


def _matches_by_ids(
    matches: list[CandidateMatchSchema],
    matched_record_ids: list[str],
) -> list[CandidateMatchSchema]:
    if not matched_record_ids:
        return []
    by_id = {match.record_id: match for match in matches}
    return [by_id[record_id] for record_id in matched_record_ids if record_id in by_id]


RECONCILIATION_AGENT_PROMPT = """
你是 MathScout 的 ReconciliationAgent。
你决定新候选项应如何影响主知识库，输出必须是 JSON object：
{
  "action": "skip" | "update" | "create_variant" | "create" | "conflict" | "review",
  "matched_record_ids": [string],
  "rationale": string,
  "proposed_patch": object,
  "confidence": number,
  "requires_human_review": boolean
}

规则：
- skip：候选项没有新增含义，只能更新来源计数或 last_seen。
- update：同一主记录，但候选项补充了更好证据、别名、步骤、易错点或适用题型。
- create_variant：同一教学方法下有值得保留的教师讲法、辅助线、分类规则或课堂提醒差异。
- create：同一课程语境下没有已有记录表达同一含义。
- conflict：候选项与已有教材版本、章节、适用范围或证据冲突。
- review：相似但不够确定，或证据不足。
- 不要过度合并教师方法；有真实讲法差异时优先 create_variant。
- 高风险 update/create/create_variant/conflict 默认需要人工复核。
""".strip()
