"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import Settings
from .db import Database
from .routes_ats import router as ats_router
from .routes_resumes import router as resumes_router
from .routes_vacancies import router as vacancies_router


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    database = Database(resolved_settings.database_path)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        resolved_settings.ensure_directories()
        database.initialize()
        yield

    application = FastAPI(
        title="CareerFlow",
        version=__version__,
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.db = database
    static_dir = Path(__file__).parent / "static"
    application.mount("/static", StaticFiles(directory=static_dir), name="static")
    application.include_router(vacancies_router)
    application.include_router(resumes_router)
    application.include_router(ats_router)

    @application.get("/api/health")
    def health() -> dict[str, str]:
        row = database.fetch_one("SELECT MAX(version) AS version FROM schema_version")
        return {
            "status": "ok",
            "version": __version__,
            "schema_version": str(row["version"] if row else "unknown"),
        }

    @application.get("/", response_class=FileResponse)
    def root() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    return application


app = create_app()
