"""Salesforce OAuth2 client — password flow with auto-refresh."""

import os, threading, requests
from dotenv import load_dotenv

# Load .env from the apidev directory (one level up from FSLAPP)
_env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(os.path.abspath(_env_path))

_lock = threading.Lock()
_token: str | None = None
_instance: str | None = None


def _authenticate() -> tuple[str, str]:
    payload = {
        'grant_type': 'password',
        'client_id': os.getenv('SF_CONSUMER_KEY'),
        'client_secret': os.getenv('SF_CONSUMER_SECRET'),
        'username': os.getenv('SF_USERNAME'),
        'password': os.getenv('SF_PASSWORD', '') + os.getenv('SF_SECURITY_TOKEN', ''),
    }
    resp = requests.post(os.getenv('SF_TOKEN_URL', ''), data=payload, timeout=30)
    auth = resp.json()
    if 'access_token' not in auth:
        raise RuntimeError(f"SF auth failed: {auth}")
    return auth['access_token'], auth['instance_url']


def get_auth() -> tuple[str, str]:
    global _token, _instance
    with _lock:
        if _token is None:
            _token, _instance = _authenticate()
    return _token, _instance


def refresh_auth() -> tuple[str, str]:
    global _token, _instance
    with _lock:
        _token, _instance = _authenticate()
    return _token, _instance


def sf_query(soql: str) -> dict:
    token, instance = get_auth()
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    r = requests.get(f'{instance}/services/data/v60.0/query',
                     headers=headers, params={'q': soql}, timeout=120)
    if r.status_code in (401, 403):
        token, instance = refresh_auth()
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        r = requests.get(f'{instance}/services/data/v60.0/query',
                         headers=headers, params={'q': soql}, timeout=120)
    result = r.json()
    if isinstance(result, list):
        is_expired = result and 'INVALID_SESSION' in result[0].get('errorCode', '').upper()
    elif isinstance(result, dict):
        is_expired = 'INVALID_SESSION' in result.get('errorCode', '').upper()
    else:
        is_expired = False
    if is_expired:
        token, instance = refresh_auth()
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        r = requests.get(f'{instance}/services/data/v60.0/query',
                         headers=headers, params={'q': soql}, timeout=120)
        result = r.json()
    if isinstance(result, list):
        raise RuntimeError(f"SF query error: {result}")
    if isinstance(result, dict) and 'errorCode' in result:
        raise RuntimeError(f"SF error: {result.get('message', result)}")
    return result


def sf_query_all(soql: str) -> list[dict]:
    result = sf_query(soql)
    if isinstance(result, list) or 'records' not in result:
        return []
    records = result.get('records', [])
    token, instance = get_auth()
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    while not result.get('done', True) and result.get('nextRecordsUrl'):
        result = requests.get(f'{instance}{result["nextRecordsUrl"]}',
                              headers=headers, timeout=120).json()
        if isinstance(result, list) or 'records' not in result:
            break
        records.extend(result.get('records', []))
    return records
