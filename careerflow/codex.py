"""Guarded non-interactive Codex CLI adapter."""

from __future__ import annotations

import re
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import Settings


MODEL_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")
ALLOWED_EFFORTS = {"low", "medium", "high", "xhigh", "max", "ultra"}
MODEL_CATALOG_TTL_SECONDS = 30.0
_MODEL_CATALOG_CACHE: dict[tuple[str, str, str], tuple[float, dict]] = {}


class CodexError(RuntimeError):
    """A safe user-facing Codex CLI failure."""


@dataclass(slots=True)
class CodexResult:
    response: str
    command: list[str]


def _fallback_catalog(settings: Settings, warning: str) -> dict:
    return {
        "models": [
            {
                "id": settings.codex_default_model,
                "name": settings.codex_default_model,
                "efforts": [settings.codex_reasoning_effort],
            }
        ],
        "default_model": settings.codex_default_model,
        "default_effort": settings.codex_reasoning_effort,
        "source": "configuration-fallback",
        "warning": warning,
    }


def _catalog_json(stdout: str) -> object:
    start = stdout.find("{")
    end = stdout.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Codex model catalog did not contain JSON")
    return json.loads(stdout[start : end + 1])


def _parse_catalog(settings: Settings, payload: object) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        raise ValueError("Codex model catalog has an unsupported shape")
    models: list[dict[str, object]] = []
    for raw in payload["models"]:
        if not isinstance(raw, dict) or raw.get("visibility") != "list":
            continue
        model_id = raw.get("slug") or raw.get("id")
        if not isinstance(model_id, str) or not MODEL_PATTERN.fullmatch(model_id):
            continue
        effort_rows = raw.get("supported_reasoning_levels") or raw.get("efforts")
        if not isinstance(effort_rows, list):
            continue
        efforts: list[str] = []
        for item in effort_rows:
            effort = item.get("effort") if isinstance(item, dict) else item
            if isinstance(effort, str) and effort in ALLOWED_EFFORTS and effort not in efforts:
                efforts.append(effort)
        if not efforts:
            continue
        display_name = raw.get("display_name") or raw.get("name") or model_id
        models.append({"id": model_id, "name": str(display_name), "efforts": efforts})
    if not models:
        raise ValueError("Codex model catalog contained no visible usable models")
    available = {str(model["id"]): model for model in models}
    default_model = (
        settings.codex_default_model
        if settings.codex_default_model in available
        else str(models[0]["id"])
    )
    default_efforts = available[default_model]["efforts"]
    default_effort = (
        settings.codex_reasoning_effort
        if settings.codex_reasoning_effort in default_efforts
        else str(default_efforts[0])
    )
    return {
        "models": models,
        "default_model": default_model,
        "default_effort": default_effort,
        "source": "codex-cli",
    }


def clear_model_catalog_cache() -> None:
    _MODEL_CATALOG_CACHE.clear()


def load_model_catalog(
    settings: Settings,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    now: Callable[[], float] = time.monotonic,
    force: bool = False,
) -> dict:
    key = (
        settings.codex_binary,
        settings.codex_default_model,
        settings.codex_reasoning_effort,
    )
    cached = _MODEL_CATALOG_CACHE.get(key)
    current_time = now()
    if not force and cached and current_time - cached[0] < MODEL_CATALOG_TTL_SECONDS:
        return cached[1]
    try:
        completed = runner(
            [settings.codex_binary, "debug", "models"],
            text=True,
            capture_output=True,
            timeout=max(1, min(settings.codex_timeout_seconds, 10)),
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            raise CodexError("Codex CLI model catalog command failed")
        catalog = _parse_catalog(settings, _catalog_json(completed.stdout))
    except (FileNotFoundError, subprocess.TimeoutExpired, CodexError, ValueError, json.JSONDecodeError):
        catalog = _fallback_catalog(
            settings,
            "Codex model catalog is unavailable; using the configured default profile.",
        )
    _MODEL_CATALOG_CACHE[key] = (current_time, catalog)
    return catalog


def validate_model_effort(catalog: dict, model: str, effort: str) -> tuple[str, str]:
    selected_model = model or str(catalog["default_model"])
    models = {
        str(item["id"]): item
        for item in catalog.get("models", [])
        if isinstance(item, dict) and "id" in item
    }
    if selected_model not in models:
        raise ValueError("Selected Codex model is not available")
    selected_effort = effort or (
        str(catalog["default_effort"])
        if selected_model == catalog["default_model"]
        else str(models[selected_model]["efforts"][0])
    )
    if selected_effort not in models[selected_model].get("efforts", []):
        raise ValueError("Selected reasoning effort is not supported by this model")
    return selected_model, selected_effort


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
    reasoning_effort: str = "",
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> CodexResult:
    selected_model = model or settings.codex_default_model
    selected_effort = reasoning_effort or settings.codex_reasoning_effort
    if selected_model and not MODEL_PATTERN.fullmatch(selected_model):
        raise ValueError("Model name contains unsupported characters")
    if selected_effort not in ALLOWED_EFFORTS:
        raise ValueError("Unsupported Codex reasoning effort")
    command = [
        settings.codex_binary,
        "exec",
        "--sandbox", "read-only",
        "--color", "never",
        "--ephemeral",
        "--cd", str(settings.project_root),
        "-c", f'model_reasoning_effort="{selected_effort}"',
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
