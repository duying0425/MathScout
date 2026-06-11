"""AI 文本版题目抽取器：用桩 client 验证契约映射与回退，不触网。"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mathscout.config import get_settings
from mathscout.db.base import Base
from mathscout.db.models import SourceDocument
from mathscout.extraction.ai_problem_extractor import AIProblemExtractor
from mathscout.utils.text import normalize_semantic_key


class _StubClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def chat_json(self, messages, **kwargs) -> dict:
        return self.payload


def test_maps_ai_payload_to_extracted_problem_contract():
    stem = r"已知 $a=3,b=4$，求斜边 $c$。"
    payload = {
        "problems": [
            {
                "stem": stem,
                "problem_type": "解答",
                "has_answer": True,
                "knowledge_point_titles": ["勾股定理"],
                "book_code": "G8A",
                "section_title": "探索勾股定理",
                "solutions": [
                    {
                        "approach_label": "勾股定理直接计算",
                        "steps": [r"$c=\sqrt{9+16}=5$"],
                        "final_answer": "5",
                        "technique_titles": ["勾股定理"],
                    },
                    {"approach_label": "构造法", "steps": ["作辅助线"], "technique_titles": []},
                ],
                "evidence_snippet": "已知 a=3,b=4",
                "confidence": 0.8,
            }
        ]
    }
    extractor = AIProblemExtractor(client=_StubClient(payload), settings=get_settings())

    problems = extractor.extract("原始文本", "http://x")

    assert len(problems) == 1
    problem = problems[0]
    assert problem.stem == stem
    assert problem.has_answer is True
    assert problem.semantic_key == normalize_semantic_key(stem)
    assert problem.knowledge_point_titles == ["勾股定理"]
    assert problem.book_code == "G8A"
    assert len(problem.solutions) == 2
    assert problem.solutions[0].technique_titles == ["勾股定理"]
    assert problem.solutions[0].final_answer == "5"
    assert problem.figures == []  # 文本通道不读图
    assert problem.evidence[0].snippet.startswith("已知")
    assert problem.confidence == 0.8


def test_raises_value_error_on_bad_schema():
    extractor = AIProblemExtractor(
        client=_StubClient({"problems": [{"problem_type": "解答", "confidence": 0.5}]}),
        settings=get_settings(),
    )
    with pytest.raises(ValueError):  # 缺 stem → schema 校验失败
        extractor.extract("文本", None)


def test_auto_falls_back_to_rule_when_ai_fails(monkeypatch):
    from mathscout.pipeline import problem_extract as pe

    monkeypatch.setattr(pe, "_use_ai", lambda mode, settings: True)

    class _Boom:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def extract(self, *args, **kwargs):
            raise RuntimeError("ai down")

    monkeypatch.setattr(pe, "AIProblemExtractor", _Boom)

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    document = SourceDocument(url="http://x")
    session.add(document)
    session.flush()

    text = "例1 求 $1+1$ 的值。\n解：$1+1=2$。\n答案：2\n"
    stats = pe.extract_and_reconcile_problems(session, document, text)  # auto 模式

    assert stats["problems"] >= 1  # AI 抛错后回退规则版，仍产出题目
    session.close()
