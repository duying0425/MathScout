from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from mathscout.db.base import Base
from mathscout.db.models import (
    Book,
    CandidateItemType,
    CandidateKnowledgeItem,
    Chapter,
    KnowledgePoint,
    Problem,
    ProblemKnowledgePointLink,
    ProblemSectionLink,
    ReconciliationAction,
    ReconciliationDecision,
    ReviewItem,
    Section,
    Solution,
    SolutionTechniqueLink,
    SourceDocument,
    TeachingMethod,
    TextbookSeries,
)
from mathscout.extraction.schemas import (
    EvidenceRef,
    ExtractedFigure,
    ExtractedProblem,
    ExtractedSolution,
)
from mathscout.pipeline.problem_extract import ProblemReconciler
from mathscout.utils.text import normalize_semantic_key


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _seed(session) -> dict:
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
    knowledge_point = KnowledgePoint(
        title="勾股定理", semantic_key=normalize_semantic_key("勾股定理")
    )
    technique = TeachingMethod(
        title="将军饮马模型",
        method_type="解题技巧",
        summary="对称求最短路径",
        semantic_key=normalize_semantic_key("将军饮马模型"),
    )
    document = SourceDocument(url="https://example.com/exam")
    session.add_all([section, knowledge_point, technique, document])
    session.flush()
    return {"section": section, "kp": knowledge_point, "technique": technique, "document": document}


def _problem(**overrides) -> ExtractedProblem:
    data = dict(
        stem=r"$\angle C=90^\circ$，$a=3,b=4$，求斜边 $c$。",
        problem_type="解答",
        source_type="试卷",
        has_answer=True,
        book_code="G8A",
        chapter_title="勾股定理",
        section_title="探索勾股定理",
        knowledge_point_titles=["勾股定理"],
        solutions=[
            ExtractedSolution(
                approach_label="勾股定理直接计算",
                steps=[r"$c=\sqrt{9+16}=5$"],
                final_answer="5",
                technique_titles=["将军饮马模型"],
                figures=[
                    ExtractedFigure(figure_kind="tikz", origin="ai_generated", confidence=0.7)
                ],
                confidence=0.8,
            )
        ],
        figures=[ExtractedFigure(figure_kind="image", image_path="/x.png")],
        evidence=[EvidenceRef(snippet="勾股定理例题", confidence=0.8)],
        confidence=0.8,
    )
    data.update(overrides)
    return ExtractedProblem(**data)


def test_ingest_creates_canonical_problem_solution_and_links():
    session = _session()
    seed = _seed(session)

    stats = ProblemReconciler(session).ingest([_problem()], seed["document"])

    assert stats["problems"] == 1
    assert stats["solutions"] == 1
    assert stats["figures"] == 2  # 题干 1 + 解答 1
    assert stats["section_links"] == 1
    assert stats["technique_links"] == 1
    assert stats["kp_reviews"] == 1

    problem = session.scalar(select(Problem))
    assert problem.has_answer is True
    assert problem.source_count == 1

    solution = session.scalar(select(Solution))
    assert solution.problem_id == problem.id

    # 题目→小节 弱关联
    section_link = session.scalar(select(ProblemSectionLink))
    assert section_link.section_id == seed["section"].id
    assert section_link.relation_type == "exercise_of"

    # 解答→技巧 用到（链接到既有技巧）
    technique_link = session.scalar(select(SolutionTechniqueLink))
    assert technique_link.method_id == seed["technique"].id

    # 题目→知识点 考察：不自动建链接，而是进复核
    assert session.scalar(select(func.count()).select_from(ProblemKnowledgePointLink)) == 0
    review = session.scalar(
        select(ReviewItem).where(ReviewItem.item_type == "problem_knowledge_point")
    )
    assert review.target_id == problem.id
    assert review.payload["proposed"][0]["matched_knowledge_point_id"] == str(seed["kp"].id)

    # 候选 + 调和决策
    candidate = session.scalar(
        select(CandidateKnowledgeItem).where(
            CandidateKnowledgeItem.item_type == CandidateItemType.problem
        )
    )
    assert candidate is not None
    decision = session.scalar(select(ReconciliationDecision))
    assert decision.action == ReconciliationAction.create
    assert decision.matched_table == "problems"


def test_ingest_dedupes_problem_and_ignores_unknown_technique():
    session = _session()
    seed = _seed(session)
    reconciler = ProblemReconciler(session)

    reconciler.ingest([_problem()], seed["document"])
    # 第二次：同题（同 semantic_key），且解答引用不存在的技巧
    second = _problem(
        solutions=[
            ExtractedSolution(
                approach_label="勾股定理直接计算",
                steps=[r"$c=\sqrt{9+16}=5$"],
                technique_titles=["不存在的技巧模型"],
                confidence=0.8,
            )
        ]
    )
    reconciler.ingest([second], seed["document"])

    # 题目去重为一条，source_count 累加
    assert session.scalar(select(func.count()).select_from(Problem)) == 1
    problem = session.scalar(select(Problem))
    assert problem.source_count == 2

    # 同思路解答不重复创建
    assert session.scalar(select(func.count()).select_from(Solution)) == 1

    # 不存在的技巧不新建、也不产生技巧链接（仍只有第一次匹配上的 1 条）
    assert session.scalar(select(func.count()).select_from(TeachingMethod)) == 1
    assert session.scalar(select(func.count()).select_from(SolutionTechniqueLink)) == 1

    # KP 复核项不重复生成
    assert (
        session.scalar(
            select(func.count())
            .select_from(ReviewItem)
            .where(ReviewItem.item_type == "problem_knowledge_point")
        )
        == 1
    )

    # 第二次调和记为 skip
    actions = session.scalars(select(ReconciliationDecision.action)).all()
    assert ReconciliationAction.create in actions
    assert ReconciliationAction.skip in actions
