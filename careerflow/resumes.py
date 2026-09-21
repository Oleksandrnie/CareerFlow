"""Immutable master and vacancy-specific resume version management."""

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from .db import Database, insert_and_get_id
from .files import normalize_text, safe_filename, write_bytes, write_text


def get_resume(database: Database, resume_id: int) -> dict | None:
    return database.fetch_one("SELECT * FROM resume_versions WHERE id = ?", (resume_id,))


def list_resumes(database: Database, kind: str, vacancy_id: int | None = None) -> list[dict]:
    if kind == "master":
        return database.fetch_all(
            "SELECT * FROM resume_versions WHERE kind = 'master' AND vacancy_id IS NULL ORDER BY version DESC"
        )
    return database.fetch_all(
        "SELECT * FROM resume_versions WHERE kind = 'vacancy' AND vacancy_id = ? ORDER BY version DESC",
        (vacancy_id,),
    )


def create_resume(
    database: Database,
    storage_dir: Path,
    *,
    kind: str,
    content_text: str,
    vacancy_id: int | None = None,
    label: str = "",
    original_filename: str | None = None,
    original_content: bytes | None = None,
) -> dict:
    if kind not in {"master", "vacancy"}:
        raise ValueError("Resume kind must be master or vacancy")
    if kind == "master":
        vacancy_id = None
    elif vacancy_id is None:
        raise ValueError("A valid vacancy is required for a vacancy resume")
    normalized = normalize_text(content_text)
    if not normalized:
        raise ValueError("Resume text is required")

    scope = "master" if kind == "master" else f"vacancy-{vacancy_id}"
    folder = storage_dir / "resumes" / scope / uuid4().hex
    try:
        extracted_path = folder / "extracted.txt"
        write_text(extracted_path, normalized)
        stored_filename: str | None = None
        original_path: Path | None = None
        if original_filename and original_content is not None:
            stored_filename = safe_filename(original_filename)
            original_path = folder / f"original-{stored_filename}"
            write_bytes(original_path, original_content)

        with database.transaction(immediate=True) as connection:
            if vacancy_id is None:
                row = connection.execute(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM resume_versions WHERE kind = 'master' AND vacancy_id IS NULL"
                ).fetchone()
            else:
                vacancy_exists = connection.execute(
                    "SELECT 1 FROM vacancies WHERE id = ?", (vacancy_id,)
                ).fetchone()
                if vacancy_exists is None:
                    raise ValueError("A valid vacancy is required for a vacancy resume")
                row = connection.execute(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM resume_versions WHERE kind = 'vacancy' AND vacancy_id = ?",
                    (vacancy_id,),
                ).fetchone()
            version = int(row[0])
            resume_id = insert_and_get_id(
                connection,
                """
                INSERT INTO resume_versions(
                    vacancy_id, kind, version, label, original_filename, original_path,
                    extracted_text_path, content_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vacancy_id, kind, version, label.strip(), stored_filename,
                    str(original_path) if original_path else None, str(extracted_path), normalized,
                ),
            )
            if vacancy_id is not None:
                connection.execute(
                    """
                    INSERT INTO timeline_events(vacancy_id, event_type, title, details)
                    VALUES (?, 'resume_created', ?, ?)
                    """,
                    (vacancy_id, f"Resume v{version} created", label.strip()),
                )
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    result = get_resume(database, resume_id)
    if result is None:
        raise RuntimeError("Created resume could not be loaded")
    return result


def mark_submitted(database: Database, resume_id: int) -> dict:
    resume = get_resume(database, resume_id)
    if resume is None:
        raise LookupError("Resume not found")
    if resume["kind"] != "vacancy" or resume["vacancy_id"] is None:
        raise ValueError("Only a vacancy-specific resume can be marked as submitted")
    with database.transaction() as connection:
        connection.execute(
            "UPDATE resume_versions SET is_submitted = 0 WHERE vacancy_id = ?",
            (resume["vacancy_id"],),
        )
        connection.execute(
            "UPDATE resume_versions SET is_submitted = 1 WHERE id = ?",
            (resume_id,),
        )
        connection.execute(
            """
            INSERT INTO timeline_events(vacancy_id, event_type, title, details)
            VALUES (?, 'resume_submitted', ?, ?)
            """,
            (
                resume["vacancy_id"],
                f"Resume v{resume['version']} marked as submitted",
                resume["label"],
            ),
        )
    updated = get_resume(database, resume_id)
    if updated is None:
        raise RuntimeError("Submitted resume could not be loaded")
    return updated
