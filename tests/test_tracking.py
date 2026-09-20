from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from careerflow.api import create_app
from careerflow.config import Settings


class TrackingApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        settings = Settings(root, root / "data", root / "storage", root / "data" / "test.db", "codex", 10)
        self.context = TestClient(create_app(settings))
        self.client = self.context.__enter__()
        self.vacancy = self.client.post(
            "/api/vacancies", data={"text": "Platform Engineer\nCompany: Acme\nPython, SQL, cloud"}
        ).json()

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def test_status_interviews_and_timeline(self) -> None:
        changed = self.client.post(
            f"/api/vacancies/{self.vacancy['id']}/status", json={"status": "Applied", "note": "Applied via careers page"}
        )
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.json()["status"], "Applied")
        for number in range(2):
            response = self.client.post(
                f"/api/vacancies/{self.vacancy['id']}/interviews",
                json={"interview_at": f"2026-09-2{number}T10:00", "interview_type": "Technical", "note": "Python discussion", "result": "Passed"},
            )
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()["sequence_number"], number + 1)
        timeline = self.client.get(f"/api/vacancies/{self.vacancy['id']}/timeline").json()
        titles = [event["title"] for event in timeline]
        self.assertIn("Interview #1 · Technical", titles)
        self.assertIn("Interview #2 · Technical", titles)
        self.assertEqual(self.client.get(f"/api/vacancies/{self.vacancy['id']}").json()["status"], "Interview")

    def test_notes_and_attachments(self) -> None:
        note = self.client.post(
            f"/api/vacancies/{self.vacancy['id']}/notes", json={"body": "Ask about on-call rotation"}
        )
        self.assertEqual(note.status_code, 201)
        note_id = note.json()["id"]
        edited = self.client.patch(
            f"/api/vacancies/{self.vacancy['id']}/notes/{note_id}", json={"body": "Ask about team and on-call"}
        )
        self.assertIn("team", edited.json()["body"])
        self.assertEqual(len(self.client.get(f"/api/vacancies/{self.vacancy['id']}/notes").json()), 1)

        attached = self.client.post(
            f"/api/vacancies/{self.vacancy['id']}/attachments",
            files={"file": ("interview-notes.md", b"# Notes\nGood conversation", "text/markdown")},
        )
        self.assertEqual(attached.status_code, 201)
        attachment = attached.json()
        self.assertEqual(attachment["is_text"], 1)
        download = self.client.get(
            f"/api/vacancies/{self.vacancy['id']}/attachments/{attachment['id']}/download"
        )
        self.assertEqual(download.content, b"# Notes\nGood conversation")
        self.assertEqual(self.client.delete(f"/api/vacancies/{self.vacancy['id']}/attachments/{attachment['id']}").status_code, 204)
        self.assertEqual(self.client.delete(f"/api/vacancies/{self.vacancy['id']}/notes/{note_id}").status_code, 204)

    def test_delete_can_preserve_vacancy_resumes_as_master(self) -> None:
        resume = self.client.post(
            "/api/resumes",
            data={"kind": "vacancy", "vacancy_id": self.vacancy["id"], "text": "Python platform engineer", "label": "Submitted CV"},
        ).json()
        response = self.client.delete(
            f"/api/vacancies/{self.vacancy['id']}?resume_policy=preserve_resumes"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["preserved_resume_count"], 1)
        preserved = self.client.get(f"/api/resumes/{resume['id']}").json()
        self.assertEqual(preserved["kind"], "master")
        self.assertIsNone(preserved["vacancy_id"])
        self.assertEqual(self.client.get(f"/api/vacancies/{self.vacancy['id']}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
