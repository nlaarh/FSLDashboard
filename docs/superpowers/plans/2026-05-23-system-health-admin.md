# FSLAPP System Health Admin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a PIN-protected System Health admin tab that shows runtime, cache, Salesforce, database, and environment configuration health without leaking secrets or burning external API quota.

**Architecture:** Add one focused FastAPI router for `/api/admin/system/health`, register it in `main.py`, and expose it through the existing frontend API module. Replace the large inline Admin status JSX with a reusable `AdminSystemHealth` component so `Admin.jsx` stays under the 600-line ceiling.

**Tech Stack:** FastAPI, Python, React, Vite, Tailwind, Axios, pytest.

---

### Task 1: Backend Health Endpoint

**Files:**
- Create: `backend/routers/system_health.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_system_health.py`

- [ ] Back up touched files to `/tmp/fslapp-system-health-backup-*`.
- [ ] Implement a read-only endpoint protected by the existing admin PIN check.
- [ ] Return masked environment state for `.env` and `backend/.env`.
- [ ] Use lightweight health checks only; do not live-ping Salesforce, Google Maps, OpenAI, GitHub, or AgentMail.
- [ ] Add tests for auth, response shape, and secret masking.

### Task 2: Frontend Admin Tab

**Files:**
- Create: `frontend/src/components/AdminSystemHealth.jsx`
- Modify: `frontend/src/pages/Admin.jsx`
- Modify: `frontend/src/api.js`

- [ ] Add `adminSystemHealth(pin)` to `api.js`.
- [ ] Move system health rendering into `AdminSystemHealth`.
- [ ] Keep `Admin.jsx` under 600 lines and preserve existing cache/settings/users behavior.
- [ ] Add manual refresh and last-updated timestamp in the health tab.

### Task 3: Verification

- [ ] Run the backend test file.
- [ ] Hit `/api/admin/system/health` locally with `X-Admin-Pin`.
- [ ] Run `npm run build` in `frontend`.
- [ ] Render the admin page in browser and verify the System Health tab loads.
