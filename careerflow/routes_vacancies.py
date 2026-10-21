"""HTTP API for vacancy import and editing."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from .files import MAX_UPLOAD_BYTES, ImportError as DocumentImportError
from .cleaning import build_preview
from .files import extract_vacancy_text, fetch_vacancy_url, normalize_text
from .routes_utils import read_limited_upload
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
    codex_profile: Literal["primary", "escalation"] = "primary"


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
    url: Annotated[str, Form()] = "",
    url_import_token: Annotated[str, Form()] = "",
) -> dict:
    original_content: bytes | None = None
    original_filename: str | None = None
    source_type = "text"
    raw_description = normalize_text(text)
    extracted = raw_description
    inferred_method = "pasted-text"
    structured_overrides: dict[str, str] = {}
    if url_import_token:
        cached = getattr(request.app.state, "url_imports", {}).pop(url_import_token, None)
        if cached is None:
            raise HTTPException(
                status_code=422, detail="URL import preview expired. Parse the URL again."
            )
        raw_description = cached["raw_description"]
        extracted = cached["candidate_text"]
        source_type = cached["source_type"]
        original_filename = cached["original_filename"]
        original_content = cached["original_content"]
        url = cached["canonical_url"]
        structured_overrides = {
            key: str(value)
            for key, value in cached.get("inferred_fields", {}).items()
            if key in {"title", "company", "salary"} and value
        }
        inferred_method = "url-import"
    elif url.strip():
        raise HTTPException(
            status_code=422, detail="Parse the vacancy URL before confirming the import"
        )
    elif file and file.filename:
        original_content = await read_limited_upload(
            file, MAX_UPLOAD_BYTES, "File is larger than the 25 MB MVP limit"
        )
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
    overrides = dict(structured_overrides)
    for key, value in {"title": title, "company": company, "salary": salary}.items():
        if value.strip():
            overrides[key] = value.strip()
    overrides["source"] = source.strip() or url
    return create_vacancy(
        request.app.state.db,
        request.app.state.settings.storage_dir,
        confirmed_description,
        source_type,
        original_filename=original_filename,
        original_content=original_content,
        overrides=overrides,
        raw_description=raw_description,
        cleaning_method=cleaning_method.strip() or inferred_method,
        description_confirmed=True,
    )


@router.post("/import-preview")
async def preview_import(
    request: Request,
    text: Annotated[str, Form()] = "",
    use_codex: Annotated[bool, Form()] = False,
    codex_profile: Annotated[Literal["primary", "escalation"], Form()] = "primary",
    file: Annotated[UploadFile | None, File()] = None,
    url: Annotated[str, Form()] = "",
) -> dict:
    raw_description = normalize_text(text)
    candidate = raw_description
    source_type = "text"
    method = "pasted-text"
    if url.strip():
        try:
            requested_url, canonical_url, extraction_html, extraction = fetch_vacancy_url(url)
        except DocumentImportError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        raw_description = extraction.raw_text
        candidate = extraction.candidate_text
        source_type = "url"
        method = extraction.method
    elif file and file.filename:
        try:
            content = await read_limited_upload(
                file, MAX_UPLOAD_BYTES, "File is larger than the 25 MB MVP limit"
            )
            extraction = extract_vacancy_text(file.filename, content)
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
            codex_profile=codex_profile,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response = {**preview, "source_type": source_type}
    if url.strip():
        import secrets

        token = secrets.token_urlsafe(24)
        extracted_fields = extraction.metadata.as_dict()
        inferred_fields = {
            "title": extraction.metadata.title,
            "company": extraction.metadata.company,
            "salary": extraction.metadata.salary,
            "source": canonical_url,
        }
        request.app.state.url_imports[token] = {
            "raw_description": raw_description,
            "candidate_text": candidate,
            "source_type": "url",
            "original_filename": "original.html",
            "original_content": extraction_html,
            "canonical_url": canonical_url,
            "inferred_fields": inferred_fields,
        }
        response.update(
            {
                "url": requested_url,
                "canonical_url": canonical_url,
                "url_import_token": token,
                "extracted_fields": extracted_fields,
                "inferred_fields": inferred_fields,
            }
        )
    return response


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
            codex_profile=payload.codex_profile,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{vacancy_id}/description/apply")
def apply_description(request: Request, vacancy_id: int, payload: CleaningApplyRequest) -> dict:
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
