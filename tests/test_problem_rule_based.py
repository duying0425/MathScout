from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from mathscout.db.base import Base
from mathscout.db.models import Problem, Solution, SourceDocument
from mathscout.extraction.problem_rule_based import RuleBasedProblemExtractor
from mathscout.pipeline.problem_extract import extract_and_reconcile_problems

SAMPLE = """
七年级数学期末试卷

例1 计算：(-3)+5。
解：原式 = 2。
答案：2

例2 已知 a=3，b=4，求证 a^2+b^2=25。
证明：因为 a^2+b^2=9+16=25，所以成立。

2. 解方程 x+1=3。
解法一：移项得 x=2。
解法二：两边同时减1，得 x=2。
答：x=2
"""


def test_rule_extractor_parses_stems_solutions_and_answers():
    problems = RuleBasedProblemExtractor().extract(SAMPLE, "https://example.com/exam").problems

    assert len(problems) == 3

    first, second, third = problems

    # 例1：计算题，解答带最终答案
    assert first.stem == "计算：(-3)+5。"
    assert first.problem_type == "解答"
    assert first.has_answer is True
    assert first.source_type == "试卷"  # 文中含"试卷"
    assert len(first.solutions) == 1
    assert first.solutions[0].final_answer == "2"

    # 例2：证明题
    assert second.stem.startswith("已知")
    assert second.problem_type == "证明"
    assert len(second.solutions) == 1

    # 第3题：一题多解
    assert third.stem == "解方程 x+1=3。"
    assert [s.approach_label for s in third.solutions] == ["解法一", "解法二"]
    assert third.solutions[1].final_answer == "x=2"


def test_does_not_split_on_solve_keyword_without_colon():
    # "解方程"不应被当成解答标记，整句应留在题干
    problems = RuleBasedProblemExtractor().extract("例1 解方程 2x=4。", None).problems
    assert len(problems) == 1
    assert problems[0].stem == "解方程 2x=4。"
    assert problems[0].has_answer is False
    assert problems[0].solutions == []


def test_extract_and_reconcile_end_to_end():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()

    document = SourceDocument(url="https://example.com/exam")
    session.add(document)
    session.flush()

    stats = extract_and_reconcile_problems(session, document, SAMPLE)

    assert stats["problems"] == 3
    assert stats["solutions"] == 4  # 1 + 1 + 2
    assert session.scalar(select(func.count()).select_from(Problem)) == 3
    assert session.scalar(select(func.count()).select_from(Solution)) == 4
    # 来源类别已识别
    assert session.scalar(select(Problem.source_type).limit(1)) == "试卷"
    session.close()
