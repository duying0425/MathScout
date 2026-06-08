from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from mathscout.db.base import Base
from mathscout.db.models import (
    CandidateItemType,
    CandidateKnowledgeItem,
    ManualEditAction,
    ManualEditLog,
    ReconciliationAction,
    ReconciliationDecision,
    SourceDocument,
    TeachingMethod,
)
from mathscout.review import ReviewService


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_edit_candidate_syncs_method_and_writes_log():
    session = _session()
    document = SourceDocument(url="https://example.com/lesson")
    session.add(document)
    session.flush()
    method = TeachingMethod(
        title="原标题",
        method_type="解题技巧",
        summary="原摘要",
        steps=["s1"],
    )
    session.add(method)
    session.flush()
    candidate = CandidateKnowledgeItem(
        document_id=document.id,
        item_type=CandidateItemType.teaching_method,
        title="原标题",
        payload={"summary": "原摘要", "method_type": "解题技巧", "steps": ["s1"]},
        confidence=0.6,
    )
    session.add(candidate)
    session.flush()
    session.add(
        ReconciliationDecision(
            candidate_id=candidate.id,
            action=ReconciliationAction.create,
            matched_table="teaching_methods",
            matched_id=method.id,
            rationale="创建",
        )
    )
    session.flush()

    ReviewService(session).edit_candidate(
        str(candidate.id),
        title="新标题",
        payload_updates={"summary": "新摘要", "method_type": "教学方法", "steps": ["a", "b"]},
        reason="测试编辑",
    )
    session.commit()

    # 候选被更新
    assert candidate.title == "新标题"
    assert candidate.payload["summary"] == "新摘要"
    assert candidate.payload["steps"] == ["a", "b"]

    # 同步到 canonical 方法
    assert method.title == "新标题"
    assert method.summary == "新摘要"
    assert method.method_type == "教学方法"
    assert method.steps == ["a", "b"]

    # 写入变更记录
    log = session.scalar(
        select(ManualEditLog).where(ManualEditLog.target_table == "candidate_knowledge_items")
    )
    assert log is not None
    assert log.action == ManualEditAction.update
    assert log.reason == "测试编辑"


def test_edit_candidate_without_linked_method():
    session = _session()
    document = SourceDocument(url="https://example.com/x")
    session.add(document)
    session.flush()
    candidate = CandidateKnowledgeItem(
        document_id=document.id,
        item_type=CandidateItemType.teaching_method,
        title="t",
        payload={"summary": "s"},
        confidence=0.5,
    )
    session.add(candidate)
    session.flush()

    # 没有调和决策（无对应方法）时不应报错，仅更新候选并记日志
    ReviewService(session).edit_candidate(
        str(candidate.id),
        title="t2",
        payload_updates={"summary": "s2"},
    )
    session.commit()

    assert candidate.title == "t2"
    assert candidate.payload["summary"] == "s2"
    assert session.scalar(select(ManualEditLog)) is not None
