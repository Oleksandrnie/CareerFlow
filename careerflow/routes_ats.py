"""HTTP API for ATS analysis."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .ats import latest_analysis, run_analysis
from .ats_review import create_assessment, list_assessments
from .codex import CodexError


router = APIRouter(prefix="/api/vacancies/{vacancy_id}/ats", tags=["ats"])
assessment_router = APIRouter(prefix="/api/ats", tags=["ats", "codex"])


class AtsRequest(BaseModel):
    resume_version_id: int


class AssessmentRequest(BaseModel):
    assessment_kind: str = Field(pattern="^(manager_audit|vacancy_match)$")
    resume_version_id: int
    vacancy_id: int | None = None
    locale: str = Field(default="en", pattern="^(ru|en)$")
    model: str = Field(default="", max_length=80)
    reasoning_effort: str = Field(default="", max_length=20)


@router.get("")
def get_latest(request: Request, vacancy_id: int) -> dict | None:
    return latest_analysis(request.app.state.db, vacancy_id)


@router.post("", status_code=201)
def create_analysis(request: Request, vacancy_id: int, payload: AtsRequest) -> dict:
    try:
        return run_analysis(request.app.state.db, vacancy_id, payload.resume_version_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@assessment_router.get("/assessments")
def get_assessments(
    request: Request,
    resume_version_id: int | None = None,
    vacancy_id: int | None = None,
) -> list[dict]:
    return list_assessments(
        request.app.state.db,
        resume_version_id=resume_version_id,
        vacancy_id=vacancy_id,
    )


@assessment_router.post("/assessments", status_code=201)
def run_assessment(request: Request, payload: AssessmentRequest) -> dict:
    try:
        return create_assessment(
            request.app.state.db,
            request.app.state.settings,
            kind=payload.assessment_kind,
            resume_version_id=payload.resume_version_id,
            vacancy_id=payload.vacancy_id,
            locale=payload.locale,
            model=payload.model,
            reasoning_effort=payload.reasoning_effort,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, CodexError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
