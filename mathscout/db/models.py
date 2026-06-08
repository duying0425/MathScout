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
    problem = "problem"
    solution = "solution"


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
    knowledge_point_links: Mapped[list[SectionKnowledgePointLink]] = relationship(
        back_populates="section"
    )


class StudentSkill(Base):
    __tablename__ = "student_skills"

    id: Mapped[uuid.UUID] = uuid_pk()
    skill_code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)


class KnowledgePoint(Base):
    """Canonical 知识点：跨教材版本唯一、共享（四维知识图谱的"事实层"）。

    知识点与教材小节的归属关系由 SectionKnowledgePointLink 表达（多对多），不再由
    单个小节硬绑定。`semantic_key` 为**基于内容**的去重键（规范化标题），使同一知识点
    在多个版本只存一条。见 docs/knowledge-graph-redesign.md。
    """

    __tablename__ = "knowledge_points"

    id: Mapped[uuid.UUID] = uuid_pk()
    # 注意：旧版的 section_id 硬绑定已移除，归属改由 section_knowledge_point_links 表达。
    # 旧库的物理列由 migrations._canonicalize_knowledge_points 回填链接后 DROP。
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

    section_links: Mapped[list[SectionKnowledgePointLink]] = relationship(
        back_populates="knowledge_point"
    )


class SectionKnowledgePointLink(Base):
    """小节 ⟷ 知识点（覆盖）多对多链接。

    替代旧的 KnowledgePoint.section_id 硬绑定：知识点升为 canonical（跨版本唯一），
    教材小节通过本表"覆盖"知识点；同一知识点可被多个版本的多个小节覆盖。
    relation_type: introduce（首次引入）| reinforce（巩固）| extend（拓展）。
    """

    __tablename__ = "section_knowledge_point_links"
    __table_args__ = (
        UniqueConstraint(
            "section_id",
            "knowledge_point_id",
            "relation_type",
            name="uq_section_knowledge_point_link",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sections.id"), index=True)
    knowledge_point_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_points.id"), index=True
    )
    relation_type: Mapped[str] = mapped_column(String(80), default="introduce", index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evidence_snippets.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    section: Mapped[Section] = relationship(back_populates="knowledge_point_links")
    knowledge_point: Mapped[KnowledgePoint] = relationship(back_populates="section_links")


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


# --------------------------------------------------------------------------- #
# 四维知识图谱 · 题目 / 解答 事实层（Phase B 建 schema，Phase C 接抓取/抽取/UI）       #
# 见 docs/knowledge-graph-redesign.md。题目与知识点同为版本无关的"事实"；解答是题目     #
# 专属的解题路径（可一题多解），通过 solution_technique_links 引用可复用的解题技巧       #
# （= teaching_methods）。解答 ≠ 技巧。                                              #
# --------------------------------------------------------------------------- #


class Problem(Base):
    """Canonical 题目：版本无关、弱关联到小节。题干以 LaTeX/含数学的 Markdown 存储。"""

    __tablename__ = "problems"

    id: Mapped[uuid.UUID] = uuid_pk()
    stem: Mapped[str] = mapped_column(Text)  # LaTeX / 含数学的 Markdown
    # 题型：选择/填空/解答/证明…
    problem_type: Mapped[str | None] = mapped_column(String(120), index=True)
    difficulty: Mapped[str | None] = mapped_column(String(40))  # 基础/中等/难，或数值标签
    source_type: Mapped[str | None] = mapped_column(String(80), index=True)  # 课堂/试卷/教辅/题库
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_documents.id")
    )
    has_answer: Mapped[bool] = mapped_column(Boolean, default=False)
    semantic_key: Mapped[str | None] = mapped_column(String(500), index=True)
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

    solutions: Mapped[list[Solution]] = relationship(back_populates="problem")


class Solution(Base):
    """题目的一条解题路径（可一题多解）。通过 solution_technique_links 引用所用技巧。"""

    __tablename__ = "solutions"

    id: Mapped[uuid.UUID] = uuid_pk()
    problem_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("problems.id"), index=True)
    approach_label: Mapped[str | None] = mapped_column(String(200))  # 思路名，如"构造辅助线"
    steps: Mapped[list[str]] = mapped_column(JSON, default=list)  # 分步路径（LaTeX）
    final_answer: Mapped[str | None] = mapped_column(Text)
    complexity: Mapped[str | None] = mapped_column(String(80))  # 复杂度/优劣评估
    source_teacher: Mapped[str | None] = mapped_column(String(200), index=True)
    source_org: Mapped[str | None] = mapped_column(String(300), index=True)
    source_region: Mapped[str | None] = mapped_column(String(120), index=True)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_documents.id")
    )
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evidence_snippets.id"))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    human_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_human_edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus), default=ReviewStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    problem: Mapped[Problem] = relationship(back_populates="solutions")


class Figure(Base):
    """题干 / 解题步骤的配图：原图 image_path + 可选 AI 生成的 TikZ 源码。多态归属。"""

    __tablename__ = "figures"

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_type: Mapped[str] = mapped_column(String(40), index=True)  # problem | solution
    owner_id: Mapped[uuid.UUID] = mapped_column(index=True)
    figure_kind: Mapped[str] = mapped_column(String(40), default="image")  # image | tikz
    image_path: Mapped[str | None] = mapped_column(String(1000))
    tikz_code: Mapped[str | None] = mapped_column(Text)  # AI 由图片生成（可选）
    caption: Mapped[str | None] = mapped_column(String(500))
    position: Mapped[int] = mapped_column(Integer, default=0)
    origin: Mapped[str] = mapped_column(String(40), default="original")  # original | ai_generated
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ProblemKnowledgePointLink(Base):
    """题目 ⟷ 知识点（考察）。出题前设计好的关系；AI 标注、低置信、强制进复核。"""

    __tablename__ = "problem_knowledge_point_links"
    __table_args__ = (
        UniqueConstraint(
            "problem_id", "knowledge_point_id", name="uq_problem_knowledge_point_link"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    problem_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("problems.id"), index=True)
    knowledge_point_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_points.id"), index=True
    )
    # primary | secondary
    relation_type: Mapped[str] = mapped_column(String(80), default="primary", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evidence_snippets.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ProblemSectionLink(Base):
    """题目 ⟷ 小节（弱关联）。题目从某小节"提起"但跨版本共通；软链接、非归属。"""

    __tablename__ = "problem_section_links"
    __table_args__ = (
        UniqueConstraint("problem_id", "section_id", name="uq_problem_section_link"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    problem_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("problems.id"), index=True)
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sections.id"), index=True)
    # exercise_of | introduced_in
    relation_type: Mapped[str] = mapped_column(String(80), default="exercise_of", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evidence_snippets.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class SolutionTechniqueLink(Base):
    """解答 ⟷ 技巧（用到）。一条解答用到 0/1/多个技巧；技巧 = teaching_methods。"""

    __tablename__ = "solution_technique_links"
    __table_args__ = (
        UniqueConstraint("solution_id", "method_id", name="uq_solution_technique_link"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    solution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("solutions.id"), index=True)
    method_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teaching_methods.id"), index=True)
    # primary | auxiliary
    relation_type: Mapped[str] = mapped_column(String(80), default="primary", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evidence_snippets.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


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
