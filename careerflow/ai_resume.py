"""Curated, provenance-aware context for vacancy-tailored resume generation."""

from __future__ import annotations

import json

from .ats import latest_analysis
from .db import Database
from .resumes import list_resumes
from .vacancies import get_vacancy


TAILORED_RESUME_ACTION = "Create tailored resume"
RELEVANT_ACTIONS = (
    "Improve resume",
    "Match resume to vacancy",
    "Review ATS analysis",
)


def _legacy_action(prompt: str) -> str:
    """Classify runs created before ai_runs.action existed."""
    normalized = prompt.strip().lower()
    prefixes = {
        "suggest truthful improvements": "Improve resume",
        "compare the selected resume": "Match resume to vacancy",
        "review the heuristic ats": "Review ATS analysis",
    }
    return next(
        (action for prefix, action in prefixes.items() if normalized.startswith(prefix)),
        "",
    )


def current_source_resume(database: Database, vacancy_id: int) -> dict | None:
    """Return the workflow resume, falling back to the latest Master Resume."""
    versions = list_resumes(database, "vacancy", vacancy_id)
    submitted = next((item for item in versions if item["is_submitted"]), None)
    if submitted or versions:
        return submitted or versions[0]
    masters = list_resumes(database, "master")
    return masters[0] if masters else None


def _latest_relevant_runs(database: Database, vacancy_id: int) -> dict[str, dict]:
    rows = database.fetch_all(
        """
        SELECT * FROM ai_runs
        WHERE vacancy_id = ? AND status = 'completed' AND response != ''
        ORDER BY created_at DESC, id DESC
        """,
        (vacancy_id,),
    )
    latest: dict[str, dict] = {}
    for row in rows:
        action = (row.get("action") or "").strip() or _legacy_action(row["prompt"])
        if action in RELEVANT_ACTIONS and action not in latest:
            latest[action] = row
    return latest


def build_tailored_resume_context(database: Database, vacancy_id: int) -> tuple[str, dict]:
    """Build the constrained inputs and a compact provenance record for one generation."""
    vacancy = get_vacancy(database, vacancy_id)
    if vacancy is None:
        raise LookupError("Vacancy not found")
    resume = current_source_resume(database, vacancy_id)
    if resume is None:
        raise ValueError("Create a Master Resume before generating a tailored resume")
    analysis = latest_analysis(database, vacancy_id)
    runs = _latest_relevant_runs(database, vacancy_id)

    lines = [
        "# Tailored resume source context",
        "",
        "## Source resume — sole authority for candidate facts",
        "",
        f"{resume['kind'].title()} Resume v{resume['version']} (ID {resume['id']}; "
        f"{'submitted' if resume['is_submitted'] else 'latest'}; "
        f"{resume['label'] or 'No label'}).",
        "",
        resume["content_text"],
        "",
        "## Confirmed cleaned vacancy description",
        "",
        vacancy["description"],
        "",
        "## Latest ATS analysis — advisory, not a source of candidate facts",
        "",
    ]
    if analysis:
        lines.extend(
            [
                f"Analysis ID: {analysis['id']} · Resume ID: {analysis['resume_version_id']} "
                f"· {'historical/stale' if analysis['is_stale'] else 'current'}",
                "",
                json.dumps(analysis["result"], ensure_ascii=False, indent=2),
            ]
        )
    else:
        lines.append("No ATS analysis has been run.")

    lines.extend(
        [
            "",
            "## Latest saved AI recommendations — advisory, not factual evidence",
            "",
        ]
    )
    if not runs:
        lines.append("No relevant saved AI recommendations are available.")
    for action in RELEVANT_ACTIONS:
        run = runs.get(action)
        if not run:
            continue
        lines.extend(
            [
                f"### {action} (run {run['id']}, {run['created_at']})",
                "",
                run["response"],
                "",
            ]
        )

    sources = {
        "resume_version_id": resume["id"],
        "resume_kind": resume["kind"],
        "resume_version": resume["version"],
        "resume_selection": (
            "submitted" if resume["is_submitted"] else f"latest_{resume['kind']}"
        ),
        "ats_analysis_id": analysis["id"] if analysis else None,
        "ai_run_ids": {action: run["id"] for action, run in runs.items()},
    }
    return "\n".join(lines).strip() + "\n", sources


def tailored_resume_instructions() -> str:
    return (
        "Create a complete, polished resume tailored to this vacancy and return Markdown only. "
        "The source resume section is the sole authority for candidate facts. Use the vacancy, "
        "ATS analysis, and prior AI recommendations only to prioritize, select, and truthfully "
        "rephrase facts already present in the source resume. Do not invent or infer employers, "
        "roles, dates, education, certifications, skills, responsibilities, achievements, metrics, "
        "technologies, or years of experience. Do not turn an ATS keyword or AI suggestion into a "
        "candidate fact unless the source resume supports it. Preserve material dates and identity "
        "details. Omit unsupported claims rather than adding placeholders. Produce the full resume, "
        "not advice, a critique, a change list, or commentary."
    )
