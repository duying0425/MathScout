from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from mathscout.agents.base import AgentResult, AgentStatus
from mathscout.db.base import Base
from mathscout.db.models import (
    AccessLevel,
    AgentDecision,
    CrawlJob,
    CrawlStatus,
    CrawlTask,
    ReviewItem,
    SourceDocument,
    SourceSite,
)
from mathscout.pipeline import jobs as job_module
from mathscout.pipeline.jobs import (
    CrawlJobDispatcher,
    CrawlJobRunner,
    CrawlJobScheduler,
    CrawlRuntimeHooks,
    CrawlTaskExecutor,
)


def _session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_scheduler_start_job_resets_stale_and_blocked_tasks() -> None:
    session_factory = _session_factory()
    with session_factory() as session:
        job = CrawlJob(name="test", status=CrawlStatus.blocked, source_filter={})
        session.add(job)
        session.flush()
        stale = CrawlTask(
            job_id=job.id,
            url="https://example.com/stale",
            task_type="crawl_url",
            status=CrawlStatus.running,
        )
        blocked = CrawlTask(
            job_id=job.id,
            url="https://example.com/blocked",
            task_type="discover_links",
            status=CrawlStatus.blocked,
        )
        session.add_all([stale, blocked])
        session.commit()

        CrawlJobScheduler(session, max_retries=3).start_job(job)

        session.refresh(job)
        session.refresh(stale)
        session.refresh(blocked)

    assert job.status == CrawlStatus.running
    assert stale.status == CrawlStatus.pending
    assert blocked.status == CrawlStatus.pending
    assert stale.error == "Reset from stale running state before job resume."
    assert blocked.error == "Reset from blocked state before job resume."


def test_scheduler_skips_tasks_until_not_before_is_due() -> None:
    session_factory = _session_factory()
    with session_factory() as session:
        job = CrawlJob(name="test", status=CrawlStatus.running, source_filter={})
        session.add(job)
        session.flush()
        future_task = CrawlTask(
            job_id=job.id,
            url="https://example.com/future",
            task_type="crawl_url",
            status=CrawlStatus.pending,
            not_before=datetime.utcnow() + timedelta(minutes=5),
        )
        due_task = CrawlTask(
            job_id=job.id,
            url="https://example.com/due",
            task_type="crawl_url",
            status=CrawlStatus.pending,
            not_before=datetime.utcnow() - timedelta(seconds=1),
        )
        session.add_all([future_task, due_task])
        session.commit()

        next_task = CrawlJobScheduler(session, max_retries=3).next_task(job.id)

    assert next_task is not None
    assert next_task.url == "https://example.com/due"


def test_dispatcher_returns_only_started_due_pending_jobs() -> None:
    session_factory = _session_factory()
    with session_factory() as session:
        started_due = CrawlJob(
            name="started-due",
            status=CrawlStatus.pending,
            source_filter={"extractor_mode": "rule"},
            started_at=datetime.utcnow() - timedelta(minutes=5),
        )
        not_started = CrawlJob(
            name="not-started",
            status=CrawlStatus.pending,
            source_filter={"extractor_mode": "rule"},
        )
        future = CrawlJob(
            name="future",
            status=CrawlStatus.pending,
            source_filter={"extractor_mode": "ai"},
            started_at=datetime.utcnow() - timedelta(minutes=5),
        )
        paused = CrawlJob(
            name="paused",
            status=CrawlStatus.paused,
            source_filter={"extractor_mode": "rule"},
            started_at=datetime.utcnow() - timedelta(minutes=5),
        )
        session.add_all([started_due, not_started, future, paused])
        session.flush()
        session.add_all(
            [
                CrawlTask(
                    job_id=started_due.id,
                    url="https://example.com/due",
                    task_type="crawl_url",
                    status=CrawlStatus.pending,
                    not_before=datetime.utcnow() - timedelta(seconds=1),
                ),
                CrawlTask(
                    job_id=not_started.id,
                    url="https://example.com/not-started",
                    task_type="crawl_url",
                    status=CrawlStatus.pending,
                    not_before=datetime.utcnow() - timedelta(seconds=1),
                ),
                CrawlTask(
                    job_id=future.id,
                    url="https://example.com/future",
                    task_type="crawl_url",
                    status=CrawlStatus.pending,
                    not_before=datetime.utcnow() + timedelta(minutes=5),
                ),
                CrawlTask(
                    job_id=paused.id,
                    url="https://example.com/paused",
                    task_type="crawl_url",
                    status=CrawlStatus.pending,
                    not_before=datetime.utcnow() - timedelta(seconds=1),
                ),
            ]
        )
        session.commit()

        due_jobs = CrawlJobDispatcher(session).due_jobs(limit=10)

    assert len(due_jobs) == 1
    assert due_jobs[0].job_id == str(started_due.id)
    assert due_jobs[0].extractor_mode == "rule"


def test_task_executor_runs_discovery_and_records_created_tasks(monkeypatch) -> None:
    class FakeSourceDiscoveryAgent:
        def run(self, **kwargs):
            return AgentResult(
                status=AgentStatus.succeeded,
                payload={
                    "seed_url": kwargs["seed_url"],
                    "selected_links": [
                        {
                            "url": "https://example.com/math",
                            "label": "初中数学教学设计",
                            "score": 50,
                            "reasons": ["keyword:初中", "keyword:教学设计"],
                            "policy": {"allowed": True},
                        }
                    ],
                    "selected_count": 1,
                },
            )

    monkeypatch.setattr(job_module, "SourceDiscoveryAgent", FakeSourceDiscoveryAgent)
    session_factory = _session_factory()
    with session_factory() as session:
        job = CrawlJob(name="test", status=CrawlStatus.running, source_filter={})
        session.add(job)
        session.flush()
        task = CrawlTask(
            job_id=job.id,
            url="https://example.com",
            task_type="discover_links",
            status=CrawlStatus.running,
        )
        session.add(task)
        session.commit()

        outcome = CrawlTaskExecutor(session, extractor_mode="rule", max_retries=3).execute(
            job,
            task,
        )
        session.commit()

        tasks = session.scalars(
            select(CrawlTask)
            .where(CrawlTask.job_id == job.id)
            .order_by(CrawlTask.url, CrawlTask.task_type)
        ).all()
        decisions = session.scalars(select(AgentDecision)).all()

    assert outcome.error is None
    assert outcome.result["status"] == "succeeded"
    assert outcome.result["runtime_status"] == "succeeded"
    assert outcome.result["selected_count"] == 1
    assert outcome.result["created_tasks"] == 2
    assert outcome.result["metrics"] == {"selected_count": 1, "created_tasks": 2}
    assert outcome.result["requires_review"] is False
    assert task.status == CrawlStatus.succeeded
    assert [(item.url, item.task_type) for item in tasks] == [
        ("https://example.com", "crawl_url"),
        ("https://example.com", "discover_links"),
        ("https://example.com/math", "crawl_url"),
    ]
    assert len(decisions) == 2


def test_task_executor_fails_non_http_url_before_fetch() -> None:
    session_factory = _session_factory()
    with session_factory() as session:
        job = CrawlJob(name="test", status=CrawlStatus.running, source_filter={})
        session.add(job)
        session.flush()
        task = CrawlTask(
            job_id=job.id,
            url="ftp://example.com/math",
            task_type="crawl_url",
            status=CrawlStatus.running,
        )
        session.add(task)
        session.commit()

        outcome = CrawlTaskExecutor(session, extractor_mode="rule", max_retries=3).execute(
            job,
            task,
        )

    assert task.status == CrawlStatus.failed
    assert task.retries == 3
    assert outcome.result["status"] == "failed"
    assert outcome.result["retryable"] is False
    assert outcome.error == "只支持带域名的 HTTP(S) URL。"


def test_task_executor_blocks_robots_denied_url_before_fetch() -> None:
    class DenyRobots:
        def can_fetch(self, url: str) -> bool:
            return False

    session_factory = _session_factory()
    with session_factory() as session:
        site = SourceSite(
            name="Example",
            base_url="https://example.com",
            domain="example.com",
            category="teacher_resource",
            access_level=AccessLevel.public,
            enabled=True,
            crawl_delay_seconds=0,
        )
        job = CrawlJob(name="test", status=CrawlStatus.running, source_filter={})
        session.add_all([site, job])
        session.flush()
        task = CrawlTask(
            job_id=job.id,
            url="https://example.com/math",
            task_type="crawl_url",
            status=CrawlStatus.running,
        )
        session.add(task)
        session.commit()

        hooks = CrawlRuntimeHooks(session, max_retries=3, robots_checker=DenyRobots())
        outcome = CrawlTaskExecutor(
            session,
            extractor_mode="rule",
            max_retries=3,
            hooks=hooks,
        ).execute(job, task)

    assert task.status == CrawlStatus.blocked
    assert task.retries == 3
    assert outcome.result["status"] == "blocked"
    assert outcome.result["requires_review"] is True
    assert outcome.result["review_reason"] == "robots.txt 不允许抓取该 URL。"


def test_runtime_review_item_is_created_for_blocked_source_policy() -> None:
    session_factory = _session_factory()
    with session_factory() as session:
        site = SourceSite(
            name="Example",
            base_url="https://example.com",
            domain="example.com",
            category="teacher_resource",
            access_level=AccessLevel.login_required,
            enabled=True,
            crawl_delay_seconds=0,
        )
        job = CrawlJob(name="test", status=CrawlStatus.pending, source_filter={})
        session.add_all([site, job])
        session.flush()
        task = CrawlTask(
            job_id=job.id,
            url="https://example.com/private",
            task_type="crawl_url",
            status=CrawlStatus.pending,
        )
        session.add(task)
        session.commit()

        result = CrawlJobRunner(session, extractor_mode="rule").run_job(str(job.id))

        session.refresh(job)
        session.refresh(task)
        review_items = session.scalars(select(ReviewItem)).all()

    assert result["status"] == "blocked"
    assert job.status == CrawlStatus.blocked
    assert task.status == CrawlStatus.blocked
    assert task.result_json["requires_review"] is True
    assert len(review_items) == 1
    assert review_items[0].target_id == task.id
    assert review_items[0].reason == "来源站点访问级别为 login_required，需要人工复核。"


def test_crawl_delay_defers_task_without_sleeping() -> None:
    session_factory = _session_factory()
    with session_factory() as session:
        site = SourceSite(
            name="Example",
            base_url="https://example.com",
            domain="example.com",
            category="teacher_resource",
            access_level=AccessLevel.public,
            enabled=True,
            crawl_delay_seconds=60,
        )
        job = CrawlJob(
            name="test",
            status=CrawlStatus.pending,
            source_filter={"respect_robots": False},
        )
        session.add_all([site, job])
        session.flush()
        session.add(
            SourceDocument(
                site_id=site.id,
                url="https://example.com/previous",
                status=CrawlStatus.succeeded,
                fetched_at=datetime.utcnow(),
            )
        )
        task = CrawlTask(
            job_id=job.id,
            url="https://example.com/next",
            task_type="crawl_url",
            status=CrawlStatus.pending,
        )
        session.add(task)
        session.commit()

        result = CrawlJobRunner(session, extractor_mode="rule").run_job(str(job.id))

        session.refresh(job)
        session.refresh(task)

    assert result["status"] == "pending"
    assert job.status == CrawlStatus.pending
    assert task.status == CrawlStatus.pending
    assert task.not_before is not None
    assert task.result_json["runtime_status"] == "pending"
    assert task.result_json["payload"]["policy"] == "crawl_delay"
