from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mathscout.admin import routes as admin_routes
from mathscout.agents.base import AgentResult, AgentStatus
from mathscout.crawler.fetchers import FetchResult
from mathscout.db.base import Base
from mathscout.db.models import (
    CandidateItemType,
    CandidateKnowledgeItem,
    CrawlJob,
    CrawlStatus,
    CrawlTask,
    ManualEditLog,
    ReconciliationAction,
    ReconciliationDecision,
    ReviewStatus,
    SourceDocument,
)
from mathscout.db.session import get_session
from mathscout.main import create_app
from mathscout.pipeline import jobs as job_module
from mathscout.pipeline.crawl import CrawlPipeline
from mathscout.pipeline.jobs import CrawlJobRunner


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_crawl_pipeline_marks_http_error_as_fetch_failed(tmp_path) -> None:
    raw_path = tmp_path / "bad.html"
    raw_path.write_text("<html>bad request</html>", encoding="utf-8")

    class FakeFetcher:
        settings = SimpleNamespace(text_storage_dir=tmp_path)

        async def fetch(self, url: str) -> FetchResult:
            return FetchResult(
                url=url,
                status_code=400,
                content_type="text/html",
                checksum="bad-request",
                raw_path=raw_path,
                needs_login=False,
            )

    session_factory = _session_factory()
    with session_factory() as session:
        pipeline = CrawlPipeline(session, extractor_mode="rule")
        pipeline.fetcher = FakeFetcher()

        result = pipeline.crawl_url("https://example.com/bad")
        document = session.scalar(select(SourceDocument))

    assert result["status"] == "fetch_failed"
    assert result["http_status"] == 400
    assert result["candidates"] == 0
    assert document is not None
    assert document.status == CrawlStatus.failed


def test_discovery_http_failure_is_persisted_on_task(monkeypatch) -> None:
    class FakeSourceDiscoveryAgent:
        def run(self, **kwargs):
            return AgentResult(
                status=AgentStatus.failed,
                payload={
                    "seed_url": kwargs["seed_url"],
                    "http_status": 400,
                    "selected_links": [],
                    "retryable": False,
                },
                error="种子页面 HTTP 400，不能发现链接。",
            )

    monkeypatch.setattr(job_module, "SourceDiscoveryAgent", FakeSourceDiscoveryAgent)
    session_factory = _session_factory()
    with session_factory() as session:
        job = CrawlJob(name="test", status=CrawlStatus.pending, source_filter={})
        session.add(job)
        session.flush()
        task = CrawlTask(
            job_id=job.id,
            url="https://example.com/bad",
            task_type="discover_links",
            status=CrawlStatus.pending,
        )
        session.add(task)
        session.commit()

        CrawlJobRunner(session).run_job(str(job.id))

        session.refresh(job)
        session.refresh(task)

    assert job.status == CrawlStatus.failed
    assert task.status == CrawlStatus.failed
    assert task.retries == CrawlJobRunner.max_retries
    assert task.result_json["status"] == AgentStatus.failed.value
    assert task.error == "种子页面 HTTP 400，不能发现链接。"


def test_crawl_job_status_routes_are_not_shadowed() -> None:
    session_factory = _session_factory()
    with session_factory() as session:
        job = CrawlJob(name="test", status=CrawlStatus.pending, source_filter={})
        session.add(job)
        session.flush()
        job_id = str(job.id)
        session.commit()

    app = create_app()

    def override_session():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        list_response = client.get("/admin/crawl-jobs/status")
        detail_response = client.get(f"/admin/crawl-jobs/{job_id}/status")

    assert list_response.status_code == 200
    assert detail_response.status_code == 200
    assert list_response.json()["jobs"][0]["id"] == job_id
    assert detail_response.json()["job"]["id"] == job_id


def test_review_candidate_action_updates_status_and_audit_log() -> None:
    session_factory = _session_factory()
    with session_factory() as session:
        document = SourceDocument(url="https://example.com/page")
        session.add(document)
        session.flush()
        candidate = CandidateKnowledgeItem(
            document_id=document.id,
            item_type=CandidateItemType.teaching_method,
            title="数轴比较有理数大小",
            payload={"summary": "用数轴位置比较大小。"},
            evidence_ids=[],
            confidence=0.8,
            review_status=ReviewStatus.pending,
        )
        session.add(candidate)
        session.flush()
        decision = ReconciliationDecision(
            candidate_id=candidate.id,
            action=ReconciliationAction.create,
            matched_table="teaching_methods",
            matched_ids=[],
            rationale="测试调和。",
            proposed_patch={},
            confidence=0.8,
            auto_applied=True,
            review_status=ReviewStatus.pending,
        )
        session.add(decision)
        session.commit()

        response = admin_routes.review_candidate_action(
            str(candidate.id),
            "approve",
            session,
            reason="",
        )

        session.refresh(candidate)
        session.refresh(decision)
        logs = session.scalars(select(ManualEditLog)).all()

    assert response.status_code == 303
    assert candidate.review_status == ReviewStatus.approved
    assert decision.review_status == ReviewStatus.approved
    assert len(logs) == 1
    assert logs[0].target_table == "candidate_knowledge_items"
