"""HTTP API for ATS analysis."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .ats import latest_analysis, run_analysis


router = APIRouter(prefix="/api/vacancies/{vacancy_id}/ats", tags=["ats"])


class AtsRequest(BaseModel):
    resume_version_id: int


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
