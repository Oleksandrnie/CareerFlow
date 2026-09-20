"""Run CareerFlow locally with ``python run.py``."""

from __future__ import annotations

import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "careerflow.api:app",
        host=os.getenv("CAREERFLOW_HOST", "127.0.0.1"),
        port=int(os.getenv("CAREERFLOW_PORT", "8000")),
        reload=os.getenv("CAREERFLOW_RELOAD", "0") == "1",
    )

