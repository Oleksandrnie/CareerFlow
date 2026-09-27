"""Read-only, SQLite-backed analytics calculations."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from .db import Database


OUTCOMES = (
    "offer_accepted", "offer_declined", "employer_rejected", "candidate_withdrew",
    "vacancy_closed", "no_response",
)
EVENT_FOR_STAGE = {
    "application_submitted": "application_submitted",
    "interview_invited": "interview_scheduled",
    "interview_completed": "interview_completed",
    "offer_received": "offer_received",
    "offer_accepted": "offer_accepted",
}


def _parse_date(value: str | None, label: str) -> date | None:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be YYYY-MM-DD") from exc


def _bounds(from_value: str | None, to_value: str | None) -> tuple[date | None, date | None]:
    start = _parse_date(from_value, "from")
    end = _parse_date(to_value, "to")
    if start and end and start > end:
        raise ValueError("from must not be later than to")
    return start, end


def _period_clause(column: str, start: date | None, end: date | None) -> tuple[str, list[str]]:
    clauses: list[str] = []
    params: list[str] = []
    if start:
        clauses.append(f"{column} >= ?")
        params.append(start.isoformat())
    if end:
        clauses.append(f"{column} < ?")
        params.append((end + timedelta(days=1)).isoformat())
    return (" AND ".join(clauses) or "1=1"), params


def _event_count(database: Database, event_type: str, start: date | None, end: date | None, distinct: bool = False) -> int:
    clause, params = _period_clause("occurred_at", start, end)
    field = "COUNT(DISTINCT vacancy_id)" if distinct else "COUNT(*)"
    row = database.fetch_one(
        f"SELECT {field} AS value FROM funnel_events WHERE event_type = ? AND {clause}",
        (event_type, *params),
    )
    return int(row["value"] or 0) if row else 0


def _cohort_ids(database: Database, start: date | None, end: date | None) -> list[int]:
    clause, params = _period_clause("created_at", start, end)
    rows = database.fetch_all(
        f"SELECT id FROM vacancies WHERE analytics_eligible = 1 AND {clause}", params
    )
    return [int(row["id"]) for row in rows]


def _stage_ids(database: Database, vacancy_ids: list[int], event_type: str) -> set[int]:
    if not vacancy_ids:
        return set()
    placeholders = ",".join("?" for _ in vacancy_ids)
    rows = database.fetch_all(
        f"SELECT DISTINCT vacancy_id FROM funnel_events WHERE event_type = ? AND vacancy_id IN ({placeholders})",
        (event_type, *vacancy_ids),
    )
    return {int(row["vacancy_id"]) for row in rows}


def _bucket_start(value: date, bucket: str) -> date:
    if bucket == "week":
        return value - timedelta(days=value.weekday())
    return value.replace(day=1)


def _next_bucket(value: date, bucket: str) -> date:
    if bucket == "week":
        return value + timedelta(days=7)
    return (value.replace(day=28) + timedelta(days=4)).replace(day=1)


def _series(database: Database, start: date | None, end: date | None, bucket: str) -> list[dict[str, Any]]:
    if not start or not end:
        rows = database.fetch_all("SELECT MIN(date(occurred_at)) AS first, MAX(date(occurred_at)) AS last FROM funnel_events")
        if rows and rows[0]["first"]:
            start = _parse_date(rows[0]["first"], "first")
            end = _parse_date(rows[0]["last"], "last")
    if not start or not end:
        return []
    first, last = _bucket_start(start, bucket), _bucket_start(end, bucket)
    result: list[dict[str, Any]] = []
    current = first
    event_types = {"vacancies_added": "vacancy_added", "applications_submitted": "application_submitted", "interviews_completed": "interview_completed", "offers_received": "offer_received"}
    while current <= last:
        next_start = _next_bucket(current, bucket)
        counts: dict[str, int] = {}
        for key, event_type in event_types.items():
            clause, params = _period_clause("occurred_at", current, next_start - timedelta(days=1))
            counts[key] = _event_count(database, event_type, current, next_start - timedelta(days=1), distinct=(event_type != "interview_completed"))
        counts["rejections_received"] = sum(
            _event_count(database, outcome, current, next_start - timedelta(days=1), distinct=True)
            for outcome in ("employer_rejected",)
        )
        result.append({"period": current.isoformat(), **counts})
        current = next_start
    return result


def calculate(database: Database, from_value: str | None, to_value: str | None, bucket: str = "month") -> dict[str, Any]:
    if bucket not in {"week", "month"}:
        raise ValueError("bucket must be week or month")
    start, end = _bounds(from_value, to_value)
    cohort = _cohort_ids(database, start, end)
    stage_names = ["added", "application_submitted", "interview_invited", "interview_completed", "offer_received", "offer_accepted"]
    stage_events = [None, "application_submitted", "interview_scheduled", "interview_completed", "offer_received", "offer_accepted"]
    stage_sets = [set(cohort)] + [_stage_ids(database, cohort, event) for event in stage_events[1:]]
    funnel = [{"stage": name, "count": len(ids)} for name, ids in zip(stage_names, stage_sets)]
    conversion_pairs = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (0, 5)]
    conversions = []
    labels = ["added_to_application", "application_to_interview", "interview_to_completed", "completed_to_offer", "offer_to_accepted", "added_to_accepted"]
    for label, (base, reached) in zip(labels, conversion_pairs):
        denominator, numerator = len(stage_sets[base]), len(stage_sets[reached])
        conversions.append({"transition": label, "base": denominator, "reached": numerator, "percent": None if denominator == 0 else round(numerator / denominator * 100, 1)})
    activity = {
        "vacancies_added": _event_count(database, "vacancy_added", start, end, True),
        "applications_submitted": _event_count(database, "application_submitted", start, end, True),
        "vacancies_with_interview": _event_count(database, "interview_scheduled", start, end, True),
        "interviews_completed": _event_count(database, "interview_completed", start, end, False),
        "offers_received": _event_count(database, "offer_received", start, end, True),
        "rejections_received": _event_count(database, "employer_rejected", start, end, True),
        "completed_successfully": _event_count(database, "offer_accepted", start, end, True),
    }
    end_clause, end_params = _period_clause("created_at", None, end)
    active = database.fetch_one(
        f"SELECT COUNT(*) AS value FROM vacancies WHERE analytics_eligible = 1 AND outcome IS NULL AND archived_at IS NULL AND {end_clause}", end_params
    )
    activity["active_processes"] = int(active["value"] or 0) if active else 0
    outcome_clause, outcome_params = _period_clause("outcome_at", start, end)
    outcomes = {outcome: _event_count(database, outcome, start, end, True) for outcome in OUTCOMES}
    outcomes["successful"] = outcomes["offer_accepted"]
    outcomes["unsuccessful"] = sum(value for key, value in outcomes.items() if key != "offer_accepted")
    outcomes["active"] = activity["active_processes"]
    incomplete = database.fetch_all(
        "SELECT id, title, company, outcome, status FROM vacancies WHERE analytics_eligible = 1 AND ((status = 'Rejected' AND outcome IS NULL) OR (status = 'Offer' AND outcome IS NULL)) ORDER BY created_at DESC"
    )
    return {
        "period": {"from": from_value, "to": to_value, "bucket": bucket},
        "activity_metrics": activity,
        "funnel": funnel,
        "conversions": conversions,
        "series": _series(database, start, end, bucket),
        "outcomes": outcomes,
        "incomplete_records": incomplete,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
