"""Vacancy parsing and persistence operations."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from uuid import uuid4

from .db import Database, insert_and_get_id
from .files import normalize_text, safe_filename, write_bytes, write_text


EDITABLE_FIELDS = {"title", "company", "salary", "summary", "description", "source"}


def infer_vacancy_fields(text: str) -> dict[str, str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = lines[0][:160] if lines else "Untitled vacancy"
    company = ""
    for line in lines[:15]:
        match = re.match(r"(?:company|компания|employer|работодатель)\s*[:—-]\s*(.+)", line, re.I)
        if match:
            company = match.group(1).strip()[:160]
            break
    salary_match = re.search(
        r"(?im)(?:salary|зарплата|compensation)\s*[:—-]?\s*([^\n]{1,80})",
        text,
    )
    if not salary_match:
        salary_match = re.search(
            r"(?i)(?:[$€£]\s?\d[\d ,.]{2,}|\d[\d ,.]{2,}\s?(?:USD|EUR|GBP|RUB|₽))",
            text,
        )
    salary = salary_match.group(1 if salary_match.lastindex else 0).strip() if salary_match else ""
    summary = " ".join(lines[:4])[:360]
    return {"title": title, "company": company, "salary": salary, "summary": summary}


def create_vacancy(
    database: Database,
    storage_dir: Path,
    text: str,
    source_type: str,
    *,
    original_filename: str | None = None,
    original_content: bytes | None = None,
    overrides: dict[str, str] | None = None,
) -> dict:
    normalized = normalize_text(text)
    if not normalized:
        raise ValueError("Vacancy text is required")
    inferred = infer_vacancy_fields(normalized)
    for key, value in (overrides or {}).items():
        if key in inferred and value.strip():
            inferred[key] = value.strip()

    folder = storage_dir / "vacancies" / uuid4().hex
    extracted_path = folder / "extracted.txt"
    write_text(extracted_path, normalized)
    original_path: Path | None = None
    stored_filename: str | None = None
    if original_filename and original_content is not None:
        stored_filename = safe_filename(original_filename)
        original_path = folder / f"original-{stored_filename}"
        write_bytes(original_path, original_content)

    with database.transaction() as connection:
        vacancy_id = insert_and_get_id(
            connection,
            """
            INSERT INTO vacancies(
                title, company, salary, summary, description, source, source_type,
                original_filename, original_path, extracted_text_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                inferred["title"], inferred["company"], inferred["salary"],
                inferred["summary"], normalized, (overrides or {}).get("source", ""),
                source_type, stored_filename, str(original_path) if original_path else None,
                str(extracted_path),
            ),
        )
        connection.execute(
            """
            INSERT INTO timeline_events(vacancy_id, event_type, title, details)
            VALUES (?, 'vacancy_created', 'Vacancy created', ?)
            """,
            (vacancy_id, f"Imported from {source_type}"),
        )
    result = get_vacancy(database, vacancy_id)
    if result is None:
        raise RuntimeError("Created vacancy could not be loaded")
    return result


def get_vacancy(database: Database, vacancy_id: int) -> dict | None:
    return database.fetch_one("SELECT * FROM vacancies WHERE id = ?", (vacancy_id,))


def list_vacancies(database: Database, archived: bool = False) -> list[dict]:
    operator = "IS NOT NULL" if archived else "IS NULL"
    return database.fetch_all(
        f"SELECT * FROM vacancies WHERE archived_at {operator} ORDER BY created_at DESC, id DESC"
    )


def update_vacancy(database: Database, vacancy_id: int, changes: dict[str, str]) -> dict | None:
    selected = {key: value.strip() for key, value in changes.items() if key in EDITABLE_FIELDS}
    if not selected:
        return get_vacancy(database, vacancy_id)
    assignments = ", ".join(f"{key} = ?" for key in selected)
    with database.transaction() as connection:
        cursor = connection.execute(
            f"UPDATE vacancies SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (*selected.values(), vacancy_id),
        )
        if cursor.rowcount == 0:
            return None
        connection.execute(
            "INSERT INTO timeline_events(vacancy_id, event_type, title) VALUES (?, 'vacancy_updated', 'Vacancy details updated')",
            (vacancy_id,),
        )
    return get_vacancy(database, vacancy_id)


def set_archived(database: Database, vacancy_id: int, archived: bool) -> dict | None:
    value = "CURRENT_TIMESTAMP" if archived else "NULL"
    with database.transaction() as connection:
        cursor = connection.execute(
            f"UPDATE vacancies SET archived_at = {value}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (vacancy_id,),
        )
        if cursor.rowcount == 0:
            return None
        connection.execute(
            "INSERT INTO timeline_events(vacancy_id, event_type, title) VALUES (?, ?, ?)",
            (vacancy_id, "archived" if archived else "restored", "Vacancy archived" if archived else "Vacancy restored"),
        )
    return get_vacancy(database, vacancy_id)


def delete_vacancy(
    database: Database,
    storage_dir: Path,
    vacancy_id: int,
    resume_policy: str,
) -> dict[str, int]:
    if resume_policy not in {"delete_all", "preserve_resumes"}:
        raise ValueError("resume_policy must be delete_all or preserve_resumes")
    with database.transaction(immediate=True) as connection:
        vacancy_row = connection.execute(
            "SELECT * FROM vacancies WHERE id = ?", (vacancy_id,)
        ).fetchone()
        if vacancy_row is None:
            raise LookupError("Vacancy not found")
        vacancy = dict(vacancy_row)
        resumes = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM resume_versions WHERE vacancy_id = ? ORDER BY version",
                (vacancy_id,),
            ).fetchall()
        ]
        paths_to_remove = [vacancy.get("original_path"), vacancy.get("extracted_text_path")]
        paths_to_remove.extend(
            row["stored_path"]
            for row in connection.execute(
                "SELECT stored_path FROM attachments WHERE vacancy_id = ?", (vacancy_id,)
            ).fetchall()
        )
        paths_to_remove.extend(
            row["stored_path"]
            for row in connection.execute(
                "SELECT stored_path FROM generated_reports WHERE vacancy_id = ?", (vacancy_id,)
            ).fetchall()
        )
        preserved = 0
        if resume_policy == "preserve_resumes":
            next_master = int(
                connection.execute(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM resume_versions WHERE kind = 'master' AND vacancy_id IS NULL"
                ).fetchone()[0]
            )
            for offset, resume in enumerate(resumes):
                connection.execute(
                    """
                    UPDATE resume_versions
                    SET kind = 'master', vacancy_id = NULL, version = ?, is_submitted = 0,
                        label = CASE WHEN label = '' THEN ? ELSE label || ? END
                    WHERE id = ?
                    """,
                    (next_master + offset, f"Preserved from {vacancy['title']}", f" · Preserved from {vacancy['title']}", resume["id"]),
                )
                preserved += 1
        else:
            for resume in resumes:
                paths_to_remove.extend([resume.get("original_path"), resume.get("extracted_text_path")])
        connection.execute("DELETE FROM vacancies WHERE id = ?", (vacancy_id,))

    storage_root = storage_dir.resolve()
    removed_dirs: set[Path] = set()
    for raw_path in paths_to_remove:
        if not raw_path:
            continue
        path = Path(raw_path).resolve()
        if path.is_relative_to(storage_root):
            candidate = path.parent
            if candidate not in removed_dirs:
                shutil.rmtree(candidate, ignore_errors=True)
                removed_dirs.add(candidate)
    return {"deleted_vacancy_id": vacancy_id, "preserved_resume_count": preserved}
