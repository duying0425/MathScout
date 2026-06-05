from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from mathscout.agents.base import AgentStatus
from mathscout.agents.control_plane import ExecutionMonitorAgent
from mathscout.agents.source_discovery import SourceDiscoveryAgent
from mathscout.config import get_settings
from mathscout.crawler.robots import RobotsChecker
from mathscout.db.models import (
    AccessLevel,
    AgentDecision,
    AgentDecisionType,
    CrawlJob,
    CrawlStatus,
    CrawlTask,
    ReviewItem,
    ReviewStatus,
    SourceDocument,
    SourceSite,
)
from mathscout.pipeline.crawl import CrawlPipeline
from mathscout.runtime import RuntimeObservation, RuntimeStatus, normalize_task_result


@dataclass(frozen=True)
class TaskExecutionOutcome:
    result: dict[str, object]
    error: str | None = None


@dataclass(frozen=True)
class RuntimeHookOutcome:
    task_status: CrawlStatus
    outcome: TaskExecutionOutcome


@dataclass(frozen=True)
class DueCrawlJob:
    job_id: str
    extractor_mode: str


class CrawlJobScheduler:
    terminal_statuses = {
        CrawlStatus.paused,
        CrawlStatus.cancelled,
        CrawlStatus.succeeded,
        CrawlStatus.failed,
        CrawlStatus.blocked,
    }

    def __init__(self, session: Session, max_retries: int) -> None:
        self.session = session
        self.max_retries = max_retries

    def start_job(self, job: CrawlJob) -> None:
        original_status = job.status
        job.status = CrawlStatus.running
        job.started_at = job.started_at or datetime.utcnow()
        self._reset_stale_running_tasks(job.id)
        if original_status == CrawlStatus.blocked:
            self._reset_blocked_tasks(job.id)
        self.session.commit()

    def refresh_job_or_raise(self, job_id: uuid.UUID, raw_job_id: str) -> CrawlJob:
        self.session.expire_all()
        job = self.session.get(CrawlJob, job_id)
        if job is None:
            raise ValueError(f"运行过程中找不到爬取任务: {raw_job_id}")
        return job

    def next_task(self, job_id: uuid.UUID) -> CrawlTask | None:
        now = datetime.utcnow()
        return self.session.scalar(
            select(CrawlTask)
            .where(
                CrawlTask.job_id == job_id,
                or_(CrawlTask.not_before.is_(None), CrawlTask.not_before <= now),
                or_(
                    CrawlTask.status == CrawlStatus.pending,
                    (CrawlTask.status == CrawlStatus.failed)
                    & (CrawlTask.retries < self.max_retries),
                ),
            )
            .order_by(CrawlTask.created_at.asc())
        )

    def mark_task_running(self, task: CrawlTask) -> None:
        task.status = CrawlStatus.running
        task.not_before = None
        task.updated_at = datetime.utcnow()
        self.session.commit()

    def finish_when_no_work(self, job_id: uuid.UUID) -> CrawlStatus:
        job = self.session.get(CrawlJob, job_id)
        if job is None:
            raise ValueError(f"找不到爬取任务: {job_id}")
        terminal_status = self.terminal_status(job_id)
        job.status = terminal_status
        if terminal_status in {CrawlStatus.pending, CrawlStatus.running}:
            job.finished_at = None
        else:
            job.finished_at = datetime.utcnow()
        self.session.commit()
        return terminal_status

    def job_status(self, job_id: uuid.UUID) -> dict[str, int]:
        return {
            status.value: count
            for status, count in self.session.execute(
                select(CrawlTask.status, func.count(CrawlTask.id))
                .where(CrawlTask.job_id == job_id)
                .group_by(CrawlTask.status)
            ).all()
        }

    def terminal_status(self, job_id: uuid.UUID) -> CrawlStatus:
        counts = dict(
            self.session.execute(
                select(CrawlTask.status, func.count(CrawlTask.id))
                .where(CrawlTask.job_id == job_id)
                .group_by(CrawlTask.status)
            ).all()
        )
        if counts.get(CrawlStatus.failed, 0):
            return CrawlStatus.failed
        if counts.get(CrawlStatus.blocked, 0):
            return CrawlStatus.blocked
        if counts.get(CrawlStatus.cancelled, 0):
            return CrawlStatus.cancelled
        if counts.get(CrawlStatus.running, 0):
            return CrawlStatus.running
        if counts.get(CrawlStatus.pending, 0):
            return CrawlStatus.pending
        return CrawlStatus.succeeded

    def _reset_stale_running_tasks(self, job_id: uuid.UUID) -> None:
        stale_tasks = self.session.scalars(
            select(CrawlTask).where(
                CrawlTask.job_id == job_id,
                CrawlTask.status == CrawlStatus.running,
            )
        ).all()
        for stale_task in stale_tasks:
            stale_task.status = CrawlStatus.pending
            stale_task.not_before = None
            stale_task.error = "Reset from stale running state before job resume."
            stale_task.updated_at = datetime.utcnow()

    def _reset_blocked_tasks(self, job_id: uuid.UUID) -> None:
        blocked_tasks = self.session.scalars(
            select(CrawlTask).where(
                CrawlTask.job_id == job_id,
                CrawlTask.status == CrawlStatus.blocked,
            )
        ).all()
        for blocked_task in blocked_tasks:
            blocked_task.status = CrawlStatus.pending
            blocked_task.not_before = None
            blocked_task.error = "Reset from blocked state before job resume."
            blocked_task.updated_at = datetime.utcnow()


class CrawlRuntimeHooks:
    supported_schemes = {"http", "https"}
    review_access_levels = {AccessLevel.login_required, AccessLevel.paid_or_restricted}

    def __init__(
        self,
        session: Session,
        max_retries: int,
        robots_checker: RobotsChecker | None = None,
    ) -> None:
        self.session = session
        self.max_retries = max_retries
        self.robots_checker = robots_checker or RobotsChecker(get_settings().default_user_agent)

    def before_fetch(self, job: CrawlJob, task: CrawlTask) -> RuntimeHookOutcome | None:
        parsed = urlparse(task.url)
        if parsed.scheme.lower() not in self.supported_schemes or not parsed.netloc:
            return self._failed(
                task,
                error="只支持带域名的 HTTP(S) URL。",
                retryable=False,
                payload={
                    "hook": "before_fetch",
                    "url": task.url,
                    "scheme": parsed.scheme,
                    "domain": parsed.netloc,
                },
            )

        site = self._source_site_for_url(task.url)
        if site is None:
            return None
        if not site.enabled:
            return self._blocked(
                task,
                reason="来源站点已停用，需要人工复核后重新启用。",
                payload=self._site_policy_payload(task.url, site, "source_enabled"),
            )
        if site.access_level in self.review_access_levels:
            return self._blocked(
                task,
                reason=f"来源站点访问级别为 {site.access_level.value}，需要人工复核。",
                payload=self._site_policy_payload(task.url, site, "source_access_level"),
            )
        if self._respect_robots(job):
            site.robots_checked_at = datetime.utcnow()
            try:
                robots_allowed = self.robots_checker.can_fetch(task.url)
            except Exception as exc:
                return self._failed(
                    task,
                    error=f"robots.txt 检查失败：{exc}",
                    retryable=True,
                    payload=self._site_policy_payload(task.url, site, "robots_error"),
                )
            if not robots_allowed:
                return self._blocked(
                    task,
                    reason="robots.txt 不允许抓取该 URL。",
                    payload=self._site_policy_payload(task.url, site, "robots"),
                )

        return self._defer_for_crawl_delay(task, site)

    def _source_site_for_url(self, url: str) -> SourceSite | None:
        parsed = urlparse(url)
        base_url = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
        domain = (parsed.hostname or parsed.netloc).lower()
        return self.session.scalar(
            select(SourceSite).where(
                or_(
                    SourceSite.base_url == base_url,
                    SourceSite.base_url == base_url.rstrip("/"),
                    SourceSite.base_url == f"{base_url}/",
                    SourceSite.domain == parsed.netloc,
                    SourceSite.domain == domain,
                )
            )
        )

    def _respect_robots(self, job: CrawlJob) -> bool:
        source_filter = job.source_filter or {}
        value = source_filter.get("respect_robots", True)
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)

    def _defer_for_crawl_delay(
        self,
        task: CrawlTask,
        site: SourceSite,
    ) -> RuntimeHookOutcome | None:
        delay_seconds = int(site.crawl_delay_seconds or 0)
        if delay_seconds <= 0:
            return None
        latest_fetch = self.session.scalar(
            select(func.max(SourceDocument.fetched_at)).where(SourceDocument.site_id == site.id)
        )
        if latest_fetch is None:
            return None
        elapsed_seconds = (datetime.utcnow() - latest_fetch.replace(tzinfo=None)).total_seconds()
        wait_seconds = delay_seconds - elapsed_seconds
        if wait_seconds <= 0:
            return None
        not_before = datetime.utcnow() + timedelta(seconds=wait_seconds)
        task.not_before = not_before
        observation = RuntimeObservation(
            status=RuntimeStatus.pending,
            metrics={
                "wait_seconds": round(wait_seconds, 3),
                "crawl_delay_seconds": delay_seconds,
            },
            retryable=True,
            payload={
                **self._site_policy_payload(task.url, site, "crawl_delay"),
                "not_before": not_before.isoformat(),
            },
        )
        return RuntimeHookOutcome(
            task_status=CrawlStatus.pending,
            outcome=TaskExecutionOutcome(
                result=observation.model_dump(mode="json"),
                error=None,
            ),
        )

    def _failed(
        self,
        task: CrawlTask,
        *,
        error: str,
        retryable: bool,
        payload: dict[str, object],
    ) -> RuntimeHookOutcome:
        task.retries = (
            min(task.retries + 1, self.max_retries) if retryable else self.max_retries
        )
        observation = RuntimeObservation.failure(
            error,
            retryable=retryable,
            payload=payload,
        )
        return RuntimeHookOutcome(
            task_status=CrawlStatus.failed,
            outcome=TaskExecutionOutcome(
                result=observation.model_dump(mode="json"),
                error=error,
            ),
        )

    def _blocked(
        self,
        task: CrawlTask,
        *,
        reason: str,
        payload: dict[str, object],
    ) -> RuntimeHookOutcome:
        task.retries = self.max_retries
        observation = RuntimeObservation.blocked_review(reason, payload=payload)
        return RuntimeHookOutcome(
            task_status=CrawlStatus.blocked,
            outcome=TaskExecutionOutcome(
                result=observation.model_dump(mode="json"),
                error=reason,
            ),
        )

    def _site_policy_payload(
        self,
        url: str,
        site: SourceSite,
        hook: str,
    ) -> dict[str, object]:
        return {
            "hook": "before_fetch",
            "policy": hook,
            "url": url,
            "site_id": str(site.id),
            "site_name": site.name,
            "base_url": site.base_url,
            "domain": site.domain,
            "access_level": site.access_level.value,
            "enabled": site.enabled,
        }


class CrawlTaskExecutor:
    def __init__(
        self,
        session: Session,
        extractor_mode: str,
        max_retries: int,
        hooks: CrawlRuntimeHooks | None = None,
    ) -> None:
        self.session = session
        self.extractor_mode = extractor_mode
        self.max_retries = max_retries
        self.hooks = hooks or CrawlRuntimeHooks(session, max_retries=max_retries)

    def execute(self, job: CrawlJob, task: CrawlTask) -> TaskExecutionOutcome:
        hook_outcome = self.hooks.before_fetch(job, task)
        if hook_outcome is not None:
            task.status = hook_outcome.task_status
            return TaskExecutionOutcome(
                result=normalize_task_result(hook_outcome.outcome.result),
                error=hook_outcome.outcome.error,
            )

        task_error = None
        if task.task_type == "discover_links":
            result = self.run_discovery_task(job, task)
            if result.get("status") == AgentStatus.blocked.value:
                task.status = CrawlStatus.blocked
            elif result.get("status") == AgentStatus.failed.value:
                task_error = self.record_result_failure(
                    task,
                    result,
                    "链接发现失败。",
                )
            else:
                task.status = CrawlStatus.succeeded
        else:
            result = CrawlPipeline(
                self.session,
                extractor_mode=self.extractor_mode,
            ).crawl_url(task.url)
            if result.get("status") == "blocked_login":
                task.status = CrawlStatus.blocked
            elif result.get("status") == "fetch_failed":
                task_error = self.record_result_failure(
                    task,
                    result,
                    "页面抓取失败。",
                )
            else:
                task.status = CrawlStatus.succeeded
        return TaskExecutionOutcome(
            result=normalize_task_result(result),
            error=task_error,
        )

    def record_result_failure(
        self,
        task: CrawlTask,
        result: dict[str, object],
        default_error: str,
    ) -> str:
        task.status = CrawlStatus.failed
        if result.get("retryable") is False:
            task.retries = self.max_retries
        else:
            task.retries = min(task.retries + 1, self.max_retries)
        return str(result.get("error") or default_error)

    def run_discovery_task(self, job: CrawlJob, task: CrawlTask) -> dict[str, object]:
        source_filter = job.source_filter or {}
        objective = str(source_filter.get("objective") or job.name)
        max_links = int(source_filter.get("discovery_max_links") or 12)
        allow_external = bool(source_filter.get("allow_external_discovery") or False)
        result = SourceDiscoveryAgent().run(
            seed_url=task.url,
            objective=objective,
            max_links=max_links,
            allow_external=allow_external,
        )
        discovered_links = list(result.payload.get("selected_links", []))
        fallback_used = result.status == AgentStatus.succeeded and not discovered_links
        links_to_crawl = list(discovered_links)
        seed_crawl_included = False
        if result.status == AgentStatus.succeeded:
            links_to_crawl.insert(0, _seed_crawl_link(task.url, fallback_used=fallback_used))
            seed_crawl_included = True
        created_tasks = self.create_crawl_tasks_from_discovery(job, task, links_to_crawl)
        self.record_discovery_decisions(job, task, links_to_crawl, created_tasks)
        return {
            "status": result.status.value,
            "seed_url": task.url,
            "selected_count": len(discovered_links),
            "created_tasks": len(created_tasks),
            "selected_links": discovered_links,
            "seed_crawl_included": seed_crawl_included,
            "fallback_used": fallback_used,
            "error": result.error,
            "retryable": result.payload.get("retryable", True),
            "payload": result.payload,
        }

    def create_crawl_tasks_from_discovery(
        self,
        job: CrawlJob,
        source_task: CrawlTask,
        selected_links: list[object],
    ) -> list[CrawlTask]:
        existing_tasks = {
            (url, task_type)
            for url, task_type in self.session.execute(
                select(CrawlTask.url, CrawlTask.task_type).where(CrawlTask.job_id == job.id)
            ).all()
        }
        created: list[CrawlTask] = []
        for raw_link in selected_links:
            if not isinstance(raw_link, dict):
                continue
            url = str(raw_link.get("url") or "")
            task_key = (url, "crawl_url")
            if not url or task_key in existing_tasks:
                continue
            task = CrawlTask(
                job_id=job.id,
                url=url,
                task_type="crawl_url",
                status=CrawlStatus.pending,
                result_json={
                    "discovered_from": str(source_task.id),
                    "discovery_score": raw_link.get("score"),
                    "discovery_reasons": raw_link.get("reasons", []),
                },
            )
            self.session.add(task)
            self.session.flush()
            existing_tasks.add(task_key)
            created.append(task)
        return created

    def record_discovery_decisions(
        self,
        job: CrawlJob,
        source_task: CrawlTask,
        selected_links: list[object],
        created_tasks: list[CrawlTask],
    ) -> None:
        created_by_url = {task.url: task for task in created_tasks}
        for raw_link in selected_links:
            if not isinstance(raw_link, dict):
                continue
            url = str(raw_link.get("url") or "")
            created_task = created_by_url.get(url)
            if created_task is None:
                continue
            score = _float_or_zero(raw_link.get("score"))
            reasons = raw_link.get("reasons", [])
            fallback_used = _link_has_seed_fallback_reason(reasons)
            self.session.add(
                AgentDecision(
                    session_id=_source_filter_uuid(job, "session_id"),
                    command_id=_source_filter_uuid(job, "command_id"),
                    decision_type=AgentDecisionType.create_task,
                    target_type="crawl_task",
                    target_id=created_task.id,
                    rationale=_discovery_decision_rationale(fallback_used),
                    input_metrics={
                        "seed_url": source_task.url,
                        "score": score,
                        "reasons": reasons,
                    },
                    policy_checks=raw_link.get("policy", {}),
                    action_payload={
                        "url": url,
                        "label": raw_link.get("label"),
                        "job_id": str(job.id),
                    },
                    confidence=min(score / 40, 1.0),
                    auto_executed=True,
                )
            )


class CrawlRuntimeRecorder:
    def __init__(self, session: Session) -> None:
        self.session = session

    def apply_execution_monitor_decision(
        self,
        job: CrawlJob,
        task: CrawlTask,
        result: dict[str, object],
    ) -> None:
        review_pending_for_task = self.record_review_request_if_needed(job, task, result)

        source_filter = job.source_filter or {}
        decision = ExecutionMonitorAgent().evaluate_task(
            objective=str(source_filter.get("objective") or job.name),
            job={
                "id": str(job.id),
                "name": job.name,
                "status": job.status.value,
                "source_filter": source_filter,
            },
            task={
                "id": str(task.id),
                "url": task.url,
                "task_type": task.task_type,
                "status": task.status.value,
                "retries": task.retries,
            },
            result=result,
            task_counts=self.task_counts_for_agent(job.id),
        )
        if decision is None:
            return

        auto_executed = decision.action in {
            "continue",
            "pause_job",
            "stop_job",
            "adjust_strategy",
        }
        target_type = "crawl_task" if decision.action == "request_review" else "crawl_job"
        target_id = task.id if decision.action == "request_review" else job.id
        self.session.add(
            AgentDecision(
                session_id=_source_filter_uuid(job, "session_id"),
                command_id=_source_filter_uuid(job, "command_id"),
                decision_type=_monitor_decision_type(decision.action),
                target_type=target_type,
                target_id=target_id,
                rationale=decision.rationale,
                input_metrics={
                    "task_id": str(task.id),
                    "task_url": task.url,
                    "task_result": result,
                    "task_counts": self.task_counts_for_agent(job.id),
                },
                policy_checks={
                    "allowed_monitor_actions": [
                        "continue",
                        "pause_job",
                        "stop_job",
                        "request_review",
                        "adjust_strategy",
                    ],
                    "no_destructive_database_action": True,
                },
                action_payload={
                    "action": decision.action,
                    "strategy_patch": decision.strategy_patch,
                    "review_reason": decision.review_reason,
                },
                confidence=decision.confidence,
                auto_executed=auto_executed,
            )
        )

        if decision.action == "pause_job":
            job.status = CrawlStatus.paused
        elif decision.action == "stop_job":
            task_counts = self.task_counts_for_agent(job.id)
            if task_counts.get(CrawlStatus.failed.value, 0):
                job.status = CrawlStatus.failed
            elif task_counts.get(CrawlStatus.blocked.value, 0):
                job.status = CrawlStatus.blocked
            elif task_counts.get(CrawlStatus.cancelled.value, 0):
                job.status = CrawlStatus.cancelled
            else:
                job.status = CrawlStatus.succeeded
            job.finished_at = datetime.utcnow()
        elif decision.action == "adjust_strategy" and decision.strategy_patch:
            job.source_filter = {**source_filter, **decision.strategy_patch}
        elif decision.action == "request_review":
            if review_pending_for_task or self._pending_review_exists(task.id):
                return
            self.session.add(
                ReviewItem(
                    item_type="ai_execution_monitor",
                    target_table="crawl_tasks",
                    target_id=task.id,
                    status=ReviewStatus.pending,
                    reason=decision.review_reason or decision.rationale,
                    payload={
                        "job_id": str(job.id),
                        "task_id": str(task.id),
                        "url": task.url,
                        "result": result,
                    },
                )
            )

    def record_review_request_if_needed(
        self,
        job: CrawlJob,
        task: CrawlTask,
        result: dict[str, object],
    ) -> bool:
        if result.get("requires_review") is not True:
            return False
        if self._pending_review_exists(task.id):
            return True
        reason = str(
            result.get("review_reason")
            or result.get("error")
            or "任务执行结果需要人工复核。"
        )
        self.session.add(
            ReviewItem(
                item_type="runtime_observation",
                target_table="crawl_tasks",
                target_id=task.id,
                status=ReviewStatus.pending,
                reason=reason,
                payload={
                    "job_id": str(job.id),
                    "task_id": str(task.id),
                    "url": task.url,
                    "task_type": task.task_type,
                    "result": result,
                },
            )
        )
        return True

    def _pending_review_exists(self, task_id: uuid.UUID) -> bool:
        existing = self.session.scalar(
            select(ReviewItem).where(
                ReviewItem.target_table == "crawl_tasks",
                ReviewItem.target_id == task_id,
                ReviewItem.status == ReviewStatus.pending,
            )
        )
        return existing is not None

    def task_counts_for_agent(self, job_id: uuid.UUID) -> dict[str, int]:
        return {
            status.value: count
            for status, count in self.session.execute(
                select(CrawlTask.status, func.count(CrawlTask.id))
                .where(CrawlTask.job_id == job_id)
                .group_by(CrawlTask.status)
            ).all()
        }


class CrawlJobRunner:
    max_retries = 3

    def __init__(self, session: Session, extractor_mode: str = "auto") -> None:
        self.session = session
        self.extractor_mode = extractor_mode
        self.scheduler = CrawlJobScheduler(session, max_retries=self.max_retries)
        self.executor = CrawlTaskExecutor(
            session,
            extractor_mode=extractor_mode,
            max_retries=self.max_retries,
        )
        self.recorder = CrawlRuntimeRecorder(session)

    def create_job(self, name: str, urls: list[str]) -> dict[str, str | int]:
        job = CrawlJob(
            name=name,
            status=CrawlStatus.pending,
            source_filter={"urls": urls},
        )
        self.session.add(job)
        self.session.flush()
        for url in urls:
            self.session.add(
                CrawlTask(
                    job_id=job.id,
                    url=url,
                    task_type="crawl_url",
                    status=CrawlStatus.pending,
                )
            )
        self.session.commit()
        return {"job_id": str(job.id), "task_count": len(urls)}

    def create_job_from_file(self, name: str, path: Path) -> dict[str, str | int]:
        urls = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        return self.create_job(name=name, urls=urls)

    def run_job(self, job_id: str) -> dict[str, str | int]:
        parsed_job_id = uuid.UUID(job_id)
        job = self.session.get(CrawlJob, parsed_job_id)
        if job is None:
            raise ValueError(f"找不到爬取任务: {job_id}")
        if job.status == CrawlStatus.cancelled:
            return {"job_id": job_id, "status": "cancelled", "processed": 0}

        self.scheduler.start_job(job)

        processed = 0
        while True:
            job = self.scheduler.refresh_job_or_raise(parsed_job_id, job_id)
            if job.status in self.scheduler.terminal_statuses:
                return {"job_id": job_id, "status": job.status.value, "processed": processed}

            task = self.scheduler.next_task(parsed_job_id)
            if task is None:
                terminal_status = self.scheduler.finish_when_no_work(parsed_job_id)
                return {"job_id": job_id, "status": terminal_status.value, "processed": processed}

            self.scheduler.mark_task_running(task)

            task_id = task.id
            try:
                outcome = self.executor.execute(job, task)
                task.result_json = outcome.result
                task.error = outcome.error
                processed += 1
                self.recorder.apply_execution_monitor_decision(job, task, outcome.result)
            except Exception as exc:
                self.session.rollback()
                task = self.session.get(CrawlTask, task_id)
                if task is None:
                    raise
                task.status = CrawlStatus.failed
                task.retries += 1
                task.error = str(exc)
            finally:
                task.updated_at = datetime.utcnow()
                self.session.commit()

    def stop_job(self, job_id: str) -> dict[str, str]:
        job = self.session.get(CrawlJob, uuid.UUID(job_id))
        if job is None:
            raise ValueError(f"找不到爬取任务: {job_id}")
        job.status = CrawlStatus.paused
        self.session.commit()
        return {"job_id": job_id, "status": "paused"}

    def cancel_job(self, job_id: str) -> dict[str, str]:
        job = self.session.get(CrawlJob, uuid.UUID(job_id))
        if job is None:
            raise ValueError(f"找不到爬取任务: {job_id}")
        job.status = CrawlStatus.cancelled
        job.finished_at = datetime.utcnow()
        self.session.commit()
        return {"job_id": job_id, "status": "cancelled"}

    def job_status(self, job_id: str) -> dict[str, str | int]:
        parsed_job_id = uuid.UUID(job_id)
        job = self.session.get(CrawlJob, parsed_job_id)
        if job is None:
            raise ValueError(f"找不到爬取任务: {job_id}")
        counts = dict(
            self.session.execute(
                select(CrawlTask.status, func.count(CrawlTask.id))
                .where(CrawlTask.job_id == parsed_job_id)
                .group_by(CrawlTask.status)
            ).all()
        )
        return {
            "job_id": job_id,
            "status": job.status.value,
            "pending": counts.get(CrawlStatus.pending, 0),
            "running": counts.get(CrawlStatus.running, 0),
            "succeeded": counts.get(CrawlStatus.succeeded, 0),
            "failed": counts.get(CrawlStatus.failed, 0),
            "blocked": counts.get(CrawlStatus.blocked, 0),
        }

    def _record_result_failure(
        self,
        task: CrawlTask,
        result: dict[str, object],
        default_error: str,
    ) -> str:
        return self.executor.record_result_failure(task, result, default_error)

    def _run_discovery_task(self, job: CrawlJob, task: CrawlTask) -> dict[str, object]:
        return self.executor.run_discovery_task(job, task)

    def _create_crawl_tasks_from_discovery(
        self,
        job: CrawlJob,
        source_task: CrawlTask,
        selected_links: list[object],
    ) -> list[CrawlTask]:
        return self.executor.create_crawl_tasks_from_discovery(job, source_task, selected_links)

    def _record_discovery_decisions(
        self,
        job: CrawlJob,
        source_task: CrawlTask,
        selected_links: list[object],
        created_tasks: list[CrawlTask],
    ) -> None:
        self.executor.record_discovery_decisions(job, source_task, selected_links, created_tasks)

    def _apply_execution_monitor_decision(
        self,
        job: CrawlJob,
        task: CrawlTask,
        result: dict[str, object],
    ) -> None:
        self.recorder.apply_execution_monitor_decision(job, task, result)

    def _terminal_status(self, job_id: uuid.UUID) -> CrawlStatus:
        return self.scheduler.terminal_status(job_id)

    def _task_counts_for_agent(self, job_id: uuid.UUID) -> dict[str, int]:
        return self.recorder.task_counts_for_agent(job_id)


class CrawlJobDispatcher:
    def __init__(self, session: Session, max_retries: int = CrawlJobRunner.max_retries) -> None:
        self.session = session
        self.max_retries = max_retries

    def due_jobs(self, limit: int = 3) -> list[DueCrawlJob]:
        now = datetime.utcnow()
        due_task_exists = (
            select(CrawlTask.id)
            .where(
                CrawlTask.job_id == CrawlJob.id,
                or_(CrawlTask.not_before.is_(None), CrawlTask.not_before <= now),
                or_(
                    CrawlTask.status == CrawlStatus.pending,
                    (CrawlTask.status == CrawlStatus.failed)
                    & (CrawlTask.retries < self.max_retries),
                ),
            )
            .exists()
        )
        jobs = self.session.scalars(
            select(CrawlJob)
            .where(
                CrawlJob.status == CrawlStatus.pending,
                CrawlJob.started_at.is_not(None),
                due_task_exists,
            )
            .order_by(CrawlJob.created_at.asc())
            .limit(limit)
        ).all()
        return [
            DueCrawlJob(
                job_id=str(job.id),
                extractor_mode=str((job.source_filter or {}).get("extractor_mode") or "auto"),
            )
            for job in jobs
        ]


def _source_filter_uuid(job: CrawlJob, key: str) -> uuid.UUID | None:
    value = (job.source_filter or {}).get(key)
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _float_or_zero(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _seed_crawl_link(seed_url: str, fallback_used: bool = False) -> dict[str, object]:
    reason = "发现结果为空，回退抓取种子页" if fallback_used else "优先抓取人工提供的种子页"
    return {
        "url": seed_url,
        "label": "种子页回退抓取" if fallback_used else "人工种子页",
        "score": 1,
        "reasons": [reason],
        "source_url": seed_url,
        "policy": {
            "allowed": True,
            "reason": reason,
            "checks": {"fallback_seed_url": True},
        },
    }


def _fallback_seed_link(seed_url: str) -> dict[str, object]:
    return _seed_crawl_link(seed_url, fallback_used=True)


def _link_has_seed_fallback_reason(reasons: object) -> bool:
    if not isinstance(reasons, list):
        return False
    return "发现结果为空，回退抓取种子页" in reasons


def _discovery_decision_rationale(fallback_used: bool) -> str:
    if fallback_used:
        return "SourceDiscoveryAgent 没有从种子页发现可抓取链接，因此回退创建种子页本身的抓取任务。"
    return (
        "SourceDiscoveryAgent 选择该链接，因为它匹配用户目标，"
        "并呈现出教学资源或教师方法相关信号。"
    )


def _monitor_decision_type(action: str) -> AgentDecisionType:
    if action == "pause_job":
        return AgentDecisionType.pause_source
    if action == "stop_job":
        return AgentDecisionType.stop_session
    if action == "request_review":
        return AgentDecisionType.request_review
    if action == "adjust_strategy":
        return AgentDecisionType.adjust_strategy
    return AgentDecisionType.adjust_strategy
