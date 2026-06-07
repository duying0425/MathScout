# Import models so SQLAlchemy registers all metadata before create_all.
import mathscout.db.models  # noqa: F401
from mathscout.db.base import Base
from mathscout.db.session import engine


def create_database_schema() -> None:
    Base.metadata.create_all(bind=engine)
