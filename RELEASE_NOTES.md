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

## v1.10 — 2026-10-05

| | |
|---|---|
| Tag | `release/v1.10` |
| Commit | `da508ef` |
| Bundle | `index-Qy6LI9dH.js` |
| Deploy | GitHub Actions run `37383756265`, 2026-10-05 (daytime, on the user's explicit instruction), success, 54 s |
| Roll back to | `release/v1.9` = `82f4420` (bundle `index-BKp-HTOv.js`) |

**Changed**
- Replay list: cases per SA (count chip, "Cases:" filter), and a panel with each case's full trail: when, who (person or system), what, and what people wrote (notes, comments, emails, call notes). Cases are Human (opened by a person) or Automatic (integration/system), with a Both / Human / Automatic switch for cases and for events. The panel opens on the case people wrote on.
- An unbuilt day shows its work orders as soon as the build has read them (about 3 s on production) instead of waiting ~35 s; the full view opens by itself.
- Replay speed: the call-story rate limit counts only real Salesforce pulls (cache hits are free); hovering a work order starts loading its story.
- Hot screens (queue, command center, garages, watch list) are warmed once after a restart.
- Backend: `/api/case-trail/{wo_id}` (replay permission), `case_trail.py`; `call-flags` adds one grouped case-count query; the build publishes its calls as it goes.
- Tests: 461 passing.

---

## v1.9 — 2026-10-05

| | |
|---|---|
| Tag | `release/v1.9` |
| Commit | `82f4420` |
| Bundle | `index-BKp-HTOv.js` |
| Deploy | GitHub Actions run `37281697932`, 2026-10-05, success, 55 s |
| Roll back to | `release/v1.8` = `a3437cb` (bundle `index-Co5Cta7c.js`) |

**Changed** (frontend only)
- Replay work-order list: a satisfaction score badge is the first thing in every row (number out of 100, green 80+, amber 60-79, red below 60). A dash and "no survey" (reason on hover) when the call has no survey. Verified with screenshots on the live site.

## v1.8 — 2026-10-05

| | |
|---|---|
| Tag | `release/v1.8` |
| Commit | `a3437cb` |
| Bundle | `index-Co5Cta7c.js` |
| Deploy | GitHub Actions run `37280726832`, 2026-10-05, success, 55 s |
| Roll back to | `release/v1.7` = `37fbf1b` (bundle `index-DN23C1I7.js`) |

**Changed**
- Server compresses text answers (gzip): main script 2.2 MB to 576 KB (-74%), day data 398 KB to 27 KB (-93%). Hashed build files are cached for a year. Downloads (photos, exports, DB dumps) are excluded. (`backend/compression.py`)
- Replay: picking a garage and day that is not built starts the build by itself and opens the data when ready. No Build button. Tested on production: unbuilt day opened with 0 clicks, 1 build, ~35 s.
- First work order on production: 2.28 s to 1.91 s (repeat visit 1.46 s).

## v1.7 — 2026-10-05

| | |
|---|---|
| Tag | `release/v1.7` |
| Commit | `37fbf1b` |
| Bundle | `index-DN23C1I7.js` |
| Deploy | GitHub Actions run `37280221950`, 2026-10-05, success, 56 s (was 215 s) |
| Roll back to | `release/v1.6` = `0172cc7` (bundle `index-D1eUy0f5.js`) |

**Changed**
- Survey score (NPS x10) and result on every SA in the Replay list, a reason when there is none, and "Score below 80 / 80 and above" filters.
- Replay list shows as soon as the day data arrives; replay and survey requests start in parallel.
- Hot screens (queue, command center, garages, watch list) are warmed once after a restart.
- Pipeline polls Azure's deployment status instead of a fixed 180 s sleep: 215 s to 56 s.
- Tests: fixed the 5 old failing tests and the unloadable test file; backend suite 444 passing.

---

## v1.6 — 2026-10-05

| | |
|---|---|
| Tag | `release/v1.6` |
| Commit | `0172cc7` |
| Bundle | `index-D1eUy0f5.js` |
| Deploy | GitHub Actions run `37278303259`, 2026-10-05, success |
| Roll back to | `release/v1.5` = `4df825c` (bundle `index-BTWZobhZ.js`) |

**Changed** (frontend only)
- Menu: "Report Card" removed, "Replay" kept. The `/report-card` page still exists by address.

## v1.5 — 2026-10-05

| | |
|---|---|
| Tag | `release/v1.5` |
| Commit | `4df825c` |
| Bundle | `index-BTWZobhZ.js` |
| Deploy | GitHub Actions run `37277828356`, 2026-10-05, success |
| Roll back to | `release/v1.4` = `56c6964` (bundle `index-DJ96HwED.js`) |

**Changed** (frontend only)
- Contractor screens show one clear message ("No garages are assigned to your account yet") for a contractor account with no garages, instead of a raw HTTP 400.

---

## v1.4 — 2026-10-05

| | |
|---|---|
| Tag | `release/v1.4` |
| Commit | `56c6964` |
| Bundle | `index-DJ96HwED.js` |
| Deploy | GitHub Actions run `37276332337`, 2026-10-05 ~03:15 ET, success |
| Roll back to | `release/v1.3` = `462b5d8` (bundle `index-Da_tVr0N.js`) |

**Changed**
- Replay work-order list shows each call's address (city), and flags calls with no address ("No address on this call"). Frontend only: `GarageReplay.jsx`.
- Tested on production with the test login: 076DO, Oct 3: city shown on the rows, Missed PTA filter 36 of 161, 85% totally satisfied, no console errors, no failed requests.

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
