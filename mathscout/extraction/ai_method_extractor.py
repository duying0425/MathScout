from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError

from mathscout.ai.openai_compatible import ChatMessage, OpenAICompatibleClient
from mathscout.config import Settings, get_settings
from mathscout.extraction.schemas import CandidateKnowledgeItemSchema, EvidenceRef
from mathscout.utils.text import normalize_semantic_key


class AIMethodItem(BaseModel):
    title: str
    method_type: str = "解题技巧"
    summary: str
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
    source_teacher: str | None = None
    source_org: str | None = None
    source_region: str | None = None
    evidence_snippet: str
    confidence: float = Field(ge=0.0, le=1.0)


class AIMethodExtractionPayload(BaseModel):
    methods: list[AIMethodItem] = Field(default_factory=list)


class AIMethodExtractor:
    def __init__(
        self,
        client: OpenAICompatibleClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client or OpenAICompatibleClient(self.settings)

    def extract(
        self,
        text: str,
        document_url: str | None = None,
    ) -> list[CandidateKnowledgeItemSchema]:
        clipped_text = text[: self.settings.ai_max_text_chars]
        response = self.client.chat_json(
            [
                ChatMessage(
                    role="system",
                    content=(
                        "你是初中数学教研资料抽取助手。只抽取教师给出的解题技巧、"
                        "教学方法、易错提醒、模型套路、辅助线方法。不要抽取普通知识点目录。"
                        "输出必须是 JSON object，格式为 {\"methods\": [...]}。"
                    ),
                ),
                ChatMessage(
                    role="user",
                    content=(
                        "从下面文本中抽取教师解题技巧，并尽量映射到教材章节/知识点。"
                        "每条 method 字段：title, method_type, summary, steps, "
                        "applicable_patterns, prerequisites, common_misconceptions, "
                        "classroom_warnings, example_patterns, textbook_series, book_code, "
                        "chapter_title, section_title, knowledge_point_titles, skill_codes, "
                        "source_teacher, source_org, source_region, "
                        "evidence_snippet, confidence。\n\n"
                        f"来源 URL: {document_url or ''}\n\n文本:\n{clipped_text}"
                    ),
                ),
            ]
        )
        try:
            payload = AIMethodExtractionPayload.model_validate(response)
        except ValidationError as exc:
            raise ValueError(f"AI extraction response schema mismatch: {exc}") from exc

        candidates: list[CandidateKnowledgeItemSchema] = []
        for item in payload.methods:
            semantic_key = normalize_semantic_key(item.title)
            candidates.append(
                CandidateKnowledgeItemSchema(
                    item_type="teaching_method",
                    title=item.title,
                    semantic_key=semantic_key,
                    textbook_series=item.textbook_series,
                    book_code=item.book_code,
                    chapter_title=item.chapter_title,
                    section_title=item.section_title,
                    payload={
                        "summary": item.summary,
                        "method_type": item.method_type,
                        "steps": item.steps,
                        "applicable_patterns": item.applicable_patterns,
                        "prerequisites": item.prerequisites,
                        "common_misconceptions": item.common_misconceptions,
                        "classroom_warnings": item.classroom_warnings,
                        "example_patterns": item.example_patterns,
                        "knowledge_point_titles": item.knowledge_point_titles,
                        "skill_codes": item.skill_codes,
                        "source_teacher": item.source_teacher,
                        "source_org": item.source_org,
                        "source_region": item.source_region,
                        "extractor": "ai_method_extractor_v0",
                    },
                    evidence=[
                        EvidenceRef(
                            document_url=document_url,
                            snippet=item.evidence_snippet[:500],
                            confidence=item.confidence,
                        )
                    ],
                    confidence=item.confidence,
                )
            )
        return candidates
