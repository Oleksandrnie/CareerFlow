from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from careerflow.api import create_app
from careerflow.config import Settings


class FoundationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.settings = Settings(
            project_root=root,
            data_dir=root / "data",
            storage_dir=root / "storage",
            database_path=root / "data" / "test.db",
            codex_binary="codex",
            codex_timeout_seconds=10,
        )
        self.client_context = TestClient(create_app(self.settings))
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def test_health_initializes_database_and_storage(self) -> None:
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertTrue(self.settings.database_path.exists())
        self.assertTrue((self.settings.storage_dir / "vacancies").is_dir())
        self.assertTrue((self.settings.storage_dir / "reports").is_dir())

        with sqlite3.connect(self.settings.database_path) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertTrue(
            {
                "vacancies",
                "resume_versions",
                "ats_analyses",
                "timeline_events",
                "notes",
                "attachments",
                "ai_runs",
            }.issubset(tables)
        )

    def test_default_codex_profile_is_minimal(self) -> None:
        self.assertEqual(self.settings.codex_default_model, "gpt-5.6-luna")
        self.assertEqual(self.settings.codex_reasoning_effort, "low")
        self.assertEqual(self.settings.codex_cleaning_model, "gpt-5.6-luna")
        self.assertEqual(self.settings.codex_cleaning_effort, "low")
        self.assertEqual(self.settings.codex_cleaning_escalation_model, "gpt-5.6-sol")
        self.assertEqual(self.settings.codex_cleaning_escalation_effort, "medium")

    def test_dotenv_configures_cleaning_profile_without_overriding_shell(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "CAREERFLOW_CLEANING_CODEX_MODEL=gpt-from-file\n"
                "CAREERFLOW_CLEANING_CODEX_EFFORT=high # local choice\n"
                "CAREERFLOW_CLEANING_ESCALATION_CODEX_MODEL=gpt-escalation\n"
                "CAREERFLOW_CLEANING_ESCALATION_CODEX_EFFORT=xhigh\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"CAREERFLOW_CLEANING_CODEX_MODEL": "gpt-from-shell"},
                clear=True,
            ):
                settings = Settings.from_env(root)
        self.assertEqual(settings.codex_cleaning_model, "gpt-from-shell")
        self.assertEqual(settings.codex_cleaning_effort, "high")
        self.assertEqual(settings.codex_cleaning_escalation_model, "gpt-escalation")
        self.assertEqual(settings.codex_cleaning_escalation_effort, "xhigh")

    def test_root_reports_ready(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("CareerFlow", response.text)


if __name__ == "__main__":
    unittest.main()
