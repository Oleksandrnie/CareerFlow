"""Portable Markdown context reports for a vacancy."""

from __future__ import annotations

import difflib
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from .ats import latest_analysis
from .db import Database, insert_and_get_id
from .resumes import get_resume, list_resumes
from .tracking import interviews, list_attachments, list_notes, timeline
from .vacancies import get_vacancy


MAX_TEXT_ATTACHMENT_CHARS = 200_000


def _heading(value: str) -> str:
    return value.replace("\n", " ").strip()


def _resume_changes(versions: list[dict]) -> list[str]:
    ordered = list(reversed(versions))
    lines: list[str] = []
    previous_words: list[str] | None = None
    for version in ordered:
        words = version["content_text"].split()
        detail = f"{len(words)} words"
        if previous_words is not None:
            diff = list(difflib.ndiff(previous_words, words))
            added = sum(item.startswith("+ ") for item in diff)
            removed = sum(item.startswith("- ") for item in diff)
            detail += f", +{added}/-{removed} words vs previous version"
        marker = " — SUBMITTED" if version["is_submitted"] else ""
        lines.append(
            f"- Vacancy Resume v{version['version']}: {version['label'] or 'No label'} ({detail}){marker}"
        )
        previous_words = words
    return lines


def _build_report_context(
    database: Database, vacancy_id: int, *, include_raw: bool = False
) -> tuple[str, dict]:
    vacancy = get_vacancy(database, vacancy_id)
    if vacancy is None:
        raise LookupError("Vacancy not found")
    analysis = latest_analysis(database, vacancy_id)
    versions = list_resumes(database, "vacancy", vacancy_id)
    submitted = next((item for item in versions if item["is_submitted"]), None)
    selected = submitted or (versions[0] if versions else None)
    analyzed_resume = get_resume(database, analysis["resume_version_id"]) if analysis else None
    events = timeline(database, vacancy_id)
    interview_rows = interviews(database, vacancy_id)
    notes = list_notes(database, vacancy_id)
    attachments = list_attachments(database, vacancy_id)

    lines = [
        f"# {_heading(vacancy['title'])} — {_heading(vacancy['company'] or 'Company not set')}",
        "",
        "> CareerFlow local context report. Verify all details before sharing externally.",
        "",
        "## Overview",
        "",
        f"- Status: {vacancy['status']}",
        f"- Salary: {vacancy['salary'] or 'Not specified'}",
        f"- Source: {vacancy['source'] or vacancy['source_type']}",
        f"- Added: {vacancy['created_at']}",
        f"- Latest match: {str(vacancy['match_percent']) + '%' if vacancy['match_percent'] is not None else 'Not analyzed'}",
        "",
        vacancy["summary"] or "No summary.",
        "",
        "## Vacancy description",
        "",
        vacancy["description"],
        "",
    ]
    if include_raw:
        lines.extend(
            [
                "## Diagnostic raw vacancy description",
                "",
                vacancy["raw_description"] or vacancy["description"],
                "",
            ]
        )
    lines.extend(["## Resume context", ""])
    if selected:
        lines.extend(
            [
                f"Workflow resume: {'submitted' if selected['is_submitted'] else 'latest'} Vacancy Resume v{selected['version']} (ID {selected['id']}; {selected['label'] or 'No label'}).",
                "",
                selected["content_text"],
                "",
                "### Version history and changes",
                "",
                *_resume_changes(versions),
            ]
        )
    else:
        lines.append("No vacancy-specific resume version has been added.")

    if analysis:
        analyzed_kind = analysis["resume_kind_at_analysis"] or (
            analyzed_resume["kind"] if analyzed_resume else "unknown"
        )
        analyzed_version = analysis["resume_version_at_analysis"] or (
            analyzed_resume["version"] if analyzed_resume else "unknown"
        )
        lines.extend(
            [
                "",
                "### Resume used for ATS analysis",
                "",
                f"{str(analyzed_kind).title()} Resume v{analyzed_version} (ID {analysis['resume_version_id']}).",
                "",
            ]
        )
        if analysis["resume_deleted"]:
            lines.extend(
                [
                    "This resume version was deleted and its content was redacted.",
                ]
            )
        elif analyzed_resume and selected and selected["id"] == analyzed_resume["id"]:
            lines.append("Same resume as the workflow version shown above.")
        elif analyzed_resume:
            lines.extend(
                [
                    "This differs from the workflow resume shown above.",
                    "",
                    analyzed_resume["content_text"],
                ]
            )

    lines.extend(["", "## ATS analysis", ""])
    if analysis:
        result = analysis["result"]
        lines.extend(
            [
                f"Analysis ID: {analysis['id']} · Resume ID: {analysis['resume_version_id']} · Run: {analysis['created_at']}",
                "",
                (
                    f"Historical match (not current): **{analysis['match_percent']}%**"
                    if analysis["is_stale"]
                    else f"Current match: **{analysis['match_percent']}%**"
                ),
                "",
                f"> {result['disclaimer']}",
                "",
                f"Keywords: {', '.join(result['keywords']) or 'None'}",
                "",
            ]
        )
        if analysis["is_stale"]:
            lines.extend(
                [
                    "This ATS result is stale or has unknown legacy provenance; rerun analysis for the current vacancy description.",
                    "",
                ]
            )
            if analysis["description_snapshot"] is not None:
                lines.extend(
                    [
                        "### Vacancy description analyzed at that time",
                        "",
                        analysis["description_snapshot"],
                        "",
                    ]
                )
        if analysis["resume_deleted"]:
            lines.extend(
                [
                    "Resume-derived evidence is omitted because the analyzed resume was deleted.",
                    "",
                ]
            )
        for classification in ("covered", "partial", "missing"):
            lines.extend([f"### {classification.title()}", ""])
            matching = [
                item for item in result["requirements"] if item["classification"] == classification
            ]
            if not matching:
                lines.append("- None")
            for item in matching:
                lines.append(f"- {item['requirement']}")
                lines.append(f"  - Interpretation: {item['interpretation']}")
                if item["evidence"] and not analysis["resume_deleted"]:
                    lines.append(f"  - Evidence: “{item['evidence']}”")
            lines.append("")
    else:
        lines.append("No ATS analysis has been run.")

    lines.extend(["", "## Timeline", ""])
    lines.extend(
        f"- {event['event_at']} — **{event['title']}**{': ' + event['details'] if event['details'] else ''}"
        for event in reversed(events)
    )
    lines.extend(["", "## Interviews", ""])
    if interview_rows:
        lines.extend(
            f"- Interview #{item['sequence_number']} ({item['interview_at']}, {item['interview_type']}): {item['note'] or 'No note'}{'; result: ' + item['result'] if item['result'] else ''}"
            for item in reversed(interview_rows)
        )
    else:
        lines.append("No interviews recorded.")

    lines.extend(["", "## Notes", ""])
    if notes:
        for note in reversed(notes):
            lines.extend([f"### {note['created_at']}", "", note["body"], ""])
    else:
        lines.append("No notes recorded.")

    lines.extend(["", "## Attachments", ""])
    if not attachments:
        lines.append("No attachments.")
    for attachment in attachments:
        lines.append(
            f"- {attachment['filename']} ({attachment['media_type']}, {attachment['size_bytes']} bytes)"
        )
        if attachment["is_text"]:
            try:
                content = Path(attachment["stored_path"]).read_text(
                    encoding="utf-8", errors="replace"
                )
                lines.extend(
                    [
                        "",
                        f"### Text: {attachment['filename']}",
                        "",
                        content[:MAX_TEXT_ATTACHMENT_CHARS],
                        "",
                    ]
                )
            except OSError:
                lines.append("  - Text content is unavailable on disk.")
    included_resumes = [item for item in (selected, analyzed_resume) if item]
    source_resume = selected or analyzed_resume
    sources = {
        "vacancy_description_revision": vacancy["description_revision"],
        "vacancy_description_sha256": hashlib.sha256(
            vacancy["description"].encode("utf-8")
        ).hexdigest(),
        "resume_version_id": source_resume["id"] if source_resume else None,
        "workflow_resume_id": selected["id"] if selected else None,
        "ats_analysis_id": analysis["id"] if analysis else None,
        "ats_resume_id": analysis["resume_version_id"] if analysis else None,
        "included_resume_ids": sorted({item["id"] for item in included_resumes}),
    }
    return "\n".join(lines).strip() + "\n", sources


def build_report(database: Database, vacancy_id: int, *, include_raw: bool = False) -> str:
    return _build_report_context(database, vacancy_id, include_raw=include_raw)[0]


def build_report_with_sources(database: Database, vacancy_id: int) -> tuple[str, dict]:
    """Return AI report text and provenance from the same assembled inputs."""
    return _build_report_context(database, vacancy_id)


def save_report(
    database: Database, storage_dir: Path, vacancy_id: int, *, include_raw: bool = False
) -> dict:
    markdown = build_report(database, vacancy_id, include_raw=include_raw)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    path = storage_dir / "reports" / str(vacancy_id) / f"careerflow-{vacancy_id}-{timestamp}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    with database.transaction() as connection:
        report_id = insert_and_get_id(
            connection,
            "INSERT INTO generated_reports(vacancy_id, stored_path) VALUES (?, ?)",
            (vacancy_id, str(path)),
        )
        connection.execute(
            "INSERT INTO timeline_events(vacancy_id, event_type, title, details) VALUES (?, 'report_generated', 'Markdown report generated', ?)",
            (vacancy_id, path.name),
        )
    return {
        "id": report_id,
        "vacancy_id": vacancy_id,
        "filename": path.name,
        "stored_path": str(path),
        "markdown": markdown,
    }


def get_report(database: Database, vacancy_id: int, report_id: int) -> dict:
    report = database.fetch_one(
        "SELECT * FROM generated_reports WHERE id = ? AND vacancy_id = ?", (report_id, vacancy_id)
    )
    if report is None:
        raise LookupError("Report not found")
    return report
