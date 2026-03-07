"""Salesforce OAuth2 client — password flow with auto-refresh and retry."""

import os, threading, time as _time, requests
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


def sf_query(soql: str, _retries: int = 3) -> dict:
    token, instance = get_auth()
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

    for attempt in range(_retries):
        try:
            r = requests.get(f'{instance}/services/data/v60.0/query',
                             headers=headers, params={'q': soql}, timeout=(10, 120))
        except requests.exceptions.Timeout:
            if attempt < _retries - 1:
                _time.sleep(2 ** attempt)
                continue
            raise RuntimeError("SF query timed out after retries")

        # Retry on server errors
        if r.status_code in (500, 502, 503) and attempt < _retries - 1:
            _time.sleep(2 ** attempt)
            continue

        # Handle expired session
        if r.status_code in (401, 403):
            token, instance = refresh_auth()
            headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
            r = requests.get(f'{instance}/services/data/v60.0/query',
                             headers=headers, params={'q': soql}, timeout=(10, 120))
        break

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
                         headers=headers, params={'q': soql}, timeout=(10, 120))
        result = r.json()
    if isinstance(result, list):
        raise RuntimeError(f"SF query error: {result}")
    if isinstance(result, dict) and 'errorCode' in result:
        raise RuntimeError(f"SF error: {result.get('message', result)}")
    return result


def sf_parallel(**fns) -> dict:
    """Run multiple functions in parallel. Returns {name: result}."""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {name: pool.submit(fn) for name, fn in fns.items()}
        return {name: fut.result() for name, fut in futures.items()}


def sf_query_all(soql: str) -> list[dict]:
    result = sf_query(soql)
    if isinstance(result, list) or 'records' not in result:
        return []
    records = result.get('records', [])
    token, instance = get_auth()
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    page = 1
    while not result.get('done', True) and result.get('nextRecordsUrl'):
        page += 1
        for attempt in range(3):
            try:
                resp = requests.get(f'{instance}{result["nextRecordsUrl"]}',
                                    headers=headers, timeout=(10, 60))
                result = resp.json()
                break
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                if attempt < 2:
                    _time.sleep(2 ** attempt)
                    # Re-auth in case token expired
                    token, instance = refresh_auth()
                    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
                    continue
                raise
        if isinstance(result, list) or 'records' not in result:
            break
        records.extend(result.get('records', []))
    return records
