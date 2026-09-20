"""Deterministic, evidence-based MVP ATS matching engine."""

from __future__ import annotations

import json
import re
from collections import Counter

from .db import Database, insert_and_get_id
from .resumes import get_resume
from .vacancies import get_vacancy


STOP_WORDS = {
    "about", "after", "also", "and", "are", "but", "can", "for", "from", "have",
    "into", "its", "job", "our", "role", "that", "the", "their", "this", "using",
    "with", "will", "work", "you", "your", "для", "или", "как", "команда", "на",
    "не", "опыт", "от", "по", "работа", "с", "со", "требования", "что", "это",
}


def _tokens(text: str) -> list[str]:
    return [
        token.lower()
        for token in re.findall(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9+#.\-/]{1,}", text)
        if token.lower() not in STOP_WORDS
    ]


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
        overlap = requirement_tokens & resume_tokens
        coverage = len(overlap) / len(requirement_tokens)
        best_evidence = ""
        best_overlap = 0
        for sentence in resume_sentences:
            sentence_overlap = len(requirement_tokens & set(_tokens(sentence)))
            if sentence_overlap > best_overlap:
                best_overlap = sentence_overlap
                best_evidence = sentence
        if coverage >= 0.6:
            classification = "covered"
        elif coverage >= 0.2:
            classification = "partial"
        else:
            classification = "missing"
            best_evidence = ""
        requirement_results.append(
            {
                "requirement": requirement,
                "classification": classification,
                "matched_keywords": sorted(overlap),
                "evidence": best_evidence[:420],
                "interpretation": (
                    "Evidence found in this resume version"
                    if classification == "covered"
                    else "Some related evidence is present; the requirement may be under-described"
                    if classification == "partial"
                    else "Not evidenced in this resume version; this does not prove the experience is absent"
                ),
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
    vacancy = get_vacancy(database, vacancy_id)
    if vacancy is None:
        raise LookupError("Vacancy not found")
    resume = get_resume(database, resume_id)
    if resume is None:
        raise LookupError("Resume not found")
    if resume["kind"] == "vacancy" and resume["vacancy_id"] != vacancy_id:
        raise ValueError("This resume belongs to a different vacancy")
    result = analyze(vacancy["description"], resume["content_text"])
    with database.transaction() as connection:
        analysis_id = insert_and_get_id(
            connection,
            """
            INSERT INTO ats_analyses(vacancy_id, resume_version_id, match_percent, result_json)
            VALUES (?, ?, ?, ?)
            """,
            (vacancy_id, resume_id, result["match_percent"], json.dumps(result, ensure_ascii=False)),
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


def get_analysis(database: Database, analysis_id: int) -> dict | None:
    row = database.fetch_one("SELECT * FROM ats_analyses WHERE id = ?", (analysis_id,))
    if row:
        row["result"] = json.loads(row.pop("result_json"))
    return row


def latest_analysis(database: Database, vacancy_id: int) -> dict | None:
    row = database.fetch_one(
        "SELECT * FROM ats_analyses WHERE vacancy_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
        (vacancy_id,),
    )
    if row:
        row["result"] = json.loads(row.pop("result_json"))
    return row
