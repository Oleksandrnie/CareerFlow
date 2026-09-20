"""Application configuration derived from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    project_root: Path
    data_dir: Path
    storage_dir: Path
    database_path: Path
    codex_binary: str
    codex_timeout_seconds: int
    codex_default_model: str = "gpt-5.6-luna"
    codex_reasoning_effort: str = "low"

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> "Settings":
        root = Path(project_root or Path(__file__).resolve().parent.parent)
        data_dir = Path(os.getenv("CAREERFLOW_DATA_DIR", root / "data")).resolve()
        storage_dir = Path(os.getenv("CAREERFLOW_STORAGE_DIR", root / "storage")).resolve()
        database_path = Path(
            os.getenv("CAREERFLOW_DATABASE", data_dir / "careerflow.db")
        ).resolve()
        return cls(
            project_root=root,
            data_dir=data_dir,
            storage_dir=storage_dir,
            database_path=database_path,
            codex_binary=os.getenv("CAREERFLOW_CODEX_BINARY", "codex"),
            codex_timeout_seconds=int(os.getenv("CAREERFLOW_CODEX_TIMEOUT", "180")),
            codex_default_model=os.getenv("CAREERFLOW_CODEX_MODEL", "gpt-5.6-luna"),
            codex_reasoning_effort=os.getenv("CAREERFLOW_CODEX_EFFORT", "low"),
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        for directory in ("vacancies", "resumes", "attachments", "reports"):
            (self.storage_dir / directory).mkdir(parents=True, exist_ok=True)
