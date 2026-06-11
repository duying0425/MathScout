from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError

from mathscout.ai.openai_compatible import ChatMessage, OpenAICompatibleClient
from mathscout.config import Settings, get_settings
from mathscout.extraction.schemas import EvidenceRef, ExtractedKnowledgePoint

SYSTEM_PROMPT = "\n".join(
    [
        "你是 MathScout 的初中数学知识点抽取 Agent。",
        "",
        "任务：从教学指南、教师用书、教案、教材目录或公开教研材料中，",
        "识别并总结学生应当掌握的【知识点】（概念、性质、法则、公式、定义）。",
        "",
        "硬性规则：",
        "1. 只抽取输入文本中确有依据的知识点，不得编造概念、章节或版本。",
        "2. 知识点是学生要掌握的【概念/方法本身】，不是某道题的解答，也不是教师的讲课技巧。",
        "3. title 要短而规范（如“绝对值的意义”“一元一次方程的解法”），便于跨版本对齐去重。",
        "4. description 用自己的话简述该知识点，不要照抄长段原文。",
        "5. 能从文本判断教材版本/册/章/节时填上，不确定就留 null。",
        "6. evidence_snippet 必须短，只引用能支撑该知识点的关键片段。",
        "7. 输出必须是 JSON object，严格为 {\"knowledge_points\": [...]}。",
        "8. 不要输出 Markdown、解释文字或代码块；字段名用英文 schema 名，内容尽量用中文。",
    ]
)

USER_PROMPT_TEMPLATE = "\n".join(
    [
        "请从下面的资料中抽取学生应掌握的知识点。",
        "",
        "每个 knowledge_points 元素的字段：",
        "- title: 知识点标题，短而规范。",
        "- description: 知识点简述；不确定则 null。",
        "- textbook_series/book_code/chapter_title/section_title: 文本明确支持时填，否则 null。",
        "- skill_codes: 相关学生能力编码（如 S05），无法判断则空列表。",
        "- evidence_snippet: 支撑该知识点的短证据片段。",
        "- confidence: 0 到 1 的置信度；靠推断的字段要降低。",
        "",
        "不要抽取：目录导航、广告、版权声明，以及教师解题技巧或具体题目解答。",
        "",
        "来源 URL: {document_url}",
        "",
        "资料文本:",
        "{text}",
    ]
)


class AIKnowledgeItem(BaseModel):
    title: str
    description: str | None = None
    textbook_series: str | None = None
    book_code: str | None = None
    chapter_title: str | None = None
    section_title: str | None = None
    skill_codes: list[str] = Field(default_factory=list)
    evidence_snippet: str = ""
    confidence: float = Field(ge=0.0, le=1.0)


class AIKnowledgeExtractionPayload(BaseModel):
    knowledge_points: list[AIKnowledgeItem] = Field(default_factory=list)


class AIKnowledgeExtractor:
    """DeepSeek / OpenAI 兼容的知识点抽取器，产出 `ExtractedKnowledgePoint` 契约。

    可与（未来的）规则版互换；离线测试时注入 stub client。
    """

    def __init__(
        self,
        client: OpenAICompatibleClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client or OpenAICompatibleClient(self.settings)

    def extract(
        self, text: str, document_url: str | None = None
    ) -> list[ExtractedKnowledgePoint]:
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
            payload = AIKnowledgeExtractionPayload.model_validate(response)
        except ValidationError as exc:
            raise ValueError(f"AI 知识点抽取结果不符合 schema: {exc}") from exc

        return [self._to_contract(item, document_url) for item in payload.knowledge_points]

    @staticmethod
    def _to_contract(
        item: AIKnowledgeItem, document_url: str | None
    ) -> ExtractedKnowledgePoint:
        return ExtractedKnowledgePoint(
            title=item.title,
            description=item.description,
            textbook_series=item.textbook_series,
            book_code=item.book_code,
            chapter_title=item.chapter_title,
            section_title=item.section_title,
            skill_codes=item.skill_codes,
            evidence=[
                EvidenceRef(
                    document_url=document_url,
                    snippet=(item.evidence_snippet or item.title)[:500],
                    confidence=item.confidence,
                )
            ],
            confidence=item.confidence,
        )
