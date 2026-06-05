# API Performance Baseline - 2026-06-05

Branch: `feature/v65-salesforce-api-performance`

Rollback tag: `baseline-v65-before-api-enhancements-2026-06-05`

Baseline commits:

- `2fc8547 chore: baseline Salesforce API v65 migration`
- `f12cfe4 chore: preserve Summer 26 migration PDF`

## Environment

- Base URL: `http://127.0.0.1:8000`
- Salesforce instance: `https://aaawcny.my.salesforce.com`
- Configured Salesforce API version: `v65.0`
- Production org supported versions observed before baseline: up to `66.0`, including `65.0`

## Quality Gate Before Baseline

- `git diff --check`: passed
- `python3 -m pytest backend/tests/test_system_health.py backend/tests/test_utils.py`: 33 passed, 1 warning
- `GET /api/health`: 200, Salesforce errors 0, breaker open false
- Secret scan of generated PDF strings: no `password=`, `securityToken=`, `consumerSecret=`, `SF_PASSWORD`, `SF_SECURITY_TOKEN`, long hex secret, or `3MVG` pattern found

## Before Metrics

Collected at `2026-06-05T14:04:13-0400`.

| Endpoint | Method | Repeats | Status | Avg seconds | Min seconds | Max seconds | SF call delta | SF error delta | Bytes |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `/api/health` | GET | 3 | 200,200,200 | 0.233 | 0.222 | 0.247 | 0 | 0 | 344 |
| `/api/garages` | GET | 3 | 200,200,200 | 0.018 | 0.013 | 0.022 | 0 | 0 | 25147 |
| `/api/live-dispatch` | GET | 3 | 200,200,200 | 0.048 | 0.042 | 0.052 | 0 | 0 | 169034 |
| `/api/data-quality` | GET | 3 | 200,200,200 | 0.013 | 0.011 | 0.015 | 0 | 0 | 7686 |
| `/api/data-quality/refresh` | POST | 1 | 200 | 34.652 | 34.652 | 34.652 | 16 | 0 | 7686 |

Salesforce health at start:

```json
{
  "total_calls": 12387,
  "errors": 0,
  "breaker_open": false,
  "calls_last_60s": 137,
  "rate_limit": 300
}
```

Salesforce health at end:

```json
{
  "total_calls": 12403,
  "errors": 0,
  "breaker_open": false,
  "calls_last_60s": 76,
  "rate_limit": 300
}
```

## First Optimization Target

`POST /api/data-quality/refresh` is the first target because it is a cold-cache path with 16 Salesforce calls and 34.652 seconds of observed latency. Cached endpoints are already fast and should not be optimized first.
