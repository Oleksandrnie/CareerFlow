from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from careerflow.api import create_app
from careerflow.cleaning import build_preview, classify_blocks_with_codex, split_blocks
from careerflow.codex import CodexResult
from careerflow.config import Settings
from careerflow.files import extract_vacancy_html


class HtmlExtractionTest(unittest.TestCase):
    def test_json_ld_job_posting_has_priority_and_preserves_raw_visible_text(self) -> None:
        extraction = extract_vacancy_html(
            b"""
            <html><body><nav>Menu Careers</nav><main>Wrong generic content</main>
            <script type="application/ld+json">
            {"@context":"https://schema.org","@type":"JobPosting",
             "description":"<h2>Backend Engineer</h2><p>Python &amp; SQL</p>"}
            </script><footer>Privacy policy</footer></body></html>
            """
        )
        self.assertEqual(extraction.method, "json-ld")
        self.assertEqual(extraction.candidate_text, "Backend Engineer\nPython & SQL")
        self.assertIn("Menu Careers", extraction.raw_text)
        self.assertIn("Privacy policy", extraction.raw_text)
        self.assertNotIn("@context", extraction.raw_text)

    def test_microdata_and_rdfa_fallbacks(self) -> None:
        cases = (
            (
                b'<div itemscope itemtype="https://schema.org/JobPosting"><div itemprop="description"><h2>Requirements</h2><p>Python</p></div></div>',
                "microdata",
            ),
            (
                b'<section typeof="schema:JobPosting"><div property="schema:description"><h2>Responsibilities</h2><p>Build APIs</p></div></section>',
                "rdfa",
            ),
        )
        for html, method in cases:
            with self.subTest(method=method):
                extraction = extract_vacancy_html(html)
                self.assertEqual(extraction.method, method)
                self.assertTrue(extraction.candidate_text)

    def test_spa_main_probable_container_and_visible_fallbacks(self) -> None:
        cases = (
            (
                b'<script id="__NEXT_DATA__" type="application/json">{"props":{"jobDescription":"Go engineer and PostgreSQL"}}</script>',
                "spa-state",
                "Go engineer",
            ),
            (
                b'<main><nav>Search jobs</nav><h1>Platform Engineer</h1><p>Build reliable systems</p><button>Apply now</button></main>',
                "main",
                "Platform Engineer",
            ),
            (
                b'<div class="job-description"><h1>Data Engineer</h1><p>Build pipelines</p></div>',
                "probable-container",
                "Data Engineer",
            ),
            (b'<div><h1>QA Engineer</h1><p>Test releases</p></div>', "visible-text", "QA Engineer"),
        )
        for html, method, marker in cases:
            with self.subTest(method=method):
                extraction = extract_vacancy_html(html)
                self.assertEqual(extraction.method, method)
                self.assertIn(marker, extraction.candidate_text)
                self.assertNotIn("Apply now", extraction.candidate_text)


class CleaningClassificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            Path("/tmp/careerflow-test"),
            Path("/tmp/careerflow-test/data"),
            Path("/tmp/careerflow-test/storage"),
            Path("/tmp/careerflow-test/data/test.db"),
            "codex",
            10,
        )

    def test_local_cleaning_removes_only_service_text_and_exact_duplicates(self) -> None:
        preview = build_preview(
            "Backend Engineer\nResponsibilities\nBuild APIs\nBuild APIs\nApply now\nCareers",
            method="pasted-text",
        )
        self.assertEqual(
            preview["description"],
            "Backend Engineer\nResponsibilities\nBuild APIs\nCareers",
        )
        self.assertEqual(len(preview["removed_blocks"]), 2)
        self.assertEqual(preview["uncertain_blocks"][0]["text"], "Careers")

    def test_codex_classification_uses_only_known_original_blocks(self) -> None:
        blocks = split_blocks("Salary: 120000 USD\nPython 3.12\nApply now")

        def fake_runner(settings, prompt):
            self.assertIn("Do not rewrite", prompt)
            return CodexResult(
                '[{"id":"b1","classification":"keep","reason":"fact"},'
                '{"id":"b2","classification":"keep","reason":"requirement",'
                '"text":"INVENTED"},'
                '{"id":"b3","classification":"remove","reason":"control"}]',
                ["codex"],
            )

        classified = classify_blocks_with_codex(self.settings, blocks, runner=fake_runner)
        self.assertEqual([item["text"] for item in classified], [item["text"] for item in blocks])
        preview = build_preview(
            "Salary: 120000 USD\nPython 3.12\nApply now",
            settings=self.settings,
            use_codex=True,
            codex_runner=fake_runner,
        )
        self.assertEqual(preview["description"], "Salary: 120000 USD\nPython 3.12")
        self.assertNotIn("INVENTED", preview["description"])

    def test_codex_unknown_or_missing_ids_are_rejected(self) -> None:
        blocks = split_blocks("Python\nSQL")
        for response in (
            '[{"id":"unknown","classification":"keep"}]',
            '[{"id":"b1","classification":"keep"}]',
        ):
            with self.subTest(response=response), self.assertRaises(ValueError):
                classify_blocks_with_codex(
                    self.settings,
                    blocks,
                    runner=lambda settings, prompt, value=response: CodexResult(value, ["codex"]),
                )


class CleaningApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.settings = Settings(
            root, root / "data", root / "storage", root / "data" / "test.db", "codex", 10
        )
        self.context = TestClient(create_app(self.settings))
        self.client = self.context.__enter__()

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def test_import_preview_and_confirm_store_raw_and_cleaned_separately(self) -> None:
        html = b"""
        <html><body><nav>Search jobs</nav><main><h1>Python Engineer</h1>
        <p>Required: Python and SQL</p><button>Apply now</button></main><footer>Privacy policy</footer></body></html>
        """
        preview_response = self.client.post(
            "/api/vacancies/import-preview",
            files={"file": ("role.html", html, "text/html")},
        )
        self.assertEqual(preview_response.status_code, 200)
        preview = preview_response.json()
        self.assertIn("Search jobs", preview["raw_description"])
        self.assertEqual(preview["description"], "Python Engineer\nRequired: Python and SQL")
        self.assertTrue(preview["removed_blocks"])

        created = self.client.post(
            "/api/vacancies",
            data={
                "cleaned_description": preview["description"],
                "cleaning_method": preview["method"],
            },
            files={"file": ("role.html", html, "text/html")},
        )
        self.assertEqual(created.status_code, 201)
        vacancy = created.json()
        self.assertIn("Search jobs", vacancy["raw_description"])
        self.assertNotIn("Search jobs", vacancy["description"])
        self.assertIsNotNone(vacancy["description_confirmed_at"])
        self.assertTrue(Path(vacancy["original_path"]).read_bytes() == html)

    def test_apply_cleaning_invalidates_ats_but_never_changes_raw(self) -> None:
        vacancy = self.client.post(
            "/api/vacancies",
            data={"text": "Python Engineer\nRequired Python\nApply now"},
        ).json()
        resume = self.client.post(
            "/api/resumes", data={"kind": "master", "text": "Python engineer"}
        ).json()
        analysis = self.client.post(
            f"/api/vacancies/{vacancy['id']}/ats", json={"resume_version_id": resume["id"]}
        )
        self.assertEqual(analysis.status_code, 201)

        preview = self.client.post(
            f"/api/vacancies/{vacancy['id']}/description/preview", json={}
        ).json()
        self.assertIn("Apply now", vacancy["raw_description"])
        self.assertNotIn("Apply now", preview["description"])
        applied = self.client.post(
            f"/api/vacancies/{vacancy['id']}/description/apply",
            json={"description": preview["description"], "method": preview["method"]},
        )
        self.assertEqual(applied.status_code, 200)
        updated = applied.json()
        self.assertEqual(updated["raw_description"], vacancy["raw_description"])
        self.assertEqual(updated["description_revision"], vacancy["description_revision"] + 1)
        self.assertIsNone(updated["match_percent"])
        self.assertTrue(self.client.get(f"/api/vacancies/{vacancy['id']}/ats").json()["is_stale"])
        events = self.client.get(f"/api/vacancies/{vacancy['id']}/timeline").json()
        self.assertEqual(events[0]["event_type"], "description_cleaned")

        report = self.client.post(f"/api/vacancies/{vacancy['id']}/reports").json()["markdown"]
        self.assertNotIn("Diagnostic raw vacancy description", report)
        diagnostic = self.client.post(
            f"/api/vacancies/{vacancy['id']}/reports?include_raw=true"
        ).json()["markdown"]
        self.assertIn("Diagnostic raw vacancy description", diagnostic)
        self.assertIn("Apply now", diagnostic)

    def test_ats_is_blocked_until_description_is_confirmed(self) -> None:
        vacancy = self.client.post(
            "/api/vacancies", data={"text": "Required Python"}
        ).json()
        resume = self.client.post(
            "/api/resumes", data={"kind": "master", "text": "Python"}
        ).json()
        with self.context.app.state.db.transaction() as connection:
            connection.execute(
                "UPDATE vacancies SET description_confirmed_at = NULL WHERE id = ?",
                (vacancy["id"],),
            )
        blocked = self.client.post(
            f"/api/vacancies/{vacancy['id']}/ats", json={"resume_version_id": resume["id"]}
        )
        self.assertEqual(blocked.status_code, 422)
        self.assertIn("confirm", blocked.json()["detail"])


if __name__ == "__main__":
    unittest.main()
