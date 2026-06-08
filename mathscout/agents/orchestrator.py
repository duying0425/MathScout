from mathscout.orchestration.schemas import (
    NaturalLanguageDirective,
    OrchestrationAction,
    OrchestrationContext,
    OrchestrationPlan,
)


class AIOrchestratorAgent:
    """把人工目标转换成可审计的执行计划（爬取 → 提取 → 调和）。

    当前实现是**确定性规则编排**，尚未接入 LLM：无论目标内容如何，都会按固定
    顺序产出"发现链接 → 创建爬取作业 → 提取 → 调和"等动作，再把每一步写入
    `agent_decisions` 供前端追溯。命名保留 `AIOrchestrator` 是为了在后续接入
    LLM 策略层时复用同一套输入/输出契约（`NaturalLanguageDirective` /
    `OrchestrationPlan`），届时只需替换 `plan()` 内部逻辑即可。
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
                        "让 SourceDiscoveryAgent 先检查种子页，按关键词规则给候选链接打分，"
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
