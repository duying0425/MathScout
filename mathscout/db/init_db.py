import mathscout.db.models  # noqa: F401
from mathscout.db.migrations import ensure_database_schema
from mathscout.db.session import engine


def create_database_schema() -> None:
    ensure_database_schema(engine)
