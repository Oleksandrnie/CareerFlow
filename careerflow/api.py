"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import __version__
from .config import Settings
from .db import Database


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

    @application.get("/api/health")
    def health() -> dict[str, str]:
        row = database.fetch_one("SELECT MAX(version) AS version FROM schema_version")
        return {
            "status": "ok",
            "version": __version__,
            "schema_version": str(row["version"] if row else "unknown"),
        }

    @application.get("/")
    def root() -> dict[str, str]:
        return {"name": "CareerFlow", "status": "ready"}

    return application


app = create_app()

