"""Explicit, provenance-bound Codex assessments for resume quality and vacancy fit."""

from __future__ import annotations

import hashlib
import json
import re

from .codex import (
    CodexError,
    build_prompt,
    load_model_catalog,
    run_codex,
    validate_model_effort,
)
from .db import Database, insert_and_get_id


ASSESSMENT_SCHEMA_VERSION = 1
RUBRIC_VERSION = "manager-resume-2026-01"
_KINDS = {"manager_audit", "vacancy_match"}
_SCORE_WEIGHTS = {
    "Evidence": 0.25,
    "RoleClarity": 0.20,
    "AntiPersonaClean": 0.20,
    "TenSecondRead": 0.15,
    "KeywordFit": 0.10,
    "Structure": 0.10,
}
_ANTI_PERSONAS = (
    "Project administrator",
    "Project proxy",
    "Ritual agile PM",
    "Unimmersed delivery manager",
    "Manager-router",
    "General management without domain",
)
_TEN_SECOND_CHECKS = ("grade", "domain", "first_bullet_impact", "scope", "tools")


def _assessment_prompt(kind: str, locale: str, resume_lines: str, vacancy: dict | None) -> str:
    if kind == "manager_audit":
        if locale == "ru":
            instruction = """Проведи строгий аудит резюме менеджера проекта/доставки/технологий/продукта только по переданному резюме. Верни JSON-объект с полями: overall_summary; role_family (claimed_family, claimed_grade, supported_family, supported_grade, mismatch, quotes); grade_inflation (claimed_title_or_years, supported_family_years, severity, line_refs); anti_persona_flags (ровно шесть объектов, по одному для Project administrator, Project proxy, Ritual agile PM, Unimmersed delivery manager, Manager-router, General management without domain; у каждого status=CLEAR|PARTIAL|NONE, quotes и line_refs); evidence_review (объекты line_ref, quote, category=achievement|process|scope|noise, xyz_verdict=PASS|WEAK|FAIL|SCOPE|NOISE, xyz_assessment, attribution); structure (rubric=T, export_quality, header, chronology, skills, length, limitations); ten_second_read (ровно пять объектов по check=grade|domain|first_bullet_impact|scope|tools, result и line_refs); scores (Evidence, RoleClarity, AntiPersonaClean, TenSecondRead, KeywordFit, Structure — каждое число 0.00–1.00); overall_score_percent (целое 0–100); weighted_sum (раскрой веса 0.25/0.20/0.20/0.15/0.10/0.10 и арифметику); verdict; priority_improvements (не более пяти объектов issue, direction, line_refs); limitations. Используй стабильные ссылки L1, L2 и так далее. PASS достижение требует X+Y+Z (действие, изменение, измеримый результат/артефакт/срок); командный размер, процесс и неподтверждённые метрики не считай достижением; проверь личную атрибуцию и vanity metrics. Для каждой жёсткой оценки приводи цитату. Примени Rubric T, если структуры по тексту можно судить. Давай только направления исправления: не пиши готовые буллеты, абзацы или текст для вставки. Не придумывай опыт. Отсутствие свидетельства означает лишь «не подтверждено этим резюме». Для фото, колонок и визуальной структуры укажи, что это нельзя оценить по переданному тексту."""
        else:
            instruction = """Perform a strict audit of a project/delivery/technical/product manager resume using only the supplied resume. Return JSON with: overall_summary; role_family (claimed_family, claimed_grade, supported_family, supported_grade, mismatch, quotes); grade_inflation (claimed_title_or_years, supported_family_years, severity, line_refs); anti_persona_flags (exactly six objects named Project administrator, Project proxy, Ritual agile PM, Unimmersed delivery manager, Manager-router, General management without domain; each with status=CLEAR|PARTIAL|NONE, quotes, line_refs); evidence_review (objects with line_ref, quote, category=achievement|process|scope|noise, xyz_verdict=PASS|WEAK|FAIL|SCOPE|NOISE, xyz_assessment, attribution); structure (rubric=T, export_quality, header, chronology, skills, length, limitations); ten_second_read (exactly five objects for check=grade|domain|first_bullet_impact|scope|tools, result, line_refs); scores (Evidence, RoleClarity, AntiPersonaClean, TenSecondRead, KeywordFit, Structure, each 0.00–1.00); overall_score_percent (integer 0–100); weighted_sum (show weights 0.25/0.20/0.20/0.15/0.10/0.10 and arithmetic); verdict; priority_improvements (at most five objects with issue, direction, line_refs); limitations. Cite stable references L1, L2, etc. An achievement PASS requires X+Y+Z (action, change, measurable result/artifact/time); team size, process and unattributed metrics are not achievements. Check personal attribution and employer vanity metrics. Back every hard verdict with a quote. Use Rubric T where structure can be assessed from text. Give fix directions only; do not write paste-ready bullets or resume sections. Do not invent experience. Missing evidence means only not evidenced in this resume. State that photos, columns, and visual structure cannot be assessed from supplied text."""
    else:
        if locale == "ru":
            instruction = """Сопоставь резюме с конкретной вакансией по требованиям. Верни JSON-объект с полями overall_summary, requirements (массив объектов requirement, status=covered|partial|not_evidenced|insufficient_input, resume_line_refs, vacancy_quote, explanation), strengths, gaps, limitations. Ссылайся только на строки резюме L1, L2 и так далее; для требований цитируй короткий фрагмент описания вакансии. Не считай отсутствие свидетельства доказательством отсутствия навыка. Не указывай вероятность трудоустройства и не выдумывай общий процент. Если описание вакансии недостаточно, используй insufficient_input."""
        else:
            instruction = """Compare the resume with this specific vacancy's requirements. Return a JSON object with overall_summary, requirements (objects with requirement, status=covered|partial|not_evidenced|insufficient_input, resume_line_refs, vacancy_quote, explanation), strengths, gaps, and limitations. Cite only resume lines L1, L2, etc.; cite a short vacancy-description quote for each requirement. Missing evidence is not proof that the candidate lacks a skill. Do not give probability of employment or invent an overall percentage. Use insufficient_input if the vacancy description is inadequate."""

    vacancy_text = ""
    if vacancy is not None:
        vacancy_text = f"\n\n--- CONFIRMED VACANCY DESCRIPTION ---\n{vacancy['description']}\n--- END VACANCY DESCRIPTION ---"
    user_prompt = f"{instruction}\n\n--- SELECTED RESUME (stable line references) ---\n{resume_lines}\n--- END SELECTED RESUME ---{vacancy_text}"
    return user_prompt


def _extract_json(response: str) -> dict | None:
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", response).lstrip("\ufeff").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            result, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(result, dict):
            return result
    return None


def _validate_result(kind: str, payload: dict) -> str | None:
    if not isinstance(payload.get("overall_summary"), str):
        return "Assessment is missing overall_summary."
    if kind == "manager_audit":
        flags = payload.get("anti_persona_flags")
        checks = payload.get("ten_second_read")
        improvements = payload.get("priority_improvements")
        if not isinstance(flags, list) or len(flags) != 6:
            return "Manager audit must include exactly six risk checks."
        if not isinstance(checks, list) or len(checks) != 5:
            return "Manager audit must include exactly five recruiter-read checks."
        if not isinstance(improvements, list) or len(improvements) > 5:
            return "Manager audit can include at most five priority improvements."
        if any(not isinstance(item, dict) for item in flags + checks + improvements):
            return "Assessment sections must contain structured objects."
        if not isinstance(payload.get("role_family"), dict):
            return "Manager audit is missing the claimed-versus-supported role assessment."
        if not isinstance(payload.get("grade_inflation"), dict):
            return "Manager audit is missing the grade inflation check."
        if not isinstance(payload.get("evidence_review"), list):
            return "Manager audit is missing the evidence line review."
        if not payload.get("verdict"):
            return "Manager audit is missing the verdict."
        if {item.get("name") for item in flags if isinstance(item.get("name"), str)} != set(_ANTI_PERSONAS):
            return "Manager audit must use the six named manager risk checks."
        if any(item.get("status") not in ("CLEAR", "PARTIAL", "NONE") for item in flags):
            return "Manager risk checks must use CLEAR, PARTIAL, or NONE status."
        if {item.get("check") for item in checks if isinstance(item.get("check"), str)} != set(_TEN_SECOND_CHECKS):
            return "Manager audit is missing one or more recruiter-read checks."
        structure = payload.get("structure")
        if not isinstance(structure, dict) or structure.get("rubric") != "T":
            return "Manager audit must identify the applied structure rubric."
        scores = payload.get("scores")
        expected_axes = {
            "Evidence", "RoleClarity", "AntiPersonaClean", "TenSecondRead", "KeywordFit", "Structure"
        }
        if not isinstance(scores, dict) or not expected_axes.issubset(scores):
            return "Manager audit is missing one or more rubric scores."
        if any(isinstance(scores[axis], bool) or not isinstance(scores[axis], (int, float)) or not 0 <= scores[axis] <= 1 for axis in expected_axes):
            return "Rubric scores must be between 0 and 1."
    else:
        requirements = payload.get("requirements")
        if not isinstance(requirements, list) or any(not isinstance(item, dict) for item in requirements):
            return "Vacancy match is missing a structured requirement list."
        allowed_statuses = {"covered", "partial", "not_evidenced", "insufficient_input"}
        if any(item.get("status") not in allowed_statuses for item in requirements):
            return "Vacancy requirement status is unsupported."
        if "match_percent" in payload or "employment_probability" in payload:
            return "Vacancy match must not return a synthetic score or hiring probability."
    return None


def _line_referenced_resume(text: str) -> str:
    return "\n".join(f"L{index}: {line}" for index, line in enumerate(text.splitlines(), 1))


def _assessment_row(row: dict) -> dict:
    result = dict(row)
    result["result"] = json.loads(result.pop("result_json")) if result.get("result_json") else None
    result["resume_deleted"] = bool(result.pop("resume_deleted_at", None))
    current_vacancy = result.pop("current_description", None)
    current_revision = result.pop("current_description_revision", None)
    result["description_changed"] = result.get("vacancy_id") is not None and (
        current_revision != result.get("description_revision")
        or current_vacancy != result.get("description_snapshot")
    )
    current_hash = result.pop("current_resume_sha256", None)
    result["resume_changed"] = bool(current_hash and current_hash != result.get("resume_sha256"))
    result["is_stale"] = result["resume_deleted"] or result["resume_changed"] or result["description_changed"]
    return result


def list_assessments(
    database: Database, *, resume_version_id: int | None = None, vacancy_id: int | None = None
) -> list[dict]:
    clauses: list[str] = []
    params: list[int] = []
    if resume_version_id is not None:
        clauses.append("a.resume_version_id = ?")
        params.append(resume_version_id)
    if vacancy_id is not None:
        clauses.append("a.vacancy_id = ?")
        params.append(vacancy_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = database.fetch_all(
        f"""SELECT a.*, r.deleted_at AS resume_deleted_at,
                   r.content_text AS current_resume_text,
                   v.description AS current_description,
                   v.description_revision AS current_description_revision
            FROM ats_assessments a
            LEFT JOIN resume_versions r ON r.id = a.resume_version_id
            LEFT JOIN vacancies v ON v.id = a.vacancy_id
            {where} ORDER BY a.created_at DESC, a.id DESC""",
        tuple(params),
    )
    assessments = []
    for row in rows:
        resume_text = row.pop("current_resume_text", None)
        row["current_resume_sha256"] = hashlib.sha256(resume_text.encode()).hexdigest() if resume_text else None
        assessments.append(_assessment_row(row))
    return assessments


def create_assessment(
    database: Database,
    settings,
    *,
    kind: str,
    resume_version_id: int,
    vacancy_id: int | None,
    locale: str,
    model: str,
    reasoning_effort: str,
) -> dict:
    if kind not in _KINDS:
        raise ValueError("Unsupported assessment kind")
    if locale not in {"ru", "en"}:
        raise ValueError("Unsupported interface language")
    if kind == "vacancy_match" and vacancy_id is None:
        raise ValueError("Vacancy matching requires a vacancy")
    with database.connect() as connection:
        resume_row = connection.execute(
            "SELECT * FROM resume_versions WHERE id = ? AND deleted_at IS NULL", (resume_version_id,)
        ).fetchone()
        if resume_row is None:
            raise LookupError("Resume not found")
        resume = dict(resume_row)
        vacancy = None
        if vacancy_id is not None:
            vacancy_row = connection.execute("SELECT * FROM vacancies WHERE id = ?", (vacancy_id,)).fetchone()
            if vacancy_row is None:
                raise LookupError("Vacancy not found")
            vacancy = dict(vacancy_row)
            if resume["kind"] == "vacancy" and resume["vacancy_id"] != vacancy_id:
                raise ValueError("This resume belongs to a different vacancy")
            if kind == "vacancy_match" and not vacancy["description_confirmed_at"]:
                raise ValueError("Review and confirm the vacancy description before matching")
    catalog = load_model_catalog(settings)
    selected_model, selected_effort = validate_model_effort(catalog, model, reasoning_effort)
    prompt = _assessment_prompt(kind, locale, _line_referenced_resume(resume["content_text"]), vacancy)
    context = "This is a user-requested resume assessment. Use only the explicitly selected resume and, for vacancy matching, the confirmed description included in the user request."
    response_language = "russian" if locale == "ru" else "english"
    final_prompt = build_prompt(prompt, context, kind, response_language)
    try:
        response = run_codex(
            settings, final_prompt, model=selected_model, reasoning_effort=selected_effort
        ).response
    except (CodexError, ValueError):
        raise
    parsed = _extract_json(response)
    validation_error = _validate_result(kind, parsed) if parsed is not None else "Codex did not return a valid JSON object."
    is_completed = parsed is not None and validation_error is None
    if is_completed and kind == "manager_audit":
        weighted_total = sum(float(parsed["scores"][axis]) * weight for axis, weight in _SCORE_WEIGHTS.items())
        parsed["overall_score_percent"] = round(weighted_total * 100)
        parsed["weighted_sum"] = {
            "weights": _SCORE_WEIGHTS,
            "arithmetic": " + ".join(
                f"{weight:.2f}×{float(parsed['scores'][axis]):.2f}" for axis, weight in _SCORE_WEIGHTS.items()
            ),
            "total": round(weighted_total, 4),
        }
    result_payload = parsed if is_completed else {"response_format_error": validation_error}
    resume_sha256 = hashlib.sha256(resume["content_text"].encode()).hexdigest()
    description_snapshot = vacancy["description"] if kind == "vacancy_match" and vacancy else None
    description_revision = vacancy["description_revision"] if description_snapshot is not None else None
    with database.transaction(immediate=True) as connection:
        current_resume = connection.execute(
            "SELECT deleted_at FROM resume_versions WHERE id = ?", (resume_version_id,)
        ).fetchone()
        if current_resume is None:
            raise LookupError("Resume not found")
        if vacancy_id is not None and kind == "vacancy_match":
            current_vacancy = connection.execute(
                "SELECT id FROM vacancies WHERE id = ?", (vacancy_id,)
            ).fetchone()
            if current_vacancy is None:
                raise LookupError("Vacancy not found")
        redacted_during_run = current_resume["deleted_at"] is not None
        if redacted_during_run:
            result_payload = {
                "redacted": True,
                "message": "Resume content was deleted while the assessment was running.",
            }
            response_to_store = ""
        else:
            response_to_store = response if is_completed else ""
        assessment_id = insert_and_get_id(
            connection,
            """INSERT INTO ats_assessments(
                schema_version, assessment_kind, engine, rubric_version,
                prompt_template_id, prompt_template_version, resume_version_id,
                resume_kind, resume_version, resume_sha256, vacancy_id,
                description_snapshot, description_revision, locale, model, reasoning_effort,
                status, result_json, response
            ) VALUES (?, ?, 'codex', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ASSESSMENT_SCHEMA_VERSION, kind, RUBRIC_VERSION, f"ats.{kind}", 1, resume_version_id,
                resume["kind"], resume["version"], resume_sha256, vacancy_id if kind == "vacancy_match" else None,
                description_snapshot, description_revision, locale, selected_model, selected_effort,
                "completed" if is_completed else "invalid_response", json.dumps(result_payload, ensure_ascii=False),
                response_to_store,
            ),
        )
        if kind == "vacancy_match" and vacancy_id is not None:
            connection.execute(
                "INSERT INTO timeline_events(vacancy_id, event_type, title, details) VALUES (?, 'ats_review_completed', 'AI resume-to-vacancy review completed', ?)",
                (vacancy_id, f"Assessment #{assessment_id} · Resume v{resume['version']}"),
            )
        if redacted_during_run:
            connection.execute(
                "UPDATE ats_assessments SET redacted_at = CURRENT_TIMESTAMP WHERE id = ?",
                (assessment_id,),
            )
    return next((item for item in list_assessments(database) if item["id"] == assessment_id), {})
