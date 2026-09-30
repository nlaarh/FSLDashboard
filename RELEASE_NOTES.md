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
