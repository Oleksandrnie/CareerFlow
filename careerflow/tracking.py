"""Vacancy status, interview, timeline, notes, and attachment services."""

from __future__ import annotations

import mimetypes
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .db import Database, insert_and_get_id
from .files import safe_filename, write_bytes
from .vacancies import get_vacancy


STATUSES = {"Saved", "Applied", "Interview", "Waiting", "Offer", "Rejected"}
TEXT_ATTACHMENT_EXTENSIONS = {".txt", ".md", ".html", ".htm", ".json", ".csv"}
MAX_ATTACHMENT_BYTES = 100 * 1024 * 1024
INTERVIEW_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?"
)
INTERVIEW_OFFSET = re.compile(r"[+-](\d{2}):(\d{2})$")


def _validated_interview_at(value: str) -> str:
    timestamp = value.strip()
    if not INTERVIEW_TIMESTAMP.fullmatch(timestamp):
        raise ValueError("Interview date must be an ISO 8601 datetime (YYYY-MM-DDTHH:MM, optionally with Z or timezone offset)")
    offset = INTERVIEW_OFFSET.search(timestamp)
    if offset:
        hours, minutes = (int(part) for part in offset.groups())
        if hours > 14 or minutes >= 60 or (hours == 14 and minutes != 0):
            raise ValueError("Interview timezone offset must be between -14:00 and +14:00")
    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Interview date must be a valid calendar datetime") from exc
    return timestamp


def _ensure_vacancy(database: Database, vacancy_id: int) -> dict:
    vacancy = get_vacancy(database, vacancy_id)
    if vacancy is None:
        raise LookupError("Vacancy not found")
    return vacancy


def timeline(database: Database, vacancy_id: int) -> list[dict]:
    _ensure_vacancy(database, vacancy_id)
    return database.fetch_all(
        "SELECT * FROM timeline_events WHERE vacancy_id = ? ORDER BY event_at DESC, id DESC",
        (vacancy_id,),
    )


def change_status(database: Database, vacancy_id: int, status: str, note: str = "") -> dict:
    vacancy = _ensure_vacancy(database, vacancy_id)
    if status not in STATUSES:
        raise ValueError("Unsupported vacancy status")
    if status == vacancy["status"] and not note.strip():
        return vacancy
    with database.transaction() as connection:
        connection.execute(
            "UPDATE vacancies SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, vacancy_id),
        )
        connection.execute(
            "INSERT INTO timeline_events(vacancy_id, event_type, title, details) VALUES (?, 'status_changed', ?, ?)",
            (vacancy_id, status, note.strip()),
        )
    return get_vacancy(database, vacancy_id) or {}


def add_interview(
    database: Database,
    vacancy_id: int,
    interview_at: str,
    interview_type: str,
    note: str,
    result: str,
) -> dict:
    interview_at = _validated_interview_at(interview_at)
    with database.transaction(immediate=True) as connection:
        vacancy_exists = connection.execute(
            "SELECT 1 FROM vacancies WHERE id = ?", (vacancy_id,)
        ).fetchone()
        if vacancy_exists is None:
            raise LookupError("Vacancy not found")
        row = connection.execute(
            "SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM interviews WHERE vacancy_id = ?",
            (vacancy_id,),
        ).fetchone()
        sequence = int(row[0])
        interview_id = insert_and_get_id(
            connection,
            """
            INSERT INTO interviews(vacancy_id, sequence_number, interview_at, interview_type, note, result)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (vacancy_id, sequence, interview_at, interview_type.strip() or "Interview", note.strip(), result.strip()),
        )
        connection.execute(
            "UPDATE vacancies SET status = 'Interview', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (vacancy_id,),
        )
        connection.execute(
            """
            INSERT INTO timeline_events(vacancy_id, event_type, title, details, event_at)
            VALUES (?, 'interview', ?, ?, ?)
            """,
            (
                vacancy_id,
                f"Interview #{sequence} · {interview_type.strip() or 'Interview'}",
                " · ".join(part for part in (note.strip(), result.strip()) if part),
                interview_at,
            ),
        )
    return database.fetch_one("SELECT * FROM interviews WHERE id = ?", (interview_id,)) or {}


def interviews(database: Database, vacancy_id: int) -> list[dict]:
    _ensure_vacancy(database, vacancy_id)
    return database.fetch_all(
        "SELECT * FROM interviews WHERE vacancy_id = ? ORDER BY sequence_number DESC",
        (vacancy_id,),
    )


def list_notes(database: Database, vacancy_id: int) -> list[dict]:
    _ensure_vacancy(database, vacancy_id)
    return database.fetch_all(
        "SELECT * FROM notes WHERE vacancy_id = ? ORDER BY created_at DESC, id DESC",
        (vacancy_id,),
    )


def add_note(database: Database, vacancy_id: int, body: str) -> dict:
    _ensure_vacancy(database, vacancy_id)
    if not body.strip():
        raise ValueError("Note cannot be empty")
    with database.transaction() as connection:
        note_id = insert_and_get_id(
            connection, "INSERT INTO notes(vacancy_id, body) VALUES (?, ?)", (vacancy_id, body.strip())
        )
        connection.execute(
            "INSERT INTO timeline_events(vacancy_id, event_type, title) VALUES (?, 'note_added', 'Note added')",
            (vacancy_id,),
        )
    return database.fetch_one("SELECT * FROM notes WHERE id = ?", (note_id,)) or {}


def update_note(database: Database, vacancy_id: int, note_id: int, body: str) -> dict:
    if not body.strip():
        raise ValueError("Note cannot be empty")
    with database.transaction() as connection:
        cursor = connection.execute(
            "UPDATE notes SET body = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND vacancy_id = ?",
            (body.strip(), note_id, vacancy_id),
        )
        if cursor.rowcount == 0:
            raise LookupError("Note not found")
        connection.execute(
            "INSERT INTO timeline_events(vacancy_id, event_type, title) VALUES (?, 'note_updated', 'Note updated')",
            (vacancy_id,),
        )
    return database.fetch_one("SELECT * FROM notes WHERE id = ?", (note_id,)) or {}


def delete_note(database: Database, vacancy_id: int, note_id: int) -> None:
    with database.transaction() as connection:
        cursor = connection.execute(
            "DELETE FROM notes WHERE id = ? AND vacancy_id = ?", (note_id, vacancy_id)
        )
        if cursor.rowcount == 0:
            raise LookupError("Note not found")
        connection.execute(
            "INSERT INTO timeline_events(vacancy_id, event_type, title) VALUES (?, 'note_deleted', 'Note deleted')",
            (vacancy_id,),
        )


def list_attachments(database: Database, vacancy_id: int) -> list[dict]:
    _ensure_vacancy(database, vacancy_id)
    return database.fetch_all(
        "SELECT * FROM attachments WHERE vacancy_id = ? ORDER BY created_at DESC, id DESC",
        (vacancy_id,),
    )


def add_attachment(
    database: Database,
    storage_dir: Path,
    vacancy_id: int,
    filename: str,
    content: bytes,
    media_type: str | None,
) -> dict:
    _ensure_vacancy(database, vacancy_id)
    if not content:
        raise ValueError("Attachment is empty")
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise ValueError("Attachment is larger than the 100 MB MVP limit")
    cleaned = safe_filename(filename)
    path = storage_dir / "attachments" / str(vacancy_id) / uuid4().hex / cleaned
    write_bytes(path, content)
    resolved_media = media_type or mimetypes.guess_type(cleaned)[0] or "application/octet-stream"
    is_text = int(Path(cleaned).suffix.lower() in TEXT_ATTACHMENT_EXTENSIONS or resolved_media.startswith("text/"))
    with database.transaction() as connection:
        attachment_id = insert_and_get_id(
            connection,
            """
            INSERT INTO attachments(vacancy_id, filename, stored_path, media_type, size_bytes, is_text)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (vacancy_id, cleaned, str(path), resolved_media, len(content), is_text),
        )
        connection.execute(
            "INSERT INTO timeline_events(vacancy_id, event_type, title, details) VALUES (?, 'file_added', 'File attached', ?)",
            (vacancy_id, cleaned),
        )
    return database.fetch_one("SELECT * FROM attachments WHERE id = ?", (attachment_id,)) or {}


def get_attachment(database: Database, vacancy_id: int, attachment_id: int) -> dict:
    result = database.fetch_one(
        "SELECT * FROM attachments WHERE id = ? AND vacancy_id = ?",
        (attachment_id, vacancy_id),
    )
    if result is None:
        raise LookupError("Attachment not found")
    return result


def delete_attachment(database: Database, vacancy_id: int, attachment_id: int) -> None:
    attachment = get_attachment(database, vacancy_id, attachment_id)
    with database.transaction() as connection:
        connection.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
        connection.execute(
            "INSERT INTO timeline_events(vacancy_id, event_type, title, details) VALUES (?, 'file_deleted', 'File removed', ?)",
            (vacancy_id, attachment["filename"]),
        )
    path = Path(attachment["stored_path"])
    path.unlink(missing_ok=True)
