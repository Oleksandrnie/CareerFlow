from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from careerflow.api import create_app
from careerflow.config import Settings


class AtsReviewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        settings = Settings(
            root, root / "data", root / "storage", root / "data" / "test.db", "codex", 10
        )
        self.context = TestClient(create_app(settings))
        self.client = self.context.__enter__()
        self.vacancy = self.client.post(
            "/api/vacancies", data={"text": "Product Project Manager\nOwn delivery planning"}
        ).json()
        self.master = self.client.post(
            "/api/resumes", data={"kind": "master", "text": "L1 evidence: led a product delivery team."}
        ).json()
        self.other = self.client.post(
            "/api/resumes", data={"kind": "master", "text": "SECRET_OTHER_RESUME"}
        ).json()
        self.catalog = {
            "models": [{"id": "mock-model", "name": "Mock", "efforts": ["low"]}],
            "default_model": "mock-model",
            "default_effort": "low",
            "source": "test",
        }

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def test_manager_audit_uses_only_selected_resume_and_redacts_result_on_delete(self) -> None:
        response_json = {
            "overall_summary": "Evidence-backed",
            "role_family": {"claimed_family": "Project Manager", "supported_family": "Project Manager"},
            "grade_inflation": {"severity": "none"},
            "scores": {
                "Evidence": 0.5,
                "RoleClarity": 0.5,
                "AntiPersonaClean": 0.5,
                "TenSecondRead": 0.5,
                "KeywordFit": 0.5,
                "Structure": 0.5,
            },
            "overall_score_percent": 50,
            "anti_persona_flags": [
                {"name": name, "status": "CLEAR", "line_refs": []}
                for name in (
                    "Project administrator", "Project proxy", "Ritual agile PM",
                    "Unimmersed delivery manager", "Manager-router",
                    "General management without domain",
                )
            ],
            "ten_second_read": [
                {"check": name, "result": "clear", "line_refs": []}
                for name in ("grade", "domain", "first_bullet_impact", "scope", "tools")
            ],
            "structure": {"rubric": "T"},
            "evidence_review": [],
            "priority_improvements": [],
            "verdict": "Conditional",
        }
        with (
            patch("careerflow.ats_review.load_model_catalog", return_value=self.catalog),
            patch(
                "careerflow.ats_review.run_codex",
                return_value=SimpleNamespace(response=json.dumps(response_json)),
            ) as codex,
        ):
            response = self.client.post(
                "/api/ats/assessments",
                json={
                    "assessment_kind": "manager_audit",
                    "resume_version_id": self.master["id"],
                    "locale": "en",
                },
            )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["result"]["overall_score_percent"], 50)
        self.assertEqual(response.json()["result"]["scores"], response_json["scores"])
        self.assertIn("weighted_sum", response.json()["result"])
        prompt = codex.call_args.args[1]
        self.assertIn("L1: L1 evidence: led a product delivery team.", prompt)
        self.assertNotIn("SECRET_OTHER_RESUME", prompt)
        self.assertNotIn(self.vacancy["description"], prompt)

        deleted = self.client.delete(f"/api/resumes/{self.master['id']}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json()["ats_assessments_redacted"], 1)
        history = self.client.get(
            f"/api/ats/assessments?resume_version_id={self.master['id']}"
        ).json()
        self.assertTrue(history[0]["resume_deleted"])
        self.assertTrue(history[0]["redacted_at"])
        self.assertEqual(history[0]["response"], "")
        self.assertTrue(history[0]["result"]["redacted"])

    def test_vacancy_match_requires_confirmed_description_and_marks_stale(self) -> None:
        vacancy_resume = self.client.post(
            "/api/resumes",
            data={
                "kind": "vacancy",
                "vacancy_id": self.vacancy["id"],
                "text": "Led delivery planning with product teams.",
            },
        ).json()
        payload = {
            "assessment_kind": "vacancy_match",
            "resume_version_id": vacancy_resume["id"],
            "vacancy_id": self.vacancy["id"],
            "locale": "ru",
        }
        with patch("careerflow.ats_review.load_model_catalog", return_value=self.catalog):
            unconfirmed = self.client.post("/api/ats/assessments", json=payload)
            self.assertEqual(unconfirmed.status_code, 422)
            with self.client.app.state.db.transaction() as connection:
                connection.execute(
                    "UPDATE vacancies SET description_confirmed_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (self.vacancy["id"],),
                )
            with patch(
                "careerflow.ats_review.run_codex",
                return_value=SimpleNamespace(
                    response=json.dumps(
                        {
                            "overall_summary": "Есть релевантное подтверждение",
                            "requirements": [],
                        },
                        ensure_ascii=False,
                    )
                ),
            ):
                created = self.client.post("/api/ats/assessments", json=payload)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["assessment_kind"], "vacancy_match")
        with self.client.app.state.db.transaction() as connection:
            connection.execute(
                "UPDATE vacancies SET description = 'Updated description', description_revision = description_revision + 1 WHERE id = ?",
                (self.vacancy["id"],),
            )
        history = self.client.get(
            f"/api/ats/assessments?resume_version_id={vacancy_resume['id']}"
        ).json()
        self.assertTrue(history[0]["description_changed"])
        self.assertTrue(history[0]["is_stale"])


if __name__ == "__main__":
    unittest.main()
