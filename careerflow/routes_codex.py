"""Codex CLI capability catalog API."""

from __future__ import annotations

from fastapi import APIRouter, Request

from .codex import load_model_catalog


router = APIRouter(prefix="/api/codex", tags=["codex"])


@router.get("/models")
def models(request: Request) -> dict:
    return load_model_catalog(request.app.state.settings)
