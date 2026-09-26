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
        self.settings = settings
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
        self.assertEqual(first.json()["source_resume_id"], master.json()["id"])
        self.assertEqual(first.json()["source_kind"], "master")
        self.assertEqual(first.json()["source_version"], 1)
        self.assertEqual(first.json()["content_text"], master.json()["content_text"])
        self.assertEqual(second.json()["version"], 2)
        self.assertEqual(self.client.post(f"/api/resumes/{first.json()['id']}/submit").status_code, 200)
        submitted = self.client.post(f"/api/resumes/{second.json()['id']}/submit").json()
        self.assertEqual(submitted["is_submitted"], 1)
        versions = self.client.get(f"/api/resumes?kind=vacancy&vacancy_id={self.vacancy['id']}").json()
        self.assertEqual([item["version"] for item in versions], [2, 1])
        self.assertEqual(sum(item["is_submitted"] for item in versions), 1)

    def test_resume_source_rules_copy_edited_markdown_and_prevent_cycles(self) -> None:
        master = self.client.post(
            "/api/resumes",
            data={"kind": "master", "label": "Base", "text": "# Base\n\nPython"},
        ).json()
        tailored = self.client.post(
            "/api/resumes",
            data={
                "kind": "vacancy",
                "vacancy_id": self.vacancy["id"],
                "source_resume_id": master["id"],
                "label": "Edited copy",
                "text": "# Tailored\n\nPython and SQL",
            },
        )
        self.assertEqual(tailored.status_code, 201)
        self.assertEqual(tailored.json()["content_text"], "# Tailored\nPython and SQL")
        self.assertEqual(tailored.json()["source_resume_id"], master["id"])

        derived = self.client.post(
            "/api/resumes",
            data={
                "kind": "vacancy",
                "vacancy_id": self.vacancy["id"],
                "source_resume_id": tailored.json()["id"],
                "text": "Second tailored version",
            },
        )
        self.assertEqual(derived.status_code, 201)
        self.assertEqual(derived.json()["source_kind"], "vacancy")
        self.assertEqual(derived.json()["source_version"], tailored.json()["version"])

        other_vacancy = self.client.post(
            "/api/vacancies", data={"text": "Other role\nRequired Go"}
        ).json()
        cross_vacancy = self.client.post(
            "/api/resumes",
            data={
                "kind": "vacancy",
                "vacancy_id": other_vacancy["id"],
                "source_resume_id": tailored.json()["id"],
                "text": "Invalid cross-vacancy child",
            },
        )
        self.assertEqual(cross_vacancy.status_code, 422)
        invalid_master = self.client.post(
            "/api/resumes",
            data={
                "kind": "master",
                "source_resume_id": tailored.json()["id"],
                "text": "Invalid master child",
            },
        )
        self.assertEqual(invalid_master.status_code, 422)

        database = self.context.app.state.db
        with self.assertRaises(sqlite3.IntegrityError):
            with database.transaction() as connection:
                connection.execute(
                    "UPDATE resume_versions SET source_resume_id = ? WHERE id = ?",
                    (derived.json()["id"], tailored.json()["id"]),
                )

        with database.transaction() as connection:
            connection.execute("DELETE FROM resume_versions WHERE id = ?", (master["id"],))
        preserved_child = self.client.get(f"/api/resumes/{tailored.json()['id']}").json()
        self.assertIsNone(preserved_child["source_resume_id"])
        self.assertEqual(preserved_child["content_text"], "# Tailored\nPython and SQL")

    def test_canonical_markdown_download(self) -> None:
        resume = self.client.post(
            "/api/resumes",
            data={"kind": "master", "text": "# Profile\n\n- Python\n- SQL"},
        ).json()
        response = self.client.get(f"/api/resumes/{resume['id']}/markdown")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, resume["content_text"])
        self.assertIn("text/markdown", response.headers["content-type"])
        self.assertIn("master-resume-v1.md", response.headers["content-disposition"])

    def test_original_resume_download_is_byte_identical_and_scoped_to_storage(self) -> None:
        original = b"Python engineer\nSQL and Docker\n"
        uploaded = self.client.post(
            "/api/resumes",
            data={"kind": "master", "label": "Uploaded"},
            files={"file": ("resume.txt", original, "text/plain")},
        )
        self.assertEqual(uploaded.status_code, 201)
        resume = uploaded.json()
        download_url = f"/api/resumes/{resume['id']}/download"
        downloaded = self.client.get(download_url)
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.content, original)
        self.assertEqual(downloaded.headers["content-type"], "application/octet-stream")
        self.assertIn("attachment", downloaded.headers["content-disposition"])
        self.assertIn("resume.txt", downloaded.headers["content-disposition"])

        pasted = self.client.post(
            "/api/resumes", data={"kind": "master", "text": "Pasted resume"}
        ).json()
        self.assertEqual(self.client.get(f"/api/resumes/{pasted['id']}/download").status_code, 404)
        self.assertEqual(self.client.get("/api/resumes/999999/download").status_code, 404)

        outside = Path(self.temp_dir.name) / "outside-private.txt"
        outside.write_bytes(b"must not be served")
        database = self.context.app.state.db
        with database.transaction() as connection:
            connection.execute(
                "UPDATE resume_versions SET original_path = ? WHERE id = ?",
                (str(outside), resume["id"]),
            )
        self.assertEqual(self.client.get(download_url).status_code, 404)

        original_path = Path(resume["original_path"])
        with database.transaction() as connection:
            connection.execute(
                "UPDATE resume_versions SET original_path = ? WHERE id = ?",
                (str(original_path), resume["id"]),
            )
        original_path.unlink()
        original_path.symlink_to(outside)
        self.assertEqual(self.client.get(download_url).status_code, 404)
        original_path.unlink()
        self.assertEqual(self.client.get(download_url).status_code, 404)

    def test_delete_resume_redacts_tombstone_removes_files_and_hides_access(self) -> None:
        response = self.client.post(
            "/api/resumes",
            data={
                "kind": "vacancy",
                "vacancy_id": self.vacancy["id"],
                "label": "Private final",
            },
            files={"file": ("private.txt", b"SECRET RESUME CONTENT", "text/plain")},
        )
        self.assertEqual(response.status_code, 201)
        resume = response.json()
        version_folder = Path(resume["extracted_text_path"]).parent
        self.assertTrue(version_folder.is_dir())
        self.client.post(f"/api/resumes/{resume['id']}/submit")

        deleted = self.client.delete(f"/api/resumes/{resume['id']}")
        self.assertEqual(deleted.status_code, 200)
        summary = deleted.json()
        self.assertFalse(summary["already_deleted"])
        self.assertTrue(summary["files_removed"])
        self.assertFalse(version_folder.exists())

        row = self.context.app.state.db.fetch_one(
            "SELECT * FROM resume_versions WHERE id = ?", (resume["id"],)
        )
        self.assertEqual(row["id"], resume["id"])
        self.assertEqual(row["version"], resume["version"])
        self.assertEqual(row["content_text"], "")
        self.assertEqual(row["label"], "")
        self.assertIsNone(row["original_path"])
        self.assertIsNone(row["extracted_text_path"])
        self.assertEqual(row["is_submitted"], 0)
        self.assertIsNotNone(row["deleted_at"])

        for method, url in (
            (self.client.get, f"/api/resumes/{resume['id']}"),
            (self.client.get, f"/api/resumes/{resume['id']}/download"),
            (self.client.get, f"/api/resumes/{resume['id']}/markdown"),
            (self.client.post, f"/api/resumes/{resume['id']}/submit"),
        ):
            with self.subTest(url=url):
                self.assertEqual(method(url).status_code, 404)
        self.assertEqual(
            self.client.get(
                f"/api/resumes?kind=vacancy&vacancy_id={self.vacancy['id']}"
            ).json(),
            [],
        )

        again = self.client.delete(f"/api/resumes/{resume['id']}")
        self.assertEqual(again.status_code, 200)
        self.assertTrue(again.json()["already_deleted"])
        replacement = self.client.post(
            "/api/resumes",
            data={
                "kind": "vacancy",
                "vacancy_id": self.vacancy["id"],
                "text": "Replacement",
            },
        ).json()
        self.assertEqual(replacement["version"], resume["version"] + 1)

    def test_deleted_source_keeps_child_provenance_but_cannot_be_reused(self) -> None:
        master = self.client.post(
            "/api/resumes", data={"kind": "master", "text": "PRIVATE MASTER"}
        ).json()
        child = self.client.post(
            "/api/resumes",
            data={
                "kind": "vacancy",
                "vacancy_id": self.vacancy["id"],
                "source_resume_id": master["id"],
                "text": "Independent child content",
            },
        ).json()

        self.assertEqual(self.client.delete(f"/api/resumes/{master['id']}").status_code, 200)
        preserved = self.client.get(f"/api/resumes/{child['id']}").json()
        self.assertEqual(preserved["source_resume_id"], master["id"])
        self.assertEqual(preserved["source_kind"], "master")
        self.assertEqual(preserved["source_version"], master["version"])
        self.assertIsNotNone(preserved["source_deleted_at"])
        self.assertEqual(preserved["content_text"], "Independent child content")

        for data in (
            {
                "kind": "vacancy",
                "vacancy_id": self.vacancy["id"],
                "source_resume_id": master["id"],
            },
            {
                "kind": "vacancy",
                "vacancy_id": self.vacancy["id"],
                "source_resume_id": master["id"],
                "text": "Do not accept deleted provenance",
            },
        ):
            with self.subTest(data=data):
                self.assertEqual(self.client.post("/api/resumes", data=data).status_code, 404)

    def test_delete_rejects_unsafe_or_shared_storage_folder(self) -> None:
        first = self.client.post(
            "/api/resumes", data={"kind": "master", "text": "First"}
        ).json()
        second = self.client.post(
            "/api/resumes", data={"kind": "master", "text": "Second"}
        ).json()
        database = self.context.app.state.db
        with database.transaction() as connection:
            connection.execute(
                "UPDATE resume_versions SET extracted_text_path = ? WHERE id = ?",
                (first["extracted_text_path"], second["id"]),
            )
        self.assertEqual(self.client.delete(f"/api/resumes/{first['id']}").status_code, 409)
        self.assertTrue(Path(first["extracted_text_path"]).exists())
        self.assertEqual(self.client.get(f"/api/resumes/{first['id']}").status_code, 200)

        outside = Path(self.temp_dir.name) / "outside-resume.md"
        outside.write_text("outside", encoding="utf-8")
        with database.transaction() as connection:
            connection.execute(
                "UPDATE resume_versions SET extracted_text_path = ? WHERE id = ?",
                (str(outside), first["id"]),
            )
        self.assertEqual(self.client.delete(f"/api/resumes/{first['id']}").status_code, 409)
        self.assertEqual(outside.read_text(encoding="utf-8"), "outside")

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

    def test_delete_preserves_ats_history_scrubs_evidence_and_only_clears_current_match(self) -> None:
        older_resume = self.client.post(
            "/api/resumes",
            data={"kind": "master", "text": "Five years Python and SQL experience."},
        ).json()
        older_analysis = self.client.post(
            f"/api/vacancies/{self.vacancy['id']}/ats",
            json={"resume_version_id": older_resume["id"]},
        ).json()
        current_resume = self.client.post(
            "/api/resumes",
            data={"kind": "master", "text": "Three years Python, SQL, and Docker."},
        ).json()
        current_analysis = self.client.post(
            f"/api/vacancies/{self.vacancy['id']}/ats",
            json={"resume_version_id": current_resume["id"]},
        ).json()

        older_delete = self.client.delete(f"/api/resumes/{older_resume['id']}").json()
        self.assertEqual(older_delete["ats_analyses_preserved"], 1)
        self.assertEqual(older_delete["current_matches_cleared"], 0)
        self.assertEqual(
            self.client.get(f"/api/vacancies/{self.vacancy['id']}").json()["match_percent"],
            current_analysis["match_percent"],
        )
        stored_older = self.context.app.state.db.fetch_one(
            "SELECT result_json FROM ats_analyses WHERE id = ?", (older_analysis["id"],)
        )
        self.assertNotIn("Five years Python", stored_older["result_json"])

        current_delete = self.client.delete(f"/api/resumes/{current_resume['id']}").json()
        self.assertEqual(current_delete["ats_analyses_preserved"], 1)
        self.assertEqual(current_delete["current_matches_cleared"], 1)
        self.assertIsNone(
            self.client.get(f"/api/vacancies/{self.vacancy['id']}").json()["match_percent"]
        )
        historical = self.client.get(
            f"/api/vacancies/{self.vacancy['id']}/ats"
        ).json()
        self.assertTrue(historical["resume_deleted"])
        self.assertTrue(historical["is_stale"])
        self.assertTrue(
            all(not item["evidence"] for item in historical["result"]["requirements"])
        )
        blocked = self.client.post(
            f"/api/vacancies/{self.vacancy['id']}/ats",
            json={"resume_version_id": current_resume["id"]},
        )
        self.assertEqual(blocked.status_code, 404)

    def test_ats_does_not_invent_evidence(self) -> None:
        result = analyze("Must have COBOL mainframe experience.", "Python web developer.")
        item = result["requirements"][0]
        self.assertEqual(item["classification"], "missing")
        self.assertEqual(item["evidence"], "")
        self.assertIn("Not evidenced", item["interpretation"])

    def test_ats_does_not_score_job_intro_or_company_marketing_as_requirements(self) -> None:
        vacancy = """Менеджер по работе с клиентами
Компания HARDKOD работает с 2010 года.
Мы специализируемся на SEO, техподдержке и создании сайтов.
Ищем аккаунт менеджера, который будет помогать нашей команде и заказчикам лучше понимать друг друга.
Перед Вами будут стоять следующие задачи:
Увеличивать LTV действующих клиентов и сокращать отток клиентов.
Что будете делать:
Активно взаимодействовать с клиентами по телефону, CRM, вести деловую переписку.
Требования:
Опыт работы аккаунт менеджером от 1 года.
Опыт в продажах B2B.
Умение доносить суть простыми словами.
В свою очередь мы гарантируем:
Высокий уровень дохода: оклад + проценты.
Удаленная работа по графику 5/2."""

        result = analyze(
            vacancy,
            "Project manager with React, JavaScript, HTML, CSS, and API experience. "
            "Worked with clients on retention and contract renewals.",
        )

        requirement_text = "\n".join(item["requirement"] for item in result["requirements"])
        self.assertIn("Опыт работы аккаунт менеджером от 1 года", requirement_text)
        self.assertIn("Опыт в продажах B2B", requirement_text)
        self.assertIn("Умение доносить суть простыми словами", requirement_text)
        self.assertIn("Активно взаимодействовать с клиентами", requirement_text)
        self.assertNotIn("Перед Вами будут стоять", requirement_text)
        self.assertNotIn("Мы специализируемся на SEO", requirement_text)
        self.assertNotIn("Компания HARDKOD работает", requirement_text)
        self.assertNotIn("Высокий уровень дохода", requirement_text)
        self.assertNotIn("Удаленная работа", requirement_text)
        self.assertNotIn("мы", result["keywords"])
        self.assertNotIn("вакансия", result["keywords"])
        self.assertNotIn("hardkod", result["keywords"])
        self.assertNotIn("seo", result["keywords"])
        self.assertNotIn("дохода", result["keywords"])
        self.assertLess(result["match_percent"], 20)

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
                5,
            )
            vacancy = database.fetch_one("SELECT * FROM vacancies WHERE id = 1")
            self.assertEqual(vacancy["raw_description"], vacancy["description"])
            self.assertEqual(vacancy["description_confirmed_at"], "2026-09-21")
            resume = database.fetch_one("SELECT * FROM resume_versions WHERE id = 1")
            self.assertIsNone(resume["source_resume_id"])
            self.assertIsNone(resume["deleted_at"])
            ai_columns = {
                row["name"]
                for row in database.fetch_all("PRAGMA table_info(ai_runs)")
            }
            self.assertIn("reasoning_effort", ai_columns)


if __name__ == "__main__":
    unittest.main()
