from sqlalchemy import create_engine, inspect, text

from mathscout.db.migrations import ensure_database_schema


def test_ensure_database_schema_adds_pipeline_fields_to_existing_source_documents():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE source_documents (id VARCHAR PRIMARY KEY)"))

    ensure_database_schema(engine)

    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("source_documents")}
    assert {"pipeline_status", "pipeline_error", "document_kind"} <= columns

    indexes = {index["name"] for index in inspector.get_indexes("source_documents")}
    assert "ix_source_documents_pipeline_status" in indexes
