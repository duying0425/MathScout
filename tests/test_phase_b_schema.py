"""Phase B：题目/解答事实层 schema 烟雾测试。

只验证新表能被 create_all 建出、外键自洽、基本关系可用——不涉及抓取/抽取/UI（Phase C）。
"""

from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker

from mathscout.db.base import Base
from mathscout.db.models import (
    Book,
    Chapter,
    Figure,
    KnowledgePoint,
    Problem,
    ProblemKnowledgePointLink,
    ProblemSectionLink,
    Section,
    Solution,
    SolutionTechniqueLink,
    TeachingMethod,
    TextbookSeries,
)


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)()


def test_new_fact_layer_tables_are_created():
    engine, session = _session()
    tables = set(inspect(engine).get_table_names())
    assert {
        "problems",
        "solutions",
        "figures",
        "problem_knowledge_point_links",
        "problem_section_links",
        "solution_technique_links",
    } <= tables
    session.close()


def test_problem_solution_technique_graph_persists():
    _, session = _session()

    # 教材结构（仅为 problem_section_links 的小节外键铺路）
    series = TextbookSeries(name="北师大版初中数学")
    session.add(series)
    session.flush()
    book = Book(series_id=series.id, book_code="G8A", grade=8, semester="A", label="八年级上册")
    session.add(book)
    session.flush()
    chapter = Chapter(book_id=book.id, chapter_code="G8A-C1", title="勾股定理")
    session.add(chapter)
    session.flush()
    section = Section(chapter_id=chapter.id, section_code="G8A-C1-S1", title="探索勾股定理")
    session.add(section)

    knowledge_point = KnowledgePoint(title="勾股定理", semantic_key="勾股定理")
    technique = TeachingMethod(
        title="将军饮马模型", method_type="解题技巧", summary="对称求最短路径"
    )
    session.add_all([section, knowledge_point, technique])
    session.flush()

    problem = Problem(
        stem=r"$\angle C=90^\circ$，$a=3,b=4$，求斜边 $c$。",
        problem_type="解答",
        source_type="试卷",
        has_answer=True,
        semantic_key="勾股-345",
    )
    session.add(problem)
    session.flush()

    solution = Solution(
        problem_id=problem.id,
        approach_label="勾股定理直接计算",
        steps=[r"$c=\sqrt{a^2+b^2}$", r"$c=\sqrt{9+16}=5$"],
        final_answer="5",
    )
    session.add(solution)
    session.flush()

    session.add_all(
        [
            Figure(
                owner_type="problem",
                owner_id=problem.id,
                figure_kind="tikz",
                origin="ai_generated",
            ),
            ProblemKnowledgePointLink(
                problem_id=problem.id,
                knowledge_point_id=knowledge_point.id,
                relation_type="primary",
            ),
            ProblemSectionLink(
                problem_id=problem.id, section_id=section.id, relation_type="exercise_of"
            ),
            SolutionTechniqueLink(
                solution_id=solution.id, method_id=technique.id, relation_type="primary"
            ),
        ]
    )
    session.commit()

    # 关系：一题多解 + 解答回指题目
    assert [s.id for s in problem.solutions] == [solution.id]
    assert solution.problem.id == problem.id

    # 三种链接都落库
    assert session.scalar(
        select(ProblemKnowledgePointLink).where(ProblemKnowledgePointLink.problem_id == problem.id)
    ).knowledge_point_id == knowledge_point.id
    assert session.scalar(
        select(ProblemSectionLink).where(ProblemSectionLink.problem_id == problem.id)
    ).section_id == section.id
    assert session.scalar(
        select(SolutionTechniqueLink).where(SolutionTechniqueLink.solution_id == solution.id)
    ).method_id == technique.id
    assert session.scalar(
        select(Figure).where(Figure.owner_type == "problem", Figure.owner_id == problem.id)
    ).figure_kind == "tikz"
    session.close()
