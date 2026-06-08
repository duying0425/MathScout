from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError

from mathscout.ai.openai_compatible import ChatMessage, OpenAICompatibleClient
from mathscout.config import Settings, get_settings
from mathscout.extraction.schemas import CandidateKnowledgeItemSchema, EvidenceRef
from mathscout.utils.text import normalize_semantic_key

SYSTEM_PROMPT = "\n".join(
    [
        "你是 MathScout 的初中数学教研资料抽取 Agent。",
        "",
        "你的任务是从公开网页、PDF 或教研材料中抽取教师可复用的方法。",
        "重点包括：解题方法、教学方法、易错提醒、建模套路、",
        "几何辅助线策略、课堂讲解路径。",
        "",
        "硬性规则：",
        "1. 只抽取输入文本中有证据支持的内容。",
        "2. 不得编造教材版本、章节、教师、地区、学校或方法。",
        "3. 不要把普通知识点目录当作教学方法。",
        "4. 只有包含讲解路径、解题策略、课堂提醒、例题模式或方法步骤时才抽取。",
        "5. 同一知识点下的不同讲法、辅助线、分类规则、直观模型要保留差异。",
        "6. evidence_snippet 必须短，只引用能支撑该方法的关键片段。",
        "7. 不要整段复制原文。",
        "8. 输出必须是 JSON object，格式严格为 {\"methods\": [...]}。",
        "9. 不要输出 Markdown、解释文字或代码块。",
        "10. JSON 字段名必须使用英文 schema 字段名，字段内容尽量使用中文。",
        "11. 解题技巧/模型是【跨题复用】的抽象方法（如将军饮马、手拉手模型、数形结合），"
        "而非某一道题的完整解答。要抽取可迁移到同类题的方法本身，不要为每道题各造一个技巧。",
    ]
)

USER_PROMPT_TEMPLATE = "\n".join(
    [
        "请从下面的资料中抽取教师解题方法和教学方法。",
        "并尽量映射到教材版本、册别、章节、小节和知识点。",
        "",
        "每个 methods 元素必须包含这些字段：",
        "- title: 方法标题，中文，短而具体。",
        "- method_type: 例如“解题技巧”“教学方法”“易错提醒”。“解题技巧”应是可复用的"
        "解题模型/套路（跨题适用），不是某道题的一次性解答。",
        "- summary: 方法摘要，用自己的话概括，不要照抄长段原文。",
        "- steps: 方法步骤，列表。",
        "- applicable_patterns: 适用题型或课堂场景，列表。",
        "- prerequisites: 前置知识或能力，列表。",
        "- common_misconceptions: 常见误区，列表。",
        "- classroom_warnings: 课堂提醒，列表。",
        "- example_patterns: 例题模式，列表。",
        "- textbook_series: 文本明确支持的教材版本；不确定则为 null。",
        "- book_code: 例如 G7A/G7B；不确定则为 null。",
        "- chapter_title: 文本明确支持的章节；不确定则为 null。",
        "- section_title: 文本明确支持的小节；不确定则为 null。",
        "- knowledge_point_titles: 相关知识点标题，列表。",
        "- skill_codes: 学生能力编码，无法判断则空列表。",
        "- source_teacher: 文本明确出现的教师姓名；不确定则为 null。",
        "- source_org: 文本明确出现的学校或机构；不确定则为 null。",
        "- source_region: 文本明确出现的地区；不确定则为 null。",
        "- evidence_snippet: 支撑该方法的短证据片段。",
        "- confidence: 0 到 1 的置信度；章节映射靠推断时要降低。",
        "",
        "不要抽取：",
        "- 只有目录、导航、广告、下载按钮、版权声明的内容。",
        "- 没有教师方法价值的普通知识点罗列。",
        "- 不能被文本证据支持的章节、地区或教师信息。",
        "",
        "来源 URL: {document_url}",
        "",
        "资料文本:",
        "{text}",
    ]
)


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
                ChatMessage(role="system", content=SYSTEM_PROMPT),
                ChatMessage(
                    role="user",
                    content=USER_PROMPT_TEMPLATE.format(
                        document_url=document_url or "",
                        text=clipped_text,
                    ),
                ),
            ]
        )
        try:
            payload = AIMethodExtractionPayload.model_validate(response)
        except ValidationError as exc:
            raise ValueError(f"AI 抽取结果不符合 schema: {exc}") from exc

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
                        "extractor": "ai_method_extractor_v1",
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
