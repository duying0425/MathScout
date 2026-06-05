from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from mathscout.db.base import Base
from mathscout.db.models import (
    CandidateItemType,
    CandidateKnowledgeItem,
    ManualEditLog,
    ReconciliationAction,
    ReconciliationDecision,
    ReviewStatus,
    SourceDocument,
)
from mathscout.review import ReviewService


def _session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_review_service_applies_candidate_action_and_returns_observation() -> None:
    session_factory = _session_factory()
    with session_factory() as session:
        document = SourceDocument(url="https://example.com/page")
        session.add(document)
        session.flush()
        candidate = CandidateKnowledgeItem(
            document_id=document.id,
            item_type=CandidateItemType.teaching_method,
            title="数轴比较有理数大小",
            payload={"summary": "用数轴位置比较大小。"},
            evidence_ids=[],
            confidence=0.8,
            review_status=ReviewStatus.pending,
        )
        session.add(candidate)
        session.flush()
        decision = ReconciliationDecision(
            candidate_id=candidate.id,
            action=ReconciliationAction.create,
            matched_table="teaching_methods",
            matched_ids=[],
            rationale="测试调和。",
            proposed_patch={},
            confidence=0.8,
            auto_applied=True,
            review_status=ReviewStatus.pending,
        )
        session.add(decision)
        session.commit()

        observation = ReviewService(session).apply_candidate_action(
            str(candidate.id),
            "approve",
            editor="tester",
        )
        session.commit()

        session.refresh(candidate)
        session.refresh(decision)
        logs = session.scalars(select(ManualEditLog)).all()

    assert observation.status == "succeeded"
    assert observation.target_table == "candidate_knowledge_items"
    assert observation.target_id == str(candidate.id)
    assert observation.manual_edit_log_id == str(logs[0].id)
    assert candidate.review_status == ReviewStatus.approved
    assert decision.review_status == ReviewStatus.approved
    assert logs[0].editor == "tester"
