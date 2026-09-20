from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from careerflow.api import create_app
from careerflow.ats import analyze
from careerflow.config import Settings


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
        result = analysis["result"]
        self.assertIn("requirements", result)
        self.assertIn("not that the candidate lacks", result["disclaimer"])
        evidenced = [item for item in result["requirements"] if item["evidence"]]
        self.assertTrue(evidenced)
        vacancy = self.client.get(f"/api/vacancies/{self.vacancy['id']}").json()
        self.assertEqual(vacancy["match_percent"], analysis["match_percent"])

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

    def test_master_cannot_be_submitted(self) -> None:
        master = self.client.post(
            "/api/resumes", data={"kind": "master", "text": "Python engineer"}
        ).json()
        response = self.client.post(f"/api/resumes/{master['id']}/submit")
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
