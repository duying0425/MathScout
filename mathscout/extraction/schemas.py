from typing import Literal

from pydantic import BaseModel, Field


class EvidenceRef(BaseModel):
    document_url: str | None = None
    snippet: str | None = Field(default=None, max_length=500)
    page_number: int | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractedKnowledgePoint(BaseModel):
    title: str
    description: str | None = None
    textbook_series: str | None = None
    book_code: str | None = None
    chapter_title: str | None = None
    section_title: str | None = None
    skill_codes: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractedTeachingMethod(BaseModel):
    title: str
    method_type: str
    summary: str
    source_teacher: str | None = None
    source_org: str | None = None
    source_region: str | None = None
    explanation_style: str | None = None
    steps: list[str] = Field(default_factory=list)
    applicable_patterns: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    common_misconceptions: list[str] = Field(default_factory=list)
    classroom_warnings: list[str] = Field(default_factory=list)
    example_patterns: list[str] = Field(default_factory=list)
    textbook_series: str | None = None
    book_code: str | None = None
    chapter_title: str | None = None
    section_title: str | None = None
    knowledge_point_titles: list[str] = Field(default_factory=list)
    skill_codes: list[str] = Field(default_factory=list)
    course_alignment_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractedRegionAdoption(BaseModel):
    province: str
    city: str | None = None
    district: str | None = None
    school_name: str | None = None
    textbook_series: str
    grade: int | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


CandidateItemType = Literal[
    "knowledge_point",
    "teaching_method",
    "teaching_method_variant",
    "student_skill",
    "region_adoption",
    "textbook_structure",
]

ReconciliationAction = Literal["skip", "update", "create_variant", "create", "conflict", "review"]


class CandidateKnowledgeItemSchema(BaseModel):
    item_type: CandidateItemType
    title: str
    semantic_key: str | None = None
    textbook_series: str | None = None
    book_code: str | None = None
    chapter_title: str | None = None
    section_title: str | None = None
    payload: dict = Field(default_factory=dict)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class CandidateMatchSchema(BaseModel):
    table: str
    record_id: str
    title: str
    match_reason: str
    similarity: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)


class ReconciliationDecisionSchema(BaseModel):
    candidate: CandidateKnowledgeItemSchema
    action: ReconciliationAction
    matched_records: list[CandidateMatchSchema] = Field(default_factory=list)
    rationale: str
    proposed_patch: dict = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    requires_human_review: bool = True
