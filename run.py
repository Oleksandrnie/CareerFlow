"""Run CareerFlow locally with ``python run.py``."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from careerflow.config import load_project_env


if __name__ == "__main__":
    load_project_env(Path(__file__).resolve().parent)
    uvicorn.run(
        "careerflow.api:app",
        host=os.getenv("CAREERFLOW_HOST", "127.0.0.1"),
        port=int(os.getenv("CAREERFLOW_PORT", "8000")),
        reload=os.getenv("CAREERFLOW_RELOAD", "0") == "1",
    )
