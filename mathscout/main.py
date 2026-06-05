from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from mathscout.admin.routes import router as admin_router
from mathscout.api.routes import router as api_router
from mathscout.db.migrations import ensure_database_schema
from mathscout.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    ensure_database_schema(engine)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="MathScout",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )
    app.include_router(api_router, prefix="/api")
    app.include_router(admin_router, prefix="/admin")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
