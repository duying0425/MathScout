import uuid

from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import sessionmaker

from mathscout.db.base import Base
from mathscout.db.migrations import ensure_database_schema
from mathscout.db.models import KnowledgePoint, SectionKnowledgePointLink
from mathscout.utils.text import normalize_semantic_key


def test_ensure_database_schema_adds_pipeline_fields_to_existing_source_documents():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE source_documents (id VARCHAR PRIMARY KEY)"))
        connection.execute(text("INSERT INTO source_documents (id) VALUES ('legacy-document')"))

    ensure_database_schema(engine)

    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("source_documents")}
    assert {"pipeline_status", "pipeline_error", "document_kind"} <= columns

    indexes = {index["name"] for index in inspector.get_indexes("source_documents")}
    assert "ix_source_documents_pipeline_status" in indexes

    with engine.connect() as connection:
        pipeline_status = connection.scalar(
            text("SELECT pipeline_status FROM source_documents WHERE id = 'legacy-document'")
        )
    assert pipeline_status == "crawled"


def test_canonicalizes_knowledge_points_into_links_and_merges_duplicates():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    section_one = uuid.uuid4().hex
    section_two = uuid.uuid4().hex

    # 模拟旧库：knowledge_points 带 section_id 列（NOT NULL 硬绑定单个小节）、
    # 带 section 作用域的 semantic_key；同名"数轴"出现在两个小节，应合并为一条 canonical。
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE knowledge_points ADD COLUMN section_id CHAR(32)"))
        connection.execute(
            text(
                "CREATE INDEX ix_knowledge_points_section_id "
                "ON knowledge_points (section_id)"
            )
        )
        for title, section_id, key in [
            ("数轴", section_one, "x:G7A:S1:数轴"),
            ("数轴", section_two, "x:G7A:S2:数轴"),
            ("绝对值", section_one, "x:G7A:S1:绝对值"),
        ]:
            connection.execute(
                text(
                    "INSERT INTO knowledge_points "
                    "(id, section_id, title, semantic_key, source_type, confidence, "
                    " source_count, human_locked, review_status) "
                    "VALUES (:id, :sid, :title, :key, 'template', 0.9, 1, 0, 'pending')"
                ),
                {"id": uuid.uuid4().hex, "sid": section_id, "title": title, "key": key},
            )

    ensure_database_schema(engine)

    # 旧 section_id 列已被 DROP
    kp_columns = {column["name"] for column in inspect(engine).get_columns("knowledge_points")}
    assert "section_id" not in kp_columns

    with session_factory() as session:
        points = session.scalars(select(KnowledgePoint)).all()
        # 两条"数轴"合并为一条 → 共 2 个 canonical 知识点
        assert sorted(p.title for p in points) == ["数轴", "绝对值"]
        # semantic_key 改为基于内容，不再带 section 作用域
        for point in points:
            assert ":" not in (point.semantic_key or "")
            assert point.semantic_key == normalize_semantic_key(point.title)

        axis = next(p for p in points if p.title == "数轴")
        axis_links = session.scalars(
            select(SectionKnowledgePointLink).where(
                SectionKnowledgePointLink.knowledge_point_id == axis.id
            )
        ).all()
        assert len(axis_links) == 2  # 同一 canonical 知识点覆盖两个小节
        assert all(link.relation_type == "introduce" for link in axis_links)

        abs_point = next(p for p in points if p.title == "绝对值")
        abs_links = session.scalars(
            select(SectionKnowledgePointLink).where(
                SectionKnowledgePointLink.knowledge_point_id == abs_point.id
            )
        ).all()
        assert len(abs_links) == 1

    # 幂等：再次运行不应重复回填或再次合并
    ensure_database_schema(engine)
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(KnowledgePoint)) == 2
        assert (
            session.scalar(select(func.count()).select_from(SectionKnowledgePointLink)) == 3
        )
