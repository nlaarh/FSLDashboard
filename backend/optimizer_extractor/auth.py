"""SF auth via the locally-stored `sf` CLI session (alias 'prod').

`sf org login web --instance-url https://aaawcny.my.salesforce.com --alias prod`
must have been run once. After that, this module mints fresh access tokens
on demand using the refresh token sf CLI manages.
"""

import json
import subprocess
from dataclasses import dataclass


@dataclass
class SFSession:
    access_token: str
    instance_url: str
    username: str


def get_session(alias: str = 'prod') -> SFSession:
    """Return current SF session via the sf CLI. Refreshes token automatically."""
    result = subprocess.run(
        ['sf', 'org', 'display', '--target-org', alias, '--json'],
        capture_output=True, text=True, check=True,
    )
    payload = json.loads(result.stdout)
    if payload.get('status', 0) != 0:
        raise RuntimeError(f"sf org display failed: {payload}")
    r = payload['result']
    return SFSession(
        access_token=r['accessToken'],
        instance_url=r['instanceUrl'],
        username=r['username'],
    )
