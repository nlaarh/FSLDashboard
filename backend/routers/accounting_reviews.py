"""Accounting — WOA reviewer decisions (approve / flag / pending). SQLite-backed."""

import os
from fastapi import APIRouter, Query, Request, HTTPException
from pydantic import BaseModel
import database
import users
from routers.auth import _verify_cookie

router = APIRouter()


def _get_reviewer(request: Request) -> str:
    """Derive reviewer identity from the logged-in session. Never trust client-supplied text."""
    # Cookie session (local login)
    cookie = request.cookies.get("fslapp_auth")
    if cookie:
        username = _verify_cookie(cookie)
        if username:
            user = users.get_user(username)
            if user:
                return user.get('name') or user.get('username', username)
    # Azure Easy Auth (production SSO)
    if os.environ.get("WEBSITE_SITE_NAME"):
        principal = request.headers.get("x-ms-client-principal")
        if principal:
            import base64, json as _json
            try:
                data = _json.loads(base64.b64decode(principal + "==").decode())
                return data.get("name") or data.get("preferred_username") or "SSO User"
            except Exception:
                pass
    return "Unknown"


class ReviewPayload(BaseModel):
    status: str   # 'approved' | 'flagged' | 'pending'
    note: str = ''


@router.get("/api/accounting/wo-adjustments/review-statuses")
def api_woa_review_statuses(ids: str = Query('', description="Comma-separated WOA IDs")):
    """Return reviewer decisions for a batch of WOA IDs (no SF calls — SQLite only)."""
    if not ids:
        return {}
    id_list = [i.strip() for i in ids.split(',') if i.strip()][:500]
    return database.get_woa_reviews_batch(id_list)


@router.post("/api/accounting/wo-adjustments/{woa_id}/review")
def api_set_woa_review(woa_id: str, payload: ReviewPayload, request: Request):
    """Save a reviewer decision for a WOA. Reviewer identity derived from session."""
    valid = {'approved', 'flagged', 'pending'}
    status = payload.status.lower()
    if status not in valid:
        raise HTTPException(status_code=400, detail=f"status must be one of {valid}")
    reviewer = _get_reviewer(request)
    return database.set_woa_review(woa_id, status, payload.note, reviewer)
