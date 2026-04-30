"""Find optimizer runs that need extraction.

Queries SF for runs in a date window via the standard REST API
(works with the SF CLI session — no UI needed for this part).
"""

import urllib.request
import urllib.parse
import json
from datetime import datetime, timezone, timedelta

from .auth import SFSession


def list_runs(session: SFSession, since: datetime, until: datetime | None = None) -> list[dict]:
    """Return [{Id, Name, FSL__Status__c, CreatedDate}] for runs in the window."""
    until = until or datetime.now(timezone.utc)
    soql = (
        "SELECT Id, Name, FSL__Status__c, FSL__Type__c, "
        "FSL__External_Identifier__c, CreatedDate "
        "FROM FSL__Optimization_Request__c "
        f"WHERE CreatedDate >= {since.strftime('%Y-%m-%dT%H:%M:%SZ')} "
        f"AND CreatedDate <= {until.strftime('%Y-%m-%dT%H:%M:%SZ')} "
        "ORDER BY CreatedDate ASC"
    )
    url = f"{session.instance_url}/services/data/v59.0/query?q={urllib.parse.quote(soql)}"
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {session.access_token}'})
    body = urllib.request.urlopen(req).read()
    return json.loads(body).get('records', [])


def runs_for_date(session: SFSession, day: datetime) -> list[dict]:
    """Convenience: all runs for one day (UTC)."""
    start = day.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
    return list_runs(session, start, start + timedelta(days=1))
