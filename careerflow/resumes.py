"""Immutable master and vacancy-specific resume version management."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

from .db import Database, insert_and_get_id, insert_funnel_event
from .files import normalize_text, safe_filename, write_bytes, write_text


RESUME_WITH_SOURCE = """
SELECT child.*, source.kind AS source_kind, source.version AS source_version,
       source.label AS source_label, source.vacancy_id AS source_vacancy_id,
       source.deleted_at AS source_deleted_at
FROM resume_versions AS child
LEFT JOIN resume_versions AS source ON source.id = child.source_resume_id
"""


def get_resume(database: Database, resume_id: int) -> dict | None:
    return database.fetch_one(
        f"{RESUME_WITH_SOURCE} WHERE child.id = ? AND child.deleted_at IS NULL",
        (resume_id,),
    )


def get_original_resume(database: Database, storage_dir: Path, resume_id: int) -> tuple[Path, str]:
    resume = get_resume(database, resume_id)
    if resume is None or not resume["original_path"] or not resume["original_filename"]:
        raise LookupError("Resume original not found")
    filename = safe_filename(resume["original_filename"])
    path = Path(resume["original_path"]).resolve()
    allowed_root = (storage_dir / "resumes").resolve()
    if (
        not path.is_relative_to(allowed_root)
        or path.name != f"original-{filename}"
        or not path.is_file()
    ):
        raise LookupError("Resume original not found")
    return path, filename


def list_resumes(database: Database, kind: str, vacancy_id: int | None = None) -> list[dict]:
    if kind == "master":
        return database.fetch_all(
            f"{RESUME_WITH_SOURCE} WHERE child.kind = 'master' AND child.vacancy_id IS NULL AND child.deleted_at IS NULL ORDER BY child.version DESC"
        )
    return database.fetch_all(
        f"{RESUME_WITH_SOURCE} WHERE child.kind = 'vacancy' AND child.vacancy_id = ? AND child.deleted_at IS NULL ORDER BY child.version DESC",
        (vacancy_id,),
    )


def _validate_source(
    connection, *, kind: str, vacancy_id: int | None, source_resume_id: int | None
) -> dict | None:
    if source_resume_id is None:
        return None
    row = connection.execute(
        "SELECT id, kind, vacancy_id, version FROM resume_versions WHERE id = ? AND deleted_at IS NULL",
        (source_resume_id,),
    ).fetchone()
    if row is None:
        raise LookupError("Source resume not found")
    source = dict(row)
    if kind == "master" and source["kind"] != "master":
        raise ValueError("A Master Resume version can only be based on another Master Resume")
    if kind == "vacancy" and source["kind"] == "vacancy" and source["vacancy_id"] != vacancy_id:
        raise ValueError("A vacancy resume can only use a source from the same vacancy")
    return source


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
    source_resume_id: int | None = None,
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
        extracted_path = folder / "resume.md"
        write_text(extracted_path, normalized)
        stored_filename: str | None = None
        original_path: Path | None = None
        if original_filename and original_content is not None:
            stored_filename = safe_filename(original_filename)
            original_path = folder / f"original-{stored_filename}"
            write_bytes(original_path, original_content)

        with database.transaction(immediate=True) as connection:
            source = _validate_source(
                connection,
                kind=kind,
                vacancy_id=vacancy_id,
                source_resume_id=source_resume_id,
            )
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
                    extracted_text_path, content_text, source_resume_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vacancy_id, kind, version, label.strip(), stored_filename,
                    str(original_path) if original_path else None, str(extracted_path), normalized,
                    source_resume_id,
                ),
            )
            if vacancy_id is not None:
                source_detail = ""
                if source:
                    source_detail = (
                        f"Based on {'Master Resume' if source['kind'] == 'master' else 'Vacancy Resume'} "
                        f"v{source['version']} (ID {source['id']})"
                    )
                connection.execute(
                    """
                    INSERT INTO timeline_events(vacancy_id, event_type, title, details)
                    VALUES (?, 'resume_created', ?, ?)
                    """,
                    (
                        vacancy_id,
                        f"Resume v{version} created",
                        " · ".join(part for part in (label.strip(), source_detail) if part),
                    ),
                )
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    result = get_resume(database, resume_id)
    if result is None:
        raise RuntimeError("Created resume could not be loaded")
    return result


def _storage_folder_for_deletion(connection, storage_dir: Path, resume: dict) -> Path | None:
    allowed_root = (storage_dir / "resumes").resolve()
    raw_paths = [
        ("extracted_text_path", resume.get("extracted_text_path")),
        ("original_path", resume.get("original_path")),
    ]
    stored_paths = [(name, Path(value)) for name, value in raw_paths if value]
    if not stored_paths:
        return None

    resolved_paths = [(name, path.resolve()) for name, path in stored_paths]
    if any(not path.is_relative_to(allowed_root) for _, path in resolved_paths):
        raise ValueError("Resume storage path is outside storage/resumes")
    if any(name == "extracted_text_path" and path.name != "resume.md" for name, path in resolved_paths):
        raise ValueError("Resume Markdown storage path is invalid")
    if resume.get("original_path"):
        filename = resume.get("original_filename")
        if not filename or Path(resume["original_path"]).resolve().name != f"original-{safe_filename(filename)}":
            raise ValueError("Resume original storage path is invalid")

    folders = {path.parent for _, path in resolved_paths}
    if len(folders) != 1:
        raise ValueError("Resume files do not share one version storage folder")
    folder = folders.pop()
    expected_scope = allowed_root / (
        "master" if resume["kind"] == "master" else f"vacancy-{resume['vacancy_id']}"
    )
    if folder == allowed_root or folder.parent != expected_scope.resolve():
        raise ValueError("Resume version storage folder is invalid")

    other_rows = connection.execute(
        "SELECT id, original_path, extracted_text_path FROM resume_versions WHERE id != ?",
        (resume["id"],),
    ).fetchall()
    for other in other_rows:
        for value in (other["original_path"], other["extracted_text_path"]):
            if value and Path(value).resolve().parent == folder:
                raise ValueError("Resume version storage folder is shared by another resume")
    return folder


def _redact_stored_reports(
    connection,
    storage_dir: Path,
    resume: dict,
    evidence_excerpts: list[str],
) -> int:
    vacancy_ids = {
        int(row["vacancy_id"])
        for row in connection.execute(
            "SELECT DISTINCT vacancy_id FROM ats_analyses WHERE resume_version_id = ?",
            (resume["id"],),
        ).fetchall()
    }
    if resume["vacancy_id"] is not None:
        vacancy_ids.add(int(resume["vacancy_id"]))
    if not vacancy_ids:
        return 0

    resume_text = resume["content_text"]
    evidence_excerpts = sorted(set(filter(None, evidence_excerpts)), key=len, reverse=True)
    if not resume_text and not evidence_excerpts:
        return 0
    report_root = (storage_dir / "reports").resolve()
    placeholders_sql = ",".join("?" for _ in vacancy_ids)
    report_rows = connection.execute(
        f"SELECT stored_path FROM generated_reports WHERE vacancy_id IN ({placeholders_sql})",
        tuple(sorted(vacancy_ids)),
    ).fetchall()
    redacted_count = 0
    for report in report_rows:
        path = Path(report["stored_path"]).resolve()
        if not path.is_relative_to(report_root):
            raise ValueError("Generated report path is outside storage/reports")
        if not path.is_file():
            continue
        markdown = path.read_text(encoding="utf-8", errors="replace")
        redacted = markdown
        if resume_text:
            redacted = redacted.replace(
                resume_text, "Resume content was deleted and redacted."
            )
        for value in evidence_excerpts:
            redacted = redacted.replace(
                f"  - Evidence: “{value}”",
                "  - Evidence: [deleted resume evidence redacted]",
            )
        if redacted != markdown:
            path.write_text(redacted, encoding="utf-8")
            redacted_count += 1
    return redacted_count


def delete_resume(database: Database, storage_dir: Path, resume_id: int) -> dict:
    """Redact one resume version while retaining its historical identity and links."""
    with database.transaction(immediate=True) as connection:
        row = connection.execute(
            "SELECT * FROM resume_versions WHERE id = ?", (resume_id,)
        ).fetchone()
        if row is None:
            raise LookupError("Resume not found")
        resume = dict(row)
        analysis_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM ats_analyses WHERE resume_version_id = ?",
                (resume_id,),
            ).fetchone()[0]
        )
        if resume["deleted_at"] is not None:
            return {
                "id": resume_id,
                "kind": resume["kind"],
                "version": resume["version"],
                "vacancy_id": resume["vacancy_id"],
                "deleted_at": resume["deleted_at"],
                "already_deleted": True,
                "files_removed": False,
                "ats_analyses_preserved": analysis_count,
                "current_matches_cleared": 0,
                "reports_redacted": 0,
            }

        folder = _storage_folder_for_deletion(connection, storage_dir, resume)
        analysis_rows = connection.execute(
            "SELECT id, result_json FROM ats_analyses WHERE resume_version_id = ?",
            (resume_id,),
        ).fetchall()
        evidence_excerpts: list[str] = []
        scrubbed_results: list[tuple[str, int]] = []
        for analysis in analysis_rows:
            result = json.loads(analysis["result_json"])
            for requirement in result.get("requirements", []):
                evidence = requirement.get("evidence", "")
                if evidence:
                    evidence_excerpts.append(evidence)
                    requirement["evidence"] = ""
            scrubbed_results.append(
                (json.dumps(result, ensure_ascii=False), int(analysis["id"]))
            )
        reports_redacted = _redact_stored_reports(
            connection, storage_dir, resume, evidence_excerpts
        )
        current_vacancy_rows = connection.execute(
            """
            SELECT DISTINCT analysis.vacancy_id
            FROM ats_analyses AS analysis
            JOIN vacancies AS vacancy ON vacancy.id = analysis.vacancy_id
            WHERE analysis.resume_version_id = ?
              AND analysis.id = (
                  SELECT latest.id FROM ats_analyses AS latest
                  WHERE latest.vacancy_id = analysis.vacancy_id
                  ORDER BY latest.created_at DESC, latest.id DESC LIMIT 1
              )
              AND analysis.description_revision IS NOT NULL
              AND analysis.description_revision = vacancy.description_revision
              AND analysis.description_snapshot = vacancy.description
              AND vacancy.match_percent IS NOT NULL
            """,
            (resume_id,),
        ).fetchall()
        current_vacancy_ids = [int(item["vacancy_id"]) for item in current_vacancy_rows]

        connection.execute(
            """
            UPDATE resume_versions
            SET label = '', original_filename = NULL, original_path = NULL,
                extracted_text_path = NULL, content_text = '', is_submitted = 0,
                deleted_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (resume_id,),
        )
        if scrubbed_results:
            connection.executemany(
                "UPDATE ats_analyses SET result_json = ? WHERE id = ?",
                scrubbed_results,
            )
        if current_vacancy_ids:
            connection.executemany(
                "UPDATE vacancies SET match_percent = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                ((vacancy_id,) for vacancy_id in current_vacancy_ids),
            )
        if resume["vacancy_id"] is not None:
            connection.execute(
                """
                INSERT INTO timeline_events(vacancy_id, event_type, title, details)
                VALUES (?, 'resume_deleted', ?, 'Resume content and stored files redacted')
                """,
                (
                    resume["vacancy_id"],
                    f"Resume v{resume['version']} deleted",
                ),
            )

        files_removed = bool(folder and (folder.exists() or folder.is_symlink()))
        if files_removed:
            shutil.rmtree(folder)
        deleted_at = connection.execute(
            "SELECT deleted_at FROM resume_versions WHERE id = ?", (resume_id,)
        ).fetchone()[0]
        return {
            "id": resume_id,
            "kind": resume["kind"],
            "version": resume["version"],
            "vacancy_id": resume["vacancy_id"],
            "deleted_at": deleted_at,
            "already_deleted": False,
            "files_removed": files_removed,
            "ats_analyses_preserved": analysis_count,
            "current_matches_cleared": len(current_vacancy_ids),
            "reports_redacted": reports_redacted,
        }


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
        insert_funnel_event(
            connection, resume["vacancy_id"], "application_submitted",
            metadata={"resume_version_id": resume_id},
        )
    updated = get_resume(database, resume_id)
    if updated is None:
        raise RuntimeError("Submitted resume could not be loaded")
    return updated
