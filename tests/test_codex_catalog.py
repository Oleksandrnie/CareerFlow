from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from careerflow.api import create_app
from careerflow.codex import (
    CodexResult,
    clear_model_catalog_cache,
    load_model_catalog,
    validate_model_effort,
)
from careerflow.config import Settings


class ModelCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        clear_model_catalog_cache()
        root = Path("/tmp/careerflow-catalog-test")
        self.settings = Settings(
            root,
            root / "data",
            root / "storage",
            root / "data" / "test.db",
            "codex-test",
            180,
        )

    def tearDown(self) -> None:
        clear_model_catalog_cache()

    def test_catalog_filters_hidden_models_and_uses_model_specific_efforts(self) -> None:
        calls = []
        payload = {
            "models": [
                {
                    "slug": "gpt-5.6-luna",
                    "display_name": "GPT-5.6-Luna",
                    "visibility": "list",
                    "supported_reasoning_levels": [
                        {"effort": "low"},
                        {"effort": "medium"},
                        {"effort": "high"},
                    ],
                },
                {
                    "slug": "gpt-hidden",
                    "display_name": "Hidden",
                    "visibility": "hide",
                    "supported_reasoning_levels": [{"effort": "high"}],
                },
                {
                    "slug": "gpt-6-sol",
                    "display_name": "GPT-6-Sol",
                    "visibility": "list",
                    "supported_reasoning_levels": [
                        {"effort": "medium"},
                        {"effort": "ultra"},
                    ],
                },
            ]
        }

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

        first = load_model_catalog(self.settings, runner=runner, now=lambda: 100.0)
        second = load_model_catalog(self.settings, runner=runner, now=lambda: 101.0)
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], ["codex-test", "debug", "models"])
        self.assertFalse(calls[0][1]["shell"])
        self.assertEqual(calls[0][1]["timeout"], 10)
        self.assertEqual([item["id"] for item in first["models"]], ["gpt-5.6-luna", "gpt-6-sol"])
        self.assertEqual(first["models"][1]["efforts"], ["medium", "ultra"])
        self.assertEqual(first["source"], "codex-cli")
        self.assertNotIn("warning", first)

        self.assertEqual(
            validate_model_effort(first, "gpt-6-sol", "ultra"),
            ("gpt-6-sol", "ultra"),
        )
        with self.assertRaises(ValueError):
            validate_model_effort(first, "gpt-hidden", "high")
        with self.assertRaises(ValueError):
            validate_model_effort(first, "gpt-6-sol", "low")

    def test_unavailable_catalog_returns_only_configured_default(self) -> None:
        def unavailable(command, **kwargs):
            raise FileNotFoundError

        catalog = load_model_catalog(self.settings, runner=unavailable, force=True)
        self.assertEqual(
            catalog["models"],
            [{"id": "gpt-5.6-luna", "name": "gpt-5.6-luna", "efforts": ["low"]}],
        )
        self.assertEqual(catalog["source"], "configuration-fallback")
        self.assertIn("unavailable", catalog["warning"])


class ModelCatalogApiTest(unittest.TestCase):
    def setUp(self) -> None:
        clear_model_catalog_cache()
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.settings = Settings(
            root, root / "data", root / "storage", root / "data" / "test.db", "codex-test", 10
        )
        self.context = TestClient(create_app(self.settings))
        self.client = self.context.__enter__()
        self.vacancy = self.client.post(
            "/api/vacancies", data={"text": "Backend Engineer\nRequired Python"}
        ).json()
        self.catalog = {
            "models": [
                {"id": "gpt-5.6-luna", "name": "Luna", "efforts": ["low", "medium"]},
                {"id": "gpt-6-sol", "name": "Sol", "efforts": ["high", "ultra"]},
            ],
            "default_model": "gpt-5.6-luna",
            "default_effort": "low",
            "source": "codex-cli",
        }

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)
        self.temp_dir.cleanup()
        clear_model_catalog_cache()

    @patch("careerflow.routes_codex.load_model_catalog")
    def test_catalog_endpoint(self, mocked_catalog) -> None:
        mocked_catalog.return_value = self.catalog
        response = self.client.get("/api/codex/models")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.catalog)

    @patch("careerflow.routes_ai_reports.run_codex")
    @patch("careerflow.routes_ai_reports.load_model_catalog")
    def test_ai_run_validates_and_records_model_effort(self, mocked_catalog, mocked_run) -> None:
        mocked_catalog.return_value = self.catalog
        mocked_run.return_value = CodexResult("Done", ["codex"])
        url = f"/api/vacancies/{self.vacancy['id']}/ai-runs"

        invalid = self.client.post(
            url,
            json={"prompt": "Help", "model": "gpt-6-sol", "reasoning_effort": "low"},
        )
        self.assertEqual(invalid.status_code, 422)
        mocked_run.assert_not_called()

        created = self.client.post(
            url,
            json={"prompt": "Help", "model": "gpt-6-sol", "reasoning_effort": "ultra"},
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["model"], "gpt-6-sol")
        self.assertEqual(created.json()["reasoning_effort"], "ultra")
        self.assertEqual(mocked_run.call_args.kwargs["reasoning_effort"], "ultra")
        events = self.client.get(f"/api/vacancies/{self.vacancy['id']}/timeline").json()
        self.assertIn("Model: gpt-6-sol", events[0]["details"])
        self.assertIn("Effort: ultra", events[0]["details"])


if __name__ == "__main__":
    unittest.main()
