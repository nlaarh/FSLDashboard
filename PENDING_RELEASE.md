# Waiting to release

These fixes are built and tested but **not live**. They ship only when the owner says "release",
and never during the working day. When released, move each line into RELEASE_NOTES.md and delete
this file.

Branch: `fix/replay-fixes` (based on main `b79a10d`).

| # | Fix | Commits | Checked |
|---|-----|---------|---------|
| 1 | Replay no longer says "Driver arrived in time" when no driver arrived (seen on WO 05210512). Upcoming promise shows "Promise due"; a passed promise with no arrival shows "Promise missed" in red. Same mistake fixed in Call Story. | bc00f78, 99624f4 | Real call data from the live app: old says "arrived in time", new says "Promise due — not reached yet". 183 tests pass. |
| 2 | One map and one replay: the Watchlist replay uses the same map as the Replay tab (duplicate map code removed). | 47508cf | Tests pass; browser check pending. |
| 3 | Replay opens at 10x instead of 60x. Speed buttons 1x / 10x / 60x / 300x unchanged. | e81e275 | Build + 46 frontend tests pass; browser check pending. |
| 4 | Replay message lines are back: each message draws a line from the channel to the driver or member; earlier ones stay faded. | 687deb2 | Build + tests pass; browser check pending. |
| 5 | Customer bubbles show the call type (tow, battery, tire, lockout, winch, fuel) in Garage Live, Replay and the Watchlist. | e9bb851 | Build + tests pass; browser check pending. |

Tracked elsewhere (not app code): service resource blanked by a Salesforce background job (WO 05209814) — needs the Salesforce admin.
