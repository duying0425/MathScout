from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from mathscout.db.migrations import ensure_database_schema


def test_ensure_database_schema_adds_crawl_task_not_before_column() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE crawl_tasks (id TEXT PRIMARY KEY)"))

    ensure_database_schema(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("crawl_tasks")}

    assert "not_before" in columns
