"""HTTP API for vacancy import and editing."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from .files import ImportError as DocumentImportError
from .files import extract_text, normalize_text
from .vacancies import create_vacancy, get_vacancy, list_vacancies, set_archived, update_vacancy


router = APIRouter(prefix="/api/vacancies", tags=["vacancies"])


class VacancyUpdate(BaseModel):
    title: str | None = None
    company: str | None = None
    salary: str | None = None
    summary: str | None = None
    description: str | None = None
    source: str | None = None


def _require_vacancy(request: Request, vacancy_id: int) -> dict:
    vacancy = get_vacancy(request.app.state.db, vacancy_id)
    if vacancy is None:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    return vacancy


@router.get("")
def vacancies(request: Request, archived: bool = False) -> list[dict]:
    return list_vacancies(request.app.state.db, archived)


@router.post("", status_code=201)
async def add_vacancy(
    request: Request,
    text: Annotated[str, Form()] = "",
    title: Annotated[str, Form()] = "",
    company: Annotated[str, Form()] = "",
    salary: Annotated[str, Form()] = "",
    source: Annotated[str, Form()] = "",
    file: Annotated[UploadFile | None, File()] = None,
) -> dict:
    original_content: bytes | None = None
    original_filename: str | None = None
    source_type = "text"
    extracted = normalize_text(text)
    if file and file.filename:
        original_content = await file.read()
        original_filename = file.filename
        try:
            extracted, source_type = extract_text(file.filename, original_content)
        except DocumentImportError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not extracted:
        raise HTTPException(status_code=422, detail="Paste vacancy text or choose a supported file")
    return create_vacancy(
        request.app.state.db,
        request.app.state.settings.storage_dir,
        extracted,
        source_type,
        original_filename=original_filename,
        original_content=original_content,
        overrides={"title": title, "company": company, "salary": salary, "source": source},
    )


@router.get("/{vacancy_id}")
def vacancy(request: Request, vacancy_id: int) -> dict:
    return _require_vacancy(request, vacancy_id)


@router.patch("/{vacancy_id}")
def edit_vacancy(request: Request, vacancy_id: int, payload: VacancyUpdate) -> dict:
    result = update_vacancy(
        request.app.state.db,
        vacancy_id,
        {key: value for key, value in payload.model_dump(exclude_none=True).items()},
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    return result


@router.post("/{vacancy_id}/archive")
def archive_vacancy(request: Request, vacancy_id: int) -> dict:
    result = set_archived(request.app.state.db, vacancy_id, True)
    if result is None:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    return result


@router.post("/{vacancy_id}/restore")
def restore_vacancy(request: Request, vacancy_id: int) -> dict:
    result = set_archived(request.app.state.db, vacancy_id, False)
    if result is None:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    return result
