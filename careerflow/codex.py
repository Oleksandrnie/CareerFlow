"""Guarded non-interactive Codex CLI adapter."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import Settings


MODEL_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")


class CodexError(RuntimeError):
    """A safe user-facing Codex CLI failure."""


@dataclass(slots=True)
class CodexResult:
    response: str
    command: list[str]


def build_prompt(user_prompt: str, context: str, action: str = "") -> str:
    if not user_prompt.strip():
        raise ValueError("A prompt is required")
    return "\n".join(
        [
            "You are assisting with a job-search workspace.",
            "Return advice or draft text only. Do not modify files, run commands, or claim experience not evidenced in the supplied context.",
            f"Requested action: {action.strip() or 'Custom request'}",
            f"User request: {user_prompt.strip()}",
            "",
            "--- CAREERFLOW CONTEXT ---",
            context,
            "--- END CONTEXT ---",
        ]
    )


def run_codex(
    settings: Settings,
    prompt: str,
    *,
    model: str = "",
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> CodexResult:
    selected_model = model or settings.codex_default_model
    if selected_model and not MODEL_PATTERN.fullmatch(selected_model):
        raise ValueError("Model name contains unsupported characters")
    if settings.codex_reasoning_effort not in {"low", "medium", "high", "xhigh", "max", "ultra"}:
        raise ValueError("Unsupported Codex reasoning effort")
    command = [
        settings.codex_binary,
        "exec",
        "--sandbox", "read-only",
        "--color", "never",
        "--ephemeral",
        "--cd", str(settings.project_root),
        "-c", f'model_reasoning_effort="{settings.codex_reasoning_effort}"',
    ]
    if selected_model:
        command.extend(["--model", selected_model])
    command.append("-")
    try:
        completed = runner(
            command,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=settings.codex_timeout_seconds,
            check=False,
            shell=False,
        )
    except FileNotFoundError as exc:
        raise CodexError("Codex CLI was not found. Set CAREERFLOW_CODEX_BINARY or install Codex.") from exc
    except subprocess.TimeoutExpired as exc:
        raise CodexError(f"Codex CLI timed out after {settings.codex_timeout_seconds} seconds") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "Unknown Codex CLI error").strip()
        raise CodexError(detail[-1500:])
    response = completed.stdout.strip()
    if not response:
        raise CodexError("Codex CLI returned an empty response")
    return CodexResult(response=response, command=command)
