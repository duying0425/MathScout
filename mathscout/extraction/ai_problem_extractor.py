from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError

from mathscout.ai.openai_compatible import ChatMessage, OpenAICompatibleClient
from mathscout.config import Settings, get_settings
from mathscout.extraction.schemas import EvidenceRef, ExtractedProblem, ExtractedSolution
from mathscout.utils.text import normalize_semantic_key

SYSTEM_PROMPT = "\n".join(
    [
        "你是 MathScout 的初中数学题目抽取 Agent。",
        "",
        "任务：从公开网页、试卷、教辅或教研材料中抽取【题目】及其【解答】。",
        "",
        "硬性规则：",
        "1. 只抽取输入文本中确有的题目，不得编造题干、答案、章节或知识点。",
        "2. 数学式子保留 LaTeX 写法（$...$ / $$...$$），不要改写或求值。",
        "3. 把【题干】与【解答】分开：题干放 stem，解题过程放对应 solution。",
        "4. 一题多解时，每种思路是一个独立 solution（用 approach_label 标注思路名）。",
        "5. knowledge_point_titles 是该题【考察】的知识点（出题设计意图），不确定就留空，"
        "不要硬凑——这些标注会交人工复核。",
        "6. technique_titles 是解答用到的【可复用解题技巧/模型】（如将军饮马、手拉手），"
        "不是这道题的一次性步骤；没有明确可复用模型就留空。",
        "7. 输出必须是 JSON object，严格为 {\"problems\": [...]}。",
        "8. 不要输出 Markdown、解释文字或代码块；字段名用英文 schema 名，内容尽量用中文。",
    ]
)

USER_PROMPT_TEMPLATE = "\n".join(
    [
        "请从下面的资料中抽取题目与解答。",
        "",
        "每个 problems 元素的字段：",
        "- stem: 题干（保留 LaTeX）。",
        "- problem_type: 题型，如“选择”“填空”“解答”“证明”；不确定则 null。",
        "- difficulty: 难度，如“基础”“中等”“难”；不确定则 null。",
        "- source_type: 来源类别，如“课堂”“试卷”“教辅”“题库”；不确定则 null。",
        "- has_answer: 资料是否给出解答/答案，true 或 false。",
        "- knowledge_point_titles: 考察的知识点标题列表；不确定留空。",
        "- textbook_series/book_code/chapter_title/section_title: 文本明确支持时填，否则 null。",
        "- solutions: 解答列表，每个含 approach_label、steps（分步，保留 LaTeX）、",
        "  final_answer、complexity、technique_titles、source_teacher/source_org/source_region。",
        "- evidence_snippet: 支撑该题的短证据片段。",
        "- confidence: 0 到 1 的置信度；靠推断的字段要降低。",
        "",
        "不要抽取：目录、导航、广告、版权声明，以及没有题干的内容。",
        "",
        "来源 URL: {document_url}",
        "",
        "资料文本:",
        "{text}",
    ]
)


class AISolutionItem(BaseModel):
    approach_label: str | None = None
    steps: list[str] = Field(default_factory=list)
    final_answer: str | None = None
    complexity: str | None = None
    technique_titles: list[str] = Field(default_factory=list)
    source_teacher: str | None = None
    source_org: str | None = None
    source_region: str | None = None


class AIProblemItem(BaseModel):
    stem: str
    problem_type: str | None = None
    difficulty: str | None = None
    source_type: str | None = None
    has_answer: bool = False
    knowledge_point_titles: list[str] = Field(default_factory=list)
    textbook_series: str | None = None
    book_code: str | None = None
    chapter_title: str | None = None
    section_title: str | None = None
    solutions: list[AISolutionItem] = Field(default_factory=list)
    evidence_snippet: str = ""
    confidence: float = Field(ge=0.0, le=1.0)


class AIProblemExtractionPayload(BaseModel):
    problems: list[AIProblemItem] = Field(default_factory=list)


class AIProblemExtractor:
    """DeepSeek / OpenAI 兼容的【文本版】题目抽取器。

    产出与规则版相同的 `ExtractedProblem` 契约，可在编排入口与规则版互换。
    纯文本通道：不读图，故 figures 留空（图片附件由规则抽取器的确定性解析负责）。
    """

    def __init__(
        self,
        client: OpenAICompatibleClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client or OpenAICompatibleClient(self.settings)

    def extract(self, text: str, document_url: str | None = None) -> list[ExtractedProblem]:
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
            payload = AIProblemExtractionPayload.model_validate(response)
        except ValidationError as exc:
            raise ValueError(f"AI 题目抽取结果不符合 schema: {exc}") from exc

        return [self._to_contract(item, document_url) for item in payload.problems]

    @staticmethod
    def _to_contract(item: AIProblemItem, document_url: str | None) -> ExtractedProblem:
        solutions = [
            ExtractedSolution(
                approach_label=solution.approach_label,
                steps=solution.steps,
                final_answer=solution.final_answer,
                complexity=solution.complexity,
                technique_titles=solution.technique_titles,
                source_teacher=solution.source_teacher,
                source_org=solution.source_org,
                source_region=solution.source_region,
                figures=[],
                confidence=item.confidence,
            )
            for solution in item.solutions
        ]
        return ExtractedProblem(
            stem=item.stem,
            problem_type=item.problem_type,
            difficulty=item.difficulty,
            source_type=item.source_type,
            has_answer=item.has_answer or bool(item.solutions),
            semantic_key=normalize_semantic_key(item.stem),
            knowledge_point_titles=item.knowledge_point_titles,
            textbook_series=item.textbook_series,
            book_code=item.book_code,
            chapter_title=item.chapter_title,
            section_title=item.section_title,
            solutions=solutions,
            figures=[],
            evidence=[
                EvidenceRef(
                    document_url=document_url,
                    snippet=(item.evidence_snippet or item.stem)[:500],
                    confidence=item.confidence,
                )
            ],
            confidence=item.confidence,
        )
