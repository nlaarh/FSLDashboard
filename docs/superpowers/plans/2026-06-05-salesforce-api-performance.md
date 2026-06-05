# Salesforce API Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve FSLPulse Salesforce API speed and reliability while preserving the current working v65 baseline and proving before/after behavior.

**Architecture:** Keep `sf_client.py` as the single Salesforce API gateway, then add narrowly scoped helpers for REST composite batch, SOQL explain, and per-call timing. Convert one high-value endpoint at a time, starting with `data_quality`, because its cold refresh currently performs many independent Salesforce queries and has a measurable refresh path.

**Tech Stack:** FastAPI, Python requests, Salesforce REST API v65.0, pytest, curl-based API benchmarks, Vite/React build verification.

---

## Protected Baseline

- Baseline branch at start: `main`.
- Local baseline commits:
  - `2fc8547 chore: baseline Salesforce API v65 migration`
  - `f12cfe4 chore: preserve Summer 26 migration PDF`
- Rollback tag: `baseline-v65-before-api-enhancements-2026-06-05`
- Feature branch: `feature/v65-salesforce-api-performance`
- No push or deploy without explicit user approval.

## Task 1: Salesforce REST Helper Tests

**Files:**
- Modify: `backend/sf_client.py`
- Test: `backend/tests/test_sf_client_api_helpers.py`

- [ ] Write failing tests for URL construction and composite request body shape.
- [ ] Run `python3 -m pytest backend/tests/test_sf_client_api_helpers.py -q` and confirm the tests fail because helpers do not exist.
- [ ] Add `sf_rest_get`, `sf_rest_post`, `sf_composite_batch`, and `sf_query_explain` in `backend/sf_client.py`.
- [ ] Run the new test file and targeted existing tests.
- [ ] Commit: `feat: add Salesforce REST helper primitives`.

## Task 2: Data Quality Composite Batch

**Files:**
- Modify: `backend/routers/data_quality.py`
- Test: `backend/tests/test_data_quality_query_builders.py`

- [ ] Extract data-quality SOQL strings into named builder functions.
- [ ] Write failing tests that verify each query preserves Tow Drop-Off exclusion and expected filters.
- [ ] Implement a composite-batch fetch path for independent count/sample queries.
- [ ] Keep the existing `sf_parallel` path as a fallback behind a helper.
- [ ] Run `POST /api/data-quality/refresh` before and after; compare latency and Salesforce call count.
- [ ] Commit: `feat: use composite batch for data quality refresh`.

## Task 3: Query Plan Diagnostics

**Files:**
- Modify: `backend/sf_client.py`
- Create or modify: `backend/routers/salesforce_diagnostics.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_salesforce_diagnostics.py`

- [ ] Add tests for a safe admin-only query explain endpoint or internal helper.
- [ ] Implement query explain using Salesforce REST `explain` support.
- [ ] Add endpoint only if it follows existing auth/admin patterns.
- [ ] Verify against one `ServiceAppointment` count query.
- [ ] Commit: `feat: add Salesforce query plan diagnostics`.

## Task 4: GraphQL Capability Probe

**Files:**
- Modify: `backend/sf_client.py`
- Create: `migration/graphql_capability_probe.md`

- [ ] Add a small helper for GraphQL POST requests if supported by the org.
- [ ] Probe only read-only schema/object support for the fields needed by SA detail or live dispatch.
- [ ] Do not replace existing endpoints unless the probe proves the exact FSL objects and fields are supported.
- [ ] Record results in `migration/graphql_capability_probe.md`.

## Task 5: Pub/Sub and CDC Feasibility Gate

**Files:**
- Create: `migration/pubsub_cdc_feasibility.md`

- [ ] Verify whether Change Data Capture is enabled for `ServiceAppointment`, `AssignedResource`, and `ServiceResource`.
- [ ] If not enabled, mark setup steps as required confirmation.
- [ ] Do not add a production subscriber until org setup and replay storage are confirmed.

## Task 6: Final Verification

- [ ] Run backend tests impacted by the changes.
- [ ] Run `cd frontend && npm run build`.
- [ ] Hit `/api/health`, `/api/data-quality`, `/api/data-quality/refresh`, `/api/live-dispatch`, and `/api/garages`.
- [ ] Browser-verify the app renders after frontend build if the local browser plugin is available; otherwise report browser limitation explicitly.
- [ ] Produce before/after benchmark report.
- [ ] If results regress, revert only the failing enhancement commit and keep the protected baseline intact.
