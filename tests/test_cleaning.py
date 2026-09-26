from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from careerflow.api import create_app
from careerflow.ats import analyze
from careerflow.cleaning import build_preview, classify_blocks_with_codex, split_blocks
from careerflow.codex import CodexError, CodexResult
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

    def test_codex_cannot_restore_clear_noise_or_remove_reviewable_uncertainty(self) -> None:
        def fake_runner(settings, prompt):
            return CodexResult(
                '[{"id":"b1","classification":"keep"},'
                '{"id":"b2","classification":"keep"},'
                '{"id":"b3","classification":"remove"}]',
                ["codex"],
            )

        preview = build_preview(
            "Required Python\nApply now\nCareers",
            settings=self.settings,
            use_codex=True,
            codex_runner=fake_runner,
        )
        self.assertEqual(preview["description"], "Required Python\nCareers")
        self.assertEqual(preview["method"], "codex:local-blocks")
        self.assertEqual(
            [(item["text"], item["classification"]) for item in preview["blocks"]],
            [
                ("Required Python", "keep"),
                ("Apply now", "remove"),
                ("Careers", "uncertain"),
            ],
        )

    def test_codex_failure_or_invalid_classification_falls_back_with_diagnostics(self) -> None:
        def cli_failure(settings, prompt):
            raise CodexError("CLI is busy")

        def invalid_classification(settings, prompt):
            return CodexResult(
                '[{"id":"unknown","classification":"remove"}]', ["codex"]
            )

        failures = (cli_failure, invalid_classification)
        for runner in failures:
            with self.subTest(runner=runner):
                preview = build_preview(
                    "Required Python\nApply now\nCareers",
                    settings=self.settings,
                    use_codex=True,
                    codex_runner=runner,
                )
                self.assertEqual(preview["description"], "Required Python\nCareers")
                self.assertEqual(preview["method"], "local-fallback:local-blocks")
                self.assertEqual(preview["diagnostics"]["classification_source"], "local")
                self.assertTrue(preview["diagnostics"]["fallback_used"])
                self.assertIn("Review uncertain blocks", preview["warnings"][0])

    def test_structural_noise_and_recommendation_sections_are_removed_conservatively(self) -> None:
        preview = build_preview(
            "\n".join(
                (
                    "Хабр Карьера",
                    "Все сервисы Хабра",
                    "Ответы на любые вопросы об IT",
                    "Профессиональное развитие в IT.",
                    "Моя лента",
                    "Platform Engineer",
                    "Требования",
                    "Опыт Python и PostgreSQL от 3 лет.",
                    "Careers",
                    "Рекомендуемые вакансии:",
                    "Unrelated Mobile Developer",
                    "Требуется опыт Java и Spring.",
                    "https://career.example/jobs/42",
                )
            ),
            method="pasted-text",
        )
        self.assertEqual(
            preview["description"],
            "Platform Engineer\nТребования\nОпыт Python и PostgreSQL от 3 лет.\nCareers",
        )
        self.assertEqual([item["text"] for item in preview["uncertain_blocks"]], ["Careers"])
        removed_text = {item["text"] for item in preview["removed_blocks"]}
        self.assertIn("Все сервисы Хабра", removed_text)
        self.assertIn("Моя лента", removed_text)
        self.assertIn("Unrelated Mobile Developer", removed_text)
        self.assertIn("https://career.example/jobs/42", removed_text)

        result = analyze(
            "\n".join(item["text"] for item in preview["blocks"]),
            "Python PostgreSQL developer with 4 years of experience.",
        )
        requirements = "\n".join(item["requirement"] for item in result["requirements"])
        self.assertIn("Python", requirements)
        for noise in (
            "Все сервисы Хабра",
            "Ответы на любые вопросы об IT",
            "Профессиональное развитие в IT.",
            "Unrelated Mobile Developer",
            "Java",
            "https://career.example/jobs/42",
        ):
            self.assertNotIn(noise, requirements)
        self.assertNotIn("java", result["keywords"])
        self.assertNotIn("unrelated", result["keywords"])

        resumed_content = build_preview(
            "Similar jobs\nUnrelated title\nRequirements\nMust know Go",
            method="pasted-text",
        )
        self.assertEqual(resumed_content["description"], "Requirements\nMust know Go")


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

    def test_confirmed_html_preview_keeps_real_requirements_out_of_page_noise(self) -> None:
        html = b"""
        <html><body><main>
        <p>&#1061;&#1072;&#1073;&#1088; &#1050;&#1072;&#1088;&#1100;&#1077;&#1088;&#1072;</p>
        <p>&#1042;&#1089;&#1077; &#1089;&#1077;&#1088;&#1074;&#1080;&#1089;&#1099; &#1061;&#1072;&#1073;&#1088;&#1072;</p>
        <p>&#1054;&#1090;&#1074;&#1077;&#1090;&#1099; &#1085;&#1072; &#1083;&#1102;&#1073;&#1099;&#1077; &#1074;&#1086;&#1087;&#1088;&#1086;&#1089;&#1099; &#1086;&#1073; IT</p>
        <p>&#1055;&#1088;&#1086;&#1092;&#1077;&#1089;&#1089;&#1080;&#1086;&#1085;&#1072;&#1083;&#1100;&#1085;&#1086;&#1077; &#1088;&#1072;&#1079;&#1074;&#1080;&#1090;&#1080;&#1077; &#1074; IT</p>
        <h1>Platform Engineer</h1>
        <h2>&#1058;&#1088;&#1077;&#1073;&#1086;&#1074;&#1072;&#1085;&#1080;&#1103;</h2>
        <p>&#1054;&#1087;&#1099;&#1090; Python &#1080; PostgreSQL &#1086;&#1090; 3 &#1083;&#1077;&#1090;.</p>
        <h2>&#1056;&#1077;&#1082;&#1086;&#1084;&#1077;&#1085;&#1076;&#1091;&#1077;&#1084;&#1099;&#1077; &#1074;&#1072;&#1082;&#1072;&#1085;&#1089;&#1080;&#1080;</h2>
        <div>Unrelated Mobile Developer</div>
        <p>&#1058;&#1088;&#1077;&#1073;&#1091;&#1077;&#1090;&#1089;&#1103; &#1086;&#1087;&#1099;&#1090; Java &#1080; Spring.</p>
        <p>https://career.example/jobs/42</p>
        </main></body></html>
        """
        preview_response = self.client.post(
            "/api/vacancies/import-preview",
            files={"file": ("role.html", html, "text/html")},
        )
        self.assertEqual(preview_response.status_code, 200)
        preview = preview_response.json()
        self.assertIn("Python", preview["description"])
        self.assertNotIn("&#1061;", preview["description"])
        self.assertNotIn("Unrelated Mobile Developer", preview["description"])

        vacancy = self.client.post(
            "/api/vacancies",
            data={
                "cleaned_description": preview["description"],
                "cleaning_method": preview["method"],
            },
            files={"file": ("role.html", html, "text/html")},
        ).json()
        resume = self.client.post(
            "/api/resumes",
            data={"kind": "master", "text": "Python PostgreSQL engineer with 4 years experience."},
        ).json()
        analysis = self.client.post(
            f"/api/vacancies/{vacancy['id']}/ats",
            json={"resume_version_id": resume["id"]},
        )
        self.assertEqual(analysis.status_code, 201)
        requirements = "\n".join(
            item["requirement"] for item in analysis.json()["result"]["requirements"]
        )
        self.assertIn("Python", requirements)
        self.assertNotIn("Unrelated Mobile Developer", requirements)
        self.assertNotIn("Java", requirements)

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
