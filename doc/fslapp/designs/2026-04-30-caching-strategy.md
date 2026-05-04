# Optimizer Caching Strategy

**Date:** 2026-04-30
**Author:** Architecture review
**Status:** Decision

---

## Recommendation

**Azure Cache for Redis Basic C0 (~$16/mo)** as the single shared cache tier. Keep SF lookups (`_RESOURCE_NAMES` etc.) where they are — in-process, 1h TTL — they're fine and cross-worker drift on driver-name lookups is harmless.

One tier, one failure mode, one place to reason about freshness. The hybrid is the seductive wrong answer for a single engineer with a 1-minute freshness budget.

## Why not the others

- **(2) Postgres materialized views** presumes the Postgres migration lands. The brief requires "works with DuckDB OR Postgres." DuckDB has no first-class refresh-on-event materialized view, and adding one would be the wrong primitive anyway — runs are immutable after `process_run()`, so we want "cache forever, invalidate on event," not "recompute periodically."
- **(3) In-process LRU only** breaks the moment we scale to 4 uvicorn workers. The blob-sync `_loop()` runs in exactly one worker. The other three have no invalidation signal. Setting a 30s TTL to compensate means four workers each recompute the 1.5–2s health query every 30s — we'd amplify DB load, not reduce it. Cross-process invalidation needs an external coordinator. That coordinator is Redis.
- **(4) Hybrid** triples the operational surface (Redis + matviews + in-proc) for a workload of 5–10 dispatchers. Three failure modes, three invalidation paths, one engineer. No.

## What to cache

| Endpoint | Key | TTL | Why |
|---|---|---|---|
| `GET /api/optimizer/files?date=…` | `files:list:{date}` | 60s | 2.4s with 16-worker blob fan-out, continuously polled, hottest absolute savings. 60s is well under the 1-min freshness budget; invalidated explicitly on new run. |
| `GET /api/optimizer/runs/{run_id}/health` | `health:{run_id}` | 1 hour | 0.5–2s join across 5.7M-row `opt_driver_verdicts`. **Immutable** once parsed — TTL is just a memory-safety backstop. |
| `GET /api/optimizer/runs/{run_id}` (get_run_detail) | `run_detail:{run_id}` | 1 hour | Heavy joins, immutable. Same reasoning. |
| `GET /api/optimizer/runs?from&to&territory` | `runs:list:{from}:{to}:{territory}` | 30s | Cheap query, frequent poll. Nice-to-have. Short TTL because the `to=now()` window keeps changing. |
| `GET /api/optimizer/sa/{sa_number}` | `sa:{sa_number}:{run_id\|all}` | 5 min | Per-SA decision tree. Slightly stale acceptable; chat tool calls hit this hard. |
| `GET /api/optimizer/patterns?territory&days` | `patterns:{territory}:{days}` | 5 min | Aggregation across days, used by chat. |
| SF lookups (Resource/Skill/Territory names) | (in-process, unchanged) | 1h | Already in-process. ID→Name doesn't drift meaningfully and only the sync worker writes them. Moving to Redis adds zero value. |

## Invalidation strategy

One hook, in `optimizer_blob_sync.process_run()`, immediately after the `INSERT OR REPLACE` block and before `_mark_processed(..., 'ok')`:

```
cache.delete_many(
    f"health:{run_id}",                # belt-and-suspenders (key shouldn't exist yet)
    f"run_detail:{run_id}",            # same
    f"files:list:{run_at_date}",       # new blob exists for this date
    "runs:list:*",                     # any time-window list could now include this run
)
```

The `runs:list:*` wildcard is the only non-trivial one — implement via Redis `SCAN MATCH` then `DEL`. With 30s TTL on that key family, even a missed invalidation is bounded to 30 seconds of staleness, well inside the 1-minute SLA.

`process_run` is the **only** writer in the system. There is no other invalidation point.

## Multi-worker uvicorn

Today (1 worker) in-process LRU would technically work. At 4 workers it breaks because:

1. `optimizer_blob_sync.start()` spawns a thread inside whichever worker process calls it at startup. The other three workers never see the parsed run except via DuckDB. They have no in-process cache to invalidate even if we wanted them to.
2. Therefore in-process TTLs must be short enough that drift is invisible (≤30s on a 1.5s query) — which negates most of the cache benefit.

Redis is the cheapest answer because it makes the cache *worker-agnostic*: any worker writes, any worker reads, the sync worker invalidates, everybody sees fresh data.

**Side note (worth fixing separately):** with 4 workers, `optimizer_blob_sync.start()` will run in all four. The `opt_blob_audit` PK prevents duplicate ingest, but we waste 3× blob LIST calls every 30s. Fix by gating `start()` on a worker-id check or moving the loop to a separate process. Not part of this caching decision but flagging it.

## Code change footprint

- **New file `cache.py`** (~80 lines): thin `redis-py` wrapper exposing `get_json(key)`, `set_json(key, value, ttl)`, `delete_many(*keys)`, `delete_pattern(pattern)`. All calls wrapped in `try/except` — Redis failure logs and returns `None` (cache miss), never raises.
- **3–4 endpoints in `routers/optimizer.py`** (~5 lines each): standard `cached = cache.get_json(key); if cached: return cached; result = …; cache.set_json(key, result, ttl); return result`.
- **One hook in `optimizer_blob_sync.process_run`** (~5 lines): the `delete_many` block above.
- **`requirements.txt`**: add `redis>=5.0`.
- **`main.py`**: read `REDIS_URL` env var on startup, log connectivity once.

Total: ~120 LOC. No new files except `cache.py`. No frontend changes.

## Cost

- **Azure Redis Basic C0** — 250MB, single node, no SLA — **~$16/mo**. Fits budget. Sufficient for 5–10 users and the key set above (cache footprint will be measured in single-digit MB).
- C1 ($55/mo, 1GB) is unnecessary — we don't need the memory and Basic doesn't have HA at any size.
- **Standard C0** (~$40/mo) gets you a replica + 99.9% SLA. **Defer to Phase 2** if/when dispatchers complain about cold-cache slowness during Redis maintenance windows. Cache loss = slow request, not data loss, so HA is not load-bearing.

## Risk and rollback

**Failure mode if Redis is down:** every cache call returns `None` (miss) inside the `try/except`. Endpoints fall through to DuckDB/Blob. Latency goes back to baseline (worst case: `/api/optimizer/files` at 2.4s, `/health` at 1.5s). No data corruption, no errors surfaced to users. Frontend is unaffected.

**Rollback:** delete the `REDIS_URL` env var. The wrapper treats unset URL as "cache disabled" and every call short-circuits to a miss. Zero code change to disable.

**Data correctness risk:** the only way to serve stale data is if `process_run` succeeds but the `delete_many` call fails. Mitigation: TTLs on every key (max 1h on immutable keys, 60s on volatile ones) bound staleness to the TTL even in the worst case. The 1-min freshness SLA is met by the 60s `files:list` TTL alone.

## Phase 2 (not now)

- Upgrade to Standard C0 if HA matters.
- Move SF lookups to Redis only if we go multi-process for the sync worker.
- Replace the `runs:list:*` wildcard with key-tagging if Redis SCAN cost becomes measurable (it won't at this scale).
