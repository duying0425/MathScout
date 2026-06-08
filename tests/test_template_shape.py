import json
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from mathscout.db.base import Base
from mathscout.db.models import KnowledgePoint, SectionKnowledgePointLink
from mathscout.importers.template import import_template_dir

TEMPLATE_DIR = Path(".template/beishida_math_json_v3_with_template")


def test_template_files_have_expected_shape() -> None:
    files = sorted(TEMPLATE_DIR.glob("G*.json"))
    assert files

    for file in files:
        data = json.loads(file.read_text(encoding="utf-8"))
        assert "meta" in data
        assert "shared_skill_catalog" in data
        assert "semester" in data
        assert data["semester"]["chapters"]


def test_import_template_produces_canonical_knowledge_points() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    with session_factory() as session:
        import_template_dir(session, TEMPLATE_DIR)

    with session_factory() as session:
        keys = session.scalars(select(KnowledgePoint.semantic_key)).all()
        # canonical：每个知识点只有一条记录（semantic_key 唯一），不再带 section 作用域旧键
        assert keys
        assert len(keys) == len(set(keys))
        assert all(":" not in (key or "") for key in keys)
        # 每个知识点至少被一个小节覆盖
        link_count = session.scalar(
            select(func.count()).select_from(SectionKnowledgePointLink)
        )
        assert link_count >= len(keys)

    # 幂等：重复导入不应改变 canonical 知识点数量
    with session_factory() as session:
        before = session.scalar(select(func.count()).select_from(KnowledgePoint))
        import_template_dir(session, TEMPLATE_DIR)
    with session_factory() as session:
        after = session.scalar(select(func.count()).select_from(KnowledgePoint))
    assert before == after
