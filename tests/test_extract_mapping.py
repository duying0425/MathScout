import types

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from mathscout.config import get_settings
from mathscout.db.base import Base
from mathscout.db.models import (
    Book,
    Chapter,
    KnowledgePoint,
    MethodKnowledgePointLink,
    MethodSectionLink,
    Section,
    TeachingMethod,
    TextbookSeries,
)
from mathscout.pipeline.extract import ExtractPipeline


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _seed_textbook(session) -> Section:
    series = TextbookSeries(name="北师大版初中数学")
    session.add(series)
    session.flush()
    book = Book(series_id=series.id, book_code="G7A", grade=7, semester="A", label="七年级上册")
    session.add(book)
    session.flush()
    chapter = Chapter(book_id=book.id, chapter_code="G7A-C2", title="有理数及其运算")
    session.add(chapter)
    session.flush()
    section = Section(chapter_id=chapter.id, section_code="G7A-C2-S5", title="有理数的加减法")
    session.add(section)
    session.flush()
    for title in ("有理数加法", "有理数减法"):
        session.add(KnowledgePoint(section_id=section.id, title=title))
    session.flush()
    return section


def _method(session) -> TeachingMethod:
    method = TeachingMethod(
        title="符号优先的加减法",
        method_type="解题技巧",
        summary="先定符号再算绝对值",
    )
    session.add(method)
    session.flush()
    return method


def test_maps_to_section_by_candidate_fields():
    session = _session()
    section = _seed_textbook(session)
    method = _method(session)
    candidate = types.SimpleNamespace(
        title="符号优先的加减法",
        book_code="G7A",
        chapter_title="有理数及其运算",
        section_title="有理数的加减法",
        payload={"summary": "先定符号", "knowledge_point_titles": ["有理数加法"]},
    )

    ExtractPipeline(session)._link_method_to_section(method, candidate)
    session.flush()

    section_link = session.scalar(
        select(MethodSectionLink).where(MethodSectionLink.method_id == method.id)
    )
    assert section_link is not None
    assert section_link.section_id == section.id
    assert section_link.relation_type == "matched_from_candidate_fields"
    assert section_link.confidence == get_settings().extraction_match_confidence

    kp_links = session.scalars(
        select(MethodKnowledgePointLink).where(MethodKnowledgePointLink.method_id == method.id)
    ).all()
    linked_titles = {
        session.get(KnowledgePoint, link.knowledge_point_id).title for link in kp_links
    }
    # 只链接候选明确列出的知识点，不波及同小节其它知识点
    assert linked_titles == {"有理数加法"}


def test_falls_back_to_text_match_when_no_section_fields():
    session = _session()
    _seed_textbook(session)
    method = _method(session)
    candidate = types.SimpleNamespace(
        title="减法技巧",
        book_code=None,
        chapter_title=None,
        section_title=None,
        payload={"summary": "讲解有理数减法的转化"},
    )

    ExtractPipeline(session)._link_method_to_section(method, candidate)
    session.flush()

    section_link = session.scalar(
        select(MethodSectionLink).where(MethodSectionLink.method_id == method.id)
    )
    assert section_link is not None
    assert section_link.relation_type == "inferred_from_knowledge_point"
    assert section_link.confidence == get_settings().evidence_default_confidence
