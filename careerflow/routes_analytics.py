"""HTTP route for the read-only analytics snapshot."""

from fastapi import APIRouter, HTTPException, Query, Request

from .analytics import calculate

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("")
def get_analytics(
    request: Request,
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    bucket: str = "month",
) -> dict:
    try:
        return calculate(request.app.state.db, from_date, to_date, bucket)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
