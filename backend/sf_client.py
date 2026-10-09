"""Salesforce OAuth2 client — with rate limiter, circuit breaker, and connection pooling.

Protects the production Salesforce org from being overwhelmed by FSLAPP:
1. Rate limiter: max 60 API calls/minute (configurable)
2. Circuit breaker: if SF is down (5xx, timeouts, connection errors) 5x in a row, or says REQUEST_LIMIT_EXCEEDED,
   stop calling for 60s. A query mistake (4xx) is not an outage and never counts.
3. Connection pooling: reuse TCP connections across 25+ dispatchers
4. In-flight cap: at most SF_MAX_INFLIGHT (8) requests on the wire at once, however many threads ask
"""

import contextvars
import copy
import os, threading, time as _time, logging, re, requests
from urllib.parse import quote
from collections import deque
from datetime import datetime, timezone
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

log = logging.getLogger('sf_client')

SF_API_VERSION = 'v65.0'

# (connect, read) seconds. A Salesforce call that has not answered in 20 s is hung, and it holds one of the org's
# 25 long-running slots while it hangs. Reports and history pulls that really take longer pass TIMEOUT_LONG.
TIMEOUT_DEFAULT = (5, 20)
TIMEOUT_LONG = (10, 60)


def sanitize_soql(value: str) -> str:
    """Sanitize a value for safe SOQL interpolation. Prevents SOQL injection."""
    if not isinstance(value, str):
        value = str(value)
    # Remove backslashes first, then escape single quotes for SOQL
    value = value.replace("\\", "").replace("'", "\\'")
    # Allow characters found in Salesforce data: alphanumeric, hyphens, underscores,
    # dots, spaces, colons, slashes, ampersands, commas, parens, hash, at-signs
    # (covers territory names like "J\'S AUTO", "AUTO & GLASS", SF IDs, dates)
    # Block semicolons, backticks, and other injection vectors
    if re.search(r'[;`\x00-\x1f]', value):
        raise ValueError(f"Invalid characters in SOQL parameter: {value!r}")
    return value


# Load FSLAPP/.env — the single env file for this app (see FSLAPP/.env header)
_env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
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


# ── In-flight cap + per-endpoint counters ───────────────────────────────────
# Salesforce allows 25 concurrent long (>20 s) requests for the WHOLE org (~800 users). No burst from here may pile up.
_MAX_INFLIGHT = int(os.getenv('SF_MAX_INFLIGHT', '8'))
_INFLIGHT_WAIT = 30                       # seconds a request may queue for a slot before it gives up
_inflight = threading.BoundedSemaphore(_MAX_INFLIGHT)
_inflight_now = 0
_inflight_peak = 0

# Who is asking: the web layer sets the endpoint, the refresher sets 'refresh:<key>'; anything else is 'background'.
sf_endpoint: contextvars.ContextVar = contextvars.ContextVar('sf_endpoint', default='background')
_by_endpoint: dict = {}
_MAX_ENDPOINTS = 200


def endpoint_label(path: str) -> str:
    """'/api/garages/0HhPb0000004Cb5/scorecard' -> '/api/garages/{id}/scorecard' (keeps the counter list short)."""
    return re.sub(r'/[^/]*\d[^/]*', '/{id}', path)


def _http(fn, *args, **kwargs):
    """Run one HTTP request to Salesforce inside the in-flight cap and count it against the calling endpoint."""
    global _inflight_now, _inflight_peak
    if not _inflight.acquire(timeout=_INFLIGHT_WAIT):
        raise SalesforceUnavailable(f"{_MAX_INFLIGHT} Salesforce requests already in flight; gave up waiting {_INFLIGHT_WAIT}s")
    try:
        name = sf_endpoint.get()
        with _stats_lock:
            _inflight_now += 1
            _inflight_peak = max(_inflight_peak, _inflight_now)
            if name not in _by_endpoint and len(_by_endpoint) >= _MAX_ENDPOINTS:
                name = 'other'
            _by_endpoint[name] = _by_endpoint.get(name, 0) + 1
        return fn(*args, **kwargs)
    finally:
        with _stats_lock:
            _inflight_now -= 1
        _inflight.release()


# ── Circuit Breaker ─────────────────────────────────────────────────────────
# If SF fails repeatedly, stop calling it to let it recover
_BREAKER_THRESHOLD = 5       # consecutive failures before opening circuit (detect outages fast)
_BREAKER_COOLDOWN = 60       # seconds to wait before retrying (give SF time to recover)
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


def _breaker_trip(reason: str):
    """Open the breaker now (Salesforce told us to back off)."""
    global _breaker_failures, _breaker_open_until
    with _breaker_lock:
        _breaker_failures = max(_breaker_failures, _BREAKER_THRESHOLD)
        _breaker_open_until = _time.time() + _BREAKER_COOLDOWN
    with _stats_lock:
        _stats['breaker_trips'] += 1
    log.error(f"Circuit breaker OPEN — {reason}. No SF calls for {_BREAKER_COOLDOWN}s.")


def _breaker_failure():
    """Record a failed SF call — may open the breaker."""
    global _breaker_failures, _breaker_open_until
    with _breaker_lock:
        _breaker_failures += 1
        if _breaker_failures >= _BREAKER_THRESHOLD:
            _breaker_open_until = _time.time() + _BREAKER_COOLDOWN
            _stats['breaker_trips'] += 1
            log.error(f"Circuit breaker OPEN — {_breaker_failures} consecutive SF failures. "
                      f"No SF calls for {_BREAKER_COOLDOWN}s.")


# ── Stats ───────────────────────────────────────────────────────────────────
_stats_lock = threading.Lock()
_stats = {'total_calls': 0, 'errors': 0, 'rate_waits': 0, 'breaker_trips': 0}
_recent_errors: deque = deque(maxlen=20)  # last 20 errors with timestamps
_recent_slow_queries: deque = deque(maxlen=20)  # last 20 slow SF calls


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


def _record_slow_query(kind: str, seconds: float, detail: str):
    """Record a slow Salesforce call for admin diagnostics."""
    with _stats_lock:
        _recent_slow_queries.append({
            'kind': kind,
            'seconds': round(seconds, 3),
            'detail': str(detail)[:200],
            'recorded_at': datetime.now(timezone.utc).isoformat(),
        })


def get_recent_slow_queries() -> list[dict]:
    """Return recent slow Salesforce calls, newest first."""
    with _stats_lock:
        return list(reversed(_recent_slow_queries))


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
    with _stats_lock:
        s['in_flight'], s['in_flight_peak'], s['max_in_flight'] = _inflight_now, _inflight_peak, _MAX_INFLIGHT
        s['requests_by_endpoint'] = dict(sorted(_by_endpoint.items(), key=lambda kv: -kv[1])[:30])   # real HTTP requests
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


def refresh_auth(stale_token: str | None = None) -> tuple[str, str]:
    """Log in again. When `stale_token` (the token that just failed) is given and another thread has already
    replaced it, use that one instead of logging in a second time."""
    global _token, _instance
    with _lock:
        if stale_token is not None and _token not in (None, stale_token):
            return _token, _instance
        _token, _instance = _authenticate()
    return _token, _instance


def _error_code(result) -> str:
    """Salesforce errorCode of a response body (a list of errors or one object), '' when it is not an error."""
    if isinstance(result, list):
        result = result[0] if result and isinstance(result[0], dict) else {}
    return str(result.get('errorCode', '')) if isinstance(result, dict) else ''


def _limit_exceeded(what: str, detail: str):
    """The org's API limit is hit: do not retry or log in again, stop asking for 60 s."""
    _breaker_trip('Salesforce REQUEST_LIMIT_EXCEEDED')
    _record_error(f"{what} REQUEST_LIMIT_EXCEEDED: {detail}", what)
    raise RuntimeError(f"Salesforce REQUEST_LIMIT_EXCEEDED ({what}); backing off {_BREAKER_COOLDOWN}s")


# ── REST Helpers ─────────────────────────────────────────────────────────────

def _versioned_path(path: str) -> str:
    if path.startswith('/services/data/'):
        return path
    if not path.startswith('/'):
        path = '/' + path
    return f'/services/data/{SF_API_VERSION}{path}'


def _sf_rest_request(method: str, path: str, _retries: int = 2, **kwargs) -> dict | list:
    """Authenticated Salesforce REST request with shared rate/breaker handling."""
    _breaker_check()
    _rate_limit_check()

    with _stats_lock:
        _stats['total_calls'] += 1

    token, instance = get_auth()
    url_path = _versioned_path(path)
    headers = kwargs.pop('headers', {}) or {}
    headers.setdefault('Authorization', f'Bearer {token}')
    headers.setdefault('Content-Type', 'application/json')
    timeout = kwargs.pop('timeout', TIMEOUT_DEFAULT)

    method_name = method.lower()
    request_fn = getattr(_session, method_name)

    for attempt in range(_retries):
        try:
            _t0 = _time.time()
            resp = _http(
                request_fn,
                f'{instance}{url_path}',
                headers=headers,
                timeout=timeout,
                **kwargs,
            )
            _elapsed = _time.time() - _t0
            if _elapsed > 5:
                _record_slow_query('REST', _elapsed, url_path)
                log.warning(f"Slow SF REST {method.upper()} ({_elapsed:.1f}s): {url_path[:140]}")
        except requests.exceptions.Timeout:
            if attempt < _retries - 1:
                _time.sleep(2 ** attempt)
                continue
            _breaker_failure()
            _record_error(f"SF REST {method.upper()} timed out after retries", url_path)
            raise RuntimeError(f"SF REST {method.upper()} timed out after retries")
        except requests.exceptions.ConnectionError as ce:
            if attempt < _retries - 1:
                _time.sleep(2 ** attempt)
                continue
            _breaker_failure()
            _record_error(f"SF REST {method.upper()} connection failed: {ce}", url_path)
            raise RuntimeError(f"SF REST {method.upper()} connection failed after retries")

        if resp.status_code in (500, 502, 503):
            if attempt < _retries - 1:
                _time.sleep(2 ** attempt)
                continue
            _breaker_failure()
            _record_error(f"SF REST server error {resp.status_code} after {_retries} retries", url_path)
            raise RuntimeError(f"SF REST server error {resp.status_code} after {_retries} retries")
        break

    result = resp.json()
    code = _error_code(result)
    if code == 'REQUEST_LIMIT_EXCEEDED':
        _limit_exceeded(f'SF REST {method.upper()}', url_path)
    if resp.status_code == 401 or 'INVALID_SESSION' in code.upper():       # expired token: log in again, once
        token, instance = refresh_auth(headers['Authorization'].removeprefix('Bearer '))
        headers['Authorization'] = f'Bearer {token}'
        _rate_limit_check()
        resp = _http(request_fn, f'{instance}{url_path}', headers=headers, timeout=timeout, **kwargs)
        result = resp.json()
        code = _error_code(result)
        if code == 'REQUEST_LIMIT_EXCEEDED':
            _limit_exceeded(f'SF REST {method.upper()}', url_path)

    if code:
        # Salesforce answered, so it is up: a rejected request (bad field, no access...) is not an outage
        _breaker_success()
        _record_error(f"SF REST error: {result}", url_path)
        raise RuntimeError(f"SF REST error: {result}")

    _breaker_success()
    return result


def sf_rest_get(path: str, params: dict | None = None, **kwargs) -> dict | list:
    return _sf_rest_request('GET', path, params=params or {}, **kwargs)


def sf_rest_post(path: str, body: dict | None = None, **kwargs) -> dict | list:
    return _sf_rest_request('POST', path, json=body or {}, **kwargs)


def sf_composite_batch(batch_requests: list[dict], halt_on_error: bool = False) -> dict:
    body = {
        'haltOnError': halt_on_error,
        'batchRequests': batch_requests,
    }
    result = sf_rest_post('/composite/batch', body=body)
    if not isinstance(result, dict):
        raise RuntimeError(f"SF composite batch returned non-object response: {result}")
    return result


COMPOSITE_MAX_QUERIES = 5       # Salesforce allows 5 query subrequests in one /composite request
_COMPOSITE_REF = re.compile(r'@\{[^}]+\}')


def _composite_url(soql: str) -> str:
    """URL-encode the SOQL but leave any @{ref.records[0].Id} raw: an encoded reference is not substituted and
    Salesforce answers INVALID_QUERY_FILTER_OPERATOR."""
    parts = _COMPOSITE_REF.split(soql)
    refs = _COMPOSITE_REF.findall(soql)
    out = quote(parts[0], safe='')
    for ref, part in zip(refs, parts[1:]):
        out += ref + quote(part, safe='')
    return f'/services/data/{SF_API_VERSION}/query?q={out}'


def sf_composite_query(named: dict[str, str]) -> dict[str, dict]:
    """Run up to 5 SOQL queries in ONE request (one API call). Later queries may reference earlier ones by key,
    e.g. @{wo.records[0].Id}. Returns {key: {'status': int, 'body': ...}}; a failed subrequest does not fail the
    others (allOrNone false), so the caller checks each status."""
    if not named:
        return {}
    if len(named) > COMPOSITE_MAX_QUERIES:
        raise ValueError(f'A composite request holds at most {COMPOSITE_MAX_QUERIES} queries, got {len(named)}')
    body = {'allOrNone': False,
            'compositeRequest': [{'method': 'GET', 'url': _composite_url(soql), 'referenceId': key}
                                 for key, soql in named.items()]}
    result = sf_rest_post('/composite', body=body, timeout=TIMEOUT_LONG)
    if not isinstance(result, dict) or 'compositeResponse' not in result:
        raise RuntimeError(f"SF composite returned an unexpected response: {str(result)[:200]}")
    return {r['referenceId']: {'status': r['httpStatusCode'], 'body': r['body']} for r in result['compositeResponse']}


def sf_query_explain(soql: str) -> dict:
    result = sf_rest_get('/query', params={'explain': soql})
    if not isinstance(result, dict):
        raise RuntimeError(f"SF query explain returned non-object response: {result}")
    return result


def sf_graphql(query: str, variables: dict | None = None, operation_name: str | None = None) -> dict:
    body = {'query': query}
    if variables is not None:
        body['variables'] = variables
    if operation_name:
        body['operationName'] = operation_name
    result = sf_rest_post('/graphql', body=body)
    if not isinstance(result, dict):
        raise RuntimeError(f"SF GraphQL returned non-object response: {result}")
    return result


# ── Query ───────────────────────────────────────────────────────────────────

def sf_query(soql: str, _retries: int = 2, timeout=None) -> dict:
    timeout = timeout or TIMEOUT_DEFAULT
    # Gate 1: circuit breaker
    _breaker_check()
    # Gate 2: rate limiter
    _rate_limit_check()

    with _stats_lock:
        _stats['total_calls'] += 1

    token, instance = get_auth()
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    url = f'/services/data/{SF_API_VERSION}/query'

    for attempt in range(_retries):
        try:
            _t0 = _time.time()
            r = _http(_session.get, f'{instance}{url}', headers=headers, params={'q': soql}, timeout=timeout)
            _elapsed = _time.time() - _t0
            if _elapsed > 5:
                _record_slow_query('SOQL', _elapsed, soql)
                log.warning(f"Slow SOQL ({_elapsed:.1f}s): {soql[:120]}")
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
        break

    result = r.json()
    code = _error_code(result)
    if code == 'REQUEST_LIMIT_EXCEEDED':
        _limit_exceeded('SF query', soql[:100])
    if r.status_code == 401 or 'INVALID_SESSION' in code.upper():           # expired token: log in again, once
        token, instance = refresh_auth(token)
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        _rate_limit_check()
        r = _http(_session.get, f'{instance}{url}', headers=headers, params={'q': soql}, timeout=timeout)
        result = r.json()
        code = _error_code(result)
        if code == 'REQUEST_LIMIT_EXCEEDED':
            _limit_exceeded('SF query', soql[:100])
    if code or isinstance(result, list):
        # Salesforce answered, so it is up: a rejected query (bad field, malformed SOQL...) is not an outage
        _breaker_success()
        if isinstance(result, list):
            _record_error(f"SF query error: {result}", soql)
            raise RuntimeError(f"SF query error: {result}")
        _record_error(f"SF error: {result.get('message', result)}", soql)
        raise RuntimeError(f"SF error: {result.get('message', result)}")

    # Success — reset breaker
    _breaker_success()
    return result


def sf_parallel(**fns) -> dict:
    """Run multiple functions in parallel. Returns {name: result}."""
    import concurrent.futures
    _t0 = _time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        # each thread runs in a copy of this context, so its Salesforce requests are counted for the same endpoint
        futures = {name: pool.submit(contextvars.copy_context().run, fn) for name, fn in fns.items()}
        results = {name: fut.result() for name, fut in futures.items()}
    _elapsed = _time.time() - _t0
    log.info(f"sf_parallel({', '.join(fns.keys())}) completed in {_elapsed:.1f}s")
    return results


# ── Shared reads (dashboards) ────────────────────────────────────────────────
# The dashboards (Command Center, Ops Brief, Scheduler Insights, Ops Territories) each read the same Salesforce data:
# truck logins four times, garage membership and drivers three or four times, today's appointments five times.
# A shared read makes identical queries made within `ttl` seconds, by different screens, cost ONE Salesforce read.
_shared: dict = {}
_shared_locks: dict = {}
_shared_guard = threading.Lock()
_SHARED_MAX = 300


def sf_query_all_shared(soql: str, ttl: int = 300) -> list[dict]:
    """sf_query_all for dashboards: identical queries within `ttl` seconds share one read (results may be up to `ttl`
    seconds old). Every caller gets its own private copy, so one screen can never alter another's data.
    A failed read is not remembered. Single-flight: concurrent identical queries wait for one read."""
    with _shared_guard:
        hit = _shared.get(soql)
        if hit and hit['expires'] > _time.time():
            with _stats_lock:
                _stats['shared_hits'] = _stats.get('shared_hits', 0) + 1
            return copy.deepcopy(hit['rows'])
        lock = _shared_locks.setdefault(soql, threading.Lock())
    with lock:
        with _shared_guard:
            hit = _shared.get(soql)
            if hit and hit['expires'] > _time.time():              # another thread just read it while we waited
                with _stats_lock:
                    _stats['shared_hits'] = _stats.get('shared_hits', 0) + 1
                return copy.deepcopy(hit['rows'])
        rows = sf_query_all(soql)
        with _shared_guard:
            _shared[soql] = {'rows': rows, 'expires': _time.time() + ttl}
            if len(_shared) > _SHARED_MAX:                          # drop what has expired, then the oldest
                for k in [k for k, v in _shared.items() if v['expires'] <= _time.time()] or [min(_shared, key=lambda k: _shared[k]['expires'])]:
                    _shared.pop(k, None)
                    _shared_locks.pop(k, None)
        return copy.deepcopy(rows)


ROW_WARN = 50_000      # a result this big is logged: it is almost certainly a missing filter


def sf_query_all(soql: str, timeout=None, max_records: int | None = None) -> list[dict]:
    """All rows of a query, following result pages. `max_records` (optional) stops early and returns that many rows
    with a log warning, so one runaway query cannot pull the whole table."""
    timeout = timeout or TIMEOUT_DEFAULT
    result = sf_query(soql, timeout=timeout)
    if isinstance(result, list) or 'records' not in result:
        return []
    records = result.get('records', [])
    token, instance = get_auth()
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    page = 1
    while not result.get('done', True) and result.get('nextRecordsUrl'):
        if max_records and len(records) >= max_records:
            log.warning(f"SOQL stopped at max_records={max_records} (more rows exist): {soql[:120]}")
            break
        page += 1
        with _stats_lock:
            _stats['pages'] = _stats.get('pages', 0) + 1     # every extra result page is another Salesforce API request
        _rate_limit_check()  # Each page counts against rate limit
        for attempt in range(2):
            try:
                _t0 = _time.time()
                resp = _http(_session.get, f'{instance}{result["nextRecordsUrl"]}', headers=headers, timeout=timeout)
                _elapsed = _time.time() - _t0
                if _elapsed > 5:
                    _record_slow_query('SOQL pagination', _elapsed, soql)
                    log.warning(f"Slow SOQL pagination p{page} ({_elapsed:.1f}s): {soql[:120]}")
                result = resp.json()
                if _error_code(result) == 'REQUEST_LIMIT_EXCEEDED':
                    _limit_exceeded('SF query page', soql[:100])
                _breaker_success()
                break
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                if attempt < 1:
                    _time.sleep(2 ** attempt)       # a timeout is not an expired login: no new login, just try the page again
                    continue
                # Only count after all retries exhausted
                _breaker_failure()
                raise
        if isinstance(result, list) or 'records' not in result:
            break
        records.extend(result.get('records', []))
    if max_records and len(records) > max_records:
        records = records[:max_records]
    if len(records) >= ROW_WARN:
        log.warning(f"SOQL returned {len(records)} rows (over {ROW_WARN}): {soql[:120]}")
    return records


def get_towbook_on_location(sa_ids: list[str], created: dict | None = None) -> dict[str, str]:
    """Fetch real arrival timestamps for Towbook SAs from ServiceAppointmentHistory.

    Towbook ActualStartTime is a fake future estimate. The REAL arrival is the
    CreatedDate of the history row where Status changed to 'On Location'.

    Args:
        sa_ids: List of ServiceAppointment IDs (Towbook SAs only)
        created: optional {sa_id: CreatedDate}. When given, the dashboards' shared history copy answers (no per-batch
                 Salesforce queries); without it, the original direct lookup is used.

    Returns:
        Dict mapping SA ID -> ISO datetime string of 'On Location' timestamp
    """
    if not sa_ids:
        return {}

    result = {}
    if created is not None:
        import sa_history
        for r in sa_history.rows_for('Status', sa_ids, created):          # oldest first per appointment
            if r.get('NewValue') == 'On Location' and r['ServiceAppointmentId'] not in result:
                result[r['ServiceAppointmentId']] = r['CreatedDate']      # first On Location wins
        return result
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
