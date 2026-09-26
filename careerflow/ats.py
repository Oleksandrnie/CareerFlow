"""Deterministic, evidence-based MVP ATS matching engine."""

from __future__ import annotations

import json
import re
from collections import Counter

from .db import Database, insert_and_get_id


STOP_WORDS = {
    "about", "after", "also", "and", "are", "but", "can", "for", "from", "have",
    "into", "its", "job", "our", "role", "that", "the", "their", "this", "using",
    "with", "will", "work", "you", "your", "для", "или", "как", "команда", "на",
    "не", "опыт", "от", "по", "работа", "с", "со", "требования", "что", "это",
}

GENERIC_REQUIREMENT_WORDS = {
    "experience", "knowledge", "must", "need", "preferred", "proficiency",
    "required", "requirement", "requirements", "skill", "skills",
    "знание", "знания", "навык", "навыки", "опыт", "требование", "требования",
}

NEGATION = re.compile(
    r"(?i)\b(?:no|not|never|without|lack(?:ing|s)?|cannot|can't|don't|"
    r"нет|без|не|отсутств\w*)\b"
)
YEARS = re.compile(
    r"(?i)\b(\d+(?:[.,]\d+)?)\s*\+?\s*(?:years?|yrs?|лет|года?|год)\b"
)


def _years_amounts(text: str) -> list[float]:
    return [float(match.replace(",", ".")) for match in YEARS.findall(text)]


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for raw_token in re.findall(
        r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9+#.\-/]{1,}", text
    ):
        # Keep meaningful in-token punctuation (for example C++, C#, Node.js,
        # and CI/CD), but do not let sentence punctuation change keyword identity.
        token = raw_token.lower().strip(".-/")
        if token and token not in STOP_WORDS:
            tokens.append(token)
    return tokens


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def _requirements(text: str) -> list[str]:
    lines = _sentences(text)
    signals = re.compile(
        r"(?i)\b(required|requirements?|must|need|experience|knowledge|skills?|proficien|обязанност|требован|опыт|знани|навык)\b"
    )
    selected = [line for line in lines if signals.search(line) and len(_tokens(line)) >= 2]
    if len(selected) < 3:
        selected.extend(line for line in lines if line not in selected and len(_tokens(line)) >= 3)
    return selected[:12]


def analyze(vacancy_text: str, resume_text: str) -> dict:
    resume_tokens = set(_tokens(resume_text))
    vacancy_counts = Counter(_tokens(vacancy_text))
    keywords = [word for word, _ in vacancy_counts.most_common(24)]
    resume_sentences = _sentences(resume_text)
    requirement_results: list[dict] = []

    for requirement in _requirements(vacancy_text):
        requirement_tokens = set(_tokens(requirement))
        if not requirement_tokens:
            continue
        distinctive_tokens = requirement_tokens - GENERIC_REQUIREMENT_WORDS
        if not distinctive_tokens:
            distinctive_tokens = requirement_tokens
        overlap = requirement_tokens & resume_tokens
        coverage = len(overlap) / len(requirement_tokens)
        required_years = max(_years_amounts(requirement), default=None)
        best_evidence = ""
        best_score = (-1, -1, -1)
        best_negative = False
        best_years_ok = True
        for sentence in resume_sentences:
            sentence_tokens = set(_tokens(sentence))
            if not (distinctive_tokens & sentence_tokens):
                continue
            negative = bool(NEGATION.search(sentence))
            stated_years = _years_amounts(sentence)
            years_ok = required_years is None or (
                bool(stated_years) and min(stated_years) >= required_years
            )
            score = (
                int(not negative and years_ok),
                len(distinctive_tokens & sentence_tokens),
                len(requirement_tokens & sentence_tokens),
            )
            if score > best_score:
                best_score = score
                best_evidence = sentence
                best_negative = negative
                best_years_ok = years_ok
        if coverage >= 0.6:
            classification = "covered"
        elif coverage >= 0.2:
            classification = "partial"
        else:
            classification = "missing"
            best_evidence = ""
        if classification == "covered" and (not best_evidence or best_negative or not best_years_ok):
            classification = "partial"
        if classification == "partial" and best_negative:
            interpretation = "Negative wording is present; this does not confirm the required experience"
        elif classification == "partial" and not best_years_ok:
            interpretation = "The required years are not evidenced by this resume sentence"
        elif classification == "covered":
            interpretation = "Evidence found in this resume version"
        elif classification == "partial":
            interpretation = "Some related evidence is present; the requirement may be under-described"
        else:
            interpretation = "Not evidenced in this resume version; this does not prove the experience is absent"
        requirement_results.append(
            {
                "requirement": requirement,
                "classification": classification,
                "matched_keywords": sorted(overlap),
                "evidence": best_evidence[:420],
                "interpretation": interpretation,
            }
        )

    keyword_overlap = [word for word in keywords if word in resume_tokens]
    keyword_score = len(keyword_overlap) / max(1, len(keywords))
    requirement_score = (
        sum(1 if item["classification"] == "covered" else 0.5 if item["classification"] == "partial" else 0 for item in requirement_results)
        / max(1, len(requirement_results))
    )
    match_percent = round((keyword_score * 0.4 + requirement_score * 0.6) * 100)
    return {
        "match_percent": max(0, min(100, match_percent)),
        "keywords": keywords,
        "covered_keywords": keyword_overlap,
        "missing_keywords": [word for word in keywords if word not in resume_tokens],
        "requirements": requirement_results,
        "counts": {
            "covered": sum(item["classification"] == "covered" for item in requirement_results),
            "partial": sum(item["classification"] == "partial" for item in requirement_results),
            "missing": sum(item["classification"] == "missing" for item in requirement_results),
        },
        "disclaimer": "Heuristic text comparison only. Missing means not evidenced in this resume version, not that the candidate lacks the experience.",
    }


def run_analysis(database: Database, vacancy_id: int, resume_id: int) -> dict:
    with database.transaction(immediate=True) as connection:
        vacancy = connection.execute(
            "SELECT * FROM vacancies WHERE id = ?", (vacancy_id,)
        ).fetchone()
        if vacancy is None:
            raise LookupError("Vacancy not found")
        resume = connection.execute(
            "SELECT * FROM resume_versions WHERE id = ?", (resume_id,)
        ).fetchone()
        if resume is None:
            raise LookupError("Resume not found")
        if resume["kind"] == "vacancy" and resume["vacancy_id"] != vacancy_id:
            raise ValueError("This resume belongs to a different vacancy")
        result = analyze(vacancy["description"], resume["content_text"])
        analysis_id = insert_and_get_id(
            connection,
            """
            INSERT INTO ats_analyses(
                vacancy_id, resume_version_id, match_percent, result_json,
                description_snapshot, description_revision,
                resume_kind_at_analysis, resume_version_at_analysis
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vacancy_id, resume_id, result["match_percent"],
                json.dumps(result, ensure_ascii=False), vacancy["description"],
                vacancy["description_revision"], resume["kind"], resume["version"],
            ),
        )
        connection.execute(
            "UPDATE vacancies SET match_percent = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (result["match_percent"], vacancy_id),
        )
        connection.execute(
            """
            INSERT INTO timeline_events(vacancy_id, event_type, title, details)
            VALUES (?, 'ats_completed', 'ATS analysis completed', ?)
            """,
            (vacancy_id, f"Match: {result['match_percent']}% · Resume v{resume['version']}"),
        )
    return get_analysis(database, analysis_id) or {}


def _load_analysis(database: Database, query: str, params: tuple[int, ...]) -> dict | None:
    row = database.fetch_one(query, params)
    if row:
        current_revision = row.pop("current_description_revision")
        current_description = row.pop("current_description")
        row["is_stale"] = (
            row["description_revision"] is None
            or row["description_revision"] != current_revision
            or row["description_snapshot"] != current_description
        )
        row["result"] = json.loads(row.pop("result_json"))
    return row


def get_analysis(database: Database, analysis_id: int) -> dict | None:
    return _load_analysis(
        database,
        """
        SELECT a.*, v.description_revision AS current_description_revision,
               v.description AS current_description
        FROM ats_analyses AS a JOIN vacancies AS v ON v.id = a.vacancy_id
        WHERE a.id = ?
        """,
        (analysis_id,),
    )


def latest_analysis(database: Database, vacancy_id: int) -> dict | None:
    return _load_analysis(
        database,
        """
        SELECT a.*, v.description_revision AS current_description_revision,
               v.description AS current_description
        FROM ats_analyses AS a JOIN vacancies AS v ON v.id = a.vacancy_id
        WHERE a.vacancy_id = ? ORDER BY a.created_at DESC, a.id DESC LIMIT 1
        """,
        (vacancy_id,),
    )
