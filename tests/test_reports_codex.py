from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from careerflow.api import create_app
from careerflow.codex import build_prompt, run_codex
from careerflow.routes_ai_reports import parse_ai_match_response
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

    def test_master_only_analysis_includes_the_full_analyzed_resume(self) -> None:
        vacancy = self.client.post(
            "/api/vacancies", data={"text": "Python Engineer\nRequired Python experience."}
        ).json()
        master = self.client.post(
            "/api/resumes",
            data={"kind": "master", "text": "Python experience. SECRET_FULL_CV_DETAIL_ONLY."},
        ).json()
        self.client.post(
            f"/api/vacancies/{vacancy['id']}/ats",
            json={"resume_version_id": master["id"]},
        )

        report = self.client.post(f"/api/vacancies/{vacancy['id']}/reports").json()["markdown"]
        self.assertIn("No vacancy-specific resume version has been added", report)
        self.assertIn(f"Master Resume v{master['version']} (ID {master['id']}", report)
        self.assertIn("SECRET_FULL_CV_DETAIL_ONLY", report)
        self.assertIn(f"Resume ID: {master['id']}", report)

    def test_report_distinguishes_analyzed_older_from_submitted_and_latest(self) -> None:
        submitted = self.client.post(
            "/api/resumes",
            data={
                "kind": "vacancy", "vacancy_id": self.vacancy["id"],
                "text": "SUBMITTED_CV_DETAIL SQL", "label": "Submitted",
            },
        ).json()
        latest = self.client.post(
            "/api/resumes",
            data={
                "kind": "vacancy", "vacancy_id": self.vacancy["id"],
                "text": "LATEST_UNSUBMITTED_CV_DETAIL", "label": "Draft",
            },
        ).json()
        self.client.post(f"/api/resumes/{submitted['id']}/submit")

        report = self.client.post(f"/api/vacancies/{self.vacancy['id']}/reports").json()["markdown"]
        self.assertIn(f"Workflow resume: submitted Vacancy Resume v{submitted['version']}", report)
        self.assertIn("SUBMITTED_CV_DETAIL", report)
        self.assertIn(f"Vacancy Resume v{self.resume['version']} (ID {self.resume['id']}", report)
        self.assertIn("Python engineer using SQL", report)
        self.assertIn("This differs from the workflow resume", report)
        self.assertIn(f"Vacancy Resume v{latest['version']}: Draft", report)
        self.assertNotIn("LATEST_UNSUBMITTED_CV_DETAIL", report)

    def test_deleted_resume_is_redacted_from_new_and_existing_reports(self) -> None:
        vacancy = self.client.post(
            "/api/vacancies", data={"text": "Python Engineer\nRequired Python experience."}
        ).json()
        secret = "PRIVATE_RESUME_TEXT Python experience in a confidential project."
        resume = self.client.post(
            "/api/resumes", data={"kind": "master", "text": secret}
        ).json()
        self.client.post(
            f"/api/vacancies/{vacancy['id']}/ats",
            json={"resume_version_id": resume["id"]},
        )
        existing = self.client.post(f"/api/vacancies/{vacancy['id']}/reports").json()
        self.assertIn("PRIVATE_RESUME_TEXT", existing["markdown"])

        deleted = self.client.delete(f"/api/resumes/{resume['id']}").json()
        self.assertEqual(deleted["reports_redacted"], 1)
        self.assertTrue(Path(existing["stored_path"]).is_file())
        downloaded = self.client.get(
            f"/api/vacancies/{vacancy['id']}/reports/{existing['id']}/download"
        )
        self.assertEqual(downloaded.status_code, 200)
        self.assertNotIn(b"PRIVATE_RESUME_TEXT", downloaded.content)

        fresh = self.client.post(
            f"/api/vacancies/{vacancy['id']}/reports"
        ).json()["markdown"]
        self.assertNotIn("PRIVATE_RESUME_TEXT", fresh)
        self.assertIn("resume version was deleted", fresh)
        self.assertIn("Resume-derived evidence is omitted", fresh)
        self.assertIn("Historical match (not current)", fresh)

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

    @patch("careerflow.routes_ai_reports.run_codex")
    def test_ai_history_returns_full_result_and_resolved_model(self, mocked_run) -> None:
        from careerflow.codex import CodexResult

        mocked_run.return_value = CodexResult("Full saved answer", ["codex"])
        url = f"/api/vacancies/{self.vacancy['id']}/ai-runs"
        created = self.client.post(
            url, json={"prompt": "  What should I prepare?  ", "action": "Prepare"}
        )
        self.assertEqual(created.status_code, 201)
        run = created.json()
        self.assertEqual(run["prompt"], "What should I prepare?")
        self.assertEqual(run["model"], self.settings.codex_default_model)
        self.assertEqual(run["reasoning_effort"], self.settings.codex_reasoning_effort)
        self.assertEqual(run["response"], "Full saved answer")
        self.assertEqual(mocked_run.call_args.kwargs["model"], self.settings.codex_default_model)
        self.assertEqual(
            mocked_run.call_args.kwargs["reasoning_effort"],
            self.settings.codex_reasoning_effort,
        )
        self.assertEqual(self.client.get(f"{url}/{run['id']}").json(), run)
        self.assertEqual(self.client.get(url).json()[0], run)

        other = self.client.post(
            "/api/vacancies", data={"text": "Different role\nPython"}
        ).json()
        self.assertEqual(
            self.client.get(f"/api/vacancies/{other['id']}/ai-runs/{run['id']}").status_code,
            404,
        )

    @patch("careerflow.routes_ai_reports.run_codex")
    def test_ai_prompt_and_model_validation_return_422_without_run(self, mocked_run) -> None:
        url = f"/api/vacancies/{self.vacancy['id']}/ai-runs"
        for payload in (
            {"prompt": "   "},
            {"prompt": "Valid question", "model": "bad model; command"},
        ):
            with self.subTest(payload=payload):
                response = self.client.post(url, json=payload)
                self.assertEqual(response.status_code, 422)
        mocked_run.assert_not_called()
        self.assertEqual(self.client.get(url).json(), [])

    @patch("careerflow.routes_ai_reports.run_codex")
    def test_failed_ai_run_is_retrievable_with_error_and_resolved_model(self, mocked_run) -> None:
        from careerflow.codex import CodexError

        mocked_run.side_effect = CodexError("CLI unavailable")
        url = f"/api/vacancies/{self.vacancy['id']}/ai-runs"
        response = self.client.post(url, json={"prompt": "Help me prepare"})
        self.assertEqual(response.status_code, 502)
        history = self.client.get(url).json()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["status"], "failed")
        self.assertEqual(history[0]["error"], "CLI unavailable")
        self.assertEqual(history[0]["model"], self.settings.codex_default_model)
        self.assertEqual(history[0]["reasoning_effort"], self.settings.codex_reasoning_effort)
        self.assertEqual(self.client.get(f"{url}/{history[0]['id']}").json(), history[0])

    def test_prompt_rejects_empty_request_and_model_injection(self) -> None:
        with self.assertRaises(ValueError):
            build_prompt("  ", "context")
        with self.assertRaises(ValueError):
            run_codex(self.settings, "prompt", model="bad model; rm")

    def test_ai_match_parser_accepts_strict_score_only(self) -> None:
        self.assertEqual(parse_ai_match_response('{"match_percent": 74, "summary": "Good"}'), 74)
        self.assertEqual(parse_ai_match_response('```json\n{"match_percent": 50}\n```'), 50)
        self.assertEqual(parse_ai_match_response('Here is the result:\n{"match_percent": 45, "summary": "ok"}'), 45)
        for response in (
            "not json",
            '{"match_percent": 101}',
            '{"match_percent": true}',
            '{"match_percent": 74.5}',
        ):
            with self.subTest(response=response):
                self.assertIsNone(parse_ai_match_response(response))

    @patch("careerflow.routes_ai_reports.run_codex")
    def test_ai_match_updates_separate_vacancy_score(self, mocked_run) -> None:
        from careerflow.codex import CodexResult

        mocked_run.return_value = CodexResult(
            '{"match_percent": 74, "summary": "Good match", "strengths": ["Python"], "gaps": ["Docker"]}',
            ["codex"],
        )
        before = self.client.get(f"/api/vacancies/{self.vacancy['id']}").json()
        response = self.client.post(
            f"/api/vacancies/{self.vacancy['id']}/ai-runs",
            json={"action": "Match resume to vacancy", "prompt": "Compare resume and vacancy", "model": "gpt-5.6-luna"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["ai_match_percent"], 74)
        self.assertIn("Return JSON only", mocked_run.call_args.args[1])
        after = self.client.get(f"/api/vacancies/{self.vacancy['id']}").json()
        self.assertEqual(after["ai_match_percent"], 74)
        self.assertEqual(after["match_percent"], before["match_percent"])


if __name__ == "__main__":
    unittest.main()
