from __future__ import annotations

from dataclasses import dataclass

from mathscout.extraction.schemas import CandidateKnowledgeItemSchema, EvidenceRef
from mathscout.utils.text import compact_lines, normalize_semantic_key

METHOD_KEYWORDS = (
    "解题技巧",
    "解题方法",
    "解法",
    "方法",
    "技巧",
    "口诀",
    "模型",
    "思路",
    "突破",
    "辅助线",
    "分类讨论",
    "数形结合",
    "易错",
    "注意",
    "归纳",
    "转化",
)


@dataclass(frozen=True)
class RuleBasedExtractionResult:
    candidates: list[CandidateKnowledgeItemSchema]


class RuleBasedMethodExtractor:
    def extract(self, text: str, document_url: str | None = None) -> RuleBasedExtractionResult:
        candidates: list[CandidateKnowledgeItemSchema] = []
        seen_keys: set[str] = set()
        for line in compact_lines(text):
            if not self._looks_like_method(line):
                continue
            title = self._title_from_line(line)
            semantic_key = normalize_semantic_key(title)
            if semantic_key in seen_keys:
                continue
            seen_keys.add(semantic_key)
            candidates.append(
                CandidateKnowledgeItemSchema(
                    item_type="teaching_method",
                    title=title,
                    semantic_key=semantic_key,
                    payload={
                        "summary": line,
                        "method_type": self._method_type(line),
                        "steps": [line],
                        "applicable_patterns": self._patterns(line),
                        "extractor": "rule_based_v0",
                    },
                    evidence=[
                        EvidenceRef(
                            document_url=document_url,
                            snippet=line[:500],
                            confidence=0.55,
                        )
                    ],
                    confidence=0.5,
                )
            )
        return RuleBasedExtractionResult(candidates=candidates)

    @staticmethod
    def _looks_like_method(line: str) -> bool:
        if len(line) < 8 or len(line) > 260:
            return False
        return any(keyword in line for keyword in METHOD_KEYWORDS)

    @staticmethod
    def _title_from_line(line: str) -> str:
        for separator in ("：", ":", "。", "；", ";"):
            if separator in line:
                prefix = line.split(separator, 1)[0].strip()
                if 4 <= len(prefix) <= 40:
                    return prefix
        return line[:40].strip()

    @staticmethod
    def _method_type(line: str) -> str:
        if "辅助线" in line:
            return "几何辅助线"
        if "易错" in line or "注意" in line:
            return "易错提醒"
        if "模型" in line:
            return "模型方法"
        if "口诀" in line:
            return "记忆口诀"
        return "解题技巧"

    @staticmethod
    def _patterns(line: str) -> list[str]:
        patterns = []
        for marker in ("应用题", "证明题", "计算题", "压轴题", "几何题", "函数题"):
            if marker in line:
                patterns.append(marker)
        return patterns
