from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from careerflow.api import create_app
from careerflow.codex import build_prompt, run_codex
from careerflow.config import Settings


class ReportsAndCodexTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.settings = Settings(root, root / "data", root / "storage", root / "data" / "test.db", "codex-test", 10)
        self.context = TestClient(create_app(self.settings))
        self.client = self.context.__enter__()
        self.vacancy = self.client.post(
            "/api/vacancies", data={"text": "Data Engineer\nCompany: Northwind\nMust know Python and SQL."}
        ).json()
        self.resume = self.client.post(
            "/api/resumes", data={"kind": "vacancy", "vacancy_id": self.vacancy["id"], "text": "Python engineer using SQL.", "label": "Data version"}
        ).json()
        self.client.post(
            f"/api/vacancies/{self.vacancy['id']}/ats", json={"resume_version_id": self.resume["id"]}
        )
        self.client.post(
            f"/api/vacancies/{self.vacancy['id']}/notes", json={"body": "Ask about the data platform"}
        )
        self.client.post(
            f"/api/vacancies/{self.vacancy['id']}/attachments",
            files={"file": ("prep.md", b"# Prep\nDiscuss pipelines", "text/markdown")},
        )

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def test_markdown_report_contains_portable_context_and_downloads(self) -> None:
        response = self.client.post(f"/api/vacancies/{self.vacancy['id']}/reports")
        self.assertEqual(response.status_code, 201)
        report = response.json()
        markdown = report["markdown"]
        self.assertIn("# Data Engineer", markdown)
        self.assertIn("## ATS analysis", markdown)
        self.assertIn("Python engineer using SQL", markdown)
        self.assertIn("Ask about the data platform", markdown)
        self.assertIn("Discuss pipelines", markdown)
        self.assertTrue(Path(report["stored_path"]).exists())
        download = self.client.get(
            f"/api/vacancies/{self.vacancy['id']}/reports/{report['id']}/download"
        )
        self.assertEqual(download.status_code, 200)
        self.assertIn(b"CareerFlow local context report", download.content)

    def test_codex_command_is_noninteractive_read_only_and_no_shell(self) -> None:
        calls = {}

        def fake_runner(command, **kwargs):
            calls["command"] = command
            calls["kwargs"] = kwargs
            return subprocess.CompletedProcess(command, 0, stdout="Actionable response\n", stderr="")

        result = run_codex(self.settings, "prompt", runner=fake_runner)
        self.assertEqual(result.response, "Actionable response")
        self.assertIn("exec", calls["command"])
        self.assertIn("read-only", calls["command"])
        self.assertIn("--ephemeral", calls["command"])
        self.assertIn("gpt-5.6-luna", calls["command"])
        self.assertIn('model_reasoning_effort="low"', calls["command"])
        self.assertEqual(calls["command"][-1], "-")
        self.assertFalse(calls["kwargs"]["shell"])
        self.assertEqual(calls["kwargs"]["input"], "prompt")

    @patch("careerflow.routes_ai_reports.run_codex")
    def test_ai_api_returns_and_records_text_without_mutating_vacancy(self, mocked_run) -> None:
        from careerflow.codex import CodexResult

        mocked_run.return_value = CodexResult("Prepare three STAR examples.", ["codex"])
        before = self.client.get(f"/api/vacancies/{self.vacancy['id']}").json()
        response = self.client.post(
            f"/api/vacancies/{self.vacancy['id']}/ai-runs",
            json={"action": "Prepare for interview", "prompt": "What should I prepare?", "model": "gpt-5.6-luna"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["response"], "Prepare three STAR examples.")
        self.assertIn("CAREERFLOW CONTEXT", mocked_run.call_args.args[1])
        after = self.client.get(f"/api/vacancies/{self.vacancy['id']}").json()
        self.assertEqual(before["description"], after["description"])
        self.assertEqual(len(self.client.get(f"/api/vacancies/{self.vacancy['id']}/ai-runs").json()), 1)

    def test_prompt_rejects_empty_request_and_model_injection(self) -> None:
        with self.assertRaises(ValueError):
            build_prompt("  ", "context")
        with self.assertRaises(ValueError):
            run_codex(self.settings, "prompt", model="bad model; rm")


if __name__ == "__main__":
    unittest.main()
