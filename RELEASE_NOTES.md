# FleetPulse Release Notes

Newest release first. Every production deploy gets an entry here.

Each entry records the **git tag**, **commit**, and **frontend bundle** that went live, so any
release can be found and rolled back to. The bundle name is what production serves in its
HTML (`/assets/index-<hash>.js`) — compare it against the site to confirm which build is live.

**Rolling back**
- Undo one release: `git revert <commit>` then `git push origin main` (redeploys in ~4 min).
- Go back to an exact earlier build: redeploy that release's tag (`git checkout <tag>` in a
  worktree, or revert every commit after it).
- Pushing to `main` deploys. Do it outside the working day unless it's urgent.

> Numbering starts at v1.0 on 2026-09-30. Older tags (`v2.6`–`v2.9`, `prod-*`) come from
> earlier, inconsistent numbering and are listed under *Before v1.0* for reference.

---

## v1.3 — 2026-10-05

| | |
|---|---|
| Tag | `release/v1.3` |
| Commit | `462b5d8` |
| Bundle | `index-Da_tVr0N.js` |
| Deploy | GitHub Actions run `37272959848`, 2026-10-05 ~02:40 ET, success |
| Roll back to | `release/v1.2` = `3cc48cb` (bundle `index-CPI8Ozh_.js`) |

**Changed** (Replay work-order list, flag-gated, admins and executives only)
- Member survey result per call (overall satisfaction) and the garage-day "totally satisfied %" (red under 80), with a survey filter.
- Missed PTA: red bubble and filter (uses the verdict's `pta_met`).
- SMS not sent: red SMS pill; out of territory: compass icon; "SMS: opted in / not opted in" line.
- Backend: 3 read-only SELECTs per garage-day (work orders, text log, surveys for completed calls), cached 1 h for recent days and 24 h once older than 3 days.

**Files**: `backend/report_card_flags.py`, `backend/routers/report_card.py`, `frontend/src/components/reportcard/GarageReplay.jsx`, tests.

---

## v1.2 — 2026-10-05

| | |
|---|---|
| Tag | `release/v1.2` |
| Commit | `3cc48cb` |
| Bundle | `index-CPI8Ozh_.js` |
| Deploy | GitHub Actions run `37266512384`, 2026-10-05 ~01:30 ET, success |
| Roll back to | `release/v1.1` = `af27df1` (bundle `index-BLvxJBdj.js`) — note main also holds Merge #7 (`18bc009`, Report Card, flags off) |

**Changed**
- Replay work-order list: RAP badge, out-of-territory icon, coverage level, explicit "Opted in / Not opted in to texts" line per work order.
- Red icon = opted in but no member text sent (tooltip says why); grey = not opted in; none before the 2026-09-01 text log.
- Filters: job type, member level, RAP, out of territory, no text.
- New read-only route `/api/report-card/{territory}/{date}/call-flags`: 2 Salesforce SELECTs per garage-day, cached 24 h, hard cap 8 calls.
- Replay restricted to administrators and executives (`0b03e8a`).
- Flags `scheduler_report_card` / `scheduler.replay` still default off: nothing visible until switched on.

**Files**: `backend/report_card_flags.py`, `backend/routers/report_card.py`, `frontend/src/components/reportcard/GarageReplay.jsx`, `frontend/src/api.js`, tests.

---

## v1.1 — 2026-10-02

| | |
|---|---|
| Tag | `release/v1.1` |
| Commit | `af27df1` |
| Bundle | `index-BLvxJBdj.js` (unchanged — backend-only release) |
| Deploy | GitHub Actions run `37089722529`, 2026-10-02 22:28 ET, success |
| Roll back to | `release/v1.0` = `9e4af0d` (bundle `index-BLvxJBdj.js`) |

**Changed**
- Salesforce Canvas sign-in now trusts three Salesforce orgs at once — test, UAT and production —
  each with its own Connected App consumer secret. Azure settings: `SF_CANVAS_SECRET_TEST`,
  `SF_CANVAS_SECRET_UAT`, `SF_CANVAS_SECRET_PROD` (prod not set yet), with optional per-org locks
  `SF_CANVAS_ORG_ID_TEST/_UAT/_PROD` (production org id `00DDo000001BxM7`).
- Removed from Azure: the old `SF_CANVAS_SECRET` and `SF_CANVAS_KEY_UAT` (no longer read).
- Sign-in log lines name the org: `Canvas sign-in (uat, org 00D…)`.
- Files: `backend/routers/embed.py`, `backend/tests/test_embed.py` (27 tests).

**Verified live:** requests signed with the test and UAT secrets are accepted; a wrong key is rejected.

---

## v1.0 — 2026-09-30

| | |
|---|---|
| Tag | `release/v1.0` |
| Commit | `9e4af0d` |
| Bundle | `index-BLvxJBdj.js` |
| Deploy | GitHub Actions run `36763527010`, 2026-09-30 15:08 ET, success |
| Roll back to | `checkpoint/pre-no-sa-flag` = `8852ab2` (bundle `index-B31hCgdY.js`) |

**Changed**
- **SA Watchlist → Operational Alerts: new flag "No Service Appointments on Work Order".**
  Flags an ERS Work Order that has been in *Submitted* status for more than 2 minutes with no
  Service Appointment. Those calls can't be dispatched. Normally the SA is created within
  seconds of Submitted. Covers the last 24 hours. Contractors see only their own territories.
- These rows have no appointment, so Appt # shows "—" and the Dispatch Assist button is hidden.
  The Work Order link and KMI case still show.
- The flag is added to the Operational Alerts help panel.

**Files:** `backend/routers/watchlist.py`, `backend/routers/watchlist_alerts.py`,
`frontend/src/components/SAWatchlist.jsx`

**Verified:** production serves the new bundle; `/api/watchlist` returns 200 with no error and
existing alerts intact. The same 10 backend tests fail before and after the change (pre-existing);
no new failures.

---

## Before v1.0

Production deploys before this log started. Bundle names were not recorded, except where noted.

| Date | Commit | Tag | Change |
|---|---|---|---|
| 2026-09-28 | `8852ab2` | `checkpoint/pre-no-sa-flag` | Canvas sign-in: accept sandbox emails ending in .invalid. Bundle `index-B31hCgdY.js` |
| 2026-09-28 | `ecf8248` | `prod-canvas-v1-2026-09-28` | Salesforce Canvas sign-in: embed FleetPulse in Salesforce |
| 2026-08-25 | `295a517` | `prod-before-canvas-2026-09-28` | Contractor map: hide Unable to Complete, street routes for tows |
| 2026-08-25 | `e5a9dc9` | — | Feature flags: DB-backed, admin-toggleable |
| 2026-08-25 | `6442004` | — | Fix Dispatch Map empty after 8pm ET; contractor dispatch |
