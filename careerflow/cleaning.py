"""Conservative vacancy-description block extraction and classification."""

from __future__ import annotations

import json
import re
from typing import Callable

from .codex import CodexResult, run_codex
from .config import Settings
from .files import normalize_text


CLASSIFICATIONS = {"keep", "remove", "uncertain"}
SERVICE_BLOCK = re.compile(
    r"(?i)^(?:sign in|log in|register|apply now|search jobs?|save job|share(?: this job)?|"
    r"accept(?: all)? cookies?|cookie (?:settings|preferences|policy)|privacy policy|terms of use|"
    r"related jobs?|recommended jobs?|similar jobs?|back to (?:jobs?|search)|"
    r"войти|регистрация|откликнуться|поиск вакансий|похожие вакансии|рекомендуемые вакансии|"
    r"принять cookies?|настройки cookies?|политика конфиденциальности)$"
)
UNCERTAIN_BLOCK = re.compile(
    r"(?i)^(?:home|careers?|jobs?|menu|about us|contact|главная|карьера|вакансии|меню|контакты)$"
)


def split_blocks(text: str) -> list[dict[str, str]]:
    normalized = normalize_text(text)
    return [
        {"id": f"b{index}", "text": line}
        for index, line in enumerate(normalized.splitlines(), start=1)
        if line
    ]


def classify_blocks(blocks: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    results: list[dict[str, str]] = []
    for block in blocks:
        canonical = block["text"].casefold()
        if canonical in seen:
            classification = "remove"
            reason = "Exact duplicate"
        elif SERVICE_BLOCK.fullmatch(block["text"]):
            classification = "remove"
            reason = "Unambiguous page control or service text"
        elif UNCERTAIN_BLOCK.fullmatch(block["text"]):
            classification = "uncertain"
            reason = "Short navigation-like text; retained for review"
        else:
            classification = "keep"
            reason = "Potential vacancy content"
        seen.add(canonical)
        results.append({**block, "classification": classification, "reason": reason})
    return results


def validate_classifications(
    blocks: list[dict[str, str]], classifications: object
) -> list[dict[str, str]]:
    if isinstance(classifications, dict):
        classifications = classifications.get("blocks")
    if not isinstance(classifications, list):
        raise ValueError("Codex cleanup must return a JSON list of block classifications")
    known = {block["id"]: block for block in blocks}
    validated: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in classifications:
        if not isinstance(item, dict):
            raise ValueError("Each Codex cleanup result must be an object")
        block_id = item.get("id")
        classification = item.get("classification") or item.get("action")
        if block_id not in known:
            raise ValueError(f"Codex cleanup returned unknown block id: {block_id}")
        if block_id in seen:
            raise ValueError(f"Codex cleanup returned duplicate block id: {block_id}")
        if classification not in CLASSIFICATIONS:
            raise ValueError(f"Unsupported classification for block {block_id}")
        seen.add(str(block_id))
        validated.append(
            {
                **known[str(block_id)],
                "classification": str(classification),
                "reason": str(item.get("reason", ""))[:240],
            }
        )
    missing = set(known) - seen
    if missing:
        raise ValueError(f"Codex cleanup omitted block ids: {', '.join(sorted(missing))}")
    order = {block["id"]: index for index, block in enumerate(blocks)}
    return sorted(validated, key=lambda item: order[item["id"]])


def _json_payload(value: str) -> object:
    stripped = value.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.I | re.S)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError("Codex cleanup returned invalid JSON") from exc


def classify_blocks_with_codex(
    settings: Settings,
    blocks: list[dict[str, str]],
    *,
    runner: Callable[..., CodexResult] = run_codex,
) -> list[dict[str, str]]:
    payload = [{"id": block["id"], "text": block["text"]} for block in blocks]
    prompt = "\n".join(
        [
            "Classify each vacancy-import block as keep, remove, or uncertain.",
            "Return JSON only: an array of objects with id, classification, and short reason.",
            "Return every supplied id exactly once and no other ids.",
            "Do not rewrite, translate, summarize, correct, merge, or add text.",
            "Do not change facts, requirements, numbers, dates, salary, technology names, or names.",
            "Use remove only for unambiguous page chrome, controls, cookie text, ads, or unrelated recommendations.",
            json.dumps(payload, ensure_ascii=False),
        ]
    )
    result = runner(settings, prompt)
    return validate_classifications(blocks, _json_payload(result.response))


def build_preview(
    raw_text: str,
    candidate_text: str | None = None,
    *,
    method: str = "local-blocks",
    settings: Settings | None = None,
    use_codex: bool = False,
    codex_runner: Callable[..., CodexResult] = run_codex,
) -> dict:
    raw = normalize_text(raw_text)
    candidate = normalize_text(candidate_text if candidate_text is not None else raw_text)
    blocks = split_blocks(candidate)
    if not blocks:
        raise ValueError("Vacancy description is required")
    classified = (
        classify_blocks_with_codex(settings, blocks, runner=codex_runner)
        if use_codex and settings is not None
        else classify_blocks(blocks)
    )
    retained = [item["text"] for item in classified if item["classification"] != "remove"]
    description = "\n".join(retained).strip()
    if not description:
        raise ValueError("Cleaning removed every description block; review the source manually")

    removed = [item for item in classified if item["classification"] == "remove"]
    candidate_lines = {block["text"] for block in blocks}
    for block in split_blocks(raw):
        if block["text"] not in candidate_lines:
            removed.append(
                {
                    **block,
                    "classification": "remove",
                    "reason": f"Excluded by {method} extraction",
                }
            )
    return {
        "raw_description": raw,
        "description": description,
        "method": f"codex:{method}" if use_codex else method,
        "blocks": classified,
        "removed_blocks": removed,
        "uncertain_blocks": [
            item for item in classified if item["classification"] == "uncertain"
        ],
    }
