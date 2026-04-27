"""Accounting — WOA reviewer decisions (approve / flag / pending). SQLite-backed."""

from fastapi import APIRouter, Query
from pydantic import BaseModel
import database

router = APIRouter()


class ReviewPayload(BaseModel):
    status: str        # 'approved' | 'flagged' | 'pending'
    note: str = ''
    reviewer: str = ''


@router.get("/api/accounting/wo-adjustments/review-statuses")
def api_woa_review_statuses(ids: str = Query('', description="Comma-separated WOA IDs")):
    """Return reviewer decisions for a batch of WOA IDs (no SF calls — SQLite only)."""
    if not ids:
        return {}
    id_list = [i.strip() for i in ids.split(',') if i.strip()][:500]
    return database.get_woa_reviews_batch(id_list)


@router.post("/api/accounting/wo-adjustments/{woa_id}/review")
def api_set_woa_review(woa_id: str, payload: ReviewPayload):
    """Save a reviewer decision for a WOA (approve / flag / pending)."""
    valid = {'approved', 'flagged', 'pending'}
    status = payload.status.lower()
    if status not in valid:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"status must be one of {valid}")
    return database.set_woa_review(woa_id, status, payload.note, payload.reviewer)
