from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select

from mathscout.crawler.registry import DEFAULT_SEED_SOURCES
from mathscout.db.init_db import create_database_schema
from mathscout.db.models import AccessLevel, SourceSite
from mathscout.db.session import SessionLocal
from mathscout.importers.template import import_template_dir
from mathscout.pipeline.crawl import CrawlPipeline
from mathscout.pipeline.extract import ExtractPipeline
from mathscout.pipeline.jobs import CrawlJobRunner


def main() -> None:
    parser = argparse.ArgumentParser(prog="mathscout")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── 数据库 ──────────────────────────────────────────────────────────
    subparsers.add_parser("init-db", help="创建数据库表。")

    import_parser = subparsers.add_parser(
        "import-template",
        help="将 .template 教材结构导入数据库。",
    )
    import_parser.add_argument(
        "--template-dir",
        type=Path,
        default=Path(".template/beishida_math_json_v3_with_template"),
    )

    subparsers.add_parser("seed-sources", help="写入默认来源站点。")

    # ── Phase 1：爬取 ───────────────────────────────────────────────────
    crawl_parser = subparsers.add_parser(
        "crawl-url",
        help="【Phase 1】抓取单个 URL，存文件，更新 source_documents（不调用 AI）。",
    )
    crawl_parser.add_argument("url")

    create_job_parser = subparsers.add_parser(
        "create-job",
        help="基于 URL 列表创建持久化爬取任务。",
    )
    create_job_parser.add_argument("--name", required=True)
    create_job_parser.add_argument("--url", action="append", default=[])
    create_job_parser.add_argument("--urls-file", type=Path)

    run_job_parser = subparsers.add_parser(
        "run-job",
        help="【Phase 1】运行持久化爬取任务（只抓取，不提取）。可用 stop-job 暂停后续继续。",
    )
    run_job_parser.add_argument("job_id")

    stop_job_parser = subparsers.add_parser("stop-job", help="暂停运行中的爬取任务。")
    stop_job_parser.add_argument("job_id")

    cancel_job_parser = subparsers.add_parser("cancel-job", help="取消爬取任务。")
    cancel_job_parser.add_argument("job_id")

    status_job_parser = subparsers.add_parser("job-status", help="查看爬取任务状态。")
    status_job_parser.add_argument("job_id")

    # ── Phase 2：提取 ───────────────────────────────────────────────────
    extract_pending_parser = subparsers.add_parser(
        "extract-pending",
        help="【Phase 2】对所有 pipeline_status='crawled' 的文档运行 AI 提取。",
    )
    extract_pending_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="单次处理文档上限，默认 100。",
    )
    extract_pending_parser.add_argument(
        "--extractor",
        choices=["auto", "deepseek", "ai", "rule"],
        default="auto",
    )

    extract_doc_parser = subparsers.add_parser(
        "extract-document",
        help="【Phase 2】对单个文档 ID 运行 AI 提取。",
    )
    extract_doc_parser.add_argument("document_id")
    extract_doc_parser.add_argument(
        "--extractor",
        choices=["auto", "deepseek", "ai", "rule"],
        default="auto",
    )

    args = parser.parse_args()

    # ── 路由 ────────────────────────────────────────────────────────────
    if args.command == "init-db":
        create_database_schema()
        print("database schema created")
        return

    if args.command == "import-template":
        with SessionLocal() as session:
            stats = import_template_dir(session, args.template_dir)
        print(stats)
        return

    if args.command == "seed-sources":
        with SessionLocal() as session:
            stats = seed_default_sources(session)
        print(stats)
        return

    if args.command == "crawl-url":
        with SessionLocal() as session:
            result = CrawlPipeline(session).fetch_and_store(args.url)
        print(result)
        return

    if args.command == "create-job":
        with SessionLocal() as session:
            runner = CrawlJobRunner(session)
            if args.urls_file:
                result = runner.create_job_from_file(args.name, args.urls_file)
            else:
                if not args.url:
                    raise ValueError("Provide at least one --url or --urls-file.")
                result = runner.create_job(args.name, list(args.url))
        print(result)
        return

    if args.command == "run-job":
        with SessionLocal() as session:
            result = CrawlJobRunner(session).run_job(args.job_id)
        print(result)
        return

    if args.command == "stop-job":
        with SessionLocal() as session:
            result = CrawlJobRunner(session).stop_job(args.job_id)
        print(result)
        return

    if args.command == "cancel-job":
        with SessionLocal() as session:
            result = CrawlJobRunner(session).cancel_job(args.job_id)
        print(result)
        return

    if args.command == "job-status":
        with SessionLocal() as session:
            result = CrawlJobRunner(session).job_status(args.job_id)
        print(result)
        return

    if args.command == "extract-pending":
        with SessionLocal() as session:
            result = ExtractPipeline(session, extractor_mode=args.extractor).extract_pending(
                limit=args.limit
            )
        print(result)
        return

    if args.command == "extract-document":
        with SessionLocal() as session:
            result = ExtractPipeline(
                session, extractor_mode=args.extractor
            ).extract_by_document_id(args.document_id)
        print(result)
        return


def seed_default_sources(session) -> dict[str, int]:
    created = 0
    updated = 0
    for source in DEFAULT_SEED_SOURCES:
        parsed = urlparse(source.base_url)
        site = session.scalar(select(SourceSite).where(SourceSite.base_url == source.base_url))
        if site is None:
            site = SourceSite(
                name=source.name,
                base_url=source.base_url,
                domain=parsed.netloc,
                category=source.category.value,
                access_level=AccessLevel.public,
                notes=source.notes,
            )
            session.add(site)
            created += 1
        else:
            site.name = source.name
            site.domain = parsed.netloc
            site.category = source.category.value
            site.notes = source.notes
            updated += 1
    session.commit()
    return {"created": created, "updated": updated}


if __name__ == "__main__":
    main()
