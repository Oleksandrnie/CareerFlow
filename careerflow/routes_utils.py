"""Small shared HTTP helpers for route modules."""

from __future__ import annotations

from fastapi import HTTPException, UploadFile


async def read_limited_upload(upload: UploadFile, max_bytes: int, detail: str) -> bytes:
    """Read no more than the configured upload limit plus one sentinel byte."""

    content = await upload.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=detail)
    return content
