"""HTTP API for vacancy import and editing."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from .files import ImportError as DocumentImportError
from .cleaning import build_preview
from .files import extract_vacancy_text, normalize_text
from .vacancies import (
    apply_clean_description,
    create_vacancy,
    delete_vacancy,
    get_vacancy,
    list_vacancies,
    set_archived,
    update_vacancy,
)


router = APIRouter(prefix="/api/vacancies", tags=["vacancies"])


class VacancyUpdate(BaseModel):
    title: str | None = None
    company: str | None = None
    salary: str | None = None
    summary: str | None = None
    description: str | None = None
    source: str | None = None


class CleaningPreviewRequest(BaseModel):
    use_codex: bool = False


class CleaningApplyRequest(BaseModel):
    description: str
    method: str = "manual-review"


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
    cleaned_description: Annotated[str, Form()] = "",
    cleaning_method: Annotated[str, Form()] = "",
    file: Annotated[UploadFile | None, File()] = None,
) -> dict:
    original_content: bytes | None = None
    original_filename: str | None = None
    source_type = "text"
    raw_description = normalize_text(text)
    extracted = raw_description
    inferred_method = "pasted-text"
    if file and file.filename:
        original_content = await file.read()
        original_filename = file.filename
        try:
            extraction = extract_vacancy_text(file.filename, original_content)
            raw_description = extraction.raw_text
            extracted = extraction.candidate_text
            source_type = extraction.source_type
            inferred_method = extraction.method
        except DocumentImportError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not extracted:
        raise HTTPException(status_code=422, detail="Paste vacancy text or choose a supported file")
    confirmed_description = normalize_text(cleaned_description) or extracted
    return create_vacancy(
        request.app.state.db,
        request.app.state.settings.storage_dir,
        confirmed_description,
        source_type,
        original_filename=original_filename,
        original_content=original_content,
        overrides={"title": title, "company": company, "salary": salary, "source": source},
        raw_description=raw_description,
        cleaning_method=cleaning_method.strip() or inferred_method,
        description_confirmed=True,
    )


@router.post("/import-preview")
async def preview_import(
    request: Request,
    text: Annotated[str, Form()] = "",
    use_codex: Annotated[bool, Form()] = False,
    file: Annotated[UploadFile | None, File()] = None,
) -> dict:
    raw_description = normalize_text(text)
    candidate = raw_description
    source_type = "text"
    method = "pasted-text"
    if file and file.filename:
        try:
            extraction = extract_vacancy_text(file.filename, await file.read())
        except DocumentImportError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raw_description = extraction.raw_text
        candidate = extraction.candidate_text
        source_type = extraction.source_type
        method = extraction.method
    if not raw_description:
        raise HTTPException(status_code=422, detail="Paste vacancy text or choose a supported file")
    try:
        preview = build_preview(
            raw_description,
            candidate,
            method=method,
            settings=request.app.state.settings,
            use_codex=use_codex,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**preview, "source_type": source_type}


@router.get("/{vacancy_id}")
def vacancy(request: Request, vacancy_id: int) -> dict:
    return _require_vacancy(request, vacancy_id)


@router.patch("/{vacancy_id}")
def edit_vacancy(request: Request, vacancy_id: int, payload: VacancyUpdate) -> dict:
    try:
        result = update_vacancy(
            request.app.state.db,
            vacancy_id,
            {key: value for key, value in payload.model_dump(exclude_none=True).items()},
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Vacancy not found")
    return result


@router.post("/{vacancy_id}/description/preview")
def preview_existing_description(
    request: Request, vacancy_id: int, payload: CleaningPreviewRequest
) -> dict:
    vacancy = _require_vacancy(request, vacancy_id)
    try:
        return build_preview(
            vacancy["raw_description"] or vacancy["description"],
            method="stored-raw-text",
            settings=request.app.state.settings,
            use_codex=payload.use_codex,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{vacancy_id}/description/apply")
def apply_description(
    request: Request, vacancy_id: int, payload: CleaningApplyRequest
) -> dict:
    try:
        return apply_clean_description(
            request.app.state.db, vacancy_id, payload.description, payload.method
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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


@router.delete("/{vacancy_id}")
def remove_vacancy(request: Request, vacancy_id: int, resume_policy: str) -> dict[str, int]:
    try:
        return delete_vacancy(
            request.app.state.db,
            request.app.state.settings.storage_dir,
            vacancy_id,
            resume_policy,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
