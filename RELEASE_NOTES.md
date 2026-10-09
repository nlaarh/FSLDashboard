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

## v1.14.1 — 2026-10-09

| | |
|---|---|
| Tag | `release/v1.14.1` |
| Commit | `98ee103` (merge of PR #24, branch `hotfix/v1.14.1`) |
| Bundle | `index-BrHnyEUg.js` |
| Deploy | GitHub Actions run `37976886382`, 2026-10-09, success (owner's explicit "deploy now") |
| Roll back to | `release/v1.14` = `e402daf` (bundle `index-S8sqGyHC.js`) |

**Changed**
- Watchlist: the map icon now sits in its own "Map" column next to Assist, so it lines up on every row and no longer covers Work Type.
- Call map opens much faster. The driver search now looks only at jobs assigned in the last 3 days, and for unassigned 000 calls it skips drivers whose location is over 1 hour old. 000 calls went from about 24 s to 0.3 s; a 20-driver garage from 3.7 s to 0.6 s.

---

## v1.14 — 2026-10-09

| | |
|---|---|
| Tag | `release/v1.14` |
| Commit | `e402daf` (merge of PR #23, branch `release/v1.14-prep`) |
| Bundle | `index-S8sqGyHC.js` |
| Deploy | GitHub Actions run `37972898789`, 2026-10-09, success (owner's explicit "test and deploy everything now") |
| Roll back to | `release/v1.13` = `7b515bc` (bundle `index-BEp2pkZc.js`) |

**Changed**
- Watchlist call map: a map icon on each row opens a full-window live view of the call. It shows quick info (garage phone and up to 3 contacts), who is working it (falls back to the garage dispatcher), related cases, a map with the qualified drivers and their job badges, the story, and a time slider. It refreshes about once a minute. Only roles with Replay access see texts; contractors are blocked.
- Replay Expand: big-screen mode on the Garage and Work Order tabs, with Back and Esc, covering the whole window.
- Watchlist "Potential Duplicate" no longer raises false alarms. The RAP customer name now decides (work orders 05200081 and 05200190 were false alarms).
- Role dropdown: ERS roles are offered, legacy roles are hidden, and a user's unlisted role is never silently changed.

---

## v1.13 — 2026-10-08

| | |
|---|---|
| Tag | `release/v1.13` |
| Commit | `7b515bc` (merge of PR #22, branch `fix/replay-click-and-500`) |
| Bundle | `index-BEp2pkZc.js` |
| Deploy | GitHub Actions run `37870902780`, 2026-10-08 about 9:45 PM ET (after hours, on the owner's explicit "deploy when done"), success |
| Roll back to | `release/v1.12` = `a6c1c02` (bundle `index-9Xcf0DNE.js`) |

**Changed**
- Work Order replay now shows the other qualified drivers (right skills and truck) on the map when the call was given or accepted, with distance and status. The "Right driver?" tab lists them, and clicking any truck shows its job queue. Needs the garage-day built; Towbook garages do not show other drivers.
- The garage-day view shows how calls came in (DRR, Replicant, call center, partner and so on) with counts and percent. Click one to filter.
- Maps default to a clean light street map; dark is still a toggle.
- Fixed a rare error on Replay when two requests saved the same day file at the same time.
- Replay accepts 6-digit SA numbers, and truck numbers are removed from driver names everywhere.

---

## v1.12 — 2026-10-08

| | |
|---|---|
| Tag | `release/v1.12` |
| Commit | `a6c1c02` (merge of PR #21, branch `fix/replay-click-and-500`) |
| Bundle | `index-9Xcf0DNE.js` (css `index-BAYTOnuD.css`) |
| Deploy | GitHub Actions run `37869316070`, 2026-10-08 about 9:20 PM ET (after hours, on the owner's explicit "deploy it"), success |
| Roll back to | `release/v1.11` = `e8e9d1f` (bundle `index-YDV7zsZ_.js`) |

**Changed**
- Replay now starts playing in about one second and uses far fewer Salesforce calls.
- Replay plays like a game: smooth animation, speeds of 1x / 10x / 60x / 300x, jump to next event, follow a truck, real truck types and driver names, a waiting timer for the member, pop-up notices, and a dark or light map.
- Member phone calls, callbacks and texts show on the timeline and map; click one to open the conversation (each view is logged). New setting `replay_member_contact`, on by default (prod shows it on).
- New tab with the driver's other jobs that day, and short insight call-outs.
- Fixes: Replay can be clicked while it is still loading; work order 1084964 no longer errors (calls with no promise time); drivers who are off shift are hidden on the day map.
- ERS managers can now use Replay.
- A few places say "contractor" instead of "vendor".
- Tests: backend 577 passing, frontend 14 passing; Tamy passed Replay v2 on real read-only Salesforce data.

---

## v1.11 — 2026-10-05

| | |
|---|---|
| Tag | `release/v1.11` |
| Commit | `5922c62` (merge of PR #20, branch `perf/salesforce-load`) |
| Bundle | `index-YDV7zsZ_.js` (css `index-khmI-deV.css`) |
| Deploy | GitHub Actions run `37389056416`, 2026-10-05 evening (outside working hours, on the user's explicit "deploy and test"), success |
| Roll back to | `release/v1.10` = `543cb6b` (notes commit on top of `da508ef`; bundle `index-Qy6LI9dH.js`) |

**Changed** (Salesforce load reduction, measured ~95 calls/min before)
- Dashboards refresh in the background only if a user read them in the last 15 minutes; nights and weekends make no refresh calls.
- Command Center / Ops Brief / Scheduler Insights / Ops Territories may be up to 5 minutes old; fixed a wrong Command Center cache key.
- Command Center no longer queries once per garage for Towbook: about 90 down to 13 calls per refresh.
- New shared 26-hour appointment history store (`sa_history`), updated incrementally; identical dashboard queries within 5 minutes share one read. Extra result pages now count as API requests.
- Frontend: background polling pauses when the browser tab is hidden or the computer sleeps (`pollWhileVisible`).
- Files: `backend/cache.py`, `ops.py`, `refresher.py`, `sa_history.py`, `sf_client.py`, `routers/command_center*.py`, `routers/misc_diagnostics.py`, `routers/ops.py`; `frontend/src/utils/pollWhileVisible.js`, `hooks/useCommandCenterData.js`, `pages/Dashboard.jsx`, `pages/PtaAdvisor.jsx`, `components/OptimizerTimeline.jsx`; new tests.
- Tests: 482 passing.

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
