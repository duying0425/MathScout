from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mathscout.db.models import (
    Book,
    CandidateKnowledgeItem,
    Chapter,
    CrawlJob,
    KnowledgePoint,
    ManualEditLog,
    NaturalLanguageCommand,
    ReconciliationDecision,
    ReviewItem,
    ReviewStatus,
    Section,
    SourceDocument,
    SourceSite,
    StudentSkill,
    TeachingMethod,
    TextbookSeries,
)
from mathscout.db.session import get_session

templates = Jinja2Templates(directory="mathscout/templates")
router = APIRouter()
AdminSession = Annotated[Session, Depends(get_session)]


@router.get("")
@router.get("/")
def dashboard(request: Request, session: AdminSession):
    cards = [
        {
            "label": "AI Command",
            "value": _count(session, NaturalLanguageCommand),
            "href": "/admin/command",
        },
        {
            "label": "Techniques",
            "value": _count(session, TeachingMethod),
            "href": "/admin/techniques",
        },
        {
            "label": "Knowledge",
            "value": _count(session, KnowledgePoint),
            "href": "/admin/knowledge",
        },
        {"label": "Source Sites", "value": _count(session, SourceSite), "href": "/admin/sources"},
        {"label": "Crawl Jobs", "value": _count(session, CrawlJob), "href": "/admin/crawl-jobs"},
        {
            "label": "Documents",
            "value": _count(session, SourceDocument),
            "href": "/admin/documents",
        },
        {"label": "Review Queue", "value": _review_count(session), "href": "/admin/review"},
        {"label": "Changes", "value": _count(session, ManualEditLog), "href": "/admin/changes"},
    ]
    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context={"cards": cards},
    )


@router.get("/command")
def command_center(request: Request, session: AdminSession):
    rows = [
        {
            "Command": command.raw_text,
            "Intent": _display(command.interpreted_intent),
            "Status": command.status,
            "Created": _display(command.created_at),
        }
        for command in session.scalars(
            select(NaturalLanguageCommand).order_by(NaturalLanguageCommand.created_at.desc())
        ).all()
    ]
    return _list_response(
        request=request,
        title="AI Command Center",
        columns=["Command", "Intent", "Status", "Created"],
        rows=rows,
    )


@router.get("/techniques")
def technique_library(request: Request, session: AdminSession):
    rows = [
        {
            "Title": method.title,
            "Type": method.method_type,
            "Scope": _display(method.canonical_scope),
            "Sources": method.source_count,
            "Review": method.review_status,
        }
        for method in session.scalars(
            select(TeachingMethod).order_by(TeachingMethod.created_at.desc()).limit(100)
        ).all()
    ]
    return _list_response(
        request=request,
        title="Technique Library",
        columns=["Title", "Type", "Scope", "Sources", "Review"],
        rows=rows,
    )


@router.get("/knowledge")
def knowledge_browser(request: Request, session: AdminSession):
    summary = {
        "Series": _count(session, TextbookSeries),
        "Books": _count(session, Book),
        "Chapters": _count(session, Chapter),
        "Sections": _count(session, Section),
        "Knowledge Points": _count(session, KnowledgePoint),
        "Student Skills": _count(session, StudentSkill),
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
            "Name": site.name,
            "Domain": site.domain,
            "Category": site.category,
            "Access": site.access_level,
            "Enabled": "yes" if site.enabled else "no",
        }
        for site in session.scalars(select(SourceSite).order_by(SourceSite.name)).all()
    ]
    return _list_response(
        request=request,
        title="Source Sites",
        columns=["Name", "Domain", "Category", "Access", "Enabled"],
        rows=rows,
    )


@router.get("/crawl-jobs")
def crawl_jobs(request: Request, session: AdminSession):
    rows = [
        {
            "Name": job.name,
            "Status": job.status,
            "Started": _display(job.started_at),
            "Finished": _display(job.finished_at),
            "Created": _display(job.created_at),
        }
        for job in session.scalars(select(CrawlJob).order_by(CrawlJob.created_at.desc())).all()
    ]
    return _list_response(
        request=request,
        title="Crawl Jobs",
        columns=["Name", "Status", "Started", "Finished", "Created"],
        rows=rows,
    )


@router.get("/documents")
def documents(request: Request, session: AdminSession):
    rows = [
        {
            "URL": document.url,
            "Status": document.status,
            "HTTP": _display(document.http_status),
            "Login": "yes" if document.needs_login else "no",
            "Fetched": _display(document.fetched_at),
        }
        for document in session.scalars(
            select(SourceDocument).order_by(SourceDocument.created_at.desc()).limit(100)
        ).all()
    ]
    return _list_response(
        request=request,
        title="Documents",
        columns=["URL", "Status", "HTTP", "Login", "Fetched"],
        rows=rows,
    )


@router.get("/review")
def review_queue(request: Request, session: AdminSession):
    rows = [
        {
            "Type": candidate.item_type,
            "Title": candidate.title,
            "Book": _display(candidate.book_code),
            "Chapter": _display(candidate.chapter_title),
            "Review": candidate.review_status,
            "Created": _display(candidate.created_at),
        }
        for candidate in session.scalars(
            select(CandidateKnowledgeItem)
            .where(CandidateKnowledgeItem.review_status == ReviewStatus.pending)
            .order_by(CandidateKnowledgeItem.created_at.desc())
            .limit(100)
        ).all()
    ]
    return _list_response(
        request=request,
        title="Review Queue",
        columns=["Type", "Title", "Book", "Chapter", "Review", "Created"],
        rows=rows,
    )


@router.get("/changes")
def change_log(request: Request, session: AdminSession):
    rows = [
        {
            "Target": log.target_table,
            "Action": log.action,
            "Editor": _display(log.editor),
            "Rollback": "yes" if log.can_rollback else "no",
            "Created": _display(log.created_at),
        }
        for log in session.scalars(
            select(ManualEditLog).order_by(ManualEditLog.created_at.desc()).limit(100)
        ).all()
    ]
    return _list_response(
        request=request,
        title="Change Log",
        columns=["Target", "Action", "Editor", "Rollback", "Created"],
        rows=rows,
    )


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
    decision_count = (
        session.scalar(
            select(func.count())
            .select_from(ReconciliationDecision)
            .where(ReconciliationDecision.review_status == ReviewStatus.pending)
        )
        or 0
    )
    return candidate_count + review_item_count + decision_count


def _list_response(
    request: Request,
    title: str,
    columns: list[str],
    rows: list[dict[str, Any]],
):
    return templates.TemplateResponse(
        request=request,
        name="admin/list.html",
        context={"title": title, "columns": columns, "rows": rows},
    )


def _display(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)
