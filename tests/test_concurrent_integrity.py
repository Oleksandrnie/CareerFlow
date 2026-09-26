from __future__ import annotations

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

from careerflow.db import SCHEMA, Database
from careerflow.resumes import create_resume, list_resumes
from careerflow.tracking import add_interview, interviews
from careerflow.vacancies import create_vacancy, delete_vacancy


class ConcurrentIntegrityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.storage_dir = root / "storage"
        self.database = Database(root / "data" / "test.db")
        self.database.initialize()
        self.vacancy = create_vacancy(
            self.database,
            self.storage_dir,
            "Platform Engineer\nPython and SQLite",
            "text",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _run_concurrently(self, operations: list) -> list:
        barrier = Barrier(len(operations))

        def run(operation):
            barrier.wait(timeout=10)
            return operation()

        with ThreadPoolExecutor(max_workers=len(operations)) as executor:
            futures = [executor.submit(run, operation) for operation in operations]
            return [future.result(timeout=20) for future in futures]

    def test_concurrent_master_resume_versions_are_unique_and_ordered(self) -> None:
        count = 20
        created = self._run_concurrently(
            [
                lambda number=number: create_resume(
                    self.database,
                    self.storage_dir,
                    kind="master",
                    content_text=f"Master resume {number}",
                )
                for number in range(count)
            ]
        )

        self.assertEqual(sorted(item["version"] for item in created), list(range(1, count + 1)))
        self.assertEqual(len({item["version"] for item in created}), count)

    def test_concurrent_vacancy_resume_versions_leave_no_orphan_files(self) -> None:
        count = 20
        created = self._run_concurrently(
            [
                lambda number=number: create_resume(
                    self.database,
                    self.storage_dir,
                    kind="vacancy",
                    vacancy_id=self.vacancy["id"],
                    content_text=f"Tailored resume {number}",
                )
                for number in range(count)
            ]
        )

        self.assertEqual(sorted(item["version"] for item in created), list(range(1, count + 1)))
        stored_files = list(
            (self.storage_dir / "resumes" / f"vacancy-{self.vacancy['id']}").glob(
                "*/resume.md"
            )
        )
        self.assertEqual(len(stored_files), count)
        self.assertEqual(len(list_resumes(self.database, "vacancy", self.vacancy["id"])), count)

    def test_concurrent_interviews_have_unique_ordered_sequences(self) -> None:
        count = 20
        created = self._run_concurrently(
            [
                lambda number=number: add_interview(
                    self.database,
                    self.vacancy["id"],
                    f"2026-10-{number + 1:02d}T10:00",
                    "Technical",
                    "",
                    "",
                )
                for number in range(count)
            ]
        )

        self.assertEqual(
            sorted(item["sequence_number"] for item in created),
            list(range(1, count + 1)),
        )
        self.assertEqual(len(interviews(self.database, self.vacancy["id"])), count)

    def test_preserve_and_master_allocations_share_one_safe_sequence(self) -> None:
        count = 8
        vacancies = [
            create_vacancy(
                self.database,
                self.storage_dir,
                f"Role {number}\nPython",
                "text",
            )
            for number in range(count)
        ]
        for number, vacancy in enumerate(vacancies):
            create_resume(
                self.database,
                self.storage_dir,
                kind="vacancy",
                vacancy_id=vacancy["id"],
                content_text=f"Preserved resume {number}",
            )

        operations = [
            lambda number=number: create_resume(
                self.database,
                self.storage_dir,
                kind="master",
                content_text=f"Direct master {number}",
            )
            for number in range(count)
        ]
        operations.extend(
            lambda vacancy_id=vacancy["id"]: delete_vacancy(
                self.database,
                self.storage_dir,
                vacancy_id,
                "preserve_resumes",
            )
            for vacancy in vacancies
        )

        self._run_concurrently(operations)

        masters = list_resumes(self.database, "master")
        self.assertEqual(sorted(item["version"] for item in masters), list(range(1, count * 2 + 1)))
        self.assertTrue(all(Path(item["extracted_text_path"]).is_file() for item in masters))

    def test_failed_resume_allocation_removes_new_resume_folder(self) -> None:
        failed_folder = self.storage_dir / "resumes" / "master" / "failed-allocation"

        with patch(
            "careerflow.resumes.uuid4",
            return_value=SimpleNamespace(hex="failed-allocation"),
        ), patch(
            "careerflow.resumes.insert_and_get_id",
            side_effect=sqlite3.IntegrityError("injected allocation failure"),
        ):
            with self.assertRaises(sqlite3.IntegrityError):
                create_resume(
                    self.database,
                    self.storage_dir,
                    kind="master",
                    content_text="Resume that must be rolled back",
                    original_filename="resume.txt",
                    original_content=b"private original",
                )

        self.assertFalse(failed_folder.exists())
        self.assertEqual(list_resumes(self.database, "master"), [])


class MasterVersionMigrationTest(unittest.TestCase):
    def test_initialize_repairs_legacy_duplicates_and_adds_unique_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "legacy.db")
            database.path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(database.path) as connection:
                connection.executescript(SCHEMA)
                connection.executemany(
                    """
                    INSERT INTO resume_versions(kind, vacancy_id, version, content_text)
                    VALUES ('master', NULL, ?, ?)
                    """,
                    [(1, "First"), (1, "Duplicate"), (3, "Existing third")],
                )
                connection.execute(
                    "INSERT OR IGNORE INTO schema_version(version) VALUES (1)"
                )

            database.initialize()

            rows = database.fetch_all(
                "SELECT version, content_text FROM resume_versions ORDER BY id"
            )
            self.assertEqual([row["version"] for row in rows], [1, 4, 3])
            self.assertEqual(
                database.fetch_one("SELECT MAX(version) AS version FROM schema_version")["version"],
                7,
            )
            with self.assertRaises(sqlite3.IntegrityError):
                with database.transaction() as connection:
                    connection.execute(
                        """
                        INSERT INTO resume_versions(kind, vacancy_id, version, content_text)
                        VALUES ('master', NULL, 1, 'Rejected duplicate')
                        """
                    )


if __name__ == "__main__":
    unittest.main()
