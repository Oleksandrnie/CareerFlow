"""Small SQLite persistence layer and idempotent schema initialization."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS vacancies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT 'Untitled vacancy',
    company TEXT NOT NULL DEFAULT '',
    salary TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL,
    raw_description TEXT NOT NULL DEFAULT '',
    description_cleaning_method TEXT,
    description_cleaned_at TEXT,
    description_confirmed_at TEXT,
    source TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL DEFAULT 'text',
    original_filename TEXT,
    original_path TEXT,
    extracted_text_path TEXT,
    status TEXT NOT NULL DEFAULT 'Saved' CHECK (
        status IN ('Saved', 'Applied', 'Interview', 'Waiting', 'Offer', 'Rejected')
    ),
    match_percent INTEGER,
    description_revision INTEGER NOT NULL DEFAULT 0,
    archived_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS resume_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vacancy_id INTEGER REFERENCES vacancies(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('master', 'vacancy')),
    version INTEGER NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    original_filename TEXT,
    original_path TEXT,
    extracted_text_path TEXT,
    content_text TEXT NOT NULL,
    source_resume_id INTEGER REFERENCES resume_versions(id) ON DELETE SET NULL,
    is_submitted INTEGER NOT NULL DEFAULT 0 CHECK (is_submitted IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(kind, vacancy_id, version)
);

CREATE UNIQUE INDEX IF NOT EXISTS one_submitted_resume_per_vacancy
ON resume_versions(vacancy_id) WHERE is_submitted = 1 AND vacancy_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS ats_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vacancy_id INTEGER NOT NULL REFERENCES vacancies(id) ON DELETE CASCADE,
    resume_version_id INTEGER NOT NULL REFERENCES resume_versions(id) ON DELETE CASCADE,
    match_percent INTEGER NOT NULL CHECK (match_percent BETWEEN 0 AND 100),
    result_json TEXT NOT NULL,
    description_snapshot TEXT,
    description_revision INTEGER,
    resume_kind_at_analysis TEXT,
    resume_version_at_analysis INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS timeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vacancy_id INTEGER NOT NULL REFERENCES vacancies(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    event_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS interviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vacancy_id INTEGER NOT NULL REFERENCES vacancies(id) ON DELETE CASCADE,
    sequence_number INTEGER NOT NULL,
    interview_at TEXT NOT NULL,
    interview_type TEXT NOT NULL DEFAULT 'Interview',
    note TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(vacancy_id, sequence_number)
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vacancy_id INTEGER NOT NULL REFERENCES vacancies(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vacancy_id INTEGER NOT NULL REFERENCES vacancies(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    media_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    size_bytes INTEGER NOT NULL,
    is_text INTEGER NOT NULL DEFAULT 0 CHECK (is_text IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS generated_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vacancy_id INTEGER NOT NULL REFERENCES vacancies(id) ON DELETE CASCADE,
    stored_path TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ai_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vacancy_id INTEGER NOT NULL REFERENCES vacancies(id) ON DELETE CASCADE,
    prompt TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    reasoning_effort TEXT,
    response TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_vacancies_status ON vacancies(status, archived_at);
CREATE INDEX IF NOT EXISTS idx_timeline_vacancy ON timeline_events(vacancy_id, event_at DESC);
CREATE INDEX IF NOT EXISTS idx_notes_vacancy ON notes(vacancy_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_attachments_vacancy ON attachments(vacancy_id, created_at DESC);
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            if immediate:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
        with self.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO schema_version(version) VALUES (1)"
            )
            self._ensure_unique_master_versions(connection)
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS unique_master_resume_version
                ON resume_versions(version)
                WHERE kind = 'master' AND vacancy_id IS NULL
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_version(version) VALUES (2)"
            )
            self._ensure_ats_provenance_columns(connection)
            connection.execute(
                "INSERT OR IGNORE INTO schema_version(version) VALUES (3)"
            )
            self._ensure_track_two_columns(connection)
            self._ensure_resume_source_guards(connection)
            connection.execute(
                "INSERT OR IGNORE INTO schema_version(version) VALUES (4)"
            )

    @staticmethod
    def _ensure_track_two_columns(connection: sqlite3.Connection) -> None:
        vacancy_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(vacancies)")
        }
        for name, definition in (
            ("raw_description", "TEXT"),
            ("description_cleaning_method", "TEXT"),
            ("description_cleaned_at", "TEXT"),
            ("description_confirmed_at", "TEXT"),
        ):
            if name not in vacancy_columns:
                connection.execute(f"ALTER TABLE vacancies ADD COLUMN {name} {definition}")
        connection.execute(
            "UPDATE vacancies SET raw_description = description WHERE raw_description IS NULL OR raw_description = ''"
        )
        if "created_at" in vacancy_columns:
            confirmed_fallback = "created_at"
        elif "updated_at" in vacancy_columns:
            confirmed_fallback = "updated_at"
        else:
            confirmed_fallback = "CURRENT_TIMESTAMP"
        connection.execute(
            f"UPDATE vacancies SET description_confirmed_at = COALESCE(description_confirmed_at, {confirmed_fallback})"
        )

        resume_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(resume_versions)")
        }
        if "source_resume_id" not in resume_columns:
            connection.execute(
                "ALTER TABLE resume_versions ADD COLUMN source_resume_id INTEGER REFERENCES resume_versions(id) ON DELETE SET NULL"
            )

        ai_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(ai_runs)")
        }
        if "reasoning_effort" not in ai_columns:
            connection.execute("ALTER TABLE ai_runs ADD COLUMN reasoning_effort TEXT")

    @staticmethod
    def _ensure_resume_source_guards(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS prevent_resume_source_cycle_insert
            BEFORE INSERT ON resume_versions
            WHEN NEW.source_resume_id IS NOT NULL AND NEW.id = NEW.source_resume_id
            BEGIN
                SELECT RAISE(ABORT, 'Resume source cycle is not allowed');
            END;

            CREATE TRIGGER IF NOT EXISTS prevent_resume_source_cycle_update
            BEFORE UPDATE OF source_resume_id ON resume_versions
            WHEN NEW.source_resume_id IS NOT NULL
            BEGIN
                WITH RECURSIVE ancestors(id, source_resume_id) AS (
                    SELECT id, source_resume_id FROM resume_versions WHERE id = NEW.source_resume_id
                    UNION ALL
                    SELECT parent.id, parent.source_resume_id
                    FROM resume_versions AS parent
                    JOIN ancestors ON parent.id = ancestors.source_resume_id
                )
                SELECT RAISE(ABORT, 'Resume source cycle is not allowed')
                FROM ancestors WHERE id = NEW.id;
            END;
            """
        )

    @staticmethod
    def _ensure_ats_provenance_columns(connection: sqlite3.Connection) -> None:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(vacancies)")
        }
        if "description_revision" not in columns:
            connection.execute(
                "ALTER TABLE vacancies ADD COLUMN description_revision INTEGER NOT NULL DEFAULT 0"
            )
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(ats_analyses)")
        }
        for name, column_type in (
            ("description_snapshot", "TEXT"),
            ("description_revision", "INTEGER"),
            ("resume_kind_at_analysis", "TEXT"),
            ("resume_version_at_analysis", "INTEGER"),
        ):
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE ats_analyses ADD COLUMN {name} {column_type}"
                )
        connection.execute(
            """
            UPDATE vacancies SET match_percent = NULL
            WHERE id IN (SELECT DISTINCT vacancy_id FROM ats_analyses)
              AND (
                  SELECT description_revision FROM ats_analyses
                  WHERE vacancy_id = vacancies.id ORDER BY id DESC LIMIT 1
              ) IS NULL
            """
        )

    @staticmethod
    def _ensure_unique_master_versions(connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            """
            SELECT id, version
            FROM resume_versions
            WHERE kind = 'master' AND vacancy_id IS NULL
            ORDER BY version, created_at, id
            """
        ).fetchall()
        seen: set[int] = set()
        next_version = max((int(row["version"]) for row in rows), default=0)
        for row in rows:
            version = int(row["version"])
            if version not in seen:
                seen.add(version)
                continue
            next_version += 1
            connection.execute(
                "UPDATE resume_versions SET version = ? WHERE id = ?",
                (next_version, int(row["id"])),
            )
            seen.add(next_version)

    def fetch_one(self, query: str, params: tuple[object, ...] = ()) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(query, params).fetchone()
        return dict(row) if row else None

    def fetch_all(self, query: str, params: tuple[object, ...] = ()) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def insert_and_get_id(
    connection: sqlite3.Connection, query: str, params: tuple[object, ...]
) -> int:
    cursor = connection.execute(query, params)
    if cursor.lastrowid is None:
        raise RuntimeError("SQLite did not return an inserted row id")
    return int(cursor.lastrowid)
