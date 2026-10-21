"""HTTP API for tracking activity within a vacancy."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .routes_utils import read_limited_upload
from .tracking import (
    MAX_ATTACHMENT_BYTES,
    add_attachment,
    add_interview,
    add_note,
    change_status,
    delete_attachment,
    delete_note,
    get_attachment,
    interviews,
    list_attachments,
    list_notes,
    timeline,
    update_note,
)


router = APIRouter(prefix="/api/vacancies/{vacancy_id}", tags=["tracking"])


class StatusChange(BaseModel):
    status: str
    note: str = ""
    outcome: str | None = None


class InterviewCreate(BaseModel):
    interview_at: str
    interview_type: str = "Interview"
    note: str = ""
    result: str = ""
    result_code: str = "unknown"


class NoteBody(BaseModel):
    body: str


def _translate_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404 if isinstance(exc, LookupError) else 422, detail=str(exc))


@router.get("/timeline")
def get_timeline(request: Request, vacancy_id: int) -> list[dict]:
    try:
        return timeline(request.app.state.db, vacancy_id)
    except LookupError as exc:
        raise _translate_error(exc) from exc


@router.post("/status")
def set_status(request: Request, vacancy_id: int, payload: StatusChange) -> dict:
    try:
        return change_status(
            request.app.state.db, vacancy_id, payload.status, payload.note, payload.outcome
        )
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@router.get("/interviews")
def get_interviews(request: Request, vacancy_id: int) -> list[dict]:
    try:
        return interviews(request.app.state.db, vacancy_id)
    except LookupError as exc:
        raise _translate_error(exc) from exc


@router.post("/interviews", status_code=201)
def create_interview(request: Request, vacancy_id: int, payload: InterviewCreate) -> dict:
    try:
        return add_interview(
            request.app.state.db,
            vacancy_id,
            payload.interview_at,
            payload.interview_type,
            payload.note,
            payload.result,
            payload.result_code,
        )
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@router.get("/notes")
def get_notes(request: Request, vacancy_id: int) -> list[dict]:
    try:
        return list_notes(request.app.state.db, vacancy_id)
    except LookupError as exc:
        raise _translate_error(exc) from exc


@router.post("/notes", status_code=201)
def create_note(request: Request, vacancy_id: int, payload: NoteBody) -> dict:
    try:
        return add_note(request.app.state.db, vacancy_id, payload.body)
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@router.patch("/notes/{note_id}")
def edit_note(request: Request, vacancy_id: int, note_id: int, payload: NoteBody) -> dict:
    try:
        return update_note(request.app.state.db, vacancy_id, note_id, payload.body)
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@router.delete("/notes/{note_id}", status_code=204)
def remove_note(request: Request, vacancy_id: int, note_id: int) -> Response:
    try:
        delete_note(request.app.state.db, vacancy_id, note_id)
    except LookupError as exc:
        raise _translate_error(exc) from exc
    return Response(status_code=204)


@router.get("/attachments")
def get_attachments(request: Request, vacancy_id: int) -> list[dict]:
    try:
        return list_attachments(request.app.state.db, vacancy_id)
    except LookupError as exc:
        raise _translate_error(exc) from exc


@router.post("/attachments", status_code=201)
async def create_attachment(
    request: Request,
    vacancy_id: int,
    file: Annotated[UploadFile, File()],
) -> dict:
    try:
        return add_attachment(
            request.app.state.db,
            request.app.state.settings.storage_dir,
            vacancy_id,
            file.filename or "attachment",
            await read_limited_upload(
                file, MAX_ATTACHMENT_BYTES, "Attachment is larger than the 100 MB MVP limit"
            ),
            file.content_type,
        )
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@router.get("/attachments/{attachment_id}/download")
def download_attachment(request: Request, vacancy_id: int, attachment_id: int) -> FileResponse:
    try:
        attachment = get_attachment(request.app.state.db, vacancy_id, attachment_id)
    except LookupError as exc:
        raise _translate_error(exc) from exc
    return FileResponse(
        attachment["stored_path"],
        media_type=attachment["media_type"],
        filename=attachment["filename"],
    )


@router.delete("/attachments/{attachment_id}", status_code=204)
def remove_attachment(request: Request, vacancy_id: int, attachment_id: int) -> Response:
    try:
        delete_attachment(request.app.state.db, vacancy_id, attachment_id)
    except LookupError as exc:
        raise _translate_error(exc) from exc
    return Response(status_code=204)
