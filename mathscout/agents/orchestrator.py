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
    """根据人工目标和当前状态生成可执行计划。

    当前版本先保持确定性，确保计划可审计。后续接入 LLM 策略层时，
    仍应沿用同一输入/输出契约，并把每一步写入 `agent_decisions`。
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

        if directive.strategy_preferences.get("discover_links", True):
            actions.append(
                OrchestrationAction(
                    action_type="discover_sources",
                    rationale=(
                        "让 SourceDiscoveryAgent 先检查种子页，给候选链接打分，"
                        "再选择最像教学资源的页面进入爬取队列。"
                    ),
                    payload={
                        "target_scope": target_scope,
                        "max_links_per_seed": directive.strategy_preferences.get(
                            "discovery_max_links", 12
                        ),
                        "policy": "只允许同域公开 HTTP(S) 链接",
                    },
                    priority=90,
                    confidence=0.78,
                )
            )

        actions.append(
            OrchestrationAction(
                action_type="create_crawl_job",
                rationale=(
                    "创建或继续爬取与目标教材范围匹配的公开来源任务。"
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
                rationale="解析新抓取文档，并抽取候选知识项和教师方法。",
                payload={"target_scope": target_scope},
                priority=120,
                confidence=0.7,
            )
        )
        actions.append(
            OrchestrationAction(
                action_type="create_reconciliation_job",
                rationale=(
                    "入库前先把候选项与已有主知识库记录比较，"
                    "避免重复、误合并或覆盖人工整理内容。"
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
                        "部分有价值来源需要登录授权，必须等待用户提供合法访问信息。"
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
                "在用户指定范围内抓取公开来源文档。",
                "先创建候选知识项，不直接写入主知识库表。",
                "将候选项与已有知识记录调和后再决定是否创建、更新或复核。",
            ],
            risk_notes=[
                "PolicyGuard 必须先检查爬取范围、来源权限和预算。",
                "冲突项和低置信度创建项必须进入人工复核队列。",
            ],
            stop_conditions=stop_conditions,
            confidence=0.74,
        )


class ReconciliationAgent:
    """判断新抽取候选项应该如何影响主知识库数据库。

    后续真实实现会从 SQL/向量检索中取相似主知识库记录。当前骨架先保持
    决策契约稳定，供 UI、worker 和未来模型 prompt 使用。
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
