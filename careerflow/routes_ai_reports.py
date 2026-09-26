"""HTTP API for Markdown reports and Codex CLI assistance."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from .codex import MODEL_PATTERN, CodexError, build_prompt, run_codex
from .db import insert_and_get_id
from .reports import build_report, get_report, save_report
from .vacancies import get_vacancy


router = APIRouter(prefix="/api/vacancies/{vacancy_id}", tags=["reports", "ai"])


class AiRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=10_000)
    action: str = Field(default="", max_length=120)
    model: str = Field(default="", max_length=80)

    @field_validator("prompt")
    @classmethod
    def require_nonempty_prompt(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("A prompt is required")
        return trimmed

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        trimmed = value.strip()
        if trimmed and not MODEL_PATTERN.fullmatch(trimmed):
            raise ValueError("Model name contains unsupported characters")
        return trimmed


@router.post("/reports", status_code=201)
def generate_report(request: Request, vacancy_id: int) -> dict:
    try:
        return save_report(request.app.state.db, request.app.state.settings.storage_dir, vacancy_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/reports/{report_id}/download")
def download_report(request: Request, vacancy_id: int, report_id: int) -> FileResponse:
    try:
        report = get_report(request.app.state.db, vacancy_id, report_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    path = Path(report["stored_path"])
    return FileResponse(path, media_type="text/markdown", filename=path.name)


@router.get("/ai-runs")
def ai_history(request: Request, vacancy_id: int) -> list[dict]:
    if get_vacancy(request.app.state.db, vacancy_id) is None:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    return request.app.state.db.fetch_all(
        "SELECT * FROM ai_runs WHERE vacancy_id = ? ORDER BY created_at DESC, id DESC",
        (vacancy_id,),
    )


@router.get("/ai-runs/{run_id}")
def get_ai_run(request: Request, vacancy_id: int, run_id: int) -> dict:
    row = request.app.state.db.fetch_one(
        "SELECT * FROM ai_runs WHERE id = ? AND vacancy_id = ?",
        (run_id, vacancy_id),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="AI run not found")
    return row


@router.post("/ai-runs", status_code=201)
def execute_ai(request: Request, vacancy_id: int, payload: AiRequest) -> dict:
    if get_vacancy(request.app.state.db, vacancy_id) is None:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    context = build_report(request.app.state.db, vacancy_id)
    try:
        prompt = build_prompt(payload.prompt, context, payload.action)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    selected_model = payload.model or request.app.state.settings.codex_default_model
    response = ""
    error = ""
    status = "completed"
    try:
        result = run_codex(request.app.state.settings, prompt, model=selected_model)
        response = result.response
    except (CodexError, ValueError) as exc:
        status = "failed"
        error = str(exc)
    with request.app.state.db.transaction() as connection:
        run_id = insert_and_get_id(
            connection,
            """
            INSERT INTO ai_runs(vacancy_id, prompt, model, response, status, error)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (vacancy_id, payload.prompt, selected_model, response, status, error),
        )
        connection.execute(
            "INSERT INTO timeline_events(vacancy_id, event_type, title, details) VALUES (?, 'codex_run', ?, ?)",
            (vacancy_id, "Codex request completed" if status == "completed" else "Codex request failed", payload.action),
        )
    row = request.app.state.db.fetch_one("SELECT * FROM ai_runs WHERE id = ?", (run_id,)) or {}
    if status == "failed":
        raise HTTPException(status_code=502, detail=error)
    return row
