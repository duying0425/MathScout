from __future__ import annotations

from sqlalchemy import Engine, inspect, text

from mathscout.db.base import Base


def ensure_database_schema(engine: Engine) -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_crawl_task_not_before(engine)
    _ensure_source_document_document_kind(engine)


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


def _add_not_before_ddl(dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return "ALTER TABLE crawl_tasks ADD COLUMN not_before TIMESTAMP WITH TIME ZONE"
    return "ALTER TABLE crawl_tasks ADD COLUMN not_before DATETIME"
