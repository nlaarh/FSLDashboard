# Waiting to release

These fixes are built and tested but **not live**. They ship only when the owner says "release",
and never during the working day. When released, move each line into RELEASE_NOTES.md and delete
this file.

Branch: `fix/replay-fixes` (based on main `b79a10d`).

| # | Fix | Commits | Checked |
|---|-----|---------|---------|
| 1 | Replay no longer says "Driver arrived in time" when no driver arrived (seen on WO 05210512). Upcoming promise shows "Promise due"; a passed promise with no arrival shows "Promise missed" in red. Same mistake fixed in Call Story. | bc00f78, 99624f4 | Real call data from the live app: old says "arrived in time", new says "Promise due — not reached yet". 183 tests pass. |
| 2 | One map and one replay: the Watchlist replay uses the same map as the Replay tab (duplicate map code removed). | 47508cf | Browser on fake Salesforce copy (QA run 3): PASS. |
| 3 | Replay opens at 10x instead of 60x. Speed buttons 1x / 10x / 60x / 300x unchanged. | e81e275 | Browser QA run 3: PASS. |
| 4 | Replay message lines are back: each message draws a line from the channel to the driver or member; earlier ones stay faded. | 687deb2 | Browser QA run 3: PASS (videos in SFReplica/qa/screens_run3). |
| 5 | Customer bubbles show the call type (tow, battery, tire, lockout, winch, fuel) in Garage Live, Replay and the Watchlist. | e9bb851 | Browser QA run 3: PASS. |
| 6 | Promise verdict shown in words: "Promise met", "Promise missed — N min late", "Promise missed — no driver had arrived", "Promise due". On-time is no longer red; header chip turns green "Promise met" when the driver arrived in time. | 69f6e91, 83f9a3f | Browser QA run 4: wording, colours and green chip PASS; corner toast fixed in 83f9a3f; browser QA run 5: PASS. |
| 7 | Watchlist flags (owner request 2026-10-13): "Service Territory Needs Action" waits until the appointment is over 2 minutes old; "No Service Resource" is not raised when the status is Accepted and the Integrations Towbook account accepted it. | see git log | 71 Watchlist tests pass (4 new cases). Live read 2026-10-13 9 pm: same 3 flags as before (none Towbook-accepted at that hour); today 129 of 465 calls with a cleared start were Towbook-accepted. Browser check still to do. |
| 8 | Watchlist replay (live call map): a Full screen button on the map; Esc or the button returns. No change in Salesforce requests. | see git log | Builds; 47 front-end tests pass. Browser check still to do. |
| 9 | Watchlist replay (live call map): the driver now moves every minute instead of every 2 minutes (server copy kept 50 s instead of 60 s). **Cost, approved by owner 2026-10-13:** +1 Salesforce request per minute per call someone has open; viewers of the same call share it. | see git log | Simulated 6 one-minute refreshes: old showed positions 1,1,2,2,3,3 (3 reads); new 1,2,3,4,5,6 (6 reads). 73 tests pass. Browser check still to do. |

Tracked elsewhere (not app code): service resource blanked by a Salesforce background job (WO 05209814) — needs the Salesforce admin.
