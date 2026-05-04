# Target Data Architecture — FSL Optimizer

**Date:** 2026-04-30   **Owner:** nlaaroubi   **Status:** Decision-grade, awaiting approval

> Synthesis of three sub-evaluations — read this first. Detail in:
> - [`2026-04-30-operational-db-evaluation.md`](./2026-04-30-operational-db-evaluation.md) — DB layer
> - [`2026-04-30-caching-strategy.md`](./2026-04-30-caching-strategy.md) — cache layer
> - [`2026-04-30-rag-vector-layer.md`](./2026-04-30-rag-vector-layer.md) — vector / RAG layer

## TL;DR

Replace the single-file DuckDB store with a layered, Azure-native data tier. **One Postgres instance hosts both relational data and vectors. Redis fronts the hot read paths. Embedding-backed chat is built on top of the same Postgres.**

| Layer | Service | Purpose | Monthly cost |
|---|---|---|---|
| **Operational store** | Azure Postgres Flexible Server, Burstable B2s + 64 GB Premium SSD v2 | Replaces DuckDB. MVCC, real reader/writer separation. | **$31** |
| **Cache** | Azure Cache for Redis Basic C0 | Cross-worker shared cache for the 3 hottest endpoints. | **$16** |
| **Vector / RAG** | `pgvector` extension inside the same Postgres | Per-SA narrative search for the AI chat. No new service. | **$5** (embeddings) |
| **JSON file storage** | Azure Blob (existing `fslappopt`) | Raw FSL request/response payloads. Unchanged. | already paid |
| **LLM** | Azure OpenAI (existing) | Embeddings + chat completions. | usage-based |
| **Total durable data tier** | | | **~$52 / mo** |

This stays inside your $15–50/mo per-layer ceiling, eliminates the recurring DuckDB pain, and unlocks the RAG capability you flagged — without spinning up Azure AI Search ($74/mo) or Cosmos ($100+/mo).

## Why these three together

Each layer is justified on its own (see sub-docs), but the combined choice is more than additive:

- **Postgres + pgvector in one DB** → one connection pool, one auth path, one backup, one DR plan. Vector queries can pre-filter by `run_id` / `territory` using the same indexes the rest of the app already uses. AI Search and Cosmos vector both bring a separate auth + network surface for marginal capability we don't need at 90K vectors.
- **Redis as the only cache tier** → the hybrid (Redis + matviews + in-process) was rejected because three failure modes for a single engineer is a maintenance trap. Redis is the only choice that survives multi-worker uvicorn (the blob-sync loop runs in *one* worker; the others must invalidate via a shared coordinator).
- **All three phase independently** → if Phase 2 (cache) or Phase 3 (RAG) slips, Phase 1 (DB) still delivers stability today.

## Phased migration plan

```
Week 1                Week 2-3              Week 4+
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ P1: Postgres │ ──▶ │ P2: Redis    │ ──▶ │ P3: RAG      │
│ ~3-5 days    │     │ ~2 days      │     │ ~5-7 days    │
└──────────────┘     └──────────────┘     └──────────────┘
   $31 / mo            +$16 / mo            +$5 / mo
```

### Phase 1 — Postgres cutover (week 1, blocking)

**Days 1–2 (provisioning + code path):**
- Provision Postgres Flexible B2s + 64 GB Premium SSD v2 in same region as the App Service
- Wire `OPT_DB_BACKEND` env var (default `duckdb`); add `psycopg3 + ConnectionPool` writer (size 1–2) and reader (size 2–10) pools
- Translate every DuckDB-ism: `INSERT OR REPLACE` → `INSERT … ON CONFLICT DO UPDATE`, drop the lock-retry loop, BRIN index on `opt_driver_verdicts(run_at)`

**Day 3 (dev cutover + 24h soak):**
- Stop blob-sync, `COPY` 5.7M-row verdicts CSV → Postgres (~30–60s on B2s), `ANALYZE`, flip env var, restart
- Verify `/api/optimizer/stats` counts match DuckDB exactly
- Let it run 24h; diff blob_audit + decisions counts

**Day 4–5 (prod cutover during Sunday low-traffic window):**
- Same dump/load. ~5 min downtime. Rollback = revert env var.
- Keep the `.duckdb` file 30 days, then delete.

**Top risk:** B2s CPU credit exhaustion if the 127K-run optimizer backfill runs immediately after cutover. *Mitigation:* delay backfill until 48h after cutover, OR temporarily bump to B2ms ($49) during backfill.

### Phase 2 — Redis cache (week 2-3, non-blocking)

**Day 1 (provisioning + cache module):**
- Provision Azure Redis Basic C0 (~$16/mo)
- Add `cache.py` (~80 lines, `redis-py` wrapper with try/except returning miss on failure)
- Add `REDIS_URL` env var; cache disabled if unset (zero-code rollback)

**Day 2 (cache hookup):**
- Wrap the 3 hot endpoints: `/files?date=` (60s TTL), `/runs/{id}/health` (1h TTL), `/runs/{id}` (1h TTL)
- Add invalidation hook in `optimizer_blob_sync.process_run()` after a successful insert — `delete_many(health:{run_id}, run_detail:{run_id}, files:list:{date}, runs:list:*)`
- Optional add `/sa/{sa_number}` (5 min) and `/patterns` (5 min) for chat tool calls

**Total code change:** ~120 LOC, no frontend changes, no dependency on Phase 1 (works with DuckDB or Postgres).

**Top risk:** stale data if `delete_many` fails after `process_run` succeeds. *Mitigation:* TTLs cap staleness even on missed invalidation (60s on volatile keys). Already inside your 1-min freshness SLA.

### Phase 3 — pgvector RAG (week 4+, after Phase 1 lands)

**Days 1–2 (parser extension):**
- Extend `optimizer_parser.parse_run()` to emit a per-SA narrative string ("Run X · SA-Y → Scheduled. Winner …. 47 eligible; runner-up 1.4mi farther. Excluded: 8 territory, 3 skill …")
- Bump `PARSER_VERSION` → triggers full re-parse of 1,800 existing runs

**Days 3–4 (embedding pipeline):**
- New `opt_narratives(run_id, sa_id, narrative, embedding vector(1536), …)` table with HNSW index on `embedding` and B-tree on `(run_id, territory)` for pre-filter
- After DuckDB/Postgres insert succeeds in `process_run`, batch-embed new narratives via Azure OpenAI `text-embedding-3-small` ($0.02/MTok) and INSERT
- Embedding errors mark `opt_blob_audit.status = 'embed_error'` and retry on next sync pass — *not* on the critical path

**Days 5–7 (chat integration):**
- Add ONE new tool `search_run_narratives` to `_TOOLS` in `routers/optimizer_chat.py`
- No system prompt rewrite — the LLM already routes by tool name; this is the 11th tool alongside the 10 existing structured tools
- Frontend: zero changes

**Steady-state cost:** ~$1.75/mo embeddings + <$0.10/mo query embeddings + storage included in Postgres tier = **~$5/mo**.

**Top risk:** parser-version bump triggers full re-embed ($0.36 one-time, trivial). Other risk: per-SA narrative quality — recommendation is to start with a tight template and iterate based on actual chat queries.

## Cross-cutting considerations

- **Connection model:** Phase 1 introduces psycopg3 pools. Phase 3 reuses the same pools for vector queries — no second connection layer. Multi-worker uvicorn rollout (currently 1 worker) is unblocked from this point.
- **Backup / DR:** Postgres Flexible has built-in 7-day PITR (free). Redis Basic has none — but cache loss = slow request, not data loss. Acceptable.
- **Observability:** add Azure Monitor alerts for Postgres `connections_active > 60`, Redis `evicted_keys > 0`, blob_sync `runs_failed > 0` over 30 min. All three new alerts in one Bicep file.
- **Cost ceiling:** $52/mo is the full bill at current scale. Headroom for 10× growth before B2s → B2ms (+$24) or Redis Basic → Standard (+$24) is needed. Not budget-driven decisions for >12 months.

## Decision points needing approval

Before Phase 1 starts:
1. **Region:** confirm East US 2 (matches the existing App Service)
2. **Authentication:** managed identity vs. password? Recommend managed identity for App Service → Postgres; password for local dev only.
3. **Backup retention:** 7-day PITR (free) vs. 14-day vs. 30-day. Recommend 7-day — restore-from-blob is the actual DR path; PITR is for "oops I dropped a table."
4. **VNet / private endpoint:** required by your security policy? If yes, +1 day to Phase 1 for Bicep wiring.
5. **OK to spin up B2s + Redis Basic C0 simultaneously, or stage Phase 2 a week later?**

Once those are approved, I can:
- Write the Bicep / Azure CLI provisioning script
- Write the new `optimizer_db_pg.py` (mirrors the current `optimizer_db.py` API surface)
- Build the cutover runbook

## What this doesn't fix

The **extractor lag** (FSL Cloud → Azure Blob, currently 3–4h behind real-time) is upstream of all three layers. None of this work changes that. It's a separate problem track:

- Short term: continuous extractor cron (every hour vs. every 4h)
- Medium term: parallelize Playwright workers (one per territory)
- Long term: drop Playwright by hitting FSL ContentVersion REST directly if/when that path becomes reliable

Flagging it so it doesn't get conflated with this migration.

---

**Recommended next step:** approve the 5 decision points above, then I write the provisioning Bicep + `optimizer_db_pg.py` and run them past you before any Azure resource is created.
