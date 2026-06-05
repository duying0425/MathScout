from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from mathscout.agents.control_plane import ExecutionMonitorDecision, NaturalLanguageCommandAgent
from mathscout.agents.orchestrator import AIOrchestratorAgent, ReconciliationAgent
from mathscout.agents.source_discovery import SourceDiscoveryAgent
from mathscout.config import Settings
from mathscout.db.base import Base
from mathscout.db.models import CrawlJob, CrawlStatus, CrawlTask, ReviewItem
from mathscout.extraction.schemas import CandidateKnowledgeItemSchema, CandidateMatchSchema
from mathscout.orchestration.schemas import NaturalLanguageDirective, OrchestrationContext
from mathscout.pipeline import jobs as job_module
from mathscout.pipeline.jobs import CrawlJobRunner


class FakeClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def chat_json(self, messages, *, temperature: float = 0.1) -> dict[str, Any]:
        self.calls.append({"messages": messages, "temperature": temperature})
        return self.response


def _ai_settings() -> Settings:
    return Settings(
        AI_PROVIDER="deepseek",
        DEEPSEEK_API_KEY="test-key",
        database_url="sqlite+pysqlite:///:memory:",
    )


def test_command_agent_interprets_natural_language_directive() -> None:
    client = FakeClient(
        {
            "interpreted_intent": "补齐七年级有理数教师解题方法。",
            "target_scope": {"textbook_scope": {"series": "beishida", "grade": "7"}},
            "strategy_preferences": {"discover_links": True, "extractor_mode": "ai"},
            "budgets": {"discovery_max_links": 9},
            "stop_conditions": {"no_new_methods_limit": 50},
            "review_policy": {"conflict": "queue_for_review"},
            "rationale": "目标要求 AI 自主探索公开资源。",
            "confidence": 0.91,
        }
    )

    directive = NaturalLanguageCommandAgent(client=client, settings=_ai_settings()).interpret(
        raw_text="优先补齐北师大版七年级有理数教师解题方法",
        form_defaults={"extractor_mode": "auto", "discover_links": False},
        available_urls=["https://example.com"],
        source_mode="manual_urls",
        active_sources=[],
    )

    assert directive is not None
    assert directive.interpreted_intent == "补齐七年级有理数教师解题方法。"
    assert directive.target_scope["urls"] == ["https://example.com"]
    assert directive.strategy_preferences["extractor_mode"] == "ai"
    assert directive.strategy_preferences["discover_links"] is True
    assert directive.stop_conditions["no_new_methods_limit"] == 50


def test_orchestrator_uses_ai_plan_and_backfills_required_stages() -> None:
    client = FakeClient(
        {
            "actions": [
                {
                    "action_type": "discover_sources",
                    "rationale": "先让来源发现 Agent 扩展公开教研链接。",
                    "payload": {"max_links_per_seed": 6},
                    "priority": 80,
                    "confidence": 0.86,
                    "requires_policy_check": True,
                }
            ],
            "expected_outcomes": ["发现高价值教师方法来源"],
            "risk_notes": ["只抓公开 HTTP(S) 来源"],
            "stop_conditions": {"no_new_methods_limit": 50},
            "confidence": 0.88,
        }
    )
    directive = NaturalLanguageDirective(
        raw_text="补充教师方法",
        interpreted_intent="补充教师方法",
        target_scope={"urls": ["https://example.com"]},
        strategy_preferences={"discover_links": True},
    )
    context = OrchestrationContext(objective="补充教师方法")

    plan = AIOrchestratorAgent(client=client, settings=_ai_settings()).plan(directive, context)

    action_types = [action.action_type for action in plan.actions]
    assert action_types[0] == "discover_sources"
    assert "create_crawl_job" in action_types
    assert "create_extraction_job" in action_types
    assert "create_reconciliation_job" in action_types
    assert plan.confidence == 0.88


def test_source_discovery_agent_lets_ai_select_from_policy_allowed_candidates() -> None:
    client = FakeClient(
        {
            "selected_links": [
                {
                    "url": "https://example.com/P/100.html",
                    "label": "AI 选择的教学页",
                    "score": 88,
                    "reasons": ["目标匹配且像具体教学资源"],
                    "confidence": 0.93,
                }
            ],
            "rejected_links": [],
            "strategy_notes": ["优先抓具体教学页"],
            "confidence": 0.9,
        }
    )
    html = """
    <html>
      <body>
        <a href="/P/100.html">第 1 课</a>
        <a href="/mulu/2941.html">初中数学</a>
        <a href="https://other.example.com/math">外站数学</a>
      </body>
    </html>
    """

    links = SourceDiscoveryAgent(client=client, settings=_ai_settings()).discover_from_html(
        html=html,
        seed_url="https://example.com/index.html",
        objective="找七年级有理数教师讲法",
        max_links=5,
    )

    assert [link.url for link in links] == ["https://example.com/P/100.html"]
    assert links[0].score == 88
    assert links[0].reasons[0] == "ai:目标匹配且像具体教学资源"


def test_reconciliation_agent_uses_ai_decision() -> None:
    client = FakeClient(
        {
            "action": "create_variant",
            "matched_record_ids": ["method-1"],
            "rationale": "同一方法但教师讲法路径不同，保留变体。",
            "proposed_patch": {"create_variant": True},
            "confidence": 0.87,
            "requires_human_review": True,
        }
    )
    candidate = CandidateKnowledgeItemSchema(
        item_type="teaching_method",
        title="数轴比较有理数大小",
        payload={"steps": ["画数轴", "比较位置"]},
        evidence=[],
        confidence=0.9,
    )
    match = CandidateMatchSchema(
        table="teaching_methods",
        record_id="method-1",
        title="数形结合比较有理数大小",
        match_reason="标题和步骤相似",
        similarity=0.95,
        confidence=0.92,
    )

    decision = ReconciliationAgent(client=client, settings=_ai_settings()).decide(
        candidate,
        [match],
    )

    assert decision.action == "create_variant"
    assert decision.matched_records == [match]
    assert decision.rationale == "同一方法但教师讲法路径不同，保留变体。"


def test_execution_monitor_can_pause_job_and_create_audit(monkeypatch) -> None:
    class FakeExecutionMonitorAgent:
        def evaluate_task(self, **kwargs):
            return ExecutionMonitorDecision(
                action="pause_job",
                rationale="连续低收益，暂停等待人工检查。",
                confidence=0.82,
            )

    monkeypatch.setattr(job_module, "ExecutionMonitorAgent", FakeExecutionMonitorAgent)

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    with session_factory() as session:
        job = CrawlJob(name="test", status=CrawlStatus.running, source_filter={})
        session.add(job)
        session.flush()
        task = CrawlTask(
            job_id=job.id,
            url="https://example.com/page",
            task_type="crawl_url",
            status=CrawlStatus.succeeded,
            result_json={"methods": 0},
        )
        session.add(task)
        session.flush()

        CrawlJobRunner(session)._apply_execution_monitor_decision(
            job,
            task,
            {"status": "succeeded", "methods": 0},
        )
        session.commit()

        review_items = session.scalars(select(ReviewItem)).all()

    assert job.status == CrawlStatus.paused
    assert review_items == []
