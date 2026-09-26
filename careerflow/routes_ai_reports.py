"""HTTP API for Markdown reports and Codex CLI assistance."""

from __future__ import annotations

from pathlib import Path
import json
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from .codex import (
    ALLOWED_EFFORTS,
    MODEL_PATTERN,
    CodexError,
    build_prompt,
    load_model_catalog,
    run_codex,
    validate_model_effort,
)
from .ai_resume import (
    TAILORED_RESUME_ACTION,
    build_tailored_resume_context,
    tailored_resume_instructions,
)
from .db import insert_and_get_id
from .reports import build_report_with_sources, get_report, save_report
from .vacancies import get_vacancy


router = APIRouter(prefix="/api/vacancies/{vacancy_id}", tags=["reports", "ai"])
AI_MATCH_ACTION = "Match resume to vacancy"
TAILORED_RESUME_MODEL = "gpt-5.6-sol"
TAILORED_RESUME_EFFORT = "medium"


def parse_ai_match_response(response: str) -> int | None:
    """Read a valid JSON score, tolerating harmless CLI prose/fences around it."""
    # Codex/terminal wrappers may add a BOM, ANSI color codes, or harmless
    # control characters before the JSON payload.
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", response).lstrip("\ufeff").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
        decoder = json.JSONDecoder()
        for match in re.finditer(r"\{", text):
            try:
                candidate, _ = decoder.raw_decode(text[match.start():])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and "match_percent" in candidate:
                payload = candidate
                break
        if payload is None:
            return None
    if not isinstance(payload, dict) or isinstance(payload.get("match_percent"), bool):
        return None
    value = payload.get("match_percent")
    if isinstance(value, float) and not value.is_integer():
        return None
    if not isinstance(value, (int, float)) or not 0 <= value <= 100:
        return None
    return int(value)


class AiRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=10_000)
    action: str = Field(default="", max_length=120)
    model: str = Field(default="", max_length=80)
    reasoning_effort: str = Field(default="", max_length=20)

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

    @field_validator("reasoning_effort")
    @classmethod
    def validate_effort(cls, value: str) -> str:
        trimmed = value.strip()
        if trimmed and trimmed not in ALLOWED_EFFORTS:
            raise ValueError("Unsupported Codex reasoning effort")
        return trimmed


@router.post("/reports", status_code=201)
def generate_report(request: Request, vacancy_id: int, include_raw: bool = False) -> dict:
    try:
        return save_report(
            request.app.state.db,
            request.app.state.settings.storage_dir,
            vacancy_id,
            include_raw=include_raw,
        )
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
    context_sources: dict = {}
    source_resume_id: int | None = None
    try:
        if payload.action == TAILORED_RESUME_ACTION:
            context, context_sources = build_tailored_resume_context(
                request.app.state.db, vacancy_id
            )
            source_resume_id = context_sources["resume_version_id"]
        else:
            context, context_sources = build_report_with_sources(
                request.app.state.db, vacancy_id
            )
            source_resume_id = context_sources["resume_version_id"]
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        prompt = build_prompt(payload.prompt, context, payload.action)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.action == AI_MATCH_ACTION:
        prompt += (
            "\n\nReturn JSON only with this exact shape: "
            '{"match_percent": 0, "summary": "short explanation", '
            '"strengths": ["..."], "gaps": ["..."]}. '
            "match_percent must be an integer from 0 to 100. "
            "Compare only the vacancy requirements with the selected resume evidence; "
            "ignore page navigation, company marketing, salary and generic wording."
        )
    elif payload.action == TAILORED_RESUME_ACTION:
        prompt += f"\n\n{tailored_resume_instructions()}"
    try:
        requested_model = (
            TAILORED_RESUME_MODEL
            if payload.action == TAILORED_RESUME_ACTION
            else payload.model
        )
        requested_effort = (
            TAILORED_RESUME_EFFORT
            if payload.action == TAILORED_RESUME_ACTION
            else payload.reasoning_effort
        )
        selected_model, selected_effort = validate_model_effort(
            load_model_catalog(request.app.state.settings),
            requested_model,
            requested_effort,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response = ""
    error = ""
    status = "completed"
    ai_match_percent: int | None = None
    try:
        result = run_codex(
            request.app.state.settings,
            prompt,
            model=selected_model,
            reasoning_effort=selected_effort,
        )
        response = result.response
        if payload.action == AI_MATCH_ACTION:
            ai_match_percent = parse_ai_match_response(response)
    except (CodexError, ValueError) as exc:
        status = "failed"
        error = str(exc)
    with request.app.state.db.transaction() as connection:
        run_id = insert_and_get_id(
            connection,
            """
            INSERT INTO ai_runs(
                vacancy_id, prompt, action, model, reasoning_effort, source_resume_id,
                context_sources_json, response, status, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vacancy_id,
                payload.prompt,
                payload.action,
                selected_model,
                selected_effort,
                source_resume_id,
                json.dumps(context_sources, ensure_ascii=False),
                response,
                status,
                error,
            ),
        )
        connection.execute(
            "INSERT INTO timeline_events(vacancy_id, event_type, title, details) VALUES (?, 'codex_run', ?, ?)",
            (
                vacancy_id,
                "Codex request completed" if status == "completed" else "Codex request failed",
                " · ".join(
                    part
                    for part in (
                        payload.action,
                        f"Model: {selected_model}",
                        f"Effort: {selected_effort}",
                    )
                    if part
                ),
            ),
        )
        if ai_match_percent is not None:
            connection.execute(
                "UPDATE vacancies SET ai_match_percent = ?, ai_match_updated_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (ai_match_percent, vacancy_id),
            )
    row = request.app.state.db.fetch_one("SELECT * FROM ai_runs WHERE id = ?", (run_id,)) or {}
    if payload.action == AI_MATCH_ACTION:
        row["ai_match_percent"] = ai_match_percent
    if status == "failed":
        raise HTTPException(status_code=502, detail=error)
    return row
