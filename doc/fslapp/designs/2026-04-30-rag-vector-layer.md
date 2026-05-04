# RAG / Vector Layer for Optimizer Chat

**Date:** 2026-04-30   **Owner:** nlaaroubi   **Status:** Decision

## TL;DR

Use **pgvector inside the Azure Postgres Flexible Server we are already migrating to**. Index **per-SA narratives** synthesized by `optimizer_parser.parse_run()`, embed with `text-embedding-3-small` (1536-d), expose via a new `search_run_narratives` tool inside the existing OpenAI/Anthropic tool-calling loop. Total cost: **< $5/mo** at current volume, well under the $25 target. No new Azure service.

User asked: *"should we get azure database service robust for RAG retrieval / JSON files"* — answer: **yes, and pgvector inside the Postgres you are already standing up is the right answer**. Do not add a separate vector service.

---

## Why pgvector — comparison

| Option | $/mo | Verdict |
|---|---|---|
| **pgvector in Postgres Flexible** | $0 marginal (already paying for Postgres) | **CHOSEN.** Co-located with metadata, one auth/backup path, single connection pool. Corpus is tiny (~90K vectors steady state) — way under pgvector's comfort zone. |
| Azure AI Search Basic | $74 | Hybrid BM25+vector is real but unneeded here. Proper-noun retrieval (driver names, SA numbers) is better served by metadata pre-filter (`WHERE run_id=…`) than BM25. Paying for a feature we don't need. |
| Cosmos DB Mongo vCore | ~$100+ (M10 floor) | Already over budget ceiling. Eliminate on cost. |

At 90K vectors, this is not a "search platform" workload. The simplest layer that ships wins.

---

## What to Index — Per-SA Narratives, NOT Raw JSON

**Reject indexing raw `request.json`.** Embedding 1.5MB chunks of `Resources[]` arrays produces semantically useless retrieval — chunks of resource records don't answer "why was driver X excluded from SA-794085."

**Index synthesized per-SA narratives** — one chunk per (run × SA decision). The parser already computes the verdicts; emit a narrative string alongside:

> *"Run 2026-04-30 14:15 WNY Fleet · SA-794085 (Battery, priority 100, scheduled 14:30) → Scheduled. Winner Ryan Nolan @ 12.3 min. 47 eligible; closest runner-up Christopher Reeves 13.7 min (1.4mi farther). Excluded: 8 territory, 3 skill (missing Battery Cert), 2 absent. Unscheduled reason: none."*

Dense (150–300 tokens), pre-filterable by `run_id`/`sa_number`/`territory`/`driver_name`/`exclusion_reason`. This fills the actual gap the structured tools leave: free-form questions about a specific decision's narrative context.

**Don't index** per-driver-per-SA verdicts (~2.7M rows, marginal value over filtered SQL). **Stretch**: per-run summaries (~1,800 docs) and a static library of work-rule/objective definitions (~50 docs).

## Chunking

Per-SA narrative **is** the chunk. No splitting, no overlap. Skip the entire 1.5MB-request-json chunking problem by indexing what we extract, not what we ingest.

## Embedding Model

**`text-embedding-3-small`** (1536-d, **$0.02 / MTok**). Beats `ada-002` on retrieval for half the price. `text-embedding-3-large` ($0.13/MTok) is 6.5× cost for ≤2pp recall lift on short narrative text — not worth it.

## Cost Model

| Bucket | Calculation | Cost |
|---|---|---|
| One-time backfill | 1,800 runs × ~50 SAs × ~200 tok = 18M tok × $0.02 | **$0.36** |
| Steady-state embeddings | 290 runs/day × 50 × 200 = 87M tok/mo × $0.02 | **$1.75/mo** |
| Query embeddings | <50 tok/q, low QPS | <$0.10/mo |
| Storage | 90K × 1536 × 4B ≈ 0.5 GB | included in Postgres tier |
| **Total** | | **< $5 / mo** |

Verify the "~50 SAs avg per run" assumption against `opt_runs.services_count` before backfill. Even at 4× (200 SAs/run) we land at ~$10/mo — still well under target.

## Query Pattern

**Vector-only with metadata pre-filter.** No hybrid BM25. The chat is usually scoped to a run (`run_context` is already in the request body), so:

```sql
SELECT narrative, sa_number, run_id, run_at, exclusion_reason
FROM opt_narratives
WHERE run_id = $1   -- or territory = $2 AND run_at > $3
ORDER BY embedding <=> $query_embedding
LIMIT 8;
```

## Integration with Existing Tool-Calling Chat

**Add ONE tool** to `_TOOLS` in `optimizer_chat.py`:

```python
{
  "name": "search_run_narratives",
  "description": "Semantic search over optimizer decision narratives. Use when the dispatcher asks open-ended 'why' or 'what happened' questions that don't map cleanly to a specific SA or driver.",
  "input_schema": {"properties": {
    "query": {"type": "string"},
    "run_id": {"type": "string"},
    "territory": {"type": "string"},
    "days": {"type": "integer"},
    "k": {"type": "integer", "default": 8}
  }, "required": ["query"]}
}
```

No system prompt rewrite. The LLM already routes by tool name — this is the 11th tool alongside the existing 10. The model picks it for fuzzy questions; structured tools (`get_sa_decision`, `find_idle_drivers`) still win for specific lookups.

## Indexing Pipeline

Extend `optimizer_parser.parse_run()` to emit `narrative` per SA decision (one extra string field per row). In `optimizer_blob_sync.process_run()`, **after** the DuckDB inserts succeed, batch-embed new narratives via Azure OpenAI (accepts up to 2048 inputs/request) and INSERT into `opt_narratives` (Postgres). 

**Embeddings are NOT on the critical path.** If embedding fails, mark `opt_blob_audit.status = 'embed_error'` and retry next sync pass. DuckDB metadata always lands first; vectors are an enhancement.

Bump `PARSER_VERSION` → triggers full re-process of 1,800 runs (already designed for this).

## Risks

1. **Postgres migration timing.** If migration slips beyond ~2 weeks, V1 should target a small standalone Postgres Flexible (`B1ms`, ~$15/mo) to unblock — fold into main DB on migration day.
2. **`Unchanged` SAs.** Parser currently skips verdicts for these. Decide: emit a brief narrative ("kept as-is, pinned/no change") or skip. Recommend brief — answers "did anything happen to SA-X" questions.
3. **Re-embedding cost on `PARSER_VERSION` bump.** $0.36 one-time per full reprocess. Trivial, but call it out so it doesn't surprise.

## V1 (smallest viable) vs Stretch

**V1 (1 week):** Per-SA narratives only. pgvector. One tool. Vector + `run_id` filter. Embeddings async via the existing blob-sync loop.

**Stretch (later):** Per-run summary docs · Static library of work-rule/objective/policy definitions · Cross-run pattern queries (*"show me runs with exclusion fingerprints similar to this one"*) · Re-rank by recency.
