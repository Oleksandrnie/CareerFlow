"""Curated, provenance-aware context for vacancy-tailored resume generation."""

from __future__ import annotations

from hashlib import sha256
import json

from .ats import latest_analysis
from .db import Database
from .resumes import list_resumes
from .vacancies import get_vacancy


TAILORED_RESUME_ACTION = "Create tailored resume"
RELEVANT_ACTIONS = (
    "Analyze vacancy",
    "Improve resume",
    "Match resume to vacancy",
    "Review ATS analysis",
)
CANDIDATE_ACTIONS = frozenset(RELEVANT_ACTIONS) - {"Analyze vacancy"}


def _legacy_action(prompt: str) -> str:
    """Classify runs created before ai_runs.action existed."""
    normalized = prompt.strip().lower()
    prefixes = {
        "analyze the role": "Analyze vacancy",
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


def _description_sha256(description: str) -> str:
    return sha256(description.encode("utf-8")).hexdigest()


def _int_value(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _run_sources(row: dict) -> tuple[dict, bool]:
    raw = (row.get("context_sources_json") or "").strip()
    if not raw:
        return {}, False
    try:
        sources = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}, False
    return (sources, True) if isinstance(sources, dict) else ({}, False)


def _referenced_resume_ids(row: dict, sources: dict) -> list[int]:
    ids: set[int] = set()
    for value in (
        row.get("source_resume_id"),
        sources.get("resume_version_id"),
        sources.get("workflow_resume_id"),
        sources.get("ats_resume_id"),
    ):
        resume_id = _int_value(value)
        if resume_id is not None:
            ids.add(resume_id)
    included = sources.get("included_resume_ids")
    if isinstance(included, list):
        for value in included:
            resume_id = _int_value(value)
            if resume_id is not None:
                ids.add(resume_id)
    return sorted(ids)


def _unavailable_resume_ids(database: Database, resume_ids: list[int]) -> list[int]:
    if not resume_ids:
        return []
    placeholders = ",".join("?" for _ in resume_ids)
    rows = database.fetch_all(
        f"SELECT id, deleted_at FROM resume_versions WHERE id IN ({placeholders})",  # nosec B608
        tuple(resume_ids),
    )
    states = {int(row["id"]): row["deleted_at"] for row in rows}
    return [
        resume_id
        for resume_id in resume_ids
        if states.get(resume_id) is not None or resume_id not in states
    ]


def _evaluate_run(
    database: Database,
    vacancy: dict,
    resume: dict,
    action: str,
    row: dict,
) -> dict:
    sources, valid_sources_json = _run_sources(row)
    resume_ids = _referenced_resume_ids(row, sources)
    metadata = {
        "run_id": row["id"],
        "included": True,
        "provenance_status": "legacy_unknown",
        "source_resume_id": _int_value(row.get("source_resume_id")),
        "report_source_resume_id": _int_value(sources.get("resume_version_id")),
        "workflow_resume_id": _int_value(sources.get("workflow_resume_id")),
        "ats_analysis_id": _int_value(sources.get("ats_analysis_id")),
        "ats_resume_id": _int_value(sources.get("ats_resume_id")),
        "included_resume_ids": resume_ids,
        "vacancy_description_revision": _int_value(sources.get("vacancy_description_revision")),
        "vacancy_description_sha256": (
            sources.get("vacancy_description_sha256")
            if isinstance(sources.get("vacancy_description_sha256"), str)
            else None
        ),
        "omission_reason": None,
    }
    has_recorded_provenance = bool(row.get("source_resume_id")) or (
        valid_sources_json and bool(sources)
    )
    if not has_recorded_provenance:
        metadata["warning"] = (
            "Legacy run: its source resume and vacancy snapshot were not recorded. "
            "It may be stale and is advisory only."
        )
        return metadata

    unavailable_ids = _unavailable_resume_ids(database, resume_ids)
    if unavailable_ids:
        metadata.update(
            included=False,
            provenance_status="omitted_deleted_source",
            omission_reason=(
                "Referenced resume material is deleted or unavailable "
                f"(resume IDs: {', '.join(map(str, unavailable_ids))})."
            ),
        )
        return metadata

    recorded_revision = metadata["vacancy_description_revision"]
    recorded_hash = metadata["vacancy_description_sha256"]
    current_hash = _description_sha256(vacancy["description"])
    if recorded_revision is not None and recorded_revision != vacancy["description_revision"]:
        metadata.update(
            included=False,
            provenance_status="omitted_vacancy_mismatch",
            omission_reason=(
                f"Run used vacancy description revision {recorded_revision}; "
                f"the current revision is {vacancy['description_revision']}."
            ),
        )
        return metadata
    if recorded_hash is not None and recorded_hash != current_hash:
        metadata.update(
            included=False,
            provenance_status="omitted_vacancy_mismatch",
            omission_reason="Run used a different vacancy description snapshot.",
        )
        return metadata

    recorded_source_id = (
        metadata["source_resume_id"]
        or metadata["workflow_resume_id"]
        or metadata["report_source_resume_id"]
    )
    if (
        action in CANDIDATE_ACTIONS
        and recorded_source_id is not None
        and recorded_source_id != resume["id"]
    ):
        metadata.update(
            included=False,
            provenance_status="omitted_resume_mismatch",
            omission_reason=(
                f"Run used resume ID {recorded_source_id}; the selected source resume "
                f"is ID {resume['id']}."
            ),
        )
        return metadata
    foreign_resume_ids = [resume_id for resume_id in resume_ids if resume_id != resume["id"]]
    if action in CANDIDATE_ACTIONS and foreign_resume_ids:
        metadata.update(
            included=False,
            provenance_status="omitted_extra_resume_material",
            omission_reason=(
                "Run context also contained a different resume "
                f"(resume IDs: {', '.join(map(str, foreign_resume_ids))}); its response "
                "cannot safely be reused as candidate advice for the selected source resume."
            ),
        )
        return metadata

    vacancy_verified = recorded_revision is not None and recorded_hash is not None
    source_verified = action == "Analyze vacancy" or recorded_source_id == resume["id"]
    if vacancy_verified and source_verified:
        metadata["provenance_status"] = "current_verified"
    else:
        metadata["provenance_status"] = "partial_unknown"
        metadata["warning"] = (
            "Recorded provenance is incomplete. Treat this run as potentially stale "
            "advice, never as candidate facts."
        )
    return metadata


def _ats_selection(analysis: dict | None, resume: dict) -> tuple[dict | None, str]:
    if analysis is None:
        return None, "No ATS analysis has been run."
    if analysis["is_stale"]:
        return None, (
            f"Latest ATS analysis {analysis['id']} is stale, has unknown legacy vacancy "
            "provenance, or references a deleted resume."
        )
    if analysis["resume_version_id"] != resume["id"]:
        return None, (
            f"Latest ATS analysis {analysis['id']} used resume ID "
            f"{analysis['resume_version_id']}, not selected source resume ID {resume['id']}."
        )
    return analysis, ""


def build_tailored_resume_context(database: Database, vacancy_id: int) -> tuple[str, dict]:
    """Build the constrained inputs and a compact provenance record for one generation."""
    vacancy = get_vacancy(database, vacancy_id)
    if vacancy is None:
        raise LookupError("Vacancy not found")
    if not vacancy["description_confirmed_at"]:
        raise ValueError(
            "Review and confirm the vacancy description before generating a tailored resume"
        )
    resume = current_source_resume(database, vacancy_id)
    if resume is None:
        raise ValueError("Create a Master Resume before generating a tailored resume")
    latest_ats = latest_analysis(database, vacancy_id)
    analysis, ats_omission_reason = _ats_selection(latest_ats, resume)
    runs = _latest_relevant_runs(database, vacancy_id)
    run_metadata = {
        action: _evaluate_run(database, vacancy, resume, action, run)
        for action, run in runs.items()
    }

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
        "## Vacancy fields",
        "",
        f"- Vacancy ID: {vacancy['id']}",
        f"- Title: {vacancy['title'] or 'Not specified'}",
        f"- Company: {vacancy['company'] or 'Not specified'}",
        f"- Salary: {vacancy['salary'] or 'Not specified'}",
        f"- Source: {vacancy['source'] or 'Not specified'}",
        f"- Source type: {vacancy['source_type'] or 'Not specified'}",
        f"- Status: {vacancy['status']}",
        f"- Summary: {vacancy['summary'] or 'Not specified'}",
        f"- Description revision: {vacancy['description_revision']}",
        f"- Description confirmed at: {vacancy['description_confirmed_at']}",
        "",
        "## Full confirmed vacancy description",
        "",
        vacancy["description"],
        "",
        "## Latest ATS analysis — unreliable advisory, never candidate facts",
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
        lines.append(f"ATS result omitted: {ats_omission_reason}")

    lines.extend(
        [
            "",
            "## Latest saved AI analyses and recommendations — advisory, not factual evidence",
            "",
        ]
    )
    if not runs:
        lines.append("No relevant saved AI recommendations are available.")
    for action in RELEVANT_ACTIONS:
        run = runs.get(action)
        if not run:
            continue
        metadata = run_metadata[action]
        if not metadata["included"]:
            lines.extend(
                [
                    f"### {action} (run {run['id']}, {run['created_at']})",
                    "",
                    f"Response omitted: {metadata['omission_reason']}",
                    "",
                ]
            )
            continue
        lines.extend(
            [
                f"### {action} (run {run['id']}, {run['created_at']})",
                "",
                f"Provenance status: {metadata['provenance_status']}.",
                *([metadata["warning"]] if metadata.get("warning") else []),
                "",
                run["response"],
                "",
            ]
        )

    sources = {
        "resume_version_id": resume["id"],
        "resume_kind": resume["kind"],
        "resume_version": resume["version"],
        "resume_selection": ("submitted" if resume["is_submitted"] else f"latest_{resume['kind']}"),
        "vacancy_id": vacancy["id"],
        "vacancy_description_revision": vacancy["description_revision"],
        "vacancy_description_sha256": _description_sha256(vacancy["description"]),
        "vacancy_description_confirmed_at": vacancy["description_confirmed_at"],
        "ats_analysis_id": analysis["id"] if analysis else None,
        "ats_candidate_analysis_id": latest_ats["id"] if latest_ats else None,
        "ats_inclusion_status": "included" if analysis else "omitted",
        "ats_omission_reason": ats_omission_reason or None,
        "ats_resume_id": latest_ats["resume_version_id"] if latest_ats else None,
        "ai_run_ids": {
            action: run["id"] for action, run in runs.items() if run_metadata[action]["included"]
        },
        "ai_run_sources": run_metadata,
    }
    return "\n".join(lines).strip() + "\n", sources


def tailored_resume_instructions() -> str:
    return (
        "Create a complete, polished resume tailored to this vacancy and return Markdown only. "
        "Before writing, analyze the full confirmed vacancy and directly compare it with the source "
        "resume. Use the latest included vacancy analysis, resume match, and improvement advice when "
        "available; if one is absent, perform that reasoning from the primary vacancy and source-resume "
        "text within this request without asking for or launching another run. The source resume section "
        "is the sole authority for candidate facts. Use the vacancy and prior AI advice only to prioritize, "
        "select, and truthfully rephrase facts already present there. Treat ATS as an optional, unreliable "
        "lexical hint: manually verify every useful ATS term or claim in the source resume, never use its "
        "score as a gate or quality target, and never force a keyword into an unsupported candidate fact. "
        "Do not invent or infer employers, roles, dates, education, certifications, skills, responsibilities, "
        "achievements, metrics, technologies, or years of experience. Preserve material dates and identity "
        "details. Omit unsupported claims rather than adding placeholders. Produce the full resume, not "
        "advice, a critique, a change list, reasoning, or commentary."
    )
