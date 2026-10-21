"""Application configuration derived from environment variables."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_project_env(project_root: Path) -> None:
    """Load simple KEY=VALUE entries from .env without overriding the shell."""

    path = Path(project_root) / ".env"
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, raw_value = line.partition("=")
        name = name.strip()
        if not separator or not ENV_NAME.fullmatch(name):
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        os.environ.setdefault(name, value)


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
    codex_cleaning_model: str = "gpt-5.6-luna"
    codex_cleaning_effort: str = "low"
    codex_cleaning_escalation_model: str = "gpt-5.6-sol"
    codex_cleaning_escalation_effort: str = "medium"

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> "Settings":
        root = Path(project_root or Path(__file__).resolve().parent.parent)
        load_project_env(root)
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
            codex_cleaning_model=os.getenv("CAREERFLOW_CLEANING_CODEX_MODEL", "gpt-5.6-luna"),
            codex_cleaning_effort=os.getenv("CAREERFLOW_CLEANING_CODEX_EFFORT", "low"),
            codex_cleaning_escalation_model=os.getenv(
                "CAREERFLOW_CLEANING_ESCALATION_CODEX_MODEL", "gpt-5.6-sol"
            ),
            codex_cleaning_escalation_effort=os.getenv(
                "CAREERFLOW_CLEANING_ESCALATION_CODEX_EFFORT", "medium"
            ),
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        for directory in ("vacancies", "resumes", "attachments", "reports"):
            (self.storage_dir / directory).mkdir(parents=True, exist_ok=True)
