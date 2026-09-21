from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from careerflow.api import create_app
from careerflow.ats import analyze, latest_analysis
from careerflow.config import Settings
from careerflow.db import Database


class ResumeAndAtsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        settings = Settings(root, root / "data", root / "storage", root / "data" / "test.db", "codex", 10)
        self.context = TestClient(create_app(settings))
        self.client = self.context.__enter__()
        vacancy_response = self.client.post(
            "/api/vacancies",
            data={"text": "Backend Engineer\nRequired: 3 years Python experience.\nMust know SQL and Docker.\nKubernetes experience is preferred."},
        )
        self.vacancy = vacancy_response.json()

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def test_master_clone_version_and_submitted_marker(self) -> None:
        master = self.client.post(
            "/api/resumes",
            data={"kind": "master", "label": "Base CV", "text": "Python engineer. SQL APIs. Docker production workloads."},
        )
        self.assertEqual(master.status_code, 201)
        self.assertEqual(master.json()["version"], 1)

        first = self.client.post(
            "/api/resumes",
            data={"kind": "vacancy", "vacancy_id": self.vacancy["id"], "source_resume_id": master.json()["id"], "label": "Tailored"},
        )
        second = self.client.post(
            "/api/resumes",
            data={"kind": "vacancy", "vacancy_id": self.vacancy["id"], "text": "Python SQL Docker Kubernetes", "label": "Final"},
        )
        self.assertEqual(first.json()["version"], 1)
        self.assertEqual(second.json()["version"], 2)
        self.assertEqual(self.client.post(f"/api/resumes/{first.json()['id']}/submit").status_code, 200)
        submitted = self.client.post(f"/api/resumes/{second.json()['id']}/submit").json()
        self.assertEqual(submitted["is_submitted"], 1)
        versions = self.client.get(f"/api/resumes?kind=vacancy&vacancy_id={self.vacancy['id']}").json()
        self.assertEqual([item["version"] for item in versions], [2, 1])
        self.assertEqual(sum(item["is_submitted"] for item in versions), 1)

    def test_ats_analysis_persists_evidence_and_updates_match(self) -> None:
        resume = self.client.post(
            "/api/resumes",
            data={"kind": "master", "text": "Five years building Python APIs. Used SQL and Docker in production."},
        ).json()
        response = self.client.post(
            f"/api/vacancies/{self.vacancy['id']}/ats",
            json={"resume_version_id": resume["id"]},
        )
        self.assertEqual(response.status_code, 201)
        analysis = response.json()
        self.assertGreater(analysis["match_percent"], 0)
        self.assertFalse(analysis["is_stale"])
        self.assertEqual(analysis["description_snapshot"], self.vacancy["description"])
        self.assertEqual(analysis["resume_kind_at_analysis"], "master")
        self.assertEqual(analysis["resume_version_at_analysis"], 1)
        result = analysis["result"]
        self.assertIn("requirements", result)
        self.assertIn("not that the candidate lacks", result["disclaimer"])
        evidenced = [item for item in result["requirements"] if item["evidence"]]
        self.assertTrue(evidenced)
        vacancy = self.client.get(f"/api/vacancies/{self.vacancy['id']}").json()
        self.assertEqual(vacancy["match_percent"], analysis["match_percent"])

    def test_description_edit_invalidates_match_but_preserves_historical_inputs(self) -> None:
        resume = self.client.post(
            "/api/resumes", data={"kind": "master", "text": "Python engineer"}
        ).json()
        url = f"/api/vacancies/{self.vacancy['id']}"
        original = self.client.post(
            f"{url}/ats", json={"resume_version_id": resume["id"]}
        ).json()

        metadata_edit = self.client.patch(url, json={"company": "Northwind"}).json()
        self.assertEqual(metadata_edit["match_percent"], original["match_percent"])
        self.assertFalse(self.client.get(f"{url}/ats").json()["is_stale"])

        changed = self.client.patch(
            url, json={"description": "Required COBOL mainframe experience."}
        ).json()
        self.assertIsNone(changed["match_percent"])
        historical = self.client.get(f"{url}/ats").json()
        self.assertTrue(historical["is_stale"])
        self.assertEqual(historical["description_snapshot"], self.vacancy["description"])
        self.assertEqual(historical["resume_version_id"], resume["id"])
        self.assertEqual(historical["match_percent"], original["match_percent"])

        report = self.client.post(f"{url}/reports").json()["markdown"]
        self.assertIn("Required COBOL mainframe experience.", report)
        self.assertIn("Historical match (not current)", report)
        self.assertIn("Vacancy description analyzed at that time", report)
        self.assertIn(self.vacancy["description"], report)

        fresh = self.client.post(
            f"{url}/ats", json={"resume_version_id": resume["id"]}
        ).json()
        self.assertFalse(fresh["is_stale"])
        self.assertEqual(fresh["description_snapshot"], changed["description"])
        self.assertEqual(
            self.client.get(url).json()["match_percent"], fresh["match_percent"]
        )

    def test_ats_does_not_invent_evidence(self) -> None:
        result = analyze("Must have COBOL mainframe experience.", "Python web developer.")
        item = result["requirements"][0]
        self.assertEqual(item["classification"], "missing")
        self.assertEqual(item["evidence"], "")
        self.assertIn("Not evidenced", item["interpretation"])

    def test_ats_ignores_sentence_punctuation_when_matching_skills(self) -> None:
        result = analyze(
            "Required: Kubernetes and Node.js experience.",
            "Built production services with Kubernetes. Maintained Node.js APIs.",
        )

        requirement = result["requirements"][0]
        self.assertIn("kubernetes", requirement["matched_keywords"])
        self.assertIn("node.js", requirement["matched_keywords"])
        self.assertNotEqual(requirement["classification"], "missing")

    def test_ats_evidence_prioritizes_distinctive_requirement_terms(self) -> None:
        result = analyze(
            "Kubernetes experience preferred.",
            (
                "Backend engineer with six years of Python experience. "
                "Deployed services to Kubernetes clusters."
            ),
        )

        requirement = result["requirements"][0]
        self.assertEqual(requirement["classification"], "covered")
        self.assertIn("Kubernetes", requirement["evidence"])

    def test_ats_does_not_call_explicit_negation_covered(self) -> None:
        for vacancy, resume in (
            ("Required Python experience.", "No Python experience."),
            ("Required Python experience.", "I have never used Python."),
            ("Требования: Python SQL опыт.", "Нет опыта Python SQL."),
            ("Требования: Python SQL опыт.", "Без опыта Python SQL."),
        ):
            with self.subTest(resume=resume):
                item = analyze(vacancy, resume)["requirements"][0]
                self.assertNotEqual(item["classification"], "covered")
                self.assertIn("Negative wording", item["interpretation"])

    def test_ats_requires_evidence_for_quantified_years(self) -> None:
        requirement = "Required 5 years Python experience."
        for resume in ("1 years Python experience.", "Python experience."):
            with self.subTest(resume=resume):
                item = analyze(requirement, resume)["requirements"][0]
                self.assertNotEqual(item["classification"], "covered")
                self.assertIn("required years", item["interpretation"])
        covered = analyze(requirement, "6 years Python experience.")["requirements"][0]
        self.assertEqual(covered["classification"], "covered")

    def test_master_cannot_be_submitted(self) -> None:
        master = self.client.post(
            "/api/resumes", data={"kind": "master", "text": "Python engineer"}
        ).json()
        response = self.client.post(f"/api/resumes/{master['id']}/submit")
        self.assertEqual(response.status_code, 422)


class AtsLegacyMigrationTest(unittest.TestCase):
    def test_existing_analysis_without_input_snapshot_is_stale_and_score_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "legacy.db")
            with sqlite3.connect(database.path) as connection:
                connection.executescript(
                    """
                    CREATE TABLE vacancies (
                        id INTEGER PRIMARY KEY, description TEXT NOT NULL,
                        status TEXT, archived_at TEXT, match_percent INTEGER,
                        updated_at TEXT
                    );
                    CREATE TABLE resume_versions (
                        id INTEGER PRIMARY KEY, vacancy_id INTEGER, kind TEXT,
                        version INTEGER, label TEXT, content_text TEXT,
                        is_submitted INTEGER, created_at TEXT
                    );
                    CREATE TABLE ats_analyses (
                        id INTEGER PRIMARY KEY, vacancy_id INTEGER,
                        resume_version_id INTEGER, match_percent INTEGER,
                        result_json TEXT, created_at TEXT
                    );
                    INSERT INTO vacancies VALUES (1, 'Required Python', 'Saved', NULL, 87, '2026-09-21');
                    INSERT INTO resume_versions VALUES (1, NULL, 'master', 1, '', 'Python', 0, '2026-09-21');
                    INSERT INTO ats_analyses VALUES (1, 1, 1, 87, '{"keywords": []}', '2026-09-21');
                    """
                )

            database.initialize()
            database.initialize()

            self.assertIsNone(database.fetch_one("SELECT match_percent FROM vacancies WHERE id = 1")["match_percent"])
            analysis = latest_analysis(database, 1)
            self.assertIsNotNone(analysis)
            self.assertTrue(analysis["is_stale"])
            self.assertIsNone(analysis["description_snapshot"])
            self.assertEqual(
                database.fetch_one("SELECT MAX(version) AS version FROM schema_version")["version"],
                3,
            )


if __name__ == "__main__":
    unittest.main()
