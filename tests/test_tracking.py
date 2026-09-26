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

    def test_interview_timestamp_requires_real_iso_datetime_and_accepts_offsets(self) -> None:
        url = f"/api/vacancies/{self.vacancy['id']}/interviews"
        for value in (
            "yesterday-ish", "2026-09-21", "2026-09-21 10:00",
            "2026-02-30T10:00", "2026-09-21T25:00",
            "2026-09-21T10:00+25:00", "2026-09-21T10:00+02:99",
            "2026-09-21T10:00+14:01", "   ",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    self.client.post(url, json={"interview_at": value}).status_code,
                    422,
                )
        self.assertEqual(self.client.get(url).json(), [])
        self.assertEqual(self.client.get(f"/api/vacancies/{self.vacancy['id']}").json()["status"], "Saved")

        for sequence, value in enumerate(
            ("2026-09-21T10:00", "2026-09-22T12:30Z", "2026-09-23T14:15+02:00"),
            start=1,
        ):
            with self.subTest(value=value):
                response = self.client.post(url, json={"interview_at": value})
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.json()["interview_at"], value)
                self.assertEqual(response.json()["sequence_number"], sequence)

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

    def test_delete_all_removes_related_local_files(self) -> None:
        resume = self.client.post(
            "/api/resumes",
            data={
                "kind": "vacancy",
                "vacancy_id": self.vacancy["id"],
                "text": "Python platform engineer",
            },
        ).json()
        attachment = self.client.post(
            f"/api/vacancies/{self.vacancy['id']}/attachments",
            files={"file": ("notes.txt", b"private notes", "text/plain")},
        ).json()
        report = self.client.post(
            f"/api/vacancies/{self.vacancy['id']}/reports"
        ).json()
        stored_paths = [
            Path(self.vacancy["extracted_text_path"]),
            Path(resume["extracted_text_path"]),
            Path(attachment["stored_path"]),
            Path(report["stored_path"]),
        ]
        self.assertTrue(all(path.exists() for path in stored_paths))

        response = self.client.delete(
            f"/api/vacancies/{self.vacancy['id']}?resume_policy=delete_all"
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(not path.exists() for path in stored_paths))
        self.assertEqual(self.client.get(f"/api/resumes/{resume['id']}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
