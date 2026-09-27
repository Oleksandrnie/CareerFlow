from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from careerflow.db import Database, SCHEMA
from careerflow.resumes import create_resume, mark_submitted
from careerflow.tracking import add_interview, change_status
from careerflow.vacancies import create_vacancy, list_vacancies


class AnalyticsFoundationTest(unittest.TestCase):
    def test_new_vacancy_and_domain_actions_emit_structured_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "careerflow.db")
            database.initialize()
            vacancy = create_vacancy(database, root / "storage", "Python Engineer", "text")
            resume = create_resume(
                database, root / "storage", kind="vacancy", vacancy_id=vacancy["id"], content_text="Python"
            )
            mark_submitted(database, resume["id"])
            add_interview(
                database, vacancy["id"], "2026-09-27T10:00", "Technical", "", "passed", "passed"
            )
            change_status(database, vacancy["id"], "Offer", outcome="offer_accepted")
            events = database.fetch_all(
                "SELECT event_type FROM funnel_events WHERE vacancy_id = ? ORDER BY id", (vacancy["id"],)
            )
            self.assertEqual(
                [row["event_type"] for row in events],
                ["vacancy_added", "application_submitted", "interview_scheduled", "interview_completed", "offer_received", "offer_accepted"],
            )
            self.assertEqual(database.fetch_one("SELECT result_code FROM interviews")["result_code"], "passed")

    def test_legacy_migration_archives_once_and_excludes_old_vacancies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            with sqlite3.connect(path) as connection:
                connection.executescript(SCHEMA)
                connection.executemany("INSERT INTO schema_version(version) VALUES (?)", [(version,) for version in range(1, 9)])
                connection.execute("INSERT INTO vacancies(id, description, archived_at) VALUES (1, 'old one', NULL), (2, 'old two', 'old')")
            database = Database(path)
            database.initialize()
            first = database.fetch_all("SELECT id, analytics_eligible, archived_at FROM vacancies ORDER BY id")
            database.initialize()
            second = database.fetch_all("SELECT id, analytics_eligible, archived_at FROM vacancies ORDER BY id")
            self.assertEqual([(row["analytics_eligible"], row["archived_at"]) for row in first], [(0, first[0]["archived_at"]), (0, "old")])
            self.assertEqual(second, first)
            self.assertEqual(list_vacancies(database, archived=False), [])
            self.assertEqual([row["id"] for row in list_vacancies(database, archived=True)], [2, 1])


if __name__ == "__main__":
    unittest.main()
