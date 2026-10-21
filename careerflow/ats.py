"""Deterministic, evidence-based MVP ATS matching engine."""

from __future__ import annotations

import json
import re
from collections import Counter

from .cleaning import retain_reviewable_text
from .db import Database, insert_and_get_id


STOP_WORDS = {
    "about",
    "after",
    "also",
    "and",
    "are",
    "but",
    "can",
    "for",
    "from",
    "have",
    "in",
    "into",
    "its",
    "job",
    "our",
    "role",
    "that",
    "the",
    "their",
    "this",
    "using",
    "with",
    "will",
    "work",
    "you",
    "your",
    "для",
    "или",
    "как",
    "команда",
    "на",
    "не",
    "опыт",
    "от",
    "по",
    "работа",
    "работы",
    "с",
    "со",
    "требования",
    "что",
    "это",
    "мы",
    "наш",
    "наша",
    "наши",
    "нашего",
    "компания",
    "компании",
    "вакансия",
    "вакансии",
    "будет",
    "будут",
    "который",
    "которая",
    "которые",
    "вас",
    "вам",
    "ищем",
    "перед",
    "вами",
    "следующие",
    "задачи",
    "также",
    "этот",
    "эта",
    "эти",
}

GENERIC_REQUIREMENT_WORDS = {
    "ability",
    "experience",
    "expertise",
    "familiarity",
    "knowledge",
    "know",
    "must",
    "need",
    "preferred",
    "proficiency",
    "required",
    "requirement",
    "requirements",
    "skill",
    "skills",
    "year",
    "years",
    "yr",
    "yrs",
    "знание",
    "знания",
    "навык",
    "навыки",
    "опыт",
    "требование",
    "требования",
}

NEGATION = re.compile(
    r"(?i)\b(?:no|not|never|without|lack(?:ing|s)?|cannot|can't|don't|"
    r"нет|без|не|отсутств\w*)\b"
)
YEARS = re.compile(r"(?i)\b(\d+(?:[.,]\d+)?)\s*\+?\s*(?:years?|yrs?|лет|года?|год)\b")

# These are high-confidence spelling/abbreviation equivalences, not general
# semantic synonyms. Keep the list deliberately small so ATS remains
# explainable and does not turn related concepts into false positive matches.
TECHNICAL_ALIASES = {
    "apis": "api",
    "js": "javascript",
    "javascript": "javascript",
    "ts": "typescript",
    "typescript": "typescript",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "k8s": "kubernetes",
    "kubernetes": "kubernetes",
    "cicd": "ci/cd",
    "ci/cd": "ci/cd",
    "nodejs": "node.js",
    "node.js": "node.js",
    "reactjs": "react",
    "react": "react",
}

RUSSIAN_INFLECTION_SUFFIXES = (
    "иями",
    "ями",
    "ами",
    "ого",
    "ему",
    "ому",
    "ее",
    "ие",
    "ые",
    "ой",
    "ий",
    "ый",
    "ую",
    "юю",
    "ая",
    "яя",
    "ов",
    "ев",
    "ам",
    "ям",
    "ом",
    "ем",
    "ах",
    "ях",
    "ы",
    "и",
    "а",
    "я",
    "у",
    "ю",
    "е",
    "о",
)


def _years_amounts(text: str) -> list[float]:
    return [float(match.replace(",", ".")) for match in YEARS.findall(text)]


def _matching_forms(token: str) -> set[str]:
    """Return conservative lexical forms used only for comparison.

    The original token is always retained for display and keyword output.
    Forms cover common English inflections, a small Russian noun/adjective
    inflection set, and explicit technology aliases. They are intentionally
    not a full stemmer or translation layer.
    """
    forms = {token}
    canonical = TECHNICAL_ALIASES.get(token)
    if canonical:
        forms.add(canonical)

    if re.fullmatch(r"[a-z][a-z0-9+#./-]*", token):
        if token.endswith("ies") and len(token) > 4:
            forms.add(token[:-3] + "y")
        elif token.endswith("s") and not token.endswith(("ss", "us", "is")) and len(token) > 3:
            forms.add(token[:-1])
        if token.endswith("ing") and len(token) > 5:
            forms.add(token[:-3])
        if token.endswith("ed") and len(token) > 4:
            stem = token[:-2]
            forms.update({stem, f"{stem}e"})
        for suffix in ("ment", "tion", "sion"):
            if token.endswith(suffix) and len(token) - len(suffix) >= 4:
                forms.add(token[: -len(suffix)])
    elif re.search(r"[а-яё]", token):
        for suffix in RUSSIAN_INFLECTION_SUFFIXES:
            if token.endswith(suffix) and len(token) - len(suffix) >= 4:
                forms.add(token[: -len(suffix)])

    return forms


def _matched_tokens(required_tokens: set[str], candidate_tokens: set[str]) -> set[str]:
    """Return vacancy tokens supported by at least one resume token."""
    candidate_forms = (
        set().union(*(_matching_forms(token) for token in candidate_tokens))
        if candidate_tokens
        else set()
    )
    return {token for token in required_tokens if _matching_forms(token) & candidate_forms}


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for raw_token in re.findall(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9+#.\-/]{1,}", text):
        # Keep meaningful in-token punctuation (for example C++, C#, Node.js,
        # and CI/CD), but do not let sentence punctuation change keyword identity.
        token = raw_token.lower().strip(".-/")
        if token and token not in STOP_WORDS:
            tokens.append(token)
    return tokens


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def _semantic_token_sequence(text: str) -> list[str]:
    """Return requirement terms without qualification scaffolding."""
    return [token for token in _tokens(text) if token not in GENERIC_REQUIREMENT_WORDS]


def _semantic_tokens(text: str) -> list[str]:
    """Return ordered, distinct semantic requirement terms."""
    return list(dict.fromkeys(_semantic_token_sequence(text)))


def _requirements(text: str) -> list[str]:
    lines = _sentences(text)
    signals = re.compile(
        r"(?i)\b(required|requirements?|must|need|experience|knowledge|skills?|proficien\w*|"
        r"обязанност\w*|требован\w*|опыт|знани\w*|навык\w*|умени\w*|"
        r"владени\w*|необходим\w*|требуется|"
        r"желательно|будет преимуществом|от\s+\d+\s+(?:лет|года?))\b"
    )
    # A requirement is eligible only when the sentence expresses an explicit
    # qualification or starts with a heading that introduces a requirements list.
    # Do not pad short requirement sections with arbitrary company/marketing text.
    selected: list[str] = []
    in_requirements_section = False
    in_excluded_section = False
    section_heading = re.compile(
        r"(?i)^\s*(?:требования|что\s+мы\s+ожидаем|вам\s+необходимо|"
        r"requirements|qualifications|what\s+we(?:'re|\s+are)\s+looking\s+for)\s*:?\s*$"
    )
    duty_intro = re.compile(
        r"(?i)^\s*(?:перед\s+вами\s+будут\s+стоять\s+следующие\s+задачи|"
        r"следующие\s+задачи|основные\s+задачи|ваши\s+задачи|"
        r"что\s+будете\s+делать|обязанности|"
        r"what\s+you(?:'ll|\s+will)\s+do)\s*:?\s*$"
    )
    excluded_heading = re.compile(
        r"(?i)^\s*(?:о\s+компании|company|about\s+us|мы\s+предлагаем|"
        r"условия|benefits|what\s+we\s+offer|мы\s+гарантируем)\s*:?\s*$"
    )
    for line in lines:
        if section_heading.fullmatch(line):
            in_requirements_section = True
            in_excluded_section = False
            continue
        if duty_intro.fullmatch(line):
            in_requirements_section = True
            in_excluded_section = False
            continue
        if excluded_heading.fullmatch(line):
            in_requirements_section = False
            in_excluded_section = True
            continue
        if re.match(r"(?i)^\s*(?:в свою очередь мы гарантируем|мы предлагаем)\b", line):
            in_requirements_section = False
            in_excluded_section = True
            continue
        if in_excluded_section:
            continue
        if not in_requirements_section and not signals.search(line):
            continue
        if not _semantic_tokens(line):
            continue
        # Headings and narrative about the employer are not qualifications.
        if re.match(
            r"(?i)^\s*(?:перед\s+вами\s+будут|ищем\s+.{0,80},?\s+котор\w+|"
            r"мы\s+специализируемся|компания\s+.{0,80}\s+работает\s+с\s+\d{4})",
            line,
        ):
            continue
        selected.append(line)
    return selected


def analyze(vacancy_text: str, resume_text: str) -> dict:
    # Confirmed descriptions can still contain manually retained page text. Apply
    # the same conservative, deterministic structural filter before both keyword
    # and requirement scoring; reviewable/uncertain blocks remain untouched.
    vacancy_text = retain_reviewable_text(vacancy_text)
    requirement_lines = _requirements(vacancy_text)
    vacancy_counts = Counter(_semantic_token_sequence("\n".join(requirement_lines)))
    keywords = [word for word, _ in vacancy_counts.most_common(24)]
    resume_sentences = _sentences(resume_text)
    resume_facts = [
        (
            sentence,
            set(_tokens(sentence)),
            bool(NEGATION.search(sentence)),
            _years_amounts(sentence),
        )
        for sentence in resume_sentences
    ]
    requirement_results: list[dict] = []
    evidenced_keywords: set[str] = set()

    for requirement in requirement_lines:
        requirement_tokens = set(_tokens(requirement))
        if not requirement_tokens:
            continue
        semantic_token_list = _semantic_tokens(requirement)
        if not semantic_token_list:
            semantic_token_list = list(dict.fromkeys(_tokens(requirement)))
        semantic_tokens = set(semantic_token_list)
        required_years = max(_years_amounts(requirement), default=None)
        best_evidence = ""
        best_negative = False
        best_years_ok = True
        positive_sentences: list[tuple[str, set[str], list[float], set[str]]] = []
        negative_sentences: list[tuple[str, set[str], list[float], set[str]]] = []
        for sentence, sentence_tokens, negative, stated_years in resume_facts:
            matched = _matched_tokens(semantic_tokens, sentence_tokens)
            if not matched:
                continue
            if negative:
                negative_sentences.append((sentence, sentence_tokens, stated_years, matched))
                continue
            positive_sentences.append((sentence, sentence_tokens, stated_years, matched))

        overlap = (
            set().union(*(matched for _, _, _, matched in positive_sentences))
            if positive_sentences
            else set()
        )
        negative_overlap = (
            set().union(*(matched for _, _, _, matched in negative_sentences))
            if negative_sentences
            else set()
        )
        unresolved_negative = negative_overlap - overlap
        if positive_sentences:
            evidence_candidates: list[tuple[tuple[int, int], str, bool]] = []
            for sentence, _, stated_years, matched in positive_sentences:
                years_ok = required_years is None or (
                    bool(stated_years) and min(stated_years) >= required_years
                )
                evidence_candidates.append(
                    (
                        (len(matched), int(years_ok)),
                        sentence,
                        years_ok,
                    )
                )
            _, best_evidence, best_years_ok = max(evidence_candidates, key=lambda item: item[0])
        elif negative_sentences:
            best_evidence, _, _, _ = max(
                negative_sentences,
                key=lambda item: len(item[3]),
            )
            best_negative = True

        coverage = len(overlap) / len(semantic_tokens)
        if coverage >= 0.6:
            classification = "covered"
        elif overlap:
            classification = "partial"
        else:
            classification = "missing"
        if classification == "covered" and unresolved_negative:
            classification = "partial"
        if classification == "covered" and (not best_evidence or not best_years_ok):
            classification = "partial"
        if unresolved_negative or best_negative:
            interpretation = (
                "Negative wording is present; this does not confirm the required experience"
            )
        elif classification == "partial" and not best_years_ok:
            interpretation = "The required years are not evidenced by this resume sentence"
        elif classification == "covered":
            interpretation = "Evidence found in this resume version"
        elif classification == "partial":
            interpretation = (
                "Some related evidence is present; the requirement may be under-described"
            )
        else:
            interpretation = (
                "Not evidenced in this resume version; this does not prove the experience is absent"
            )
        requirement_results.append(
            {
                "requirement": requirement,
                "classification": classification,
                "matched_keywords": sorted(overlap),
                "evidence": best_evidence[:420],
                "interpretation": interpretation,
            }
        )
        evidenced_keywords.update(overlap)

    keyword_overlap = [word for word in keywords if word in evidenced_keywords]
    keyword_score = len(keyword_overlap) / max(1, len(keywords))
    requirement_score = sum(
        1
        if item["classification"] == "covered"
        else 0.5
        if item["classification"] == "partial"
        else 0
        for item in requirement_results
    ) / max(1, len(requirement_results))
    match_percent = round((keyword_score * 0.4 + requirement_score * 0.6) * 100)
    return {
        "match_percent": max(0, min(100, match_percent)),
        "keywords": keywords,
        "covered_keywords": keyword_overlap,
        "missing_keywords": [word for word in keywords if word not in evidenced_keywords],
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
        if not vacancy["description_confirmed_at"]:
            raise ValueError(
                "Review and confirm the cleaned vacancy description before running ATS"
            )
        resume = connection.execute(
            "SELECT * FROM resume_versions WHERE id = ? AND deleted_at IS NULL",
            (resume_id,),
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
                vacancy_id,
                resume_id,
                result["match_percent"],
                json.dumps(result, ensure_ascii=False),
                vacancy["description"],
                vacancy["description_revision"],
                resume["kind"],
                resume["version"],
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
        row["resume_deleted"] = row.pop("referenced_resume_deleted_at") is not None
        row["is_stale"] = (
            row["description_revision"] is None
            or row["description_revision"] != current_revision
            or row["description_snapshot"] != current_description
            or row["resume_deleted"]
        )
        row["result"] = json.loads(row.pop("result_json"))
    return row


def get_analysis(database: Database, analysis_id: int) -> dict | None:
    return _load_analysis(
        database,
        """
        SELECT a.*, v.description_revision AS current_description_revision,
               v.description AS current_description,
               r.deleted_at AS referenced_resume_deleted_at
        FROM ats_analyses AS a JOIN vacancies AS v ON v.id = a.vacancy_id
        LEFT JOIN resume_versions AS r ON r.id = a.resume_version_id
        WHERE a.id = ?
        """,
        (analysis_id,),
    )


def latest_analysis(database: Database, vacancy_id: int) -> dict | None:
    return _load_analysis(
        database,
        """
        SELECT a.*, v.description_revision AS current_description_revision,
               v.description AS current_description,
               r.deleted_at AS referenced_resume_deleted_at
        FROM ats_analyses AS a JOIN vacancies AS v ON v.id = a.vacancy_id
        LEFT JOIN resume_versions AS r ON r.id = a.resume_version_id
        WHERE a.vacancy_id = ? ORDER BY a.created_at DESC, a.id DESC LIMIT 1
        """,
        (vacancy_id,),
    )
