# Operational DB Evaluation — Optimizer Store Migration

**Date:** 2026-04-30  **Author:** Architect  **Status:** Decision-grade, awaiting provisioning approval

## TL;DR

**Recommendation: Azure PostgreSQL Flexible Server, Burstable B2s, 64 GB Premium SSD v2.**
~$32/mo all-in. Replaces DuckDB for the optimizer store (`opt_runs`, `opt_sa_decisions`, `opt_driver_verdicts`, `opt_resources`, `opt_blob_audit`, `opt_sync_errors`).

## Why Postgres, not the others

The workload is **mixed OLTP + light OLAP on relational data with constant 1-writer / N-reader contention**. Concretely:
- Strong relational joins: `opt_sa_decisions ⋈ opt_driver_verdicts ⋈ opt_runs` everywhere in `routers/optimizer.py` (run health, driver day, unscheduled analysis).
- `FILTER (WHERE …)` aggregates, `INTERVAL` arithmetic, parameterized `?` queries — all standard ANSI SQL.
- Continuous tiny upserts (~5K verdicts / ~30s) interleaved with continuous reads — exactly MVCC's sweet spot.

**Cosmos DB (Mongo vCore or NoSQL):** wrong shape. Every read joins three collections; that means client-side joins or denormalized duplication of the 5.7M-row verdict set. RU/s pricing on a 290-runs/day write loop pushes cost past budget, and there is no `FILTER` clause or window functions. Eliminated.

**Azure SQL Database (serverless):** technically capable, but (a) auto-pause cold-starts (5–60s) will wedge the 30s blob-sync poll and timeout API requests, (b) T-SQL dialect forces rewriting `FILTER`, `INTERVAL '7 days'`, `now()`, and `INSERT OR REPLACE` to MERGE/`IF EXISTS`, and (c) the cheapest serverless config that won't cold-start (always-on min vCore=0.5) lands at ~$45/mo — same envelope as Postgres but with worse dialect compatibility. Postgres wins on dialect parity and ecosystem (psycopg, asyncpg, pg_dump).

**Postgres fits because:** MVCC kills the single-writer lock pain immediately; psycopg connection pool gives us real concurrent reader/writer separation; `INSERT … ON CONFLICT DO UPDATE`, `FILTER`, `INTERVAL`, `now()`, partial indexes all map 1:1 from current code.

## Schema migration — DuckDB-isms to fix

| DuckDB construct                              | Postgres replacement                          |
|-----------------------------------------------|-----------------------------------------------|
| `INSERT OR REPLACE INTO t(...) VALUES (...)`  | `INSERT INTO t(...) VALUES(...) ON CONFLICT (id) DO UPDATE SET col=EXCLUDED.col, ...` |
| `INSERT OR IGNORE`                            | `INSERT … ON CONFLICT (id) DO NOTHING`        |
| `TIMESTAMP DEFAULT now()`                     | unchanged (`TIMESTAMPTZ DEFAULT now()` preferred) |
| `INTERVAL '7 days'` (string-built f-string)   | `INTERVAL '7 days'` works; switch to `now() - make_interval(days => %s)` for parameter safety |
| `COUNT(*) FILTER (WHERE …)`                   | unchanged — Postgres supports `FILTER` natively |
| `ALTER TABLE … ADD COLUMN IF NOT EXISTS`      | unchanged in PG ≥ 9.6                          |
| `cursor.rowcount` (returns -1 for empty DELETE) | PG returns 0 — drop the `max(0, n)` guard   |
| `lower(col) LIKE lower(?)`                    | unchanged; consider `ILIKE` + `pg_trgm` index |
| `duckdb.IOException` lock retry               | **delete entirely** — replaced by pool         |

All five tables become straight DDL with `id TEXT PRIMARY KEY`, `run_at TIMESTAMPTZ NOT NULL`. Keep all existing indexes; add `(run_id, sa_id)` composite on `opt_driver_verdicts` (the join key) and `BRIN(run_at)` on the verdicts table — BRIN is ~kilobytes for 5.7M rows of monotonic timestamps and accelerates the `now() - INTERVAL` filters.

## One-shot ETL plan

1. Provision Postgres, run DDL + indexes (no FK constraints initially — load faster).
2. From the dev box: `duckdb -c "COPY opt_runs TO '/tmp/runs.csv' (HEADER, DELIMITER ',')"` for each table.
3. `psql \copy opt_runs FROM '/tmp/runs.csv' CSV HEADER` — Postgres `COPY` ingests CSV at 100–250K rows/sec on B2s. **5.7 M verdicts ≈ 30–60 seconds**, all five tables under 5 minutes wall-clock.
4. `ANALYZE` every table.
5. Add FKs and any deferred indexes.

**Downtime:** ~5 minutes. Stop the blob-sync thread, dump+load, flip env var, restart uvicorn. Blob audit table preserves idempotency, so any runs that arrive during the window simply get picked up on next poll — no data loss.

## Connection pooling

Use **psycopg3 + `psycopg_pool.ConnectionPool`** (sync) or `AsyncConnectionPool`.

- **Writer pool** (blob sync thread): `min_size=1, max_size=2, timeout=10`. One connection held for the duration of one parse-pass batch; explicit `BEGIN; …; COMMIT;` per run.
- **Reader pool** (FastAPI): `min_size=2, max_size=10, timeout=5`. One connection per request, returned on response. Set `default_transaction_read_only=on` on this pool.
- Server settings: `statement_timeout=30s`, `idle_in_transaction_session_timeout=60s`, `tcp_keepalives_idle=60`.
- B2s caps at ~85 concurrent connections; 12 total leaves huge headroom and survives a future scale-up to 4 uvicorn workers.

## Cutover

**Hard cutover, no dual-write.** Dual-writing across DuckDB + Postgres doubles the parser failure surface for zero benefit — the blob audit table is the source of truth for idempotency. Plan:

1. T-0: deploy Postgres-aware code path behind `OPT_DB_BACKEND=duckdb` (default). Verify in dev.
2. T+1d: dev cutover. Run for 24 h, diff `/api/optimizer/stats` counts vs DuckDB.
3. T+2d: prod cutover during low-traffic window (Sunday 06:00 ET): stop sync thread, dump/load, flip `OPT_DB_BACKEND=postgres`, restart, verify.
4. **Rollback:** revert env var + restart. DuckDB file is not deleted for 30 days; opt_blob_audit re-runs anything that arrived in between.

## Cost (East US 2, retail, May 2026)

| Component                                         | Monthly |
|---------------------------------------------------|---------|
| Postgres Flexible Server, Burstable B2s (2 vCore, 4 GB) | $24.82 |
| Premium SSD v2, 64 GB @ 3000 IOPS                 |  $5.76 |
| Backup storage (LRS, 7-day retention, ~5 GB free) |  $0.00 |
| Egress (API replies, intra-region to App Service) |  $0.00 |
| **Total**                                         | **~$31** |

Headroom: B2s sustains the workload comfortably; if CPU credits exhaust, B2ms ($49) is a one-click bump. Storage grows ~3 GB/yr at current rate; auto-grow on.

## Top 3 risks

1. **B2s CPU credit exhaustion under backfill.** The 127K-run backfill (per `optimizer_bulk_retrieval_plan.md`) bursts writes 50× normal. *Mitigation:* run backfill on B2ms, scale down to B2s after; or rate-limit the parser to ≤20 runs/min during backfill.
2. **Connection storm on multi-worker scale-up.** 4 uvicorn workers × 10-conn pool = 40 + writer = 41, still safe — but a runaway request loop could exhaust the pool. *Mitigation:* set pool `timeout=5`, surface 503 fast; add Azure Monitor alert on `connections_active > 60`.
3. **Silent dialect drift in a new query.** A future contributor writes DuckDB-only SQL (e.g., `LIST_VALUE`, `STRUCT`). *Mitigation:* keep `query_optimizer_sql` keyword denylist, add CI test that runs every helper against Postgres, retire DuckDB binary from the repo on T+30d.
