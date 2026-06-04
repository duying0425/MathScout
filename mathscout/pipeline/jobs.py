from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mathscout.db.models import CrawlJob, CrawlStatus, CrawlTask
from mathscout.pipeline.crawl import CrawlPipeline


class CrawlJobRunner:
    def __init__(self, session: Session, extractor_mode: str = "auto") -> None:
        self.session = session
        self.extractor_mode = extractor_mode

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
            raise ValueError(f"Crawl job not found: {job_id}")
        if job.status == CrawlStatus.cancelled:
            return {"job_id": job_id, "status": "cancelled", "processed": 0}

        job.status = CrawlStatus.running
        job.started_at = job.started_at or datetime.utcnow()
        stale_tasks = self.session.scalars(
            select(CrawlTask).where(
                CrawlTask.job_id == parsed_job_id,
                CrawlTask.status == CrawlStatus.running,
            )
        ).all()
        for stale_task in stale_tasks:
            stale_task.status = CrawlStatus.pending
            stale_task.error = "Reset from stale running state before job resume."
            stale_task.updated_at = datetime.utcnow()
        self.session.commit()

        processed = 0
        while True:
            self.session.expire_all()
            job = self.session.get(CrawlJob, parsed_job_id)
            if job is None:
                raise ValueError(f"Crawl job not found during run: {job_id}")
            if job.status in {CrawlStatus.paused, CrawlStatus.cancelled}:
                return {"job_id": job_id, "status": job.status.value, "processed": processed}

            task = self.session.scalar(
                select(CrawlTask)
                .where(
                    CrawlTask.job_id == parsed_job_id,
                    CrawlTask.status.in_([CrawlStatus.pending, CrawlStatus.failed]),
                )
                .order_by(CrawlTask.created_at.asc())
            )
            if task is None:
                job.status = CrawlStatus.succeeded
                job.finished_at = datetime.utcnow()
                self.session.commit()
                return {"job_id": job_id, "status": "succeeded", "processed": processed}

            task.status = CrawlStatus.running
            task.updated_at = datetime.utcnow()
            self.session.commit()

            task_id = task.id
            try:
                result = CrawlPipeline(
                    self.session,
                    extractor_mode=self.extractor_mode,
                ).crawl_url(task.url)
                task.status = (
                    CrawlStatus.blocked
                    if result.get("status") == "blocked_login"
                    else CrawlStatus.succeeded
                )
                task.result_json = result
                task.error = None
                processed += 1
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
            raise ValueError(f"Crawl job not found: {job_id}")
        job.status = CrawlStatus.paused
        self.session.commit()
        return {"job_id": job_id, "status": "paused"}

    def cancel_job(self, job_id: str) -> dict[str, str]:
        job = self.session.get(CrawlJob, uuid.UUID(job_id))
        if job is None:
            raise ValueError(f"Crawl job not found: {job_id}")
        job.status = CrawlStatus.cancelled
        job.finished_at = datetime.utcnow()
        self.session.commit()
        return {"job_id": job_id, "status": "cancelled"}

    def job_status(self, job_id: str) -> dict[str, str | int]:
        parsed_job_id = uuid.UUID(job_id)
        job = self.session.get(CrawlJob, parsed_job_id)
        if job is None:
            raise ValueError(f"Crawl job not found: {job_id}")
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
