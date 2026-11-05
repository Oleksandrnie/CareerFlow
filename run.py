"""Run CareerFlow locally with ``python run.py``."""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
import threading
import webbrowser

import uvicorn

from careerflow.config import load_project_env


def _browser_host(host: str) -> str:
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return host
    return "127.0.0.1" if address.is_unspecified else host


if __name__ == "__main__":
    load_project_env(Path(__file__).resolve().parent)
    host = os.getenv("CAREERFLOW_HOST", "127.0.0.1")
    port = int(os.getenv("CAREERFLOW_PORT", "8000"))
    open_browser = os.getenv("CAREERFLOW_OPEN_BROWSER", "1").strip().lower()
    if open_browser not in {"0", "false", "no", "off"}:
        browser_host = _browser_host(host)
        if ":" in browser_host and not browser_host.startswith("["):
            browser_host = f"[{browser_host}]"
        url = f"http://{browser_host}:{port}"
        # This runs only in the launcher process; Uvicorn reload workers import
        # the app without re-entering this __main__ block.
        # Delay briefly so Uvicorn can bind before the browser navigates.
        timer = threading.Timer(1.0, webbrowser.open, args=(url,), kwargs={"new": 2})
        timer.daemon = True
        timer.start()

    uvicorn.run(
        "careerflow.api:app",
        host=host,
        port=port,
        reload=os.getenv("CAREERFLOW_RELOAD", "0") == "1",
    )
