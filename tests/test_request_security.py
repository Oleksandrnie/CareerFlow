from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from careerflow.api import create_app
from careerflow.config import Settings


class LocalRequestSecurityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        settings = Settings(
            root, root / "data", root / "storage", root / "data" / "test.db", "codex", 10
        )
        self.context = TestClient(create_app(settings))
        self.client = self.context.__enter__()

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def test_cross_origin_write_is_rejected_before_mutation(self) -> None:
        response = self.client.post(
            "/api/vacancies",
            data={"text": "Synthetic job posting"},
            headers={"Origin": "https://attacker.example"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get("/api/vacancies").json(), [])

    def test_same_origin_write_is_allowed(self) -> None:
        response = self.client.post(
            "/api/vacancies",
            data={"text": "Synthetic job posting"},
            headers={"Origin": "http://testserver"},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(self.client.get("/api/vacancies").json()), 1)

    def test_cross_scheme_origin_is_rejected_even_when_ports_match(self) -> None:
        response = self.client.post(
            "/api/vacancies",
            data={"text": "Synthetic job posting"},
            headers={"Origin": "https://testserver:80"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get("/api/vacancies").json(), [])

    def test_public_hostnames_are_rejected(self) -> None:
        response = self.client.get("/api/health", headers={"Host": "attacker.example"})

        self.assertEqual(response.status_code, 400)

    def test_declared_oversized_request_is_rejected_before_parsing(self) -> None:
        response = self.client.post(
            "/api/vacancies",
            headers={"Content-Length": str(102 * 1024 * 1024)},
        )

        self.assertEqual(response.status_code, 413)

    @patch("careerflow.api.MAX_REQUEST_BODY_BYTES", 8)
    def test_chunked_oversized_request_is_rejected_while_streaming(self) -> None:
        body = (
            b"--test-boundary\r\n"
            b'Content-Disposition: form-data; name="text"\r\n\r\n'
            b"Synthetic job posting\r\n"
            b"--test-boundary--\r\n"
        )
        response = self.client.post(
            "/api/vacancies",
            content=iter([body]),
            headers={"Content-Type": "multipart/form-data; boundary=test-boundary"},
        )

        self.assertEqual(response.status_code, 413)

    def test_chunked_oversized_json_does_not_mutate_vacancy(self) -> None:
        vacancy = self.client.post(
            "/api/vacancies",
            data={"text": "Synthetic job posting", "title": "Original title"},
        ).json()
        payload = b'{"title":"Updated title"}'

        async def send_chunked_request() -> httpx.Response:
            async def body_chunks():
                yield payload
                yield b" " * 16

            transport = httpx.ASGITransport(app=self.context.app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as async_client:
                return await async_client.patch(
                    f"/api/vacancies/{vacancy['id']}",
                    content=body_chunks(),
                    headers={"Content-Type": "application/json"},
                )

        with patch("careerflow.api.MAX_REQUEST_BODY_BYTES", len(payload)):
            response = asyncio.run(send_chunked_request())

        self.assertEqual(response.status_code, 413)
        persisted = self.client.get(f"/api/vacancies/{vacancy['id']}").json()
        self.assertEqual(persisted["title"], "Original title")

    @patch("careerflow.routes_vacancies.MAX_UPLOAD_BYTES", 8)
    def test_vacancy_upload_is_bounded_before_file_extraction(self) -> None:
        response = self.client.post(
            "/api/vacancies",
            files={"file": ("vacancy.txt", b"123456789", "text/plain")},
        )

        self.assertEqual(response.status_code, 413)

    @patch("careerflow.routes_vacancies.MAX_UPLOAD_BYTES", 8)
    def test_vacancy_preview_upload_is_bounded(self) -> None:
        response = self.client.post(
            "/api/vacancies/import-preview",
            files={"file": ("vacancy.txt", b"123456789", "text/plain")},
        )

        self.assertEqual(response.status_code, 413)

    @patch("careerflow.routes_resumes.MAX_UPLOAD_BYTES", 8)
    def test_resume_upload_is_bounded(self) -> None:
        response = self.client.post(
            "/api/resumes",
            data={"kind": "master"},
            files={"file": ("resume.txt", b"123456789", "text/plain")},
        )

        self.assertEqual(response.status_code, 413)

    @patch("careerflow.routes_tracking.MAX_ATTACHMENT_BYTES", 8)
    def test_attachment_upload_is_bounded(self) -> None:
        vacancy = self.client.post("/api/vacancies", data={"text": "Synthetic job posting"}).json()
        response = self.client.post(
            f"/api/vacancies/{vacancy['id']}/attachments",
            files={"file": ("notes.txt", b"123456789", "text/plain")},
        )

        self.assertEqual(response.status_code, 413)


if __name__ == "__main__":
    unittest.main()
