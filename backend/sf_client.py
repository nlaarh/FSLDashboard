"""Salesforce OAuth2 client — with rate limiter, circuit breaker, and connection pooling.

Protects the production Salesforce org from being overwhelmed by FSLAPP:
1. Rate limiter: max 60 API calls/minute (configurable)
2. Circuit breaker: if SF fails 5x in a row, stop calling for 60s
3. Connection pooling: reuse TCP connections across 25+ dispatchers
"""

import os, threading, time as _time, logging, re, requests
from collections import deque
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

log = logging.getLogger('sf_client')


def sanitize_soql(value: str) -> str:
    """Sanitize a value for safe SOQL interpolation. Prevents SOQL injection."""
    if not isinstance(value, str):
        value = str(value)
    # Remove/escape characters that could break SOQL string literals
    # SOQL strings use single quotes, so escape them
    # Also remove backslashes, semicolons, and other dangerous chars
    value = value.replace("\\", "").replace("'", "\\'")
    # Only allow alphanumeric, hyphens, underscores, dots, spaces, colons
    # (covers SF IDs like 0HoXX0000000001, appointment numbers like SA-0001234, dates like 2026-03-08T00:00:00Z)
    if not re.match(r'^[a-zA-Z0-9\-_.:/ ]+$', value):
        raise ValueError(f"Invalid characters in SOQL parameter: {value!r}")
    return value


# Load .env from the apidev directory (one level up from FSLAPP)
_env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(os.path.abspath(_env_path))

_lock = threading.Lock()
_token: str | None = None
_instance: str | None = None

# ── Connection Pooling ──────────────────────────────────────────────────────
_session = requests.Session()
_adapter = HTTPAdapter(
    pool_connections=10,
    pool_maxsize=25,
    max_retries=Retry(total=0),
)
_session.mount('https://', _adapter)
_session.mount('http://', _adapter)


# ── Rate Limiter ────────────────────────────────────────────────────────────
# Sliding window: max N calls per 60 seconds
_RATE_LIMIT = int(os.getenv('SF_RATE_LIMIT', '300'))  # calls per minute (~5/sec)
_rate_lock = threading.Lock()
_call_timestamps: deque = deque()


def _rate_limit_check():
    """Block if we've exceeded the rate limit. Waits until a slot opens."""
    wait = 0.0
    with _rate_lock:
        now = _time.time()
        # Purge timestamps older than 60s
        while _call_timestamps and _call_timestamps[0] < now - 60:
            _call_timestamps.popleft()

        if len(_call_timestamps) >= _RATE_LIMIT:
            # Calculate wait time but release lock before sleeping
            wait = _call_timestamps[0] - (now - 60) + 0.1
            log.warning(f"Rate limit hit ({_RATE_LIMIT}/min). Waiting {wait:.1f}s")

    if wait > 0:
        _time.sleep(wait)

    with _rate_lock:
        # Re-purge after waiting
        now = _time.time()
        while _call_timestamps and _call_timestamps[0] < now - 60:
            _call_timestamps.popleft()
        _call_timestamps.append(_time.time())


# ── Circuit Breaker ─────────────────────────────────────────────────────────
# If SF fails repeatedly, stop calling it to let it recover
_BREAKER_THRESHOLD = 15      # consecutive failures before opening circuit
_BREAKER_COOLDOWN = 30       # seconds to wait before retrying
_breaker_lock = threading.Lock()
_breaker_failures = 0
_breaker_open_until = 0.0


class SalesforceUnavailable(RuntimeError):
    """Raised when circuit breaker is open — SF is temporarily unavailable."""
    pass


def _breaker_check():
    """Raise if circuit breaker is open."""
    with _breaker_lock:
        if _breaker_failures >= _BREAKER_THRESHOLD:
            if _time.time() < _breaker_open_until:
                remaining = round(_breaker_open_until - _time.time())
                raise SalesforceUnavailable(
                    f"Salesforce circuit breaker open — {_breaker_failures} consecutive failures. "
                    f"Retrying in {remaining}s. App will serve cached data."
                )
            # Cooldown expired — allow one attempt (half-open)
            log.info("Circuit breaker half-open — allowing one retry")


def _breaker_success():
    """Record a successful SF call — reset the breaker."""
    global _breaker_failures, _breaker_open_until
    with _breaker_lock:
        if _breaker_failures > 0:
            log.info(f"SF recovered after {_breaker_failures} failures — circuit closed")
        _breaker_failures = 0
        _breaker_open_until = 0.0


def _breaker_failure():
    """Record a failed SF call — may open the breaker."""
    global _breaker_failures, _breaker_open_until
    with _breaker_lock:
        _breaker_failures += 1
        if _breaker_failures >= _BREAKER_THRESHOLD:
            _breaker_open_until = _time.time() + _BREAKER_COOLDOWN
            log.error(f"Circuit breaker OPEN — {_breaker_failures} consecutive SF failures. "
                      f"No SF calls for {_BREAKER_COOLDOWN}s.")


# ── Stats ───────────────────────────────────────────────────────────────────
_stats_lock = threading.Lock()
_stats = {'total_calls': 0, 'errors': 0, 'rate_waits': 0, 'breaker_trips': 0}
_recent_errors: deque = deque(maxlen=20)  # last 20 errors with timestamps


def _record_error(error_msg: str, soql_snippet: str = ''):
    """Record an error with timestamp for debugging."""
    with _stats_lock:
        _stats['errors'] += 1
        _recent_errors.append({
            'time': _time.strftime('%H:%M:%S'),
            'error': str(error_msg)[:200],
            'query': soql_snippet[:100] if soql_snippet else '',
        })
    log.error(f"SF error: {error_msg}")


def get_stats():
    """Return SF client health stats for monitoring."""
    with _stats_lock:
        s = dict(_stats)
        s['recent_errors'] = list(_recent_errors)
    with _rate_lock:
        now = _time.time()
        recent = sum(1 for t in _call_timestamps if t > now - 60)
    with _breaker_lock:
        s['breaker_failures'] = _breaker_failures
        s['breaker_open'] = _breaker_failures >= _BREAKER_THRESHOLD and _time.time() < _breaker_open_until
    s['calls_last_60s'] = recent
    s['rate_limit'] = _RATE_LIMIT
    return s


# ── Auth ────────────────────────────────────────────────────────────────────

def _authenticate() -> tuple[str, str]:
    payload = {
        'grant_type': 'password',
        'client_id': os.getenv('SF_CONSUMER_KEY'),
        'client_secret': os.getenv('SF_CONSUMER_SECRET'),
        'username': os.getenv('SF_USERNAME'),
        'password': os.getenv('SF_PASSWORD', '') + os.getenv('SF_SECURITY_TOKEN', ''),
    }
    resp = _session.post(os.getenv('SF_TOKEN_URL', ''), data=payload, timeout=30)
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


# ── Query ───────────────────────────────────────────────────────────────────

def sf_query(soql: str, _retries: int = 3) -> dict:
    # Gate 1: circuit breaker
    _breaker_check()
    # Gate 2: rate limiter
    _rate_limit_check()

    with _stats_lock:
        _stats['total_calls'] += 1

    token, instance = get_auth()
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

    for attempt in range(_retries):
        try:
            r = _session.get(f'{instance}/services/data/v60.0/query',
                             headers=headers, params={'q': soql}, timeout=(10, 120))
        except requests.exceptions.Timeout:
            if attempt < _retries - 1:
                _time.sleep(2 ** attempt)
                continue
            # Only count as breaker failure after ALL retries exhausted
            _breaker_failure()
            _record_error("SF query timed out after retries", soql)
            raise RuntimeError("SF query timed out after retries")
        except requests.exceptions.ConnectionError as ce:
            if attempt < _retries - 1:
                _time.sleep(2 ** attempt)
                continue
            _breaker_failure()
            _record_error(f"SF connection failed: {ce}", soql)
            raise RuntimeError("SF connection failed after retries")

        # Retry on server errors
        if r.status_code in (500, 502, 503):
            if attempt < _retries - 1:
                _time.sleep(2 ** attempt)
                continue
            _breaker_failure()
            _record_error(f"SF server error {r.status_code} after {_retries} retries", soql)
            raise RuntimeError(f"SF server error {r.status_code} after {_retries} retries")

        # Handle expired session
        if r.status_code in (401, 403):
            token, instance = refresh_auth()
            headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
            _rate_limit_check()
            r = _session.get(f'{instance}/services/data/v60.0/query',
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
        _rate_limit_check()
        r = _session.get(f'{instance}/services/data/v60.0/query',
                         headers=headers, params={'q': soql}, timeout=(10, 120))
        result = r.json()
    if isinstance(result, list):
        _breaker_failure()
        _record_error(f"SF query error: {result}", soql)
        raise RuntimeError(f"SF query error: {result}")
    if isinstance(result, dict) and 'errorCode' in result:
        _breaker_failure()
        _record_error(f"SF error: {result.get('message', result)}", soql)
        raise RuntimeError(f"SF error: {result.get('message', result)}")

    # Success — reset breaker
    _breaker_success()
    return result


def sf_parallel(**fns) -> dict:
    """Run multiple functions in parallel. Returns {name: result}."""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
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
        _rate_limit_check()  # Each page counts against rate limit
        for attempt in range(3):
            try:
                resp = _session.get(f'{instance}{result["nextRecordsUrl"]}',
                                    headers=headers, timeout=(10, 60))
                result = resp.json()
                _breaker_success()
                break
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                if attempt < 2:
                    _time.sleep(2 ** attempt)
                    token, instance = refresh_auth()
                    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
                    continue
                # Only count after all retries exhausted
                _breaker_failure()
                raise
        if isinstance(result, list) or 'records' not in result:
            break
        records.extend(result.get('records', []))
    return records


def get_towbook_on_location(sa_ids: list[str]) -> dict[str, str]:
    """Fetch real arrival timestamps for Towbook SAs from ServiceAppointmentHistory.

    Towbook ActualStartTime is a fake future estimate. The REAL arrival is the
    CreatedDate of the history row where Status changed to 'On Location'.

    Args:
        sa_ids: List of ServiceAppointment IDs (Towbook SAs only)

    Returns:
        Dict mapping SA ID -> ISO datetime string of 'On Location' timestamp
    """
    if not sa_ids:
        return {}

    result = {}
    # Process in batches of 200 to stay within SOQL IN clause limits
    for i in range(0, len(sa_ids), 200):
        batch = sa_ids[i:i + 200]
        id_list = "','".join(batch)
        rows = sf_query_all(f"""
            SELECT ServiceAppointmentId, NewValue, CreatedDate
            FROM ServiceAppointmentHistory
            WHERE ServiceAppointmentId IN ('{id_list}')
              AND Field = 'Status'
            ORDER BY ServiceAppointmentId, CreatedDate ASC
        """)
        for r in rows:
            if r.get('NewValue') == 'On Location':
                sid = r['ServiceAppointmentId']
                if sid not in result:  # first On Location wins
                    result[sid] = r['CreatedDate']
    return result
