from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.orm import Session

from mathscout.db.base import Base
from mathscout.db.models import (
    KnowledgePoint,
    MethodKnowledgePointLink,
    SectionKnowledgePointLink,
)
from mathscout.utils.text import normalize_semantic_key


def ensure_database_schema(engine: Engine) -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_crawl_task_not_before(engine)
    _ensure_source_document_pipeline_fields(engine)
    _ensure_source_document_document_kind(engine)
    _canonicalize_knowledge_points(engine)


def _ensure_crawl_task_not_before(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("crawl_tasks"):
        return
    columns = {column["name"] for column in inspector.get_columns("crawl_tasks")}
    if "not_before" in columns:
        return
    ddl = _add_not_before_ddl(engine.dialect.name)
    with engine.begin() as connection:
        connection.execute(text(ddl))


def _ensure_source_document_document_kind(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("source_documents"):
        return
    columns = {column["name"] for column in inspector.get_columns("source_documents")}
    if "document_kind" in columns:
        return
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE source_documents ADD COLUMN document_kind VARCHAR(32)")
        )


def _ensure_source_document_pipeline_fields(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("source_documents"):
        return
    columns = {column["name"] for column in inspector.get_columns("source_documents")}
    with engine.begin() as connection:
        if "pipeline_status" not in columns:
            connection.execute(
                text("ALTER TABLE source_documents ADD COLUMN pipeline_status VARCHAR(32)")
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_source_documents_pipeline_status "
                    "ON source_documents (pipeline_status)"
                )
            )
        if "pipeline_error" not in columns:
            connection.execute(text("ALTER TABLE source_documents ADD COLUMN pipeline_error TEXT"))
        connection.execute(
            text(
                "UPDATE source_documents SET pipeline_status = 'crawled' "
                "WHERE pipeline_status IS NULL"
            )
        )


def _canonicalize_knowledge_points(engine: Engine) -> None:
    """Phase A 迁移：把"挂在单个小节下"的知识点升级为 canonical。

    旧库里 `knowledge_points` 有一列 `section_id`（NOT NULL，硬绑定单个小节）。本迁移：
    1. 按旧 `section_id` 为每条知识点回填一条 section_knowledge_point_links（introduce）。
    2. DROP 掉旧的 `section_id` 列（先删其索引），知识点彻底与单一小节解耦。
    3. 把 `semantic_key` 重算为**基于内容**（规范化标题），去掉旧的 series/section 作用域。
    4. 合并因此重复的知识点：保留一条 canonical，把其它记录的小节/方法链接改指向它后删除。

    幂等保护：以"旧 `section_id` 列是否存在"为开关——迁移成功后该列被 DROP，后续启动
    自动跳过；新建库由 ORM 直接建成无该列的新结构，同样跳过（导入器已按内容键去重）。
    """
    inspector = inspect(engine)
    if not inspector.has_table("knowledge_points"):
        return
    if not inspector.has_table("section_knowledge_point_links"):
        return
    columns = {column["name"] for column in inspector.get_columns("knowledge_points")}
    if "section_id" not in columns:
        return  # 已迁移（列已 DROP）或新建库（从未有该列）

    # 1. 按旧 section_id 回填链接（用原生 SQL 读旧列；ORM 模型已不含该列）。
    #    仅当链接表为空时回填，避免上次 DROP 失败后的重复回填触发唯一约束冲突。
    with engine.begin() as connection:
        link_count = connection.execute(
            text("SELECT COUNT(*) FROM section_knowledge_point_links")
        ).scalar_one()
        if link_count == 0:
            legacy_rows = connection.execute(
                text(
                    "SELECT id, section_id, confidence FROM knowledge_points "
                    "WHERE section_id IS NOT NULL"
                )
            ).all()
            now = datetime.utcnow().isoformat(sep=" ")
            for kp_id, section_id, confidence in legacy_rows:
                connection.execute(
                    text(
                        "INSERT INTO section_knowledge_point_links "
                        "(id, section_id, knowledge_point_id, relation_type, position, "
                        " confidence, created_at) "
                        "VALUES (:id, :sid, :kid, 'introduce', 0, :conf, :now)"
                    ),
                    {
                        "id": uuid.uuid4().hex,
                        "sid": section_id,
                        "kid": kp_id,
                        "conf": confidence if confidence is not None else 0.0,
                        "now": now,
                    },
                )

    # 2. DROP 旧的 section_id 列（先删索引；SQLite 3.35+ / PostgreSQL 均支持 DROP COLUMN）。
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX IF EXISTS ix_knowledge_points_section_id"))
        connection.execute(text("ALTER TABLE knowledge_points DROP COLUMN section_id"))

    # 3 & 4. 重算内容键并合并重复（此时 ORM 模型已与物理表一致，可安全使用）。
    with Session(engine) as session:
        for point in session.scalars(select(KnowledgePoint)).all():
            point.semantic_key = normalize_semantic_key(point.title)
        session.flush()
        _merge_duplicate_knowledge_points(session)
        session.commit()


def _merge_duplicate_knowledge_points(session: Session) -> None:
    """按 semantic_key 合并重复知识点：保留首条，链接改指向它后删除其余。"""
    groups: dict[str, list[KnowledgePoint]] = {}
    for point in session.scalars(
        select(KnowledgePoint).order_by(KnowledgePoint.semantic_key, KnowledgePoint.title)
    ).all():
        groups.setdefault(point.semantic_key or "", []).append(point)

    for points in groups.values():
        if len(points) <= 1:
            continue
        canonical, *duplicates = points
        for dup in duplicates:
            _repoint_section_links(session, dup, canonical)
            _repoint_method_links(session, dup, canonical)
            canonical.source_count = (canonical.source_count or 1) + (dup.source_count or 1)
            session.delete(dup)
    session.flush()


def _repoint_section_links(
    session: Session, dup: KnowledgePoint, canonical: KnowledgePoint
) -> None:
    for link in session.scalars(
        select(SectionKnowledgePointLink).where(
            SectionKnowledgePointLink.knowledge_point_id == dup.id
        )
    ).all():
        already = session.scalar(
            select(SectionKnowledgePointLink).where(
                SectionKnowledgePointLink.section_id == link.section_id,
                SectionKnowledgePointLink.knowledge_point_id == canonical.id,
                SectionKnowledgePointLink.relation_type == link.relation_type,
            )
        )
        if already is not None:
            session.delete(link)
        else:
            link.knowledge_point_id = canonical.id
    session.flush()


def _repoint_method_links(
    session: Session, dup: KnowledgePoint, canonical: KnowledgePoint
) -> None:
    for link in session.scalars(
        select(MethodKnowledgePointLink).where(
            MethodKnowledgePointLink.knowledge_point_id == dup.id
        )
    ).all():
        already = session.scalar(
            select(MethodKnowledgePointLink).where(
                MethodKnowledgePointLink.method_id == link.method_id,
                MethodKnowledgePointLink.knowledge_point_id == canonical.id,
                MethodKnowledgePointLink.relation_type == link.relation_type,
            )
        )
        if already is not None:
            session.delete(link)
        else:
            link.knowledge_point_id = canonical.id
    session.flush()


def _add_not_before_ddl(dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return "ALTER TABLE crawl_tasks ADD COLUMN not_before TIMESTAMP WITH TIME ZONE"
    return "ALTER TABLE crawl_tasks ADD COLUMN not_before DATETIME"
