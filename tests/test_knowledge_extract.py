import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from mathscout.config import get_settings
from mathscout.db.base import Base
from mathscout.db.models import (
    Book,
    CandidateKnowledgeItem,
    Chapter,
    KnowledgePoint,
    ReconciliationDecision,
    Section,
    SectionKnowledgePointLink,
    SourceDocument,
    TextbookSeries,
)
from mathscout.extraction.ai_knowledge_extractor import AIKnowledgeExtractor
from mathscout.extraction.schemas import EvidenceRef, ExtractedKnowledgePoint
from mathscout.pipeline.knowledge_extract import KnowledgePointReconciler


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _seed_textbook(session) -> None:
    series = TextbookSeries(name="北师大版初中数学")
    session.add(series)
    session.flush()
    book = Book(series_id=series.id, book_code="G7A", grade=7, semester="A", label="七年级上册")
    session.add(book)
    session.flush()
    chapter = Chapter(book_id=book.id, chapter_code="G7A-C2", title="有理数及其运算")
    session.add(chapter)
    session.flush()
    session.add(Section(chapter_id=chapter.id, section_code="G7A-C2-S3", title="绝对值"))
    session.flush()


def _document(session) -> SourceDocument:
    doc = SourceDocument(url="https://example.com/guide")
    session.add(doc)
    session.flush()
    return doc


def _kp(title: str, **hints) -> ExtractedKnowledgePoint:
    return ExtractedKnowledgePoint(
        title=title,
        description=hints.pop("description", "示例简述"),
        evidence=[EvidenceRef(document_url=None, snippet="证据片段", confidence=0.6)],
        confidence=0.6,
        **hints,
    )


def test_creates_canonical_kp_candidate_and_section_link():
    session = _session()
    _seed_textbook(session)
    doc = _document(session)

    extracted = _kp(
        "绝对值的意义", book_code="G7A", chapter_title="有理数及其运算", section_title="绝对值"
    )
    stats = KnowledgePointReconciler(session).ingest([extracted], doc)

    assert stats == {
        "candidates": 1,
        "knowledge_points": 1,
        "section_links": 1,
        "skipped": 0,
    }
    point = session.scalar(select(KnowledgePoint).where(KnowledgePoint.title == "绝对值的意义"))
    assert point is not None
    assert point.source_type == "extracted"  # 来自抽取，区别于 template 导入
    assert session.scalar(select(func.count()).select_from(CandidateKnowledgeItem)) == 1
    assert session.scalar(select(func.count()).select_from(ReconciliationDecision)) == 1
    link = session.scalar(
        select(SectionKnowledgePointLink).where(
            SectionKnowledgePointLink.knowledge_point_id == point.id
        )
    )
    assert link is not None and link.relation_type == "introduce"


def test_dedups_by_content_key_across_ingests():
    session = _session()
    _seed_textbook(session)
    doc = _document(session)
    reconciler = KnowledgePointReconciler(session)

    reconciler.ingest([_kp("绝对值的意义")], doc)
    stats = reconciler.ingest([_kp("绝对值的意义")], doc)  # 同标题再来一次

    assert stats["knowledge_points"] == 0  # 不新建
    assert stats["skipped"] == 1
    assert session.scalar(select(func.count()).select_from(KnowledgePoint)) == 1
    point = session.scalar(select(KnowledgePoint))
    assert point.source_count == 2  # 累计来源计数


def test_no_section_link_when_hint_missing():
    session = _session()
    _seed_textbook(session)
    doc = _document(session)

    stats = KnowledgePointReconciler(session).ingest([_kp("有理数分类")], doc)

    assert stats["knowledge_points"] == 1
    assert stats["section_links"] == 0  # 无小节线索则只建 canonical，不强连
    assert session.scalar(select(func.count()).select_from(SectionKnowledgePointLink)) == 0


class _StubClient:
    def __init__(self, payload):
        self._payload = payload

    def chat_json(self, messages, **kwargs):
        return self._payload


def test_ai_extractor_maps_payload_to_contract():
    payload = {
        "knowledge_points": [
            {
                "title": "绝对值的意义",
                "description": "数轴上点到原点的距离",
                "book_code": "G7A",
                "section_title": "绝对值",
                "skill_codes": ["S05"],
                "evidence_snippet": "绝对值表示距离",
                "confidence": 0.7,
            }
        ]
    }
    points = AIKnowledgeExtractor(client=_StubClient(payload), settings=get_settings()).extract(
        "任意文本", "https://example.com/x"
    )
    assert len(points) == 1
    point = points[0]
    assert point.title == "绝对值的意义"
    assert point.book_code == "G7A"
    assert point.skill_codes == ["S05"]
    assert point.evidence[0].snippet == "绝对值表示距离"
    assert point.confidence == 0.7


def test_ai_extractor_raises_on_bad_schema():
    bad = {"knowledge_points": [{"description": "缺少 title"}]}
    with pytest.raises(ValueError):
        AIKnowledgeExtractor(client=_StubClient(bad), settings=get_settings()).extract("t", None)
