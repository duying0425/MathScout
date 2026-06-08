from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from mathscout.admin.routes import (
    _problem_detail,
    confirm_problem_knowledge_points,
    reject_problem_knowledge_points,
)
from mathscout.db.base import Base
from mathscout.db.models import (
    KnowledgePoint,
    ManualEditAction,
    ManualEditLog,
    Problem,
    ProblemKnowledgePointLink,
    ReviewItem,
    ReviewStatus,
    SourceDocument,
    TeachingMethod,
)
from mathscout.extraction.schemas import ExtractedProblem, ExtractedSolution
from mathscout.pipeline.problem_extract import ProblemReconciler
from mathscout.utils.text import normalize_semantic_key


def _seed_problem(session) -> Problem:
    session.add(
        KnowledgePoint(title="勾股定理", semantic_key=normalize_semantic_key("勾股定理"))
    )
    session.add(
        TeachingMethod(
            title="将军饮马模型",
            method_type="解题技巧",
            summary="对称求最短路径",
            semantic_key=normalize_semantic_key("将军饮马模型"),
        )
    )
    document = SourceDocument(url="https://example.com/exam")
    session.add(document)
    session.flush()

    extracted = ExtractedProblem(
        stem="求斜边 c。",
        problem_type="解答",
        source_type="试卷",
        knowledge_point_titles=["勾股定理"],
        solutions=[
            ExtractedSolution(
                approach_label="勾股定理直接计算",
                steps=["c=5"],
                technique_titles=["将军饮马模型"],
                confidence=0.8,
            )
        ],
        confidence=0.8,
    )
    ProblemReconciler(session).ingest([extracted], document)
    return session.scalar(select(Problem))


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_problem_detail_assembles_solutions_techniques_and_kp_review():
    session = _session()
    problem = _seed_problem(session)

    detail = _problem_detail(session, problem)

    assert detail["stem"] == "求斜边 c。"
    assert detail["problem_type"] == "解答"
    assert len(detail["solutions"]) == 1
    assert detail["solutions"][0]["techniques"] == ["将军饮马模型"]
    # 考察知识点尚未确认，处于待复核，且匹配到了 canonical 知识点
    assert detail["confirmed_kps"] == []
    assert detail["kp_review"]["proposed"][0]["matched"] == "勾股定理"


def test_confirm_knowledge_points_creates_links_and_logs():
    session = _session()
    problem = _seed_problem(session)

    confirm_problem_knowledge_points(str(problem.id), session)

    links = session.scalars(
        select(ProblemKnowledgePointLink).where(
            ProblemKnowledgePointLink.problem_id == problem.id
        )
    ).all()
    assert len(links) == 1

    review = session.scalar(
        select(ReviewItem).where(ReviewItem.item_type == "problem_knowledge_point")
    )
    assert review.status == ReviewStatus.approved

    log = session.scalar(
        select(ManualEditLog).where(ManualEditLog.action == ManualEditAction.approve_ai_change)
    )
    assert log is not None
    assert log.target_id == problem.id


def test_reject_knowledge_points_marks_rejected_without_links():
    session = _session()
    problem = _seed_problem(session)

    reject_problem_knowledge_points(str(problem.id), session)

    assert session.scalar(select(func.count()).select_from(ProblemKnowledgePointLink)) == 0
    review = session.scalar(
        select(ReviewItem).where(ReviewItem.item_type == "problem_knowledge_point")
    )
    assert review.status == ReviewStatus.rejected
    log = session.scalar(
        select(ManualEditLog).where(ManualEditLog.action == ManualEditAction.reject_ai_change)
    )
    assert log is not None
