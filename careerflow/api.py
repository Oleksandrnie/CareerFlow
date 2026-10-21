"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
import ipaddress
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import Settings
from .db import Database
from .routes_ats import router as ats_router
from .routes_ai_reports import router as ai_reports_router
from .routes_analytics import router as analytics_router
from .routes_codex import router as codex_router
from .routes_resumes import router as resumes_router
from .routes_tracking import router as tracking_router
from .routes_vacancies import router as vacancies_router

MAX_REQUEST_BODY_BYTES = 101 * 1024 * 1024


def _is_local_request_host(host: str | None) -> bool:
    if not host:
        return False
    hostname = host.rstrip(".").lower()
    if hostname in {"localhost", "testserver"}:
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return (
        not address.is_unspecified
        and not address.is_multicast
        and not address.is_reserved
        and (address.is_loopback or address.is_private or address.is_link_local)
    )


def _origin_matches_request(origin_value: str, request: Request) -> bool:
    try:
        origin = urlsplit(origin_value)
        origin_host = origin.hostname
        origin_port = origin.port or (443 if origin.scheme.lower() == "https" else 80)
        request_port = request.url.port or (443 if request.url.scheme == "https" else 80)
    except ValueError:
        return False
    return (
        origin.scheme.lower() in {"http", "https"}
        and origin.scheme.lower() == request.url.scheme.lower()
        and origin_host is not None
        and origin_host.lower() == (request.url.hostname or "").lower()
        and origin_port == request_port
        and not origin.username
        and not origin.password
        and origin.path in {"", "/"}
        and not origin.query
        and not origin.fragment
    )


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
    application.state.url_imports = {}

    @application.middleware("http")
    async def protect_local_requests(request: Request, call_next):
        if not _is_local_request_host(request.url.hostname):
            return JSONResponse(
                status_code=400,
                content={"detail": "CareerFlow only accepts localhost or private-network hosts"},
            )
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and not _origin_matches_request(origin, request):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-origin browser requests are not allowed"},
                )
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                request_size = int(content_length)
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length"})
            if request_size < 0 or request_size > MAX_REQUEST_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body is larger than the 101 MB limit"},
                )
        original_receive = request._receive
        received_bytes = 0
        request_too_large = False

        async def receive_with_limit():
            nonlocal received_bytes, request_too_large
            message = await original_receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > MAX_REQUEST_BODY_BYTES:
                    request_too_large = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        request._receive = receive_with_limit
        response = await call_next(request)
        if request_too_large:
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body is larger than the 101 MB limit"},
            )
        return response

    static_dir = Path(__file__).parent / "static"
    application.mount("/static", StaticFiles(directory=static_dir), name="static")
    application.include_router(vacancies_router)
    application.include_router(resumes_router)
    application.include_router(ats_router)
    application.include_router(tracking_router)
    application.include_router(ai_reports_router)
    application.include_router(analytics_router)
    application.include_router(codex_router)

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
