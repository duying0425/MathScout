from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mathscout.agents.orchestrator import AIOrchestratorAgent
from mathscout.db.models import (
    AccessLevel,
    AgentDecision,
    AgentDecisionType,
    Book,
    CandidateKnowledgeItem,
    Chapter,
    CrawlJob,
    CrawlStatus,
    CrawlTask,
    KnowledgePoint,
    ManualEditLog,
    NaturalLanguageCommand,
    OrchestrationSession,
    OrchestrationStatus,
    ReviewItem,
    ReviewStatus,
    Section,
    SourceDocument,
    SourceSite,
    StudentSkill,
    TeachingMethod,
    TextbookSeries,
)
from mathscout.db.session import SessionLocal, get_session
from mathscout.orchestration.schemas import NaturalLanguageDirective, OrchestrationContext
from mathscout.pipeline.extract import ExtractPipeline
from mathscout.pipeline.jobs import CrawlJobRunner
from mathscout.review import ReviewActionError, ReviewService

templates = Jinja2Templates(directory="mathscout/templates")
router = APIRouter()
AdminSession = Annotated[Session, Depends(get_session)]

URL_RE = re.compile(r"https?://[^\s<>\"]+")
DISPLAY_TEXT = {
    "active": "运行中",
    "paused": "已暂停",
    "completed": "已完成",
    "blocked": "已阻塞",
    "cancelled": "已取消",
    "pending": "等待中",
    "running": "运行中",
    "succeeded": "已成功",
    "failed": "失败",
    "approved": "已通过",
    "rejected": "已拒绝",
    "needs_edit": "需编辑",
    "public": "公开",
    "login_required": "需登录",
    "needs_ocr": "待 OCR",
    "paid_or_restricted": "付费/受限",
    "unknown": "未知",
    "create_task": "创建/规划",
    "reprioritize_source": "调整来源优先级",
    "pause_source": "暂停来源",
    "retry_task": "重试任务",
    "stop_session": "停止会话",
    "adjust_strategy": "调整策略",
    "apply_reconciliation": "应用调和",
    "request_review": "请求复核",
    "discover_sources": "发现来源",
    "create_crawl_job": "爬取任务",
    "create_extraction_job": "抽取分析步骤",
    "create_reconciliation_job": "去重校验步骤",
    "crawl_job": "爬取任务",
    "crawl_task": "爬取子任务",
    "crawl_url": "页面爬取",
    "discover_links": "链接发现",
    "teaching_method": "教学方法",
    "teaching_method_variant": "教师变体",
    "knowledge_point": "知识点",
    "student_skill": "学生能力",
    "region_adoption": "地区采用",
    "textbook_structure": "教材结构",
    "knowledge_point_scope": "知识点范围",
    "official": "官方来源",
    "publisher": "出版社",
    "teacher_resource": "教师资源",
    "regional_bureau": "地方教育部门",
    "create": "创建",
    "update": "更新",
    "merge": "合并",
    "split": "拆分",
    "delete": "删除",
    "restore": "恢复",
    "approve_ai_change": "通过 AI 变更",
    "reject_ai_change": "拒绝 AI 变更",
    "lock": "锁定",
    "unlock": "解锁",
}


@router.get("")
@router.get("/")
def dashboard(request: Request, session: AdminSession):
    active_jobs = _job_rows(
        session,
        select(CrawlJob)
        .where(CrawlJob.status.in_([CrawlStatus.pending, CrawlStatus.running, CrawlStatus.paused]))
        .order_by(CrawlJob.created_at.desc())
        .limit(8),
    )
    from mathscout.db.models import PipelineStatus
    pending_extraction_count = session.scalar(
        select(func.count(SourceDocument.id)).where(
            SourceDocument.pipeline_status == PipelineStatus.crawled
        )
    ) or 0
    pending_review_count = _review_count(session)
    stats = {
        "已抓文档": _count(session, SourceDocument),
        "方法库": _count(session, TeachingMethod),
        "知识点": _count(session, KnowledgePoint),
        "候选项": _count(session, CandidateKnowledgeItem),
    }
    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context={
            "active_jobs": active_jobs,
            "pending_extraction_count": pending_extraction_count,
            "pending_review_count": pending_review_count,
            "stats": stats,
        },
    )


@router.get("/agent")
def agent_console(request: Request, session: AdminSession):
    commands = [
        {
            "id": str(command.id),
            "session_id": _display(command.session_id),
            "raw_text": command.raw_text,
            "interpreted_intent": _display(command.interpreted_intent),
            "status": _display(command.status),
            "created": _display(command.created_at),
            "error": _display(command.error),
        }
        for command in session.scalars(
            select(NaturalLanguageCommand)
            .order_by(NaturalLanguageCommand.created_at.desc())
            .limit(40)
        ).all()
    ]
    decisions = [
        {
            "type": _display(decision.decision_type),
            "target": _display(decision.target_type),
            "rationale": decision.rationale,
            "confidence": f"{decision.confidence:.2f}",
            "auto": "是" if decision.auto_executed else "否",
            "created": _display(decision.created_at),
        }
        for decision in session.scalars(
            select(AgentDecision).order_by(AgentDecision.created_at.desc()).limit(25)
        ).all()
    ]
    return templates.TemplateResponse(
        request=request,
        name="admin/agent.html",
        context={
            "commands": commands,
            "decisions": decisions,
            "default_objective": (
                "优先爬取公开官方来源和公开教研资源，围绕初中数学教材章节，"
                "收集教师解题方法、教学讲法、易错提醒和课堂变体。"
            ),
        },
    )


@router.post("/agent")
def submit_agent_command(
    request: Request,
    background_tasks: BackgroundTasks,
    session: AdminSession,
    objective: str = Form(...),
    seed_urls: str = Form(""),
    extractor_mode: str = Form("auto"),
    max_seed_urls: int = Form(8),
    discovery_max_links: int = Form(12),
    discover_links: bool = Form(False),
    auto_start: bool = Form(False),
):
    objective = objective.strip()
    if not objective:
        return _redirect("/admin/agent")

    max_seed_urls = max(1, min(max_seed_urls, 50))
    discovery_max_links = max(1, min(discovery_max_links, 50))
    urls, source_mode = _resolve_crawl_urls(session, objective, seed_urls, max_seed_urls)
    if not urls:
        raise HTTPException(
            status_code=400,
            detail="没有可用的公开来源 URL：请在“种子 URL”中粘贴链接，"
            "或先在“来源站点”里启用公开来源。",
        )

    target_scope = {
        "source_mode": source_mode,
        "urls": urls,
        "textbook_scope": _infer_textbook_scope(objective),
    }
    budgets = {"max_seed_urls": max_seed_urls, "seed_url_count": len(urls)}
    stop_conditions = {"manual_stop_allowed": True}
    strategy_preferences = {
        "extractor_mode": extractor_mode,
        "auto_start": auto_start,
        "discover_links": discover_links,
        "discovery_max_links": discovery_max_links,
        "operator_review": True,
    }

    orchestration_session = OrchestrationSession(
        objective=objective,
        status=OrchestrationStatus.active,
        target_scope=target_scope,
        strategy=strategy_preferences,
        budgets=budgets,
        stop_conditions=stop_conditions,
        created_by="admin",
    )
    session.add(orchestration_session)
    session.flush()

    directive = NaturalLanguageDirective(
        raw_text=objective,
        interpreted_intent=_interpret_command(objective, urls, extractor_mode),
        target_scope=target_scope,
        strategy_preferences=strategy_preferences,
        budgets=budgets,
        stop_conditions=stop_conditions,
        review_policy={"low_confidence": "queue_for_review"},
    )
    command = NaturalLanguageCommand(
        session_id=orchestration_session.id,
        raw_text=objective,
        interpreted_intent=directive.interpreted_intent,
        structured_directive=directive.model_dump(mode="json"),
        status=OrchestrationStatus.active,
        created_by="admin",
    )
    session.add(command)
    session.flush()

    context = _build_orchestration_context(
        session=session,
        orchestration_session=orchestration_session,
        objective=objective,
        target_scope=target_scope,
        budgets=budgets,
        stop_conditions=stop_conditions,
    )
    plan = AIOrchestratorAgent().plan(directive, context)
    orchestration_session.strategy = {
        **strategy_preferences,
        "plan": plan.model_dump(mode="json"),
    }

    job = _execute_orchestration_plan(
        session=session,
        plan=plan,
        orchestration_session=orchestration_session,
        command=command,
        urls=urls,
        extractor_mode=extractor_mode,
        discover_links=discover_links,
        discovery_max_links=discovery_max_links,
        auto_start=auto_start,
    )
    session.commit()

    if auto_start and job is not None:
        background_tasks.add_task(_run_crawl_job_background, str(job.id), extractor_mode)
    if job is not None:
        return _redirect(f"/admin/crawl-jobs/{job.id}")
    return _redirect("/admin/agent")


@router.get("/decisions")
def agent_decisions(request: Request, session: AdminSession):
    rows = [
        {
            "类型": _display(decision.decision_type),
            "目标": _display(decision.target_type),
            "理由": decision.rationale,
            "置信度": f"{decision.confidence:.2f}",
            "自动执行": "是" if decision.auto_executed else "否",
            "创建时间": _display(decision.created_at),
        }
        for decision in session.scalars(
            select(AgentDecision).order_by(AgentDecision.created_at.desc()).limit(100)
        ).all()
    ]
    return _list_response(
        request=request,
        title="Agent 决策",
        columns=["类型", "目标", "理由", "置信度", "自动执行", "创建时间"],
        rows=rows,
    )


@router.get("/techniques")
def technique_library(request: Request, session: AdminSession):
    rows = [
        {
            "标题": method.title,
            "类型": method.method_type,
            "范围": _display(method.canonical_scope),
            "来源数": method.source_count,
            "复核": _display(method.review_status),
        }
        for method in session.scalars(
            select(TeachingMethod).order_by(TeachingMethod.created_at.desc()).limit(100)
        ).all()
    ]
    return _list_response(
        request=request,
        title="方法库",
        columns=["标题", "类型", "范围", "来源数", "复核"],
        rows=rows,
    )


@router.get("/knowledge")
def knowledge_browser(request: Request, session: AdminSession):
    summary = {
        "教材系列": _count(session, TextbookSeries),
        "册别": _count(session, Book),
        "章节": _count(session, Chapter),
        "小节": _count(session, Section),
        "知识点": _count(session, KnowledgePoint),
        "学生能力": _count(session, StudentSkill),
    }
    books = [
        {
            "book_code": row.book_code,
            "label": row.label,
            "chapter_count": row.chapter_count,
            "section_count": row.section_count,
            "knowledge_count": row.knowledge_count,
        }
        for row in session.execute(
            select(
                Book.book_code,
                Book.label,
                func.count(Chapter.id.distinct()).label("chapter_count"),
                func.count(Section.id.distinct()).label("section_count"),
                func.count(KnowledgePoint.id.distinct()).label("knowledge_count"),
            )
            .outerjoin(Chapter, Chapter.book_id == Book.id)
            .outerjoin(Section, Section.chapter_id == Chapter.id)
            .outerjoin(KnowledgePoint, KnowledgePoint.section_id == Section.id)
            .group_by(Book.id)
            .order_by(Book.grade, Book.book_code)
        ).all()
    ]
    sections = [
        {
            "book_code": row.book_code,
            "chapter_title": row.chapter_title,
            "section_title": row.section_title,
            "knowledge_count": row.knowledge_count,
        }
        for row in session.execute(
            select(
                Book.book_code,
                Chapter.title.label("chapter_title"),
                Section.title.label("section_title"),
                func.count(KnowledgePoint.id).label("knowledge_count"),
            )
            .join(Chapter, Section.chapter_id == Chapter.id)
            .join(Book, Chapter.book_id == Book.id)
            .outerjoin(KnowledgePoint, KnowledgePoint.section_id == Section.id)
            .group_by(Section.id, Chapter.id, Book.id)
            .order_by(Book.grade, Book.book_code, Chapter.position, Section.position)
            .limit(40)
        ).all()
    ]
    return templates.TemplateResponse(
        request=request,
        name="admin/knowledge.html",
        context={"summary": summary, "books": books, "sections": sections},
    )


@router.get("/sources")
def source_sites(request: Request, session: AdminSession):
    rows = [
        {
            "名称": site.name,
            "URL": site.base_url,
            "域名": site.domain,
            "类别": _display(site.category),
            "访问": _display(site.access_level),
            "启用": "是" if site.enabled else "否",
        }
        for site in session.scalars(select(SourceSite).order_by(SourceSite.name)).all()
    ]
    return _list_response(
        request=request,
        title="来源站点",
        columns=["名称", "URL", "域名", "类别", "访问", "启用"],
        rows=rows,
    )


@router.get("/crawl-jobs")
def crawl_jobs(request: Request, session: AdminSession):
    jobs = _job_rows(
        session,
        select(CrawlJob).order_by(CrawlJob.created_at.desc()).limit(100),
    )
    return templates.TemplateResponse(
        request=request,
        name="admin/crawl_jobs.html",
        context={"jobs": jobs},
    )


@router.get("/crawl-jobs/status")
def crawl_jobs_status(session: AdminSession):
    jobs = _job_rows(
        session,
        select(CrawlJob).order_by(CrawlJob.created_at.desc()).limit(100),
    )
    return {"jobs": jobs}


@router.get("/crawl-jobs/{job_id}/status")
def crawl_job_status(job_id: str, session: AdminSession):
    job = _get_job(session, job_id)
    counts = _crawl_task_counts(session, job.id)
    return {
        "job": _job_row(session, job),
        "task_counts": {k.value: v for k, v in counts.items()},
    }


@router.get("/crawl-jobs/{job_id}")
def crawl_job_detail(job_id: str, request: Request, session: AdminSession):
    job = _get_job(session, job_id)
    tasks = session.scalars(
        select(CrawlTask).where(CrawlTask.job_id == job.id).order_by(CrawlTask.created_at.asc())
    ).all()
    document_ids = _document_ids_from_tasks(tasks)
    documents = _documents_for_ids(session, document_ids)
    candidate_count = _count_for_documents(session, CandidateKnowledgeItem, document_ids)

    pipeline_counts: dict[str, int] = {
        "crawled": 0,
        "extracted": 0,
        "done": 0,
        "failed": 0,
        "login_required": 0,
        "needs_ocr": 0,
    }
    for doc in documents:
        key = doc.pipeline_status.value if doc.pipeline_status else "crawled"
        pipeline_counts[key] = pipeline_counts.get(key, 0) + 1

    task_rows = [
        {
            "url": task.url,
            "type": _display(task.task_type),
            "status": _display(task.status),
            "retries": task.retries,
            "http_status": _result_value(task, "http_status"),
            "discovered": _result_value(task, "selected_count"),
            "created_tasks": _result_value(task, "created_tasks"),
            "text_length": _result_value(task, "text_length"),
            "pipeline_status": _result_value(task, "pipeline_status"),
            "note": _task_note(task),
            "error": _truncate(task.error, 160),
            "updated": _display(task.updated_at),
        }
        for task in tasks
    ]
    document_rows = [
        {
            "url": document.url,
            "http_status": _display(document.http_status),
            "login": "是" if document.needs_login else "否",
            "pipeline_status": _display_pipeline_status(document.pipeline_status),
            "pipeline_error": _truncate(document.pipeline_error, 80) if document.pipeline_error else "",
            "fetched": _display(document.fetched_at),
        }
        for document in documents
    ]
    saved_summary = {
        "已保存文档": len(documents),
        "待提取 (Phase 2)": pipeline_counts.get("crawled", 0),
        "已提取": pipeline_counts.get("extracted", 0) + pipeline_counts.get("done", 0),
        "候选项": candidate_count,
        "待复核": _pending_review_for_documents(session, document_ids),
    }
    return templates.TemplateResponse(
        request=request,
        name="admin/crawl_job_detail.html",
        context={
            "job": _job_row(session, job),
            "tasks": task_rows,
            "documents": document_rows,
            "saved_summary": saved_summary,
        },
    )


@router.post("/crawl-jobs/{job_id}/run")
def run_crawl_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    session: AdminSession,
):
    job = _get_job(session, job_id)
    if job.status not in {CrawlStatus.cancelled, CrawlStatus.running, CrawlStatus.succeeded}:
        session.commit()
        background_tasks.add_task(_run_crawl_job_background, str(job.id))
    return _redirect(f"/admin/crawl-jobs/{job.id}")


@router.post("/quick-crawl")
def quick_crawl(
    background_tasks: BackgroundTasks,
    session: AdminSession,
    urls_text: str = Form(""),
    job_name: str = Form(""),
    discover_links: str = Form(""),
):
    urls = [u.strip() for u in urls_text.splitlines() if u.strip().startswith("http")]
    if not urls:
        raise HTTPException(status_code=400, detail="请至少提供一个以 http 开头的 URL。")
    name = job_name.strip() or f"爬取 {datetime.utcnow().strftime('%m-%d %H:%M')}"
    deep = discover_links == "true"
    result = CrawlJobRunner(session).create_job(name, urls, discover_links=deep)
    job_id = result["job_id"]
    background_tasks.add_task(_run_crawl_job_background, job_id)
    return _redirect(f"/admin/crawl-jobs/{job_id}")


@router.post("/extract-pending")
def extract_pending(
    background_tasks: BackgroundTasks,
    extractor_mode: str = Form("auto"),
    limit: int = Form(100),
):
    background_tasks.add_task(_run_extract_pending_background, extractor_mode, limit)
    return _redirect("/admin")


@router.post("/crawl-jobs/{job_id}/stop")
def stop_crawl_job(job_id: str, session: AdminSession):
    job = _get_job(session, job_id)
    if job.status not in {CrawlStatus.cancelled, CrawlStatus.succeeded}:
        job.status = CrawlStatus.paused
        _update_related_session_status(session, job, OrchestrationStatus.paused)
        session.commit()
    return _redirect(f"/admin/crawl-jobs/{job.id}")


@router.post("/crawl-jobs/{job_id}/cancel")
def cancel_crawl_job(job_id: str, session: AdminSession):
    job = _get_job(session, job_id)
    job.status = CrawlStatus.cancelled
    job.finished_at = datetime.utcnow()
    _update_related_session_status(session, job, OrchestrationStatus.cancelled)
    session.commit()
    return _redirect(f"/admin/crawl-jobs/{job.id}")


@router.get("/documents")
def documents(request: Request, session: AdminSession):
    from mathscout.db.models import PipelineStatus

    rows = [
        {
            "URL": document.url,
            "状态": _display(document.status),
            "HTTP": _display(document.http_status),
            "登录": "是" if document.needs_login else "否",
            "抓取时间": _display(document.fetched_at),
            "_actions": (
                [{"label": "重新抓取", "url": f"/admin/documents/{document.id}/retry"}]
                if document.pipeline_status
                in {PipelineStatus.failed, PipelineStatus.login_required, PipelineStatus.needs_ocr}
                else []
            ),
        }
        for document in session.scalars(
            select(SourceDocument).order_by(SourceDocument.created_at.desc()).limit(100)
        ).all()
    ]
    return _list_response(
        request=request,
        title="已抓文档",
        columns=["URL", "状态", "HTTP", "登录", "抓取时间"],
        rows=rows,
        actions_enabled=True,
    )


@router.post("/documents/{document_id}/retry")
def retry_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    session: AdminSession,
):
    from mathscout.db.models import PipelineStatus

    try:
        parsed_id = uuid.UUID(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="未找到该文档。") from exc
    document = session.get(SourceDocument, parsed_id)
    if document is None:
        raise HTTPException(status_code=404, detail="未找到该文档。")
    if document.pipeline_status not in {
        PipelineStatus.failed,
        PipelineStatus.login_required,
        PipelineStatus.needs_ocr,
    }:
        raise HTTPException(status_code=400, detail="仅可重新抓取失败、需登录或待 OCR 的文档。")

    name = f"重新抓取 {datetime.utcnow().strftime('%m-%d %H:%M')}"
    result = CrawlJobRunner(session).create_job(name, [document.url], discover_links=False)
    session.commit()
    background_tasks.add_task(_run_crawl_job_background, result["job_id"])
    return _redirect("/admin/documents")


@router.get("/review")
def review_queue(request: Request, session: AdminSession):
    candidates = session.scalars(
        select(CandidateKnowledgeItem)
        .where(CandidateKnowledgeItem.review_status == ReviewStatus.pending)
        .order_by(CandidateKnowledgeItem.created_at.desc())
        .limit(100)
    ).all()
    document_ids = list({candidate.document_id for candidate in candidates})
    documents_by_id = {
        document.id: document for document in _documents_for_ids(session, document_ids)
    }
    rows = [
        {
            "kind": "candidate",
            "id": str(candidate.id),
            "type": "候选知识",
            "title": candidate.title,
            "section": _display(candidate.chapter_title),
            "summary": _truncate(str((candidate.payload or {}).get("summary") or "-"), 220),
            "confidence": f"{candidate.confidence:.2f}",
            "source": _truncate(_display(documents_by_id.get(candidate.document_id).url), 120)
            if documents_by_id.get(candidate.document_id)
            else "-",
            "status": _display(candidate.review_status),
            "created": _display(candidate.created_at),
            "_created_at": candidate.created_at,
        }
        for candidate in candidates
    ]
    rows.extend(
        {
            "kind": "item",
            "id": str(item.id),
            "type": _display(item.item_type),
            "title": _display(item.target_table or item.target_id),
            "section": "-",
            "summary": _truncate(str(item.reason or item.payload or "-"), 220),
            "confidence": "-",
            "source": "-",
            "status": _display(item.status),
            "created": _display(item.created_at),
            "_created_at": item.created_at,
        }
        for item in session.scalars(
            select(ReviewItem)
            .where(ReviewItem.status == ReviewStatus.pending)
            .order_by(ReviewItem.created_at.desc())
            .limit(100)
        ).all()
    )
    rows.sort(key=lambda row: row["_created_at"], reverse=True)
    return templates.TemplateResponse(
        request=request,
        name="admin/review.html",
        context={"rows": rows},
    )


@router.post("/review/candidates/{candidate_id}/{action}")
def review_candidate_action(
    candidate_id: str,
    action: str,
    session: AdminSession,
    reason: str = Form(""),
):
    try:
        ReviewService(session).apply_candidate_action(candidate_id, action, reason=reason)
        session.commit()
    except ReviewActionError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _redirect("/admin/review")


@router.post("/review/items/{item_id}/{action}")
def review_item_action(
    item_id: str,
    action: str,
    session: AdminSession,
    reason: str = Form(""),
):
    try:
        ReviewService(session).apply_review_item_action(item_id, action, reason=reason)
        session.commit()
    except ReviewActionError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _redirect("/admin/review")


@router.get("/changes")
def change_log(request: Request, session: AdminSession):
    rows = [
        {
            "目标": log.target_table,
            "动作": _display(log.action),
            "编辑者": _display(log.editor),
            "可回滚": "是" if log.can_rollback else "否",
            "创建时间": _display(log.created_at),
        }
        for log in session.scalars(
            select(ManualEditLog).order_by(ManualEditLog.created_at.desc()).limit(100)
        ).all()
    ]
    return _list_response(
        request=request,
        title="变更记录",
        columns=["目标", "动作", "编辑者", "可回滚", "创建时间"],
        rows=rows,
    )


def _execute_orchestration_plan(
    session: Session,
    plan,
    orchestration_session: OrchestrationSession,
    command: NaturalLanguageCommand,
    urls: list[str],
    extractor_mode: str,
    discover_links: bool,
    discovery_max_links: int,
    auto_start: bool,
) -> CrawlJob | None:
    job = None
    for action in plan.actions:
        payload = action.payload.copy()
        target_type = action.action_type
        target_id = None
        auto_executed = False
        if action.action_type == "create_crawl_job":
            job = _create_crawl_job(
                session=session,
                name=_job_name(command.raw_text),
                urls=urls,
                source_filter={
                    "urls": urls,
                    "objective": command.raw_text,
                    "session_id": str(orchestration_session.id),
                    "command_id": str(command.id),
                    "extractor_mode": extractor_mode,
                    "discover_links": discover_links,
                    "discovery_max_links": discovery_max_links,
                    "source_mode": plan.directive.target_scope.get("source_mode"),
                    "auto_start": auto_start,
                    "target_scope": plan.directive.target_scope,
                },
                task_type="discover_links" if discover_links else "crawl_url",
            )
            payload = {
                **payload,
                "job_id": str(job.id),
                "urls": urls,
                "extractor_mode": extractor_mode,
                "discover_links": discover_links,
                "discovery_max_links": discovery_max_links,
                "auto_start": auto_start,
            }
            target_type = "crawl_job"
            target_id = job.id
            auto_executed = True
        elif action.action_type in {"create_extraction_job", "create_reconciliation_job"}:
            payload = {
                **payload,
                "handled_by": "CrawlPipeline",
                "crawl_job_id": str(job.id) if job is not None else None,
            }

        session.add(
            AgentDecision(
                session_id=orchestration_session.id,
                command_id=command.id,
                decision_type=_decision_type_for_action(action.action_type),
                target_type=target_type,
                target_id=target_id,
                rationale=action.rationale,
                input_metrics={"expected_outcomes": plan.expected_outcomes},
                policy_checks=_policy_checks(action.action_type, urls),
                action_payload=payload,
                confidence=action.confidence,
                auto_executed=auto_executed,
            )
        )
    return job


def _create_crawl_job(
    session: Session,
    name: str,
    urls: list[str],
    source_filter: dict[str, Any],
    task_type: str = "crawl_url",
) -> CrawlJob:
    job = CrawlJob(
        name=name,
        status=CrawlStatus.pending,
        source_filter=source_filter,
    )
    session.add(job)
    session.flush()
    for url in urls:
        session.add(
            CrawlTask(
                job_id=job.id,
                url=url,
                task_type=task_type,
                status=CrawlStatus.pending,
            )
        )
    session.flush()
    return job


def _run_extract_pending_background(extractor_mode: str, limit: int) -> None:
    with SessionLocal() as session:
        ExtractPipeline(session, extractor_mode=extractor_mode).extract_pending(limit=limit)


def _run_crawl_job_background(job_id: str) -> None:
    try:
        with SessionLocal() as session:
            CrawlJobRunner(session).run_job(job_id)
    except Exception as exc:
        with SessionLocal() as session:
            job = session.get(CrawlJob, uuid.UUID(job_id))
            if job is not None:
                job.status = CrawlStatus.failed
                job.finished_at = datetime.utcnow()
                session.add(
                    AgentDecision(
                        session_id=_source_filter_uuid(job, "session_id"),
                        command_id=_source_filter_uuid(job, "command_id"),
                        decision_type=AgentDecisionType.request_review,
                        target_type="crawl_job",
                        target_id=job.id,
                        rationale=f"后台执行爬取任务失败：{exc}",
                        input_metrics={},
                        policy_checks={},
                        action_payload={"job_id": job_id, "error": str(exc)},
                        confidence=1.0,
                        auto_executed=False,
                    )
                )
                session.commit()


def _resolve_crawl_urls(
    session: Session,
    objective: str,
    seed_urls: str,
    max_seed_urls: int,
) -> tuple[list[str], str]:
    pasted_urls = _extract_urls(f"{seed_urls}\n{objective}")
    if pasted_urls:
        return pasted_urls[:max_seed_urls], "manual_urls"

    source_urls = [
        site.base_url
        for site in session.scalars(
            select(SourceSite)
            .where(SourceSite.enabled.is_(True), SourceSite.access_level == AccessLevel.public)
            .order_by(SourceSite.category.asc(), SourceSite.name.asc())
            .limit(max_seed_urls)
        ).all()
    ]
    return source_urls, "enabled_public_sources"


def _extract_urls(text: str) -> list[str]:
    urls = []
    seen = set()
    for match in URL_RE.findall(text):
        url = match.rstrip(".,;:!?)]}，。；：！？、")
        if url not in seen:
            urls.append(url)
            seen.add(url)
    return urls


def _build_orchestration_context(
    session: Session,
    orchestration_session: OrchestrationSession,
    objective: str,
    target_scope: dict[str, Any],
    budgets: dict[str, Any],
    stop_conditions: dict[str, Any],
) -> OrchestrationContext:
    active_sources = [
        {
            "id": str(site.id),
            "name": site.name,
            "base_url": site.base_url,
            "category": site.category,
            "access_level": site.access_level.value,
        }
        for site in session.scalars(
            select(SourceSite).where(SourceSite.enabled.is_(True)).order_by(SourceSite.name)
        ).all()
    ]
    blocked_sources = [
        source
        for source in active_sources
        if source["access_level"] in {"login_required", "paid_or_restricted"}
    ]
    return OrchestrationContext(
        session_id=str(orchestration_session.id),
        objective=objective,
        target_scope=target_scope,
        budgets=budgets,
        stop_conditions=stop_conditions,
        quality_snapshot=_recent_output_summary(session),
        active_sources=active_sources,
        blocked_sources=blocked_sources,
    )


def _policy_checks(action_type: str, urls: list[str]) -> dict[str, Any]:
    return {
        "action_type": action_type,
        "public_or_user_provided_urls": "仅使用公开来源或用户提供的 URL",
        "manual_stop_available": "后台可随时暂停或取消",
        "full_content_private": "原始全文只作为本地私有抓取材料保存",
        "url_count": len(urls),
    }


def _decision_type_for_action(action_type: str) -> AgentDecisionType:
    if action_type == "reprioritize_source":
        return AgentDecisionType.reprioritize_source
    if action_type == "pause_source":
        return AgentDecisionType.pause_source
    if action_type == "stop_session":
        return AgentDecisionType.stop_session
    if action_type in {"adjust_strategy", "resume_source"}:
        return AgentDecisionType.adjust_strategy
    if action_type in {"request_review", "request_login"}:
        return AgentDecisionType.request_review
    return AgentDecisionType.create_task


def _infer_textbook_scope(objective: str) -> dict[str, str]:
    scope: dict[str, str] = {}
    lowered = objective.lower()
    if "北师大" in objective or "beishida" in lowered:
        scope["series"] = "beishida"
    if "七年级" in objective or "初一" in objective or "7" in objective:
        scope["grade"] = "7"
    if "八年级" in objective or "初二" in objective or "8" in objective:
        scope["grade"] = "8"
    if "九年级" in objective or "初三" in objective or "9" in objective:
        scope["grade"] = "9"
    if "上册" in objective:
        scope["semester"] = "A"
    if "下册" in objective:
        scope["semester"] = "B"
    focus = []
    for keyword in ["有理数", "一元一次方程", "几何", "函数", "统计"]:
        if keyword in objective:
            focus.append(keyword)
    if focus:
        scope["focus"] = ", ".join(focus)
    return scope


def _interpret_command(objective: str, urls: list[str], extractor_mode: str) -> str:
    return (
        f"按规则规划链接发现，并为 {len(urls)} 个种子 URL 创建受监督爬取任务；"
        f"随后用 {extractor_mode} 模式分析页面并保存候选知识。"
    )


def _job_rows(session: Session, statement) -> list[dict[str, Any]]:
    return [_job_row(session, job) for job in session.scalars(statement).all()]


def _job_row(session: Session, job: CrawlJob) -> dict[str, Any]:
    counts = _crawl_task_counts(session, job.id)
    source_filter = job.source_filter or {}
    return {
        "id": str(job.id),
        "name": job.name,
        "status": _display(job.status),
        "extractor_mode": source_filter.get("extractor_mode", "auto"),
        "extractor_mode_label": _display_extractor_mode(
            source_filter.get("extractor_mode", "auto")
        ),
        "total": sum(counts.values()),
        "pending": counts.get(CrawlStatus.pending, 0),
        "running": counts.get(CrawlStatus.running, 0),
        "paused": counts.get(CrawlStatus.paused, 0),
        "succeeded": counts.get(CrawlStatus.succeeded, 0),
        "failed": counts.get(CrawlStatus.failed, 0),
        "blocked": counts.get(CrawlStatus.blocked, 0),
        "cancelled": counts.get(CrawlStatus.cancelled, 0),
        "started": _display(job.started_at),
        "finished": _display(job.finished_at),
        "created": _display(job.created_at),
        "can_run": job.status
        not in {CrawlStatus.running, CrawlStatus.cancelled, CrawlStatus.succeeded},
        "can_stop": job.status not in {CrawlStatus.cancelled, CrawlStatus.succeeded},
        "can_cancel": job.status != CrawlStatus.cancelled,
    }


def _crawl_task_counts(session: Session, job_id: uuid.UUID) -> dict[CrawlStatus, int]:
    return dict(
        session.execute(
            select(CrawlTask.status, func.count(CrawlTask.id))
            .where(CrawlTask.job_id == job_id)
            .group_by(CrawlTask.status)
        ).all()
    )


def _display_extractor_mode(value: Any) -> str:
    return {
        "auto": "自动",
        "rule": "规则",
        "rules": "规则",
        "ai": "AI",
        "deepseek": "DeepSeek",
    }.get(str(value), str(value))


def _display_pipeline_status(value: Any) -> str:
    if value is None:
        return "待提取"
    return {
        "crawled": "已爬取，待提取",
        "extracted": "已提取",
        "done": "已入库",
        "failed": "提取失败",
        "login_required": "需登录",
        "needs_ocr": "待 OCR（扫描件/图片）",
    }.get(str(value), str(value))


def _recent_output_summary(session: Session) -> dict[str, int]:
    return {
        "已抓文档": _count(session, SourceDocument),
        "候选项": _count(session, CandidateKnowledgeItem),
        "方法": _count(session, TeachingMethod),
        "待复核": _review_count(session),
        "失败任务": session.scalar(
            select(func.count())
            .select_from(CrawlTask)
            .where(CrawlTask.status == CrawlStatus.failed)
        )
        or 0,
    }


def _documents_for_ids(session: Session, document_ids: list[uuid.UUID]) -> list[SourceDocument]:
    if not document_ids:
        return []
    return session.scalars(
        select(SourceDocument)
        .where(SourceDocument.id.in_(document_ids))
        .order_by(SourceDocument.created_at.desc())
    ).all()


def _document_ids_from_tasks(tasks: list[CrawlTask]) -> list[uuid.UUID]:
    document_ids = []
    seen = set()
    for task in tasks:
        document_id = (task.result_json or {}).get("document_id")
        if not document_id:
            continue
        try:
            parsed = uuid.UUID(str(document_id))
        except ValueError:
            continue
        if parsed not in seen:
            document_ids.append(parsed)
            seen.add(parsed)
    return document_ids


def _count_for_documents(
    session: Session,
    model: type[Any],
    document_ids: list[uuid.UUID],
) -> int:
    if not document_ids:
        return 0
    return (
        session.scalar(
            select(func.count()).select_from(model).where(model.document_id.in_(document_ids))
        )
        or 0
    )


def _pending_review_for_documents(session: Session, document_ids: list[uuid.UUID]) -> int:
    if not document_ids:
        return 0
    return (
        session.scalar(
            select(func.count())
            .select_from(CandidateKnowledgeItem)
            .where(
                CandidateKnowledgeItem.document_id.in_(document_ids),
                CandidateKnowledgeItem.review_status == ReviewStatus.pending,
            )
        )
        or 0
    )


def _result_value(task: CrawlTask, key: str) -> Any:
    result = task.result_json or {}
    if key in result:
        return result.get(key, "-")
    payload = result.get("payload")
    if isinstance(payload, dict):
        return payload.get(key, "-")
    return "-"


def _task_note(task: CrawlTask) -> str:
    result = task.result_json or {}
    if result.get("fallback_used"):
        return "发现不到可用子链接，已回退抓取种子页。"
    if task.task_type == "discover_links" and task.status == CrawlStatus.succeeded:
        selected_count = _as_int(_result_value(task, "selected_count"))
        created_tasks = _as_int(_result_value(task, "created_tasks"))
        if selected_count == 0 and created_tasks == 0:
            return "发现完成，但没有生成抓取任务。"
    if result.get("status") == "blocked_login":
        return "页面需要登录，已阻塞。"
    error = result.get("error")
    if error:
        return _truncate(str(error), 160)
    return "-"


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _get_job(session: Session, job_id: str) -> CrawlJob:
    try:
        parsed_id = uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="找不到爬取任务。") from exc
    job = session.get(CrawlJob, parsed_id)
    if job is None:
        raise HTTPException(status_code=404, detail="找不到爬取任务。")
    return job


def _update_related_session_status(
    session: Session,
    job: CrawlJob,
    status: OrchestrationStatus,
) -> None:
    session_id = _source_filter_uuid(job, "session_id")
    if session_id is None:
        return
    orchestration_session = session.get(OrchestrationSession, session_id)
    if orchestration_session is not None:
        orchestration_session.status = status
        orchestration_session.updated_at = datetime.utcnow()


def _source_filter_uuid(job: CrawlJob, key: str) -> uuid.UUID | None:
    value = (job.source_filter or {}).get(key)
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _job_name(objective: str) -> str:
    compact = " ".join(objective.split())
    return f"AI: {compact[:120]}"


def _count(session: Session, model: type[Any]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def _review_count(session: Session) -> int:
    candidate_count = (
        session.scalar(
            select(func.count())
            .select_from(CandidateKnowledgeItem)
            .where(CandidateKnowledgeItem.review_status == ReviewStatus.pending)
        )
        or 0
    )
    review_item_count = (
        session.scalar(
            select(func.count())
            .select_from(ReviewItem)
            .where(ReviewItem.status == ReviewStatus.pending)
        )
        or 0
    )
    return candidate_count + review_item_count


def _list_response(
    request: Request,
    title: str,
    columns: list[str],
    rows: list[dict[str, Any]],
    actions_enabled: bool = False,
):
    return templates.TemplateResponse(
        request=request,
        name="admin/list.html",
        context={
            "title": title,
            "columns": columns,
            "rows": rows,
            "actions_enabled": actions_enabled,
        },
    )


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


_UTC8 = timezone(timedelta(hours=8))


def _display(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(_UTC8).strftime("%Y-%m-%d %H:%M")
    if hasattr(value, "value"):
        raw = str(value.value)
        return DISPLAY_TEXT.get(raw, raw)
    raw = str(value)
    return DISPLAY_TEXT.get(raw, raw)


def _truncate(value: str | None, limit: int) -> str:
    if not value:
        return "-"
    if len(value) <= limit:
        return value
    return f"{value[:limit]}..."
