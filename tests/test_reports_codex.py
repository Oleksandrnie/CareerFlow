from __future__ import annotations

from hashlib import sha256
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from careerflow.api import create_app
from careerflow.ai_resume import (
    build_tailored_resume_context,
    tailored_resume_instructions,
)
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
    def test_ordinary_ai_runs_record_the_exact_report_sources(self, mocked_run) -> None:
        from careerflow.codex import CodexResult

        mocked_run.return_value = CodexResult("Report-based response", ["codex"])
        analyzed = self.client.post(
            "/api/resumes",
            data={
                "kind": "vacancy",
                "vacancy_id": self.vacancy["id"],
                "text": "A different analyzed resume with Python.",
            },
        ).json()
        self.client.post(
            f"/api/vacancies/{self.vacancy['id']}/ats",
            json={"resume_version_id": analyzed["id"]},
        )
        self.client.post(f"/api/resumes/{self.resume['id']}/submit")

        response = self.client.post(
            f"/api/vacancies/{self.vacancy['id']}/ai-runs",
            json={"action": "Improve resume", "prompt": "Suggest truthful improvements"},
        )
        self.assertEqual(response.status_code, 201)
        run = response.json()
        sources = json.loads(run["context_sources_json"])
        vacancy = self.client.get(f"/api/vacancies/{self.vacancy['id']}").json()
        self.assertEqual(run["source_resume_id"], self.resume["id"])
        self.assertEqual(sources["resume_version_id"], self.resume["id"])
        self.assertEqual(sources["workflow_resume_id"], self.resume["id"])
        self.assertEqual(sources["ats_resume_id"], analyzed["id"])
        self.assertEqual(
            sources["included_resume_ids"], sorted([self.resume["id"], analyzed["id"]])
        )
        self.assertEqual(
            sources["vacancy_description_revision"], vacancy["description_revision"]
        )
        self.assertEqual(
            sources["vacancy_description_sha256"],
            sha256(vacancy["description"].encode("utf-8")).hexdigest(),
        )

        master_vacancy = self.client.post(
            "/api/vacancies", data={"text": "Backend Engineer\nRequired Python"}
        ).json()
        master = self.client.post(
            "/api/resumes", data={"kind": "master", "text": "Python backend work"}
        ).json()
        self.client.post(
            f"/api/vacancies/{master_vacancy['id']}/ats",
            json={"resume_version_id": master["id"]},
        )
        master_run = self.client.post(
            f"/api/vacancies/{master_vacancy['id']}/ai-runs",
            json={"action": "Analyze vacancy", "prompt": "Analyze the role"},
        ).json()
        master_sources = json.loads(master_run["context_sources_json"])
        self.assertEqual(master_run["source_resume_id"], master["id"])
        self.assertIsNone(master_sources["workflow_resume_id"])
        self.assertEqual(master_sources["ats_resume_id"], master["id"])
        self.assertEqual(master_sources["included_resume_ids"], [master["id"]])

        empty_vacancy = self.client.post(
            "/api/vacancies", data={"text": "Writer\nExcellent writing required"}
        ).json()
        empty_run = self.client.post(
            f"/api/vacancies/{empty_vacancy['id']}/ai-runs",
            json={"action": "Analyze vacancy", "prompt": "Analyze the role"},
        ).json()
        empty_sources = json.loads(empty_run["context_sources_json"])
        self.assertIsNone(empty_run["source_resume_id"])
        self.assertIsNone(empty_sources["resume_version_id"])
        self.assertEqual(empty_sources["included_resume_ids"], [])

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

    @patch("careerflow.routes_ai_reports.run_codex")
    @patch("careerflow.routes_ai_reports.load_model_catalog")
    def test_tailored_resume_uses_curated_latest_context_and_remains_read_only(
        self, mocked_catalog, mocked_run
    ) -> None:
        from careerflow.codex import CodexResult

        mocked_catalog.return_value = {
            "models": [
                {"id": "gpt-5.6-luna", "name": "Luna", "efforts": ["low"]},
                {"id": "gpt-5.6-sol", "name": "Sol", "efforts": ["medium", "high"]},
            ],
            "default_model": "gpt-5.6-luna",
            "default_effort": "low",
            "source": "codex-cli",
        }
        later_draft = self.client.post(
            "/api/resumes",
            data={
                "kind": "vacancy",
                "vacancy_id": self.vacancy["id"],
                "text": "LATEST_UNSUBMITTED_SHOULD_NOT_REPLACE_SUBMITTED",
            },
        ).json()
        self.assertNotEqual(later_draft["id"], self.resume["id"])
        self.client.post(f"/api/resumes/{self.resume['id']}/submit")
        mocked_run.side_effect = [
            CodexResult("OLD_IMPROVEMENT", ["codex"]),
            CodexResult("LATEST_IMPROVEMENT", ["codex"]),
            CodexResult("LATEST_VACANCY_ANALYSIS", ["codex"]),
            CodexResult("LATEST_MATCH", ["codex"]),
            CodexResult("LATEST_ATS_REVIEW", ["codex"]),
            CodexResult("# Tailored resume\n\nPython and SQL", ["codex"]),
        ]
        url = f"/api/vacancies/{self.vacancy['id']}/ai-runs"
        for action, prompt in (
            ("Improve resume", "Suggest truthful improvements: old"),
            ("Improve resume", "Suggest truthful improvements: latest"),
            ("Analyze vacancy", "Analyze the role and prioritize requirements"),
            ("Match resume to vacancy", "Compare the selected resume now"),
            ("Review ATS analysis", "Review the heuristic ATS evidence"),
        ):
            created = self.client.post(
                url,
                json={
                    "action": action,
                    "prompt": prompt,
                    "model": "gpt-5.6-luna",
                    "reasoning_effort": "low",
                },
            )
            self.assertEqual(created.status_code, 201)

        before = self.client.get(
            f"/api/resumes?kind=vacancy&vacancy_id={self.vacancy['id']}"
        ).json()
        tailored = self.client.post(
            url,
            json={
                "action": "Create tailored resume",
                "prompt": "Create the complete resume.",
                "model": "gpt-5.6-luna",
                "reasoning_effort": "low",
            },
        )
        self.assertEqual(tailored.status_code, 201)
        run = tailored.json()
        self.assertEqual(run["action"], "Create tailored resume")
        self.assertEqual(run["model"], "gpt-5.6-sol")
        self.assertEqual(run["reasoning_effort"], "medium")
        self.assertEqual(run["source_resume_id"], self.resume["id"])
        sources = json.loads(run["context_sources_json"])
        self.assertEqual(sources["resume_version_id"], self.resume["id"])
        self.assertIsNotNone(sources["ats_analysis_id"])
        self.assertEqual(set(sources["ai_run_ids"]), {
            "Analyze vacancy", "Improve resume", "Match resume to vacancy",
            "Review ATS analysis"
        })
        self.assertEqual(sources["ats_inclusion_status"], "included")
        generated_prompt = mocked_run.call_args.args[1]
        self.assertIn("LATEST_IMPROVEMENT", generated_prompt)
        self.assertNotIn("OLD_IMPROVEMENT", generated_prompt)
        self.assertIn("LATEST_VACANCY_ANALYSIS", generated_prompt)
        self.assertIn("LATEST_MATCH", generated_prompt)
        self.assertIn("LATEST_ATS_REVIEW", generated_prompt)
        self.assertIn("- Title: Data Engineer", generated_prompt)
        self.assertIn("- Company: Northwind", generated_prompt)
        self.assertIn("## Full confirmed vacancy description", generated_prompt)
        self.assertIn("Must know Python and SQL.", generated_prompt)
        self.assertNotIn("LATEST_UNSUBMITTED_SHOULD_NOT_REPLACE_SUBMITTED", generated_prompt)
        self.assertIn("sole authority for candidate facts", generated_prompt)
        self.assertIn("Do not invent or infer", generated_prompt)
        self.assertIn("return Markdown only", generated_prompt)
        self.assertEqual(
            self.client.get(
                f"/api/resumes?kind=vacancy&vacancy_id={self.vacancy['id']}"
            ).json(),
            before,
        )

    @patch("careerflow.routes_ai_reports.run_codex")
    @patch("careerflow.routes_ai_reports.load_model_catalog")
    def test_tailored_resume_falls_back_to_latest_master_source(
        self, mocked_catalog, mocked_run
    ) -> None:
        from careerflow.codex import CodexResult

        mocked_catalog.return_value = {
            "models": [
                {"id": "gpt-5.6-sol", "name": "Sol", "efforts": ["medium", "high"]}
            ],
            "default_model": "gpt-5.6-sol",
            "default_effort": "medium",
            "source": "codex-cli",
        }
        vacancy = self.client.post(
            "/api/vacancies", data={"text": "Platform Engineer\nRequired Kubernetes"}
        ).json()
        older = self.client.post(
            "/api/resumes", data={"kind": "master", "text": "OLDER_MASTER_CONTENT"}
        ).json()
        master = self.client.post(
            "/api/resumes",
            data={
                "kind": "master",
                "source_resume_id": older["id"],
                "text": "LATEST_MASTER_CONTENT with Kubernetes",
            },
        ).json()
        mocked_run.return_value = CodexResult("# Tailored from master", ["codex"])
        response = self.client.post(
            f"/api/vacancies/{vacancy['id']}/ai-runs",
            json={"action": "Create tailored resume", "prompt": "Create it"},
        )
        self.assertEqual(response.status_code, 201)
        run = response.json()
        self.assertEqual(run["source_resume_id"], master["id"])
        sources = json.loads(run["context_sources_json"])
        self.assertEqual(sources["resume_kind"], "master")
        self.assertEqual(sources["resume_selection"], "latest_master")
        generated_prompt = mocked_run.call_args.args[1]
        self.assertIn("LATEST_MASTER_CONTENT", generated_prompt)
        self.assertNotIn("OLDER_MASTER_CONTENT", generated_prompt)

    @patch("careerflow.routes_ai_reports.run_codex")
    def test_tailored_context_gates_ats_and_prior_ai_by_provenance(
        self, mocked_run
    ) -> None:
        from careerflow.codex import CodexResult

        analyzed = self.client.post(
            "/api/resumes",
            data={
                "kind": "vacancy",
                "vacancy_id": self.vacancy["id"],
                "text": "DIFFERENT_ANALYZED_RESUME Python",
            },
        ).json()
        latest_ats = self.client.post(
            f"/api/vacancies/{self.vacancy['id']}/ats",
            json={"resume_version_id": analyzed["id"]},
        ).json()
        self.client.post(f"/api/resumes/{self.resume['id']}/submit")
        mocked_run.side_effect = [
            CodexResult("MULTI_RESUME_IMPROVEMENT", ["codex"]),
            CodexResult("VACANCY_ONLY_ANALYSIS", ["codex"]),
        ]
        url = f"/api/vacancies/{self.vacancy['id']}/ai-runs"
        self.client.post(
            url,
            json={"action": "Improve resume", "prompt": "Suggest truthful improvements"},
        )
        self.client.post(
            url,
            json={"action": "Analyze vacancy", "prompt": "Analyze the role"},
        )

        deleted = self.client.post(
            "/api/resumes", data={"kind": "master", "text": "DELETED_SOURCE_TEXT"}
        ).json()
        vacancy = self.client.get(f"/api/vacancies/{self.vacancy['id']}").json()
        known_sources = {
            "vacancy_description_revision": vacancy["description_revision"],
            "vacancy_description_sha256": sha256(
                vacancy["description"].encode("utf-8")
            ).hexdigest(),
            "resume_version_id": self.resume["id"],
            "workflow_resume_id": self.resume["id"],
            "ats_analysis_id": latest_ats["id"],
            "ats_resume_id": analyzed["id"],
            "included_resume_ids": [self.resume["id"], deleted["id"]],
        }
        database = self.client.app.state.db
        with database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO ai_runs(
                    vacancy_id, prompt, action, source_resume_id,
                    context_sources_json, response, status
                ) VALUES (?, ?, ?, ?, ?, ?, 'completed')
                """,
                (
                    self.vacancy["id"],
                    "Review the heuristic ATS",
                    "Review ATS analysis",
                    self.resume["id"],
                    json.dumps(known_sources),
                    "DELETED_SOURCE_REVIEW",
                ),
            )
            connection.execute(
                """
                INSERT INTO ai_runs(
                    vacancy_id, prompt, action, context_sources_json, response, status
                ) VALUES (?, ?, '', '{}', ?, 'completed')
                """,
                (
                    self.vacancy["id"],
                    "Compare the selected resume with the vacancy requirements",
                    "LEGACY_MATCH_ADVICE",
                ),
            )
        self.client.delete(f"/api/resumes/{deleted['id']}")

        context, sources = build_tailored_resume_context(
            database, self.vacancy["id"]
        )
        self.assertIsNone(sources["ats_analysis_id"])
        self.assertEqual(sources["ats_candidate_analysis_id"], latest_ats["id"])
        self.assertEqual(sources["ats_inclusion_status"], "omitted")
        self.assertIn("not selected source resume", sources["ats_omission_reason"])
        self.assertNotIn(f"Analysis ID: {latest_ats['id']}", context)

        self.assertNotIn("MULTI_RESUME_IMPROVEMENT", context)
        self.assertEqual(
            sources["ai_run_sources"]["Improve resume"]["provenance_status"],
            "omitted_extra_resume_material",
        )
        self.assertIn("VACANCY_ONLY_ANALYSIS", context)
        self.assertIn("LEGACY_MATCH_ADVICE", context)
        self.assertIn("Legacy run", context)
        self.assertNotIn("DELETED_SOURCE_REVIEW", context)
        self.assertEqual(
            sources["ai_run_sources"]["Review ATS analysis"]["provenance_status"],
            "omitted_deleted_source",
        )

    @patch("careerflow.routes_ai_reports.run_codex")
    def test_tailored_context_omits_runs_and_ats_after_vacancy_change(
        self, mocked_run
    ) -> None:
        from careerflow.codex import CodexResult

        mocked_run.return_value = CodexResult("OLD_VACANCY_ADVICE", ["codex"])
        self.client.post(
            f"/api/vacancies/{self.vacancy['id']}/ai-runs",
            json={"action": "Improve resume", "prompt": "Suggest truthful improvements"},
        )
        updated_description = (
            "Data Engineer\nCompany: Northwind\nMust know Python, SQL, and Kafka."
        )
        updated = self.client.patch(
            f"/api/vacancies/{self.vacancy['id']}",
            json={"description": updated_description},
        )
        self.assertEqual(updated.status_code, 200)

        context, sources = build_tailored_resume_context(
            self.client.app.state.db, self.vacancy["id"]
        )
        self.assertIn(updated_description, context)
        self.assertNotIn("OLD_VACANCY_ADVICE", context)
        self.assertEqual(sources["ats_inclusion_status"], "omitted")
        self.assertIn("stale", sources["ats_omission_reason"])
        self.assertEqual(
            sources["ai_run_sources"]["Improve resume"]["provenance_status"],
            "omitted_vacancy_mismatch",
        )

    def test_tailored_context_includes_legacy_vacancy_analysis_with_warning(self) -> None:
        database = self.client.app.state.db
        with database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO ai_runs(
                    vacancy_id, prompt, action, context_sources_json, response, status
                ) VALUES (?, ?, '', '{}', ?, 'completed')
                """,
                (
                    self.vacancy["id"],
                    "Analyze the role and prioritize its requirements.",
                    "LEGACY_VACANCY_ANALYSIS",
                ),
            )

        context, sources = build_tailored_resume_context(
            database, self.vacancy["id"]
        )
        self.assertIn("LEGACY_VACANCY_ANALYSIS", context)
        self.assertIn("Legacy run", context)
        self.assertIn("Analyze vacancy", sources["ai_run_ids"])
        self.assertEqual(
            sources["ai_run_sources"]["Analyze vacancy"]["provenance_status"],
            "legacy_unknown",
        )

    def test_tailored_resume_requires_confirmed_description(self) -> None:
        with self.client.app.state.db.transaction() as connection:
            connection.execute(
                "UPDATE vacancies SET description_confirmed_at = NULL WHERE id = ?",
                (self.vacancy["id"],),
            )
        with self.assertRaisesRegex(ValueError, "Review and confirm"):
            build_tailored_resume_context(
                self.client.app.state.db, self.vacancy["id"]
            )

    def test_tailored_resume_instructions_require_direct_analysis_and_safe_ats_use(self) -> None:
        instructions = tailored_resume_instructions()
        self.assertIn("analyze the full confirmed vacancy", instructions)
        self.assertIn("directly compare it with the source resume", instructions)
        self.assertIn("without asking for or launching another run", instructions)
        self.assertIn("sole authority for candidate facts", instructions)
        self.assertIn("optional, unreliable lexical hint", instructions)
        self.assertIn("never use its score as a gate or quality target", instructions)
        self.assertIn("never force a keyword", instructions)

    @patch("careerflow.routes_ai_reports.run_codex")
    def test_tailored_resume_requires_any_resume_source(self, mocked_run) -> None:
        vacancy = self.client.post(
            "/api/vacancies", data={"text": "Platform Engineer\nRequired Kubernetes"}
        ).json()
        response = self.client.post(
            f"/api/vacancies/{vacancy['id']}/ai-runs",
            json={"action": "Create tailored resume", "prompt": "Create it"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("Master Resume", response.json()["detail"])
        mocked_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
