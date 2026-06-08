from __future__ import annotations

import re
from dataclasses import dataclass

from mathscout.extraction.schemas import EvidenceRef, ExtractedProblem, ExtractedSolution
from mathscout.utils.text import compact_lines, normalize_semantic_key

# 题目起始标记：例N / 【例N】/ 第N题 / 题N / "N." / "N、"
PROBLEM_START = re.compile(r"^(?:【?\s*例\s*\d+\s*】?|第\s*\d+\s*题|题\s*\d+|\d+\s*[.、)）])\s*")
# 解答起始标记：多字标记（解答/解析/证明/略解/答案）冒号可选；单字（解/证/答）必须带冒号，
# 以免把"解方程""证书"等误判为解答。
SOLUTION_MARKER = re.compile(
    r"^(?:【?\s*解析\s*】?|解答|证明|略解|答案)\s*[:：]?\s*|^(?:解|证|答)\s*[:：]\s*"
)
# 多解标记：解法一/方法二…
APPROACH_MARKER = re.compile(
    r"^(解法\s*[一二三四五六七八九十0-9]+|方法\s*[一二三四五六七八九十0-9]+)\s*[:：]?\s*"
)
# 最终答案：答案：X / 答：X
ANSWER_MARKER = re.compile(r"^(?:答案|答)\s*[:：]\s*(.+)$")


@dataclass(frozen=True)
class RuleBasedProblemResult:
    problems: list[ExtractedProblem]


class RuleBasedProblemExtractor:
    """从清洗后的文本中按标记切分题目与解答（规则版，置信度较低，作为离线基线）。

    AI 版抽取器（Phase C 后续切片）输出同一 `ExtractedProblem` 契约，可与本类互换。
    """

    def extract(self, text: str, document_url: str | None = None) -> RuleBasedProblemResult:
        lines = compact_lines(text)
        problems: list[ExtractedProblem] = []
        source_type = self._source_type(text, document_url)
        for block in self._split_blocks(lines):
            stem_lines, solution_lines = self._split_stem_and_solution(block)
            stem = " ".join(stem_lines).strip()
            if len(stem) < 6:  # 太短，多半是噪声而非真正的题
                continue
            solutions = self._build_solutions(solution_lines)
            problems.append(
                ExtractedProblem(
                    stem=stem,
                    problem_type=self._problem_type(stem),
                    source_type=source_type,
                    has_answer=bool(solution_lines),
                    semantic_key=normalize_semantic_key(stem),
                    solutions=solutions,
                    evidence=[
                        EvidenceRef(
                            document_url=document_url, snippet=stem[:500], confidence=0.45
                        )
                    ],
                    confidence=0.4,
                )
            )
        return RuleBasedProblemResult(problems=problems)

    # ------------------------------------------------------------------ #

    def _split_blocks(self, lines: list[str]) -> list[list[str]]:
        """按题目起始标记把文本切成若干题块；首个标记之前的导言丢弃。"""
        blocks: list[list[str]] = []
        current: list[str] | None = None
        for line in lines:
            if PROBLEM_START.match(line):
                if current is not None:
                    blocks.append(current)
                current = [PROBLEM_START.sub("", line, count=1).strip()]
            elif current is not None:
                current.append(line)
        if current is not None:
            blocks.append(current)
        return blocks

    def _split_stem_and_solution(self, block: list[str]) -> tuple[list[str], list[str]]:
        for index, line in enumerate(block):
            if SOLUTION_MARKER.match(line):
                first = SOLUTION_MARKER.sub("", line, count=1).strip()
                rest = [first, *block[index + 1 :]] if first else block[index + 1 :]
                return block[:index], rest
            if APPROACH_MARKER.match(line):
                # 直接以"解法一"开头、无"解："前缀：解答区从此开始，保留标记行供多解切分。
                return block[:index], block[index:]
        return block, []

    def _build_solutions(self, solution_lines: list[str]) -> list[ExtractedSolution]:
        if not solution_lines:
            return []
        groups = self._split_by_approach(solution_lines)
        solutions: list[ExtractedSolution] = []
        for label, body in groups:
            steps = [line for line in body if line]
            if not steps:
                continue
            solutions.append(
                ExtractedSolution(
                    approach_label=label,
                    steps=steps,
                    final_answer=self._final_answer(steps),
                    confidence=0.4,
                )
            )
        return solutions

    @staticmethod
    def _split_by_approach(lines: list[str]) -> list[tuple[str | None, list[str]]]:
        groups: list[tuple[str | None, list[str]]] = []
        label: str | None = None
        body: list[str] = []
        for line in lines:
            match = APPROACH_MARKER.match(line)
            if match:
                if body:
                    groups.append((label, body))
                label = match.group(1).strip()
                remainder = APPROACH_MARKER.sub("", line, count=1).strip()
                body = [remainder] if remainder else []
            else:
                body.append(line)
        if body or label is not None:
            groups.append((label, body))
        return groups or [(None, lines)]

    @staticmethod
    def _final_answer(steps: list[str]) -> str | None:
        for line in steps:
            match = ANSWER_MARKER.match(line)
            if match:
                return match.group(1).strip()
        return None

    @staticmethod
    def _problem_type(stem: str) -> str:
        if "求证" in stem or "证明" in stem:
            return "证明"
        if "下列" in stem or "选项" in stem:
            return "选择"
        if "填空" in stem or "____" in stem or "＿" in stem:
            return "填空"
        return "解答"

    @staticmethod
    def _source_type(text: str, document_url: str | None) -> str | None:
        haystack = f"{text[:2000]} {document_url or ''}"
        if any(k in haystack for k in ("试卷", "中考", "期末", "期中", "月考", "模拟")):
            return "试卷"
        if any(k in haystack for k in ("教案", "课件", "学案", "教学设计")):
            return "课堂"
        if "题库" in haystack:
            return "题库"
        return None
