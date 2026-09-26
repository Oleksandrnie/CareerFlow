"""HTTP API for immutable resume versions."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response

from .files import ImportError as DocumentImportError
from .files import extract_text, normalize_text
from .resumes import create_resume, get_original_resume, get_resume, list_resumes, mark_submitted


router = APIRouter(prefix="/api/resumes", tags=["resumes"])


@router.get("")
def resumes(
    request: Request,
    kind: Annotated[str, Query(pattern="^(master|vacancy)$")] = "master",
    vacancy_id: int | None = None,
) -> list[dict]:
    if kind == "vacancy" and vacancy_id is None:
        raise HTTPException(status_code=422, detail="vacancy_id is required")
    return list_resumes(request.app.state.db, kind, vacancy_id)


@router.post("", status_code=201)
async def add_resume(
    request: Request,
    kind: Annotated[str, Form(pattern="^(master|vacancy)$")],
    text: Annotated[str, Form()] = "",
    label: Annotated[str, Form()] = "",
    vacancy_id: Annotated[int | None, Form()] = None,
    source_resume_id: Annotated[int | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
) -> dict:
    original_content: bytes | None = None
    original_filename: str | None = None
    content_text = normalize_text(text)
    if source_resume_id is not None and not content_text and not (file and file.filename):
        source = get_resume(request.app.state.db, source_resume_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Source resume not found")
        content_text = source["content_text"]
        label = label or f"Based on {source['kind']} v{source['version']}"
    elif file and file.filename:
        original_content = await file.read()
        original_filename = file.filename
        try:
            content_text, _ = extract_text(file.filename, original_content)
        except DocumentImportError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not content_text:
        raise HTTPException(status_code=422, detail="Paste resume text, choose a PDF/DOCX/TXT file, or select a source version")
    try:
        return create_resume(
            request.app.state.db,
            request.app.state.settings.storage_dir,
            kind=kind,
            content_text=content_text,
            vacancy_id=vacancy_id,
            label=label,
            original_filename=original_filename,
            original_content=original_content,
            source_resume_id=source_resume_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{resume_id}")
def resume(request: Request, resume_id: int) -> dict:
    result = get_resume(request.app.state.db, resume_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    return result


@router.get("/{resume_id}/download")
def download_original_resume(request: Request, resume_id: int) -> FileResponse:
    try:
        path, filename = get_original_resume(
            request.app.state.db, request.app.state.settings.storage_dir, resume_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type="application/octet-stream", filename=filename)


@router.get("/{resume_id}/markdown")
def download_markdown_resume(request: Request, resume_id: int) -> Response:
    resume = get_resume(request.app.state.db, resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    scope = "master" if resume["kind"] == "master" else "vacancy"
    filename = f"{scope}-resume-v{resume['version']}.md"
    return Response(
        content=resume["content_text"],
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{resume_id}/submit")
def submit_resume(request: Request, resume_id: int) -> dict:
    try:
        return mark_submitted(request.app.state.db, resume_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
