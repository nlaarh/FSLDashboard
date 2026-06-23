"""Admin-only Salesforce diagnostics."""

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Request

from routers.admin import _check_pin
from salesforce_queries.registry import get_named_query
from sf_client import sf_query_explain

router = APIRouter()


def _named_query(name: str) -> tuple[str, str]:
    since = f"{(date.today() - timedelta(days=28)).isoformat()}T00:00:00Z"
    try:
        soql = get_named_query(name, since=since)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown Salesforce diagnostic query")
    return since, soql


@router.get("/api/admin/salesforce/query-plan/{name}")
def salesforce_query_plan(name: str, request: Request):
    """Return Salesforce query optimizer plan for a named read-only diagnostic."""
    _check_pin(request)
    since, soql = _named_query(name)
    return {
        "name": name,
        "since": since,
        "soql": soql,
        "plan": sf_query_explain(soql),
    }
