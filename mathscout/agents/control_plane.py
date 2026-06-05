from __future__ import annotations

import json
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, Field

from mathscout.ai.openai_compatible import ChatMessage, OpenAICompatibleClient
from mathscout.config import Settings, get_settings
from mathscout.orchestration.schemas import (
    NaturalLanguageDirective,
    OrchestrationAction,
    OrchestrationContext,
    OrchestrationPlan,
)


class ChatJsonClient(Protocol):
    def chat_json(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        ...


TModel = TypeVar("TModel", bound=BaseModel)


AI_DISABLED_PROVIDERS = {"", "rule", "rules", "off", "disabled", "none"}


class AgentCallFailure(RuntimeError):
    pass


class LLMBackedAgent:
    agent_name = "agent"
    temperature = 0.1

    def __init__(
        self,
        client: ChatJsonClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client

    @property
    def ai_enabled(self) -> bool:
        provider = self.settings.ai_provider.lower().strip()
        return provider not in AI_DISABLED_PROVIDERS and bool(self.settings.ai_api_key)

    @property
    def client(self) -> ChatJsonClient:
        if self._client is not None:
            return self._client
        self._client = OpenAICompatibleClient(self.settings)
        return self._client

    def call_model(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        output_model: type[TModel],
        temperature: float | None = None,
    ) -> TModel:
        if not self.ai_enabled and self._client is None:
            raise AgentCallFailure(f"{self.agent_name} AI is disabled.")

        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(
                role="user",
                content=json.dumps(payload, ensure_ascii=False, default=str),
            ),
        ]
        try:
            response = self.client.chat_json(
                messages,
                temperature=self.temperature if temperature is None else temperature,
            )
            return output_model.model_validate(response)
        except Exception as exc:
            raise AgentCallFailure(f"{self.agent_name} model call failed: {exc}") from exc


class CommandInterpretation(BaseModel):
    interpreted_intent: str
    target_scope: dict[str, Any] = Field(default_factory=dict)
    strategy_preferences: dict[str, Any] = Field(default_factory=dict)
    budgets: dict[str, Any] = Field(default_factory=dict)
    stop_conditions: dict[str, Any] = Field(default_factory=dict)
    review_policy: dict[str, Any] = Field(default_factory=dict)
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)


class OrchestratorPlanPayload(BaseModel):
    actions: list[OrchestrationAction]
    expected_outcomes: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    stop_conditions: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)


class SourceCandidate(BaseModel):
    url: str
    label: str
    prior_score: float = 0.0
    prior_reasons: list[str] = Field(default_factory=list)
    policy: dict[str, Any] = Field(default_factory=dict)


class SourceSelectionItem(BaseModel):
    url: str
    label: str | None = None
    score: float = Field(ge=0.0, le=100.0)
    reasons: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class SourceSelection(BaseModel):
    selected_links: list[SourceSelectionItem] = Field(default_factory=list)
    rejected_links: list[dict[str, Any]] = Field(default_factory=list)
    strategy_notes: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


ExecutionAction = Literal[
    "continue",
    "pause_job",
    "stop_job",
    "request_review",
    "adjust_strategy",
]


class ExecutionMonitorDecision(BaseModel):
    action: ExecutionAction
    rationale: str
    strategy_patch: dict[str, Any] = Field(default_factory=dict)
    review_reason: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class NaturalLanguageCommandAgent(LLMBackedAgent):
    agent_name = "NaturalLanguageCommandAgent"

    def interpret(
        self,
        *,
        raw_text: str,
        form_defaults: dict[str, Any],
        available_urls: list[str],
        source_mode: str,
        active_sources: list[dict[str, Any]],
    ) -> NaturalLanguageDirective | None:
        if not self.ai_enabled and self._client is None:
            return None
        try:
            result = self.call_model(
                system_prompt=COMMAND_AGENT_PROMPT,
                payload={
                    "raw_text": raw_text,
                    "form_defaults": form_defaults,
                    "available_urls": available_urls,
                    "source_mode": source_mode,
                    "active_sources": active_sources[:50],
                },
                output_model=CommandInterpretation,
            )
        except AgentCallFailure:
            return None

        target_scope = {
            **result.target_scope,
            "source_mode": source_mode,
            "urls": available_urls,
        }
        strategy_preferences = {
            **form_defaults,
            **result.strategy_preferences,
            "control_plane": "multi_agent_ai",
            "command_agent_rationale": result.rationale,
        }
        budgets = {
            **_dict_value(form_defaults.get("budgets")),
            **result.budgets,
            "seed_url_count": len(available_urls),
        }
        return NaturalLanguageDirective(
            raw_text=raw_text,
            interpreted_intent=result.interpreted_intent,
            target_scope=target_scope,
            strategy_preferences=strategy_preferences,
            budgets=budgets,
            stop_conditions=result.stop_conditions,
            review_policy=result.review_policy,
        )


class OrchestratorPlanningAgent(LLMBackedAgent):
    agent_name = "OrchestratorPlanningAgent"

    def plan(
        self,
        directive: NaturalLanguageDirective,
        context: OrchestrationContext,
    ) -> OrchestrationPlan | None:
        if not self.ai_enabled and self._client is None:
            return None
        try:
            result = self.call_model(
                system_prompt=ORCHESTRATOR_AGENT_PROMPT,
                payload={
                    "directive": directive.model_dump(mode="json"),
                    "context": context.model_dump(mode="json"),
                    "allowed_action_types": [
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
                    ],
                },
                output_model=OrchestratorPlanPayload,
            )
        except AgentCallFailure:
            return None
        return OrchestrationPlan(
            directive=directive,
            actions=result.actions,
            expected_outcomes=result.expected_outcomes,
            risk_notes=result.risk_notes,
            stop_conditions=result.stop_conditions or directive.stop_conditions,
            confidence=result.confidence,
        )


class SourceSelectionAgent(LLMBackedAgent):
    agent_name = "SourceSelectionAgent"

    def select_links(
        self,
        *,
        objective: str,
        seed_url: str,
        candidates: list[SourceCandidate],
        max_links: int,
    ) -> SourceSelection | None:
        if not self.ai_enabled and self._client is None:
            return None
        try:
            return self.call_model(
                system_prompt=SOURCE_SELECTION_AGENT_PROMPT,
                payload={
                    "objective": objective,
                    "seed_url": seed_url,
                    "max_links": max_links,
                    "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
                },
                output_model=SourceSelection,
            )
        except AgentCallFailure:
            return None


class ExecutionMonitorAgent(LLMBackedAgent):
    agent_name = "ExecutionMonitorAgent"

    def evaluate_task(
        self,
        *,
        objective: str,
        job: dict[str, Any],
        task: dict[str, Any],
        result: dict[str, Any],
        task_counts: dict[str, int],
    ) -> ExecutionMonitorDecision | None:
        if not self.ai_enabled and self._client is None:
            return None
        try:
            return self.call_model(
                system_prompt=EXECUTION_MONITOR_AGENT_PROMPT,
                payload={
                    "objective": objective,
                    "job": job,
                    "task": task,
                    "result": result,
                    "task_counts": task_counts,
                },
                output_model=ExecutionMonitorDecision,
            )
        except AgentCallFailure:
            return None


def _dict_value(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


COMMAND_AGENT_PROMPT = """
你是 MathScout 的 NaturalLanguageCommandAgent。
你负责把用户自然语言目标转换为可执行的结构化指令，不要直接执行工具。

输出必须是 JSON object，字段严格为：
{
  "interpreted_intent": string,
  "target_scope": object,
  "strategy_preferences": object,
  "budgets": object,
  "stop_conditions": object,
  "review_policy": object,
  "rationale": string,
  "confidence": number
}

要求：
- 主动识别教材版本、年级、册别、章节、知识点、来源偏好、停止条件和复核要求。
- 如果用户希望 AI 自主探索，应设置 strategy_preferences.discover_links=true。
- extractor_mode 只能是 auto、ai、deepseek、rule 之一。
- 不要编造 URL；只能使用输入里的 available_urls。
- 预算和停止条件要可执行，例如 max_seed_urls、discovery_max_links、no_new_methods_limit。
""".strip()


ORCHESTRATOR_AGENT_PROMPT = """
你是 MathScout 的 AIOrchestratorAgent，是多 Agent 控制平面的总控。
你根据用户指令和当前系统状态，分派后续 Agent 与工具执行。

输出必须是 JSON object，字段严格为：
{
  "actions": [
    {
      "action_type": string,
      "rationale": string,
      "payload": object,
      "priority": integer,
      "confidence": number,
      "requires_policy_check": boolean
    }
  ],
  "expected_outcomes": [string],
  "risk_notes": [string],
  "stop_conditions": object,
  "confidence": number
}

要求：
- 只使用输入中的 allowed_action_types。
- 规划必须体现多 Agent 流程：来源发现、爬取任务、抽取、调和、质量/停止条件。
- AI 可以决定是否发现链接、优先级、批量规模、失败处理和何时请求人工复核。
- 硬性策略边界由 PolicyGuard 执行；不要建议绕过登录、验证码、付费、robots 或版权限制。
- 每个 action 的 payload 要包含给执行 Agent 使用的参数。
""".strip()


SOURCE_SELECTION_AGENT_PROMPT = """
你是 MathScout 的 SourceSelectionAgent。
你不是关键词打分器，而是根据目标判断哪些候选链接最值得作为下一批抓取任务。

输出必须是 JSON object，字段严格为：
{
  "selected_links": [
    {
      "url": string,
      "label": string | null,
      "score": number,
      "reasons": [string],
      "confidence": number
    }
  ],
  "rejected_links": [object],
  "strategy_notes": [string],
  "confidence": number
}

要求：
- 只能从 candidates 中选择 URL，不能发明 URL。
- 不要选择 policy.allowed 为 false 的链接。
- 优先选择与初中数学、教材章节、教师解题方法、教学设计、易错点、例题讲法相关的页面。
- 普通首页、泛目录、广告、登录注册、非数学科目、纯静态资源不要选。
- selected_links 数量不超过 max_links。
""".strip()


EXECUTION_MONITOR_AGENT_PROMPT = """
你是 MathScout 的 ExecutionMonitorAgent。
你观察每个任务执行结果，并决定爬取作业下一步继续、暂停、停止、请求复核或调整策略。

输出必须是 JSON object，字段严格为：
{
  "action": "continue" | "pause_job" | "stop_job" | "request_review" | "adjust_strategy",
  "rationale": string,
  "strategy_patch": object,
  "review_reason": string | null,
  "confidence": number
}

要求：
- 只有明显低收益、连续失败、登录阻塞、预算耗尽或用户停止条件触发时才 pause_job 或 stop_job。
- 发现冲突、异常失败或需要人工访问凭据时 request_review。
- 普通成功抓取一般 continue。
- strategy_patch 只能包含执行策略调整，不要包含破坏性数据库操作。
""".strip()
