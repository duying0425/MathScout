from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mathscout.db.base import Base


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


class AccessLevel(StrEnum):
    public = "public"
    login_required = "login_required"
    paid_or_restricted = "paid_or_restricted"
    unknown = "unknown"


class CrawlStatus(StrEnum):
    pending = "pending"
    running = "running"
    paused = "paused"
    cancelled = "cancelled"
    succeeded = "succeeded"
    failed = "failed"
    blocked = "blocked"


class PipelineStatus(StrEnum):
    crawled = "crawled"            # Phase 1 done: files on disk, ready for extraction
    extracted = "extracted"        # Phase 2 done: candidates in DB, ready for reconciliation
    done = "done"                  # Phase 3 done: reconciled into knowledge base
    failed = "failed"              # Any phase failed
    login_required = "login_required"  # Blocked by login wall
    needs_ocr = "needs_ocr"        # 扫描件/图片，待 OCR（未配置 Azure 文档智能时）


class ReviewStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    needs_edit = "needs_edit"


class CandidateItemType(StrEnum):
    knowledge_point = "knowledge_point"
    teaching_method = "teaching_method"
    teaching_method_variant = "teaching_method_variant"
    student_skill = "student_skill"
    region_adoption = "region_adoption"
    textbook_structure = "textbook_structure"


class ReconciliationAction(StrEnum):
    skip = "skip"
    update = "update"
    create_variant = "create_variant"
    create = "create"
    conflict = "conflict"
    review = "review"


class OrchestrationStatus(StrEnum):
    active = "active"
    paused = "paused"
    completed = "completed"
    blocked = "blocked"
    cancelled = "cancelled"


class AgentDecisionType(StrEnum):
    create_task = "create_task"
    reprioritize_source = "reprioritize_source"
    pause_source = "pause_source"
    retry_task = "retry_task"
    stop_session = "stop_session"
    adjust_strategy = "adjust_strategy"
    apply_reconciliation = "apply_reconciliation"
    request_review = "request_review"


class ManualEditAction(StrEnum):
    create = "create"
    update = "update"
    merge = "merge"
    split = "split"
    delete = "delete"
    restore = "restore"
    approve_ai_change = "approve_ai_change"
    reject_ai_change = "reject_ai_change"
    lock = "lock"
    unlock = "unlock"


class SourceSite(Base):
    __tablename__ = "source_sites"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200))
    base_url: Mapped[str] = mapped_column(String(500), unique=True)
    domain: Mapped[str] = mapped_column(String(200), index=True)
    category: Mapped[str] = mapped_column(String(80), index=True)
    access_level: Mapped[AccessLevel] = mapped_column(
        Enum(AccessLevel),
        default=AccessLevel.unknown,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    crawl_delay_seconds: Mapped[int] = mapped_column(Integer, default=3)
    robots_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terms_url: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    documents: Mapped[list[SourceDocument]] = relationship(back_populates="site")


class SourceDocument(Base):
    __tablename__ = "source_documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_sites.id"))
    url: Mapped[str] = mapped_column(String(1000), index=True)
    canonical_url: Mapped[str | None] = mapped_column(String(1000))
    title: Mapped[str | None] = mapped_column(String(500))
    content_type: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[CrawlStatus] = mapped_column(Enum(CrawlStatus), default=CrawlStatus.pending)
    http_status: Mapped[int | None] = mapped_column(Integer)
    needs_login: Mapped[bool] = mapped_column(Boolean, default=False)
    checksum: Mapped[str | None] = mapped_column(String(128), index=True)
    raw_path: Mapped[str | None] = mapped_column(String(1000))
    text_path: Mapped[str | None] = mapped_column(String(1000))
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    pipeline_status: Mapped[PipelineStatus | None] = mapped_column(
        Enum(PipelineStatus), index=True, nullable=True
    )
    pipeline_error: Mapped[str | None] = mapped_column(Text)
    # 识别出的文档类型（DocumentKind 值，如 html/pdf_digital/word/...），供后台展示与排查。
    document_kind: Mapped[str | None] = mapped_column(String(32))

    site: Mapped[SourceSite | None] = relationship(back_populates="documents")
    evidence_snippets: Mapped[list[EvidenceSnippet]] = relationship(back_populates="document")


class EvidenceSnippet(Base):
    __tablename__ = "evidence_snippets"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_documents.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    start_offset: Mapped[int | None] = mapped_column(Integer)
    end_offset: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    document: Mapped[SourceDocument] = relationship(back_populates="evidence_snippets")


class TextbookSeries(Base):
    __tablename__ = "textbook_series"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), unique=True)
    publisher: Mapped[str | None] = mapped_column(String(200))
    school_system: Mapped[str | None] = mapped_column(String(50))
    curriculum_standard_basis: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)

    books: Mapped[list[Book]] = relationship(back_populates="series")


class Book(Base):
    __tablename__ = "books"
    __table_args__ = (UniqueConstraint("series_id", "book_code", name="uq_books_series_book_code"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    series_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("textbook_series.id"), index=True)
    book_code: Mapped[str] = mapped_column(String(20), index=True)
    grade: Mapped[int] = mapped_column(Integer)
    semester: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(100))
    edition_label: Mapped[str | None] = mapped_column(String(100))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)

    series: Mapped[TextbookSeries] = relationship(back_populates="books")
    chapters: Mapped[list[Chapter]] = relationship(back_populates="book")


class Chapter(Base):
    __tablename__ = "chapters"
    __table_args__ = (UniqueConstraint("book_id", "chapter_code", name="uq_chapters_book_code"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id"), index=True)
    chapter_code: Mapped[str] = mapped_column(String(50), index=True)
    title: Mapped[str] = mapped_column(String(300))
    chapter_goal: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)

    book: Mapped[Book] = relationship(back_populates="chapters")
    sections: Mapped[list[Section]] = relationship(back_populates="chapter")


class Section(Base):
    __tablename__ = "sections"
    __table_args__ = (
        UniqueConstraint("chapter_id", "section_code", name="uq_sections_chapter_code"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    chapter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chapters.id"), index=True)
    section_code: Mapped[str] = mapped_column(String(60), index=True)
    title: Mapped[str] = mapped_column(String(300))
    position: Mapped[int] = mapped_column(Integer, default=0)

    chapter: Mapped[Chapter] = relationship(back_populates="sections")
    knowledge_points: Mapped[list[KnowledgePoint]] = relationship(back_populates="section")


class StudentSkill(Base):
    __tablename__ = "student_skills"

    id: Mapped[uuid.UUID] = uuid_pk()
    skill_code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"

    id: Mapped[uuid.UUID] = uuid_pk()
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sections.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    semantic_key: Mapped[str | None] = mapped_column(String(500), index=True)
    source_type: Mapped[str] = mapped_column(String(80), default="extracted")
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evidence_snippets.id"))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source_count: Mapped[int] = mapped_column(Integer, default=1)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    human_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_human_edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus), default=ReviewStatus.pending
    )

    section: Mapped[Section] = relationship(back_populates="knowledge_points")


class TeachingMethod(Base):
    __tablename__ = "teaching_methods"

    id: Mapped[uuid.UUID] = uuid_pk()
    title: Mapped[str] = mapped_column(String(300))
    semantic_key: Mapped[str | None] = mapped_column(String(500), index=True)
    method_type: Mapped[str] = mapped_column(String(80), index=True)
    canonical_scope: Mapped[str | None] = mapped_column(String(120), index=True)
    summary: Mapped[str] = mapped_column(Text)
    steps: Mapped[list[str]] = mapped_column(JSON, default=list)
    applicable_patterns: Mapped[list[str]] = mapped_column(JSON, default=list)
    prerequisites: Mapped[list[str]] = mapped_column(JSON, default=list)
    common_misconceptions: Mapped[list[str]] = mapped_column(JSON, default=list)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evidence_snippets.id"))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source_count: Mapped[int] = mapped_column(Integer, default=1)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    human_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_human_edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus), default=ReviewStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class TeachingMethodVariant(Base):
    __tablename__ = "teaching_method_variants"

    id: Mapped[uuid.UUID] = uuid_pk()
    method_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teaching_methods.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    source_teacher: Mapped[str | None] = mapped_column(String(200), index=True)
    source_org: Mapped[str | None] = mapped_column(String(300), index=True)
    source_region: Mapped[str | None] = mapped_column(String(120), index=True)
    explanation_style: Mapped[str | None] = mapped_column(String(120), index=True)
    summary: Mapped[str] = mapped_column(Text)
    steps: Mapped[list[str]] = mapped_column(JSON, default=list)
    applicable_patterns: Mapped[list[str]] = mapped_column(JSON, default=list)
    classroom_warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    example_patterns: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_documents.id"))
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evidence_snippets.id"))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    human_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_human_edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus), default=ReviewStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class MethodSectionLink(Base):
    __tablename__ = "method_section_links"
    __table_args__ = (
        UniqueConstraint("method_id", "section_id", "relation_type", name="uq_method_section_link"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    method_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teaching_methods.id"), index=True)
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sections.id"), index=True)
    relation_type: Mapped[str] = mapped_column(String(80), default="primary", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evidence_snippets.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class MethodKnowledgePointLink(Base):
    __tablename__ = "method_knowledge_point_links"
    __table_args__ = (
        UniqueConstraint(
            "method_id",
            "knowledge_point_id",
            "relation_type",
            name="uq_method_knowledge_point_link",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    method_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teaching_methods.id"), index=True)
    knowledge_point_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_points.id"), index=True
    )
    relation_type: Mapped[str] = mapped_column(String(80), default="primary", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evidence_snippets.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class RegionAdoption(Base):
    __tablename__ = "region_adoptions"

    id: Mapped[uuid.UUID] = uuid_pk()
    series_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("textbook_series.id"), index=True)
    province: Mapped[str] = mapped_column(String(80), index=True)
    city: Mapped[str | None] = mapped_column(String(80), index=True)
    district: Mapped[str | None] = mapped_column(String(80), index=True)
    school_name: Mapped[str | None] = mapped_column(String(200), index=True)
    grade: Mapped[int | None] = mapped_column(Integer)
    valid_from: Mapped[str | None] = mapped_column(String(30))
    valid_to: Mapped[str | None] = mapped_column(String(30))
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evidence_snippets.id"))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus), default=ReviewStatus.pending
    )


class CrawlJob(Base):
    __tablename__ = "crawl_jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[CrawlStatus] = mapped_column(Enum(CrawlStatus), default=CrawlStatus.pending)
    source_filter: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CrawlTask(Base):
    __tablename__ = "crawl_tasks"

    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crawl_jobs.id"), index=True)
    url: Mapped[str] = mapped_column(String(1000), index=True)
    task_type: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[CrawlStatus] = mapped_column(Enum(CrawlStatus), default=CrawlStatus.pending)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_documents.id"), index=True)
    extractor_name: Mapped[str] = mapped_column(String(120))
    extractor_version: Mapped[str] = mapped_column(String(80))
    model_name: Mapped[str | None] = mapped_column(String(120))
    prompt_version: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[CrawlStatus] = mapped_column(Enum(CrawlStatus), default=CrawlStatus.pending)
    output_hash: Mapped[str | None] = mapped_column(String(128))
    output_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class CandidateKnowledgeItem(Base):
    __tablename__ = "candidate_knowledge_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_documents.id"), index=True)
    extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("extraction_runs.id"))
    item_type: Mapped[CandidateItemType] = mapped_column(Enum(CandidateItemType), index=True)
    title: Mapped[str] = mapped_column(String(300))
    semantic_key: Mapped[str | None] = mapped_column(String(500), index=True)
    textbook_series: Mapped[str | None] = mapped_column(String(200), index=True)
    book_code: Mapped[str | None] = mapped_column(String(20), index=True)
    chapter_title: Mapped[str | None] = mapped_column(String(300), index=True)
    section_title: Mapped[str | None] = mapped_column(String(300), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus), default=ReviewStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ReconciliationDecision(Base):
    __tablename__ = "reconciliation_decisions"

    id: Mapped[uuid.UUID] = uuid_pk()
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_knowledge_items.id"), index=True
    )
    action: Mapped[ReconciliationAction] = mapped_column(Enum(ReconciliationAction), index=True)
    matched_table: Mapped[str | None] = mapped_column(String(120), index=True)
    matched_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    matched_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    rationale: Mapped[str] = mapped_column(Text)
    proposed_patch: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    auto_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus), default=ReviewStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class OrchestrationSession(Base):
    __tablename__ = "orchestration_sessions"

    id: Mapped[uuid.UUID] = uuid_pk()
    objective: Mapped[str] = mapped_column(Text)
    status: Mapped[OrchestrationStatus] = mapped_column(
        Enum(OrchestrationStatus), default=OrchestrationStatus.active, index=True
    )
    target_scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    strategy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    budgets: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    stop_conditions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class NaturalLanguageCommand(Base):
    __tablename__ = "natural_language_commands"

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("orchestration_sessions.id"), index=True
    )
    raw_text: Mapped[str] = mapped_column(Text)
    interpreted_intent: Mapped[str | None] = mapped_column(Text)
    structured_directive: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[OrchestrationStatus] = mapped_column(
        Enum(OrchestrationStatus), default=OrchestrationStatus.active, index=True
    )
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class AgentDecision(Base):
    __tablename__ = "agent_decisions"

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("orchestration_sessions.id"), index=True
    )
    command_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("natural_language_commands.id"), index=True
    )
    decision_type: Mapped[AgentDecisionType] = mapped_column(Enum(AgentDecisionType), index=True)
    target_type: Mapped[str | None] = mapped_column(String(120), index=True)
    target_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    rationale: Mapped[str] = mapped_column(Text)
    input_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    policy_checks: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    action_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    auto_executed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class QualitySnapshot(Base):
    __tablename__ = "quality_snapshots"

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("orchestration_sessions.id"), index=True
    )
    textbook_series: Mapped[str | None] = mapped_column(String(200), index=True)
    book_code: Mapped[str | None] = mapped_column(String(20), index=True)
    chapter_code: Mapped[str | None] = mapped_column(String(50), index=True)
    coverage_rate: Mapped[float | None] = mapped_column(Float)
    novelty_rate: Mapped[float | None] = mapped_column(Float)
    duplicate_rate: Mapped[float | None] = mapped_column(Float)
    conflict_rate: Mapped[float | None] = mapped_column(Float)
    average_confidence: Mapped[float | None] = mapped_column(Float)
    source_yield: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    failure_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    budget_usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ManualEditLog(Base):
    __tablename__ = "manual_edit_logs"

    id: Mapped[uuid.UUID] = uuid_pk()
    target_table: Mapped[str] = mapped_column(String(120), index=True)
    target_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    action: Mapped[ManualEditAction] = mapped_column(Enum(ManualEditAction), index=True)
    before_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    after_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reason: Mapped[str | None] = mapped_column(Text)
    editor: Mapped[str | None] = mapped_column(String(120), index=True)
    related_review_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("review_items.id"))
    related_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reconciliation_decisions.id")
    )
    can_rollback: Mapped[bool] = mapped_column(Boolean, default=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ReviewItem(Base):
    __tablename__ = "review_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    item_type: Mapped[str] = mapped_column(String(80), index=True)
    target_table: Mapped[str | None] = mapped_column(String(120))
    target_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    status: Mapped[ReviewStatus] = mapped_column(Enum(ReviewStatus), default=ReviewStatus.pending)
    reason: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
