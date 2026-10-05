# Call Story: Architecture ("type a call, see what happened and why")

Owner: Dan · Data rules: Henry (`call-story-spec.md`, rules `cs1`) · Build: Ruby · QA: Tamy · Release: Kathy
Status: DRAFT for user approval · 2026-10-04 · Builds on Scheduler Report Card slice 1 (branch
`feature/scheduler-report-card`, uncommitted) and `architecture.md`.
Design only. No app code, no Salesforce or Postgres queries were run to write it.

---

## 0. Decisions recorded (product owner, answers to call-story-spec §14)

| # | Question | Decision | Effect on this design |
|---|---|---|---|
| D1 | What is "stuck in the grid"? | Flag **two separate stuck types**. **PARKED_IN_SPOT**: the call sits in a `000-<region> SPOT` bucket (G1). **NO_OWNER**: no garage or driver owns the call, for example after a reject or decline, or while it sits in a raw grid zone. **Out-of-grid address** (G4) is an informational flag when it's cheap. | §4.3. `PARKED_IN_SPOT` = segment S8. `NO_OWNER` = S7 + S9 (+ G3 "SPOT - UNASSIGNED GRIDS"). G4 reuses the cached `/api/map/grids` polygons, so it costs 0 extra SF calls. |
| D2 | Which PTA is the member's promise? | Grade against the **original** promise. Show the revised PTA next to it, flagged **"PTA re-based"**. | §4.4. Initial PTA = the last `ERS_PTA__c` row within 5 s of creation. O1 resolved: report card r2 grades the same initial PTA (metrics-spec §7.7). |
| D3 | Who can see it? | AAA **supervisors and above**, using the report card's permission. A garage-scoped contractor view comes later. | `scheduler.report_card` + a new flag `call_story`. Never contractor. O4 covers whether a `supervisor` role should join the set. |
| D4 | SMS | Show Sent / Failed / Skipped from `SMS_Send_Log__c` (calls from 9/1 on), labelled **"Sent ≠ delivered"**. Keep a slot for delivery status in case access is granted later. Before 9/1: counts only, labelled. | §4.5. `delivery` block and per-row `delivery_status: null` slot. |
| D5 | Operating hours (C01 rank skipped) | Allowed through a small daily cached query. | Q6b `TimeSlot`, cached 24 h per grid together with the matrix. |

---

## 1. Goal

A supervisor types one call identifier and gets one page that shows:
- every step of the call in time order,
- who acted at each step,
- how long each stage took compared with that garage's normal times,
- where the call got stuck, and of which stuck type,
- which texts the member got,
- a deterministic list of causes that agrees with the report card verdict,
- an optional AI paragraph written only from those facts.

Metric meaning comes from `call-story-spec.md` (Henry) and is not repeated here.

---

## 2. Files

### Backend (new). Every file stays under 600 lines. All modules except the router and the pull are pure (no I/O).
| File | Purpose | Target |
|---|---|---|
| `backend/routers/call_story.py` | `GET /api/call-story`, `POST /api/call-story/narrative`. Gate, rate limit, cache, compose. | ~180 |
| `backend/call_story_pull.py` | Input resolution and the sequential Q1–Q9 plan (§3), with a hard call cap. Daily caches for matrix, timeslots and polygons. | ~280 |
| `backend/call_story_config.py` | `CS1` = spec §12 JSON verbatim, plus `stuck_types`, `norm_fallback` and `max_sf_calls` (§3.4). | ~90 |
| `backend/call_story_events.py` | History → grouped events E00–E18, actor classes, channel per hop, the §4.2 final-decision rule, PTA initial/final, territory kind, matrix ladder, G4 point-in-polygon. | ~380 |
| `backend/call_story_segments.py` | S1–S9 extraction and severity. **One function used by both the story and the norms** (§5). | ~250 |
| `backend/call_story_norms.py` | p50/p75/p90/p95 from report-card snapshots, the fallback chain, per-snapshot segment files. | ~220 |
| `backend/call_story_sms.py` | Log rows → labels, the §7.4 "why no text" rules, timer-restart count, pre-9/1 sessions. | ~180 |
| `backend/call_story_causes.py` | C01–C19 triggers + evidence, the headline cause, deterministic bullet sentences (template). | ~380 |
| `backend/call_story_narrative.py` | Story fact sheet → prompt → validated sentences with event ids. | ~150 |
| `backend/report_card_ai.py` | **Shared AI core**, built now (architecture §11 planned it): canonical fact hash, number and name validator, provider call through `load_ai_settings`/`call_openai_simple`, template fallback. The day verdict reuses it later. | ~220 |
| `backend/tests/test_call_story_*.py` + `fixtures/call_story/*.json` | §8. | n/a |

### Backend (changed, small)
| File | Change |
|---|---|
| `report_card_snapshot.py` | Rename `_sa_record` → `sa_record`, keeping the old name as an alias. **No behaviour change.** The story builds its SA record with the same function, so milestones, decision and channel match the report card exactly. |
| `report_card_build.py` | Rename `_Puller` → `Puller` and add an optional `max_calls` that raises `CallCapReached`. No behaviour change for builds. |
| `report_card_store.py` (69 lines) | + `load/save_segments(tid, date)`, `load/save_story_raw(wo_id)`, `load/save_ai(hash)`. Same file store and append-only rename rule. About +35 lines. |
| `feature_flags.py` | `'call_story': False`. |
| `main.py` (579) | +1 include line. |
| SA report fixes | §6: `routers/sa_report.py`, `routers/sa_report_timeline.py`, `dispatch_utils.py` (`_STATUS_LABEL`). Separate commit. |

Not changed: `permissions.py` (the story reuses `scheduler.report_card`), report-card routes and verdict logic.

### Frontend
New:
- `pages/CallStory.jsx` (~180): input box, URL state `?q=`, loading, error and ambiguous states, leg tabs.
- `components/callstory/`:
  - `StoryHeader.jsx`: call ids, grid, channel path, PTA badge (original and re-based).
  - `StoryVerdict.jsx`: headline cause, cause bullets, verdict block, "Write summary" (AI) button.
  - `SegmentStrip.jsx`: one bar per segment with p75/p90 ticks and a severity chip.
  - `StoryTimeline.jsx`: grouped events with SMS rows interleaved, and a "raw history" toggle.
  - `MatrixLadder.jsx`: ranks tried, declined, skipped (closed) or not reached.
  - `SmsSummary.jsx`: counts, the "Sent ≠ delivered" label, the pre-9/1 banner.
- Styling reuses `reportcard/reportCardStyles.js` (`verdictColour`, `fmtTime`, `fmtMin`).

Changed:
- `App.jsx`: route `/call-story` inside the main `Layout` only.
- `api.js`: `fetchCallStory(q)`, `fetchCallStoryNarrative(saId)`.
- `reportcard/CallPanel.jsx`: an "Open call story" link.
- `Layout.jsx`: search box routing (§7).

---

## 3. Salesforce plan (read-only, strictly sequential, no `sf_parallel`)

### 3.1 Resolution (spec §2), folded into Q1, so it costs 1 call for every input type
| Input (regex from `CS1.inputs`) | Q1 |
|---|---|
| SA: `^(SA-)?\d{7}$` | `ServiceAppointment WHERE AppointmentNumber = :x`, selecting `ERS_Work_Order__c` + `ERS_Work_Order__r.<WO fields>` |
| 8 digits with a leading 0 | `WorkOrder WHERE WorkOrderNumber = :x OR ERS_Source_Call_ID__c = :x`. **One call.** Two rows → `409` with both candidates |
| Other 8 digits | `WorkOrder WHERE ERS_Source_Call_ID__c = :x` |
| Call key `^\d{3}-\d{8}-\d{8}$` | `WorkOrder WHERE ERS_Call_Key__c = :x` |
| 15/18-char Id, prefix `08p` / `0WO` | direct `Id =` (prefix `1WL`: WOLI → `WorkOrderId` in the same select) |

WO fields are spec Q1's list. `Mobile_Phone__c` is read only for the pre-9/1 SMS lookup. It is never returned or logged.
Ruby runs `sf_describe` on `ServiceAppointment` (relationship name `ERS_Work_Order__r`), `WorkOrder`,
`SMS_Send_Log__c`, `ERS_Territory_Priority_Matrix__c`, `Optimization_Log__c` and `Survey_Result__c` before coding.

### 3.2 The plan
| # | Query | When | Calls |
|---|---|---|---|
| Q1 | Resolve + WO header (3.1) | always | 1 |
| Q2 | SAs on the WO: `ERS_Work_Order__c = :wo` (spec Q2 fields + `ServiceTerritoryId`, `RecordType.Name`). Non-ERS → `422` | always | 1 |
| Q3 | `ServiceAppointmentHistory WHERE ServiceAppointmentId IN (all legs)`, **all fields**, with OldValue, NewValue, CreatedBy.Name, CreatedBy.Profile.Name, CreatedById, `ORDER BY CreatedDate, Id` | always | 1 (+1 `COUNT()` only if ≥ 1,000 rows) |
| Q4 | `AssignedResource` for the legs + `ServiceResource.ERS_Driver_Type__c`, `RelatedRecordId` | always | 1 |
| Q5 | `SMS_Send_Log__c WHERE Work_Order__c = :wo` for calls ≥ `sms.log_start_utc`. **Before 9/1:** `MessagingSession WHERE MessagingEndUser.MessagingPlatformKey = :normalisedPhone AND Origin = 'TriggeredOutbound' AND CreatedDate` between WO created and closed + 1 h (one semi-join, not two queries) | always | 1 |
| Q6 + Q6b | Matrix for the grid (`ERS_Parent_Service_Territory__c = :grid`) + `TimeSlot` (and `OperatingHours.TimeZone`) for its operating hours. **Cached 24 h per grid** (`cs_matrix:<gridId>`) | cache miss | 0 or 2 |
| Q7 | Optimizer trail. Only if the history has FSL_ENGINE events. (a) `FSL__Optimization_Request__c` (type, status, `FSL__Scheduling_Policy__r.Name`) and (b) `Optimization_Log__c`, each in the union of windows [event − 2 min, event + 1 min], attributed by time and resource (T8) | conditional | 0 or 2 |
| Q8 | Blocking job for S3. **Only if** S3 is longer than the *free-driver* p75 (the lower baseline: if it doesn't exceed that, it isn't slow either way) **and** no day snapshot covers the driver. (a) That driver's `AssignedResource` with SA fields in [dispatch − 12 h, dispatch]; (b) `Field = 'Status'` history for ≤ 5 of those SAs | conditional | 0 or 2 |
| Q9 | `Survey_Result__c WHERE ERS_Work_Order__c = :wo` | always | 1 |
| G4 | Polygons from the existing `map_grids` cache (1 h, `routers/map.py`) | — | 0 (shared) |

**Budget:**

| Case | SF calls |
|---|---|
| Typical (day snapshot exists, FSL engine involved) | **7** |
| No snapshot, every condition true | **10** |
| Matrix cache miss | +2 (once a day per grid) |

**Hard cap: `CS1.max_sf_calls = 12`.** When the cap is reached, optional steps (Q7, Q8, G4) are skipped and a `data_notes` entry
says which. The page still renders.

**Why this is the lightest plan:**
- A story needs row-level history for one WO, so aggregates can't answer it.
- Every query is keyed by the WO, its 1–3 SA Ids, one grid, or a minutes-wide window. Nothing is unbounded.
- GPS, logins, roster and candidate sets are never pulled per story. They come from the day snapshot when it exists (3.3).

### 3.3 Day snapshot first, standalone pull second
- **Lookup key:** (`ServiceTerritoryId` of the member-facing leg, ET date of its `CreatedDate`), read from `report_card_store`.
  It's used only if the snapshot holds this SA's record.
- **Taken from the snapshot (0 SF calls):**
  - the verdict and evidence (`sa_features` + `verdict` with the **active** rules, so the result is identical to the Day view),
  - the drivers' open jobs at any time (S3 BUSY/FREE split, the C09 blocking SA),
  - logins and absences (C10),
  - candidate names for C13.
- **Without a snapshot:**
  - The story runs `verdict()` on its own `sa_record`, which has no candidate sets.
  - The candidate-free codes are identical to the report card by precedence, so they're shown, labelled "decision quality not checked": `NOT_GRADED_TOWBOOK`, `NOT_GRADED_CANCELED_PRE_ASSIGN`, `INBOUND_CASCADE`, `BOUNCED`.
  - Any other result is **not shown**. It would read `NOT_GRADED_INSUFFICIENT_DATA` and could contradict the report card. Instead the verdict block shows "Decision not graded: garage-day not built" and a **Build garage-day** button. The button calls the existing `POST /api/report-card/{t}/{date}/build` (past days, same permission). It never auto-builds.
  - When the build finishes, the story re-composes from the cached raw bundle with **0 new SF calls**.
- Today's calls and open calls have no snapshot (past days only). Their verdict is "call still open / today".

### 3.4 Caching and load guards
| Key | Holds | TTL |
|---|---|---|
| `cs_resolve:<normalised input>` | WO Id(s) | 24 h. Not-found results: 60 s |
| `cs_raw:<woId>` | Q1–Q9 raw bundle (no phone number) | All legs terminal and > 2 h past end: **24 h**, also written to the file store (`stories/<woId>.raw.cs1.json`, shared by workers). Otherwise **120 s**, L1 only |
| `cs_matrix:<gridId>` | matrix rows + time slots | 24 h |

- **Compose is pure CPU** (events → segments → norms → causes → verdict) and runs on every request. A newly built snapshot or new norms show up at once, without re-pulling.
- **Postgres L2 cache is not used.** `cache.disk_*` is the Postgres `cache` table, which is production when running locally; slice 1 avoided it for the same reason.
- **Guards:**
  - A process-wide `Semaphore(2)` around pulls.
  - A per-WO lock, so concurrent clicks share one pull.
  - 10 stories per user per minute (in memory) → `429`.
  - Circuit breaker open → `503`.
- **Logging:** one log line per pull with `sf_calls`, `ms`, `cache` (hit/miss), `snapshot_used`.

---

## 4. Story model (how the spec maps to code)

### 4.1 Events
- Spec §4.1 E00–E18 in `call_story_events.py`.
- Rows with the same `CreatedDate` and the same actor become one event (spec `event_group_window_sec: 0`).
- Noise fields are hidden but kept for the raw view.
- **Actor class:** `report_card_verdicts.actor_class()` with rules r1 (B4), plus spec T6. The actor on the `created` row is CALL_TAKER unless they also make an assignment.
- **Final decision:**
  - FSL legs: the last `ERS_Assigned_Resource__c` name row, from `sa_record`.
  - Towbook legs: the `Status → Accepted` row by TOWBOOK_SYNC (§4.2 / T5). The performer is `Off_Platform_Driver__c`.

### 4.2 Territory kind (feeds segments, the ladder and C05/C06/C19)
Each `ServiceTerritory` name row (Old/New) is classified with `CS1.grid`:
- `SPOT` (`000-` prefix or contains `SPOT`)
- `GRID` (zone regex)
- `UNASSIGNED` (`SPOT - UNASSIGNED GRIDS`)
- `GARAGE`

`ERS_Spotting_Number__c` gives the rank (T7). The matrix ladder marks each rank as `final` / `tried` / `declined` /
`rejected` / `skipped_closed` (from timeslots, labelled "inferred") / `not_reached`.

**Caveat:** the matrix and timeslots are **current** values (SF keeps no history), labelled "current matrix, may differ from
that day", like the report card's policy config.

### 4.3 Stuck types (D1)
| Stuck type | Segments | Detection |
|---|---|---|
| `PARKED_IN_SPOT` | S8 | territory kind SPOT, or the assigned resource is a `000-* Spot` placeholder, until the next GARAGE move |
| `NO_OWNER` | S7, S9, (G3) | S7: Rejected/Declined → next Spotted/Assigned. S9: territory kind GRID/UNASSIGNED → next GARAGE |
| *(not stuck)* `OUT_OF_GRID` | — | informational: the SA's lat/lon is outside its `ERS_Parent_Territory__c` polygon (ray-cast, first ring). It goes in `data_notes` with the zone it plots in |

S7, S8 and S9 are always at least SLOW (spec `always_flag`). Each segment row carries `stuck_type` (null for S1–S6).

### 4.4 PTA (D2)
- `basis_ts` = `ERS_Spotting_Datetime__c`, falling back to SA `CreatedDate`.
- `initial_pta` = the last `ERS_PTA__c` history row ≤ 5 s after creation (skip ≤ 0 and ≥ 999).
- `final_pta` = the current value.
- `due_initial = basis + initial`. `due_final = ERS_PTA_Due__c`.
- **Arrival:** Fleet / On-Platform = `ActualStartTime`. Towbook = the first history `Status → On Location`. The source is recorded.
- **Graded (headline) = `met_initial`.** `met_final` is shown alongside. `rebased = initial ≠ final` → C16 and the "PTA re-based"
  chip, with the actor and time of the change.
- The `critical_if_pta_passed` severity rule uses **`due_initial`**.

### 4.5 SMS (D4)
- Rows are labelled per spec §7.3. Dispatcher-contact notifications are excluded.
- Outcomes: `sent` ("Sent to SMS channel"), `failed`, `skipped:<reason>`.
- `why_not` follows the §7.4 order. The timer-restart count = the number of times the status left {Assigned, Dispatched} while
  the call was un-accepted.
- **Before 9/1:** session rows are labelled "Text sent (type unknown)". An "inferred" type is allowed only within 5 s of a status
  change. A banner says "Detailed text log starts 1 Sep 2026".
- **Delivery slot:**
  - Each row has `delivery_status: null`.
  - The top level has `delivery: {available: false, label: "Sent ≠ delivered: delivery to the phone is not visible to FleetPulse"}`.
  - If `ConversationEntry` access is granted later, one optional query fills it and `available` flips. The UI already renders both states.

---

## 5. Baselines ("normal") without extra Salesforce load

**Source: report-card day snapshots only. 0 SF calls.** A snapshot already holds every SA's status, assignment and territory
events, `busy` intervals per driver, work type and channel. These are all the inputs S1–S9 need.

1. **Per snapshot, once.** `call_story_segments.extract(snapshot_sa_record, open_jobs)` → segment rows `{garage, channel,
   segment, minutes, et_hour_block, daytype, driver_state (S3), work_type (S6)}`.
   - These are written next to the snapshot as `<tid>_<date>.segments.cs1.json` (a few KB).
   - The file is regenerated if the snapshot file is newer.
   - The **same function** runs on the story's own record, so story and norms can't drift.
   - A segment counts for the garage that held the SA during it. Time spent in another garage before an inbound move is not
     this garage's.
   - Hop channel:
     - Name `Towbook-*` → towbook. `000-* Spot` → spot.
     - Otherwise the driver's `ERS_Driver_Type__c` via the snapshot's drivers.
     - If none of these apply, the final channel.
2. **At story time.**
   - Load the segment files for that garage over **[call date − 56, call date − 1]**. The window is anchored to the call, so a
     story reads the same tomorrow as today.
   - Compute p50/p75/p90/p95 with n in memory (tens of ms).
3. **Fallback chain (`CS1.baseline` + one proposed addition):**
   1. garage × channel × segment × 4 h block × daytype
   2. garage × channel × segment
   3. channel × segment, pooled over all garages in the store
   4. **approved (O5):** segment, all channels, only for the dispatcher-owned S7/S8/S9
   5. none

   Below n = 30 at every level, severity uses **floors only**, labelled "no baseline yet (n = k)". It is never STUCK or
   CRITICAL by percentile.
4. **Coverage label** on every segment: `{key_level, n, days_covered, window}`.

**Dependency:** norms are only as good as snapshot coverage. Slice 1 has no backfill worker (architecture §12), so until it
ships the pilot has only hand-built days. Getting 56 days for WNY 100 Fleet takes about 56 builds × 16 calls ≈ 900 sequential
SF calls. That is a **user decision**: run them off-peak, one at a time (the existing build semaphore), or wait for the §12
worker. Henry's indicative §5.2 numbers are **not** used as live baselines. Tests use them only as fixtures.

---

## 6. SA report: the 5 bugs (spec §11). Supersede for the story, fix 4 in place

The story **does not reuse** `routers/sa_report*.py`. It uses `report_card_snapshot.sa_record`, `dispatch_utils.parse_assign_events`
and its own modules, so none of the bugs can reach it.

The SA report modal stays in use across the app, **including the contractor portal** (`ContractorLayout`). Its wrong
answers are worth fixing on their own, in a **separate small commit**:

| # | Bug | Action | Where |
|---|---|---|---|
| 1 | History query has no `OldValue`, so the Towbook origin is wrong | **Fix in place.** Add `OldValue` to the select. The cascade origin = the first territory row's OldValue. | `sa_report.py` |
| 2 | Missing history fields (`created`, facility, spotting #, jeopardy, address, note) | **Superseded by the story.** The SA report stays lean (fewer rows, same cache). | — |
| 3 | `_STATUS_LABEL['Accepted'] = 'En Route'` | **Fix in place.** Map it to `'Accepted'`. The only other user is `fetch_sa_timeline`, which has no callers. `_build_phases` gets an "Accepted, not rolling" phase. `SAReportTimeline.jsx` gets an `Accepted` colour. | `dispatch_utils.py`, `sa_report_timeline.py`, `SAReportTimeline.jsx` |
| 4 | `response_min` from `ActualStartTime` for every channel | **Fix in place.** Towbook = the first history `Status → On Location` (rows already fetched). Record `arrival_source`. | `sa_report_timeline._build_sa_summary` |
| 5 | `is_towbook` / `garage_type` from the `ERS_Dispatch_Method__c` formula | **Fix in place.** Add `ServiceResource.ERS_Driver_Type__c` to the existing AR query (no new call) and map with r1 `channel_map`. Without an AR, use the last assigned name (`Towbook-*` → Towbook). | `sa_report.py`, `sa_report_timeline._garage_type` |

Left as is (follow-ups, not in this feature):
- `sf_parallel` in the SA report. It is an existing, cached endpoint, and making it sequential would only make it slower.
- `is_human` = Membership User. That is the narrative wording only.

Tamy runs a regression on the modal (§8, step 10).

---

## 7. API contract and frontend

### 7.1 Routes
All story routes:
- flag `call_story` → `404` when off
- `require_feature('scheduler.report_card')` → `403`
- `_check_territory_access` on the member-facing leg's territory → `403`
- input is matched against the `CS1.inputs` regexes before any SOQL and passed through `sanitize_soql`

| Method | Route | Responses |
|---|---|---|
| GET | `/api/call-story?q=<input>[&sa=<SA-number>]` | `200` story · `400` unrecognised input · `404 {"status":"not_found"}` · `409 {"status":"ambiguous","candidates":[{type, wo_number, created, garage}]}` · `422` not ERS / older than 540 days / history gone · `429` rate limit · `503` SF unavailable or busy |
| POST | `/api/call-story/narrative` `{sa_id}` | `200` narrative (§7.3). It uses only the cached composed facts. With no cached story → `409 {"status":"load_story_first"}` |

`sa` picks the leg when a WO has more than one member-facing SA (`MULTI_SA`). The raw bundle is keyed by WO, so switching tabs
costs 0 SF calls.

### 7.2 Response (spec §13, completed)
```jsonc
{
  "meta": { "rules_version": "cs1", "engine_version": "e1", "verdict_rules_version": "r1",
            "fetched_at": "…Z", "cache": "hit|miss", "sf_calls": 7, "partial": false,
            "snapshot_used": { "territory_id": "0Hh…", "date": "2026-09-28", "built_at": "…", "provisional": false } | null },
  "resolution": { "input": "05173612", "input_type": "wo|sa|call_key|source_call_id|id",
                  "wo": { "id": "0WO…", "number": "05173612", "call_key": "084-…", "source_call_id": null },
                  "legs": [{ "sa_id": "08p…", "number": "SA-…", "work_type": "…", "role": "member|drop_off", "selected": true }] },
  "header": { "work_type": "Battery", "tow": false, "source": "DRR", "priority": "@H", "city": "…", "postal_code": "…",
              "grid": { "id": "…", "name": "WM025" }, "final_garage": "100 - …", "channel": "fleet",
              "channel_path": [{ "ts": "…Z", "garage": "076DO", "channel": "towbook" }],
              "matrix_ladder": [{ "rank": 2, "garage": "063 BISON…", "worktype": "…", "hours": "Mon–Fri 8a–5p",
                                  "state": "skipped_closed|tried|declined|rejected|final|not_reached", "inferred": true }],
              "matrix_as_of": "current", "opted_in_sms": true, "end": { "status": "Completed", "resolution": "G102", "clear": "…" } },
  "pta": { "basis_ts": "…Z", "initial_min": 90, "final_min": 120, "due_initial": "…Z", "due_final": "…Z",
           "arrival": "…Z", "arrival_source": "actual_start|history", "graded_against": "initial",
           "met_initial": false, "met_final": true, "margin_initial_min": -15, "rebased": { "ts": "…Z", "actor": "Integrations Towbook" } | null },
  "events": [{ "id": "E12", "ts": "…Z", "kind": "E09_garage_change", "actor": "…", "actor_class": "HUMAN",
               "channel": "towbook", "summary_code": "MOVED_TO_SPOT", "fields": [{ "field": "ServiceTerritory", "old": "…", "new": "…" }],
               "leg": "member", "hidden": false }],
  "segments": [{ "id": "G3", "kind": "S7", "from": "…Z", "to": "…Z", "minutes": 48.1, "stuck_type": "NO_OWNER",
                 "owner": "dispatcher", "garage": "642 …", "channel": "on_platform_contractor", "driver_state": null,
                 "baseline": { "p50": 3.5, "p75": 5.2, "p90": 6.5, "p95": 12.1, "n": 104, "key_level": "segment_all_channels",
                               "days_covered": 56, "window": ["2026-07-30", "2026-09-23"] } | null,
                 "floor_min": 10, "severity": "OK|SLOW|STUCK|CRITICAL", "severity_reason": "p95|pta_passed|floor|always_flag",
                 "event_ids": ["E9", "E14"] }],
  "sms": { "source": "send_log|messaging_session", "log_starts": "2026-09-01",
           "delivery": { "available": false, "label": "Sent ≠ delivered: delivery to the phone is not visible to FleetPulse" },
           "rows": [{ "ts": "…Z", "label": "Still working on it (30 min)", "definition": "Message_3_…",
                      "outcome": "sent|failed|skipped", "reason": null, "inferred": false, "delivery_status": null }],
           "why_not": [{ "code": "TIMER_RESTARTED", "restarts": 4, "text_key": "…" }] },
  "causes": [{ "code": "C04", "name": "ORPHANED_AFTER_REJECT", "headline": true, "event_ids": ["E9"], "segment_ids": ["G3"],
               "evidence": { "minutes": 48.1, "acted_by": "Domingo Santiago" }, "verdict_code": null, "lever": "L08",
               "diagnosis": null }],
  "verdict": { "source": "day_snapshot|partial|none", "primary": "CAPACITY_SHORT", "flags": ["OPTIMIZER_CHURN"],
               "evidence": { … },          // same evidence object as the Day view
               "note": null | "Decision not graded: garage-day not built",
               "build": { "territory_id": "0Hh…", "date": "2026-09-28", "allowed": true } | null },
  "bullets": [{ "text": "…", "cause_codes": ["C09"], "event_ids": ["E7"] }],   // deterministic template, always present
  "data_notes": [{ "code": "OUT_OF_GRID|MULTI_SA|PRE_SMS_LOG|CALL_CAP|NO_BASELINE|TOWBOOK_ACTUALSTART_EMPTY|HISTORY_COUNT_CHECKED", "text": "…" }],
  "raw_history": null                                   // only with &raw=1, same gate
}
```
Never returned: phone numbers, member name, membership number, street address, `ERS_Reason_for_changing_Facility__c` (T2).

### 7.3 Narrative (AI, cause codes only)
- Fact sheet = `events` (id, kind, actor_class, display actor), `segments` (kind, minutes, severity, baseline p-values + n), `causes`
  (code + evidence), `verdict`, `pta`, `sms.rows` (label, outcome).
- Drivers and dispatchers are anonymised ("Driver A", "Dispatcher B") per the `report_card_ai.anonymise_drivers` setting
  (default true). The UI maps the names back.
- Output: `{ "sentences": [{ "text", "event_ids", "cause_codes" }] }`.
- **Validator** (`report_card_ai`). Each of these must appear in the facts:
  - every number,
  - every person label,
  - every cause code (in the fired causes),
  - every event id (in the event list).

  Policy diagnosis must say "consistent with", never "caused by". One retry, then the template with `validation.passed = false`.
- Cached by `(fact_hash, prompt_version "cs-narr-1", model)` in the file store.
- Shown **below** the deterministic bullets, only after the user clicks **Write summary**. Never on page load.
- With no cause fired, the fixed sentence from spec §8 is used and the AI is not called.

### 7.4 Frontend placement
- **Page** `/call-story?q=…[&sa=…]`. The URL is the source of truth, so links can be shared.
- **Layout, top to bottom:**
  1. input box ("SA#, WO#, call key or source call ID")
  2. StoryHeader + PTA badge
  3. StoryVerdict (headline cause, bullets, verdict block / Build garage-day, Write summary)
  4. SegmentStrip
  5. MatrixLadder
  6. StoryTimeline with SMS interleaved; raw toggle
  7. SmsSummary
  8. data notes
- **Ambiguous** (`409`): a two-option picker. **Loading:** skeleton + "Reading Salesforce (about 3 s)".
- **Entry points:**
  1. **Top-nav search (`Layout.jsx`), only for users with the permission and the flag:**
     - A call key or 18-char Id navigates to `/call-story?q=`.
     - SA# keeps opening the SA report modal (unchanged for everyone, including contractors).
     - Each WO/SA result row in the dropdown gets a small "Story" link.
  2. **Gantt `CallPanel`:** "Open call story" → `/call-story?q=<SA number>` (same tab, browser Back returns to the Day view
     with the URL state intact).
  3. The Report Card nav entry is unchanged. The story is reached by search or from a call.
- **Render cost:** one fetch per story, timeline memoised on `meta.fetched_at`, no polling. After a Build click, the page polls
  the existing build status (3 s, 3 min max), then re-fetches the story.

---

## 8. Risks, open items and tests

### 8.1 Open items (need Henry or the user before build)
| # | Item | Proposal |
|---|---|---|
| O1 | D2 grades the story on the **original** PTA; report card r1 used the final PTA. | **Resolved (Henry, 2026-10-04):** rules **r2** = r1 + `pta_basis: "initial"` (≤ 5 s after creation, same rule as cs1 §4.4); r1 stays for comparison (metrics-spec §7.7). Needs `ERS_PTA__c` in the Q2 history pull (builder `rc-build-1.1`) and rebuilds. Measured: 9/28 PTA met 65/82 → **64/82**, **0 verdict codes change** (every re-base in 2,408 sampled calls was Integrations Towbook on an INBOUND_CASCADE call). |
| O2 | Golden 10.2 on-scene 56.5 min vs S6 floor 60. | **Resolved: the golden was wrong, the rule stands.** 56.5 min battery is SLOW (battery p75 40.8, p90 56.3) but under the 60-min floor, so C15 does not fire. The golden had used the all-work-type p90 and ignored the floor. The floor stays: a 0.2-min margin over p90 on a driver-owned stage is noise. Spec 10.2 corrected. |
| O3 | Golden 10.3 S3 68.7 min: STUCK vs CRITICAL (PTA passed during it). | **Resolved: the golden was wrong; the rule stands, tightened.** CRITICAL when the **original** PTA passes during a **pre-arrival** segment that is **at least SLOW** (spec §5.3, §12 `critical_if_pta_passed` object). 10.3 is STUCK by percentile and the PTA passed, so it is CRITICAL. The guards stop a normal 2-min segment that straddles the deadline from reading CRITICAL. Spec 10.3 corrected. |
| O4 | D3 "supervisors+": `scheduler.report_card` today = superadmin, admin, executive, ers-director. | If a `supervisor` role exists, adding it is one line and applies to both features. User confirms. |
| O5 | 10.4 S7 baseline (642 n < 30). | **Approved (product owner, 2026-10-04):** level 4 = S7/S8/S9 pooled across all channels and garages (dispatcher-owned waits only). First data from the 20 ROI snapshots: S7 pooled n = 76, p90 7.3, p95 14.7, so 10.4's 48.1 min is CRITICAL. S8 n = 20, floors only. Spec §5.2 / §12 updated. |
| O6 | 56-day snapshot coverage for norms (§5). | User decides: gentle manual builds for the pilot or wait for the backfill worker. |
| O7 | Spec §7.4 flow logic from 8/13 local metadata. | **Resolved (Henry, 2026-10-04, Tooling API read-only):** the production active versions (30/50 min v4 9/09, 80 min v5 9/15) **match** on trigger, entry criteria, "only when changed", +30/+50/+80 paths and decisions. Production adds `SMS_Send_Log__c` logging and fixes the 80-min phone check (local `EqualTo False` bug). In both, the path's status re-check is always true (OR of ≠), so the platform's path cancellation is the real guard. The outcome is unchanged. Flow owner: OR → AND. |

### 8.2 Risks and edge cases
| Risk | Handling |
|---|---|
| Tow Drop-Off | Shown as a collapsed second leg with its own SMS rows. Never in segments, PTA, causes or norms (the segment extractor rejects `is_drop_off`) |
| Towbook timestamps | Arrival from history On Location; `ActualStartTime` ignored (empty → data note). S4 has its own Towbook baseline. Final decision per §4.2 |
| DST / Eastern | Everything stored in UTC. ET blocks and daytype use `America/New_York`. TimeSlots use `OperatingHours.TimeZone`. Fixtures cover 2026-11-01 |
| Empty / odd data | WO with no SA → header + "no service appointment". No history (> 18 months) → `422`. Canceled before assignment → S1 only + C18. `MULTI_SA` → tabs |
| History > 2,000 rows | `COUNT()` check at ≥ 1,000; mismatch → retry once, then `partial: true` + note |
| Current-value config (matrix, hours, skills) | Labelled "current". C01 is marked "inferred" |
| INBOUND_CASCADE counts any territory move, including SPOT and back to the same garage | Same as the report card (shared `sa_record`), so the two agree. Henry may refine it in a later rules version |
| Load | ≤ 12 calls hard cap, sequential, per-WO dedupe, `Semaphore(2)`, 10/min/user, 24 h cache for closed calls |
| Permissions / PII | Server-side gate on every route; contractor layout never mounts the route; PII field list in §7.2 |
| Startup DDL / production Postgres | None. File store only. No test touches SF or Postgres |

### 8.3 Unit tests (Ruby, pytest, no network)
- Fixtures are the 4 golden calls captured **once** by Henry's `story.py`, anonymised in the scratchpad (fake names; Ids kept
  only if the user agrees, otherwise remapped), plus a synthetic DST case.
- `test_call_story_resolve`: each input type, ambiguity → 409, non-ERS → 422, regex rejects injection.
- `test_call_story_events`: grouping, CALL_TAKER, Towbook final decision (T5), initial PTA = last row ≤ 5 s, E08 attribution rule.
- `test_call_story_segments`: the S1–S9 golden minutes; the same function on a snapshot record gives the same rows; drop-off rejected.
- `test_call_story_norms`: anchored window, the fallback chain, n < 30 → floors only.
- `test_call_story_causes`: the cause set per golden, headline rule.
- `test_call_story_sms`: opt-out reason, timer restarts = 4 on 10.4, pre-9/1 label.
- `test_call_story_api`: flag off 404, contractor 403, 429, `sf_calls` ≤ 12 with a recorder that also asserts no `sf_parallel`.
- `test_report_card_ai`: unknown number, name, cause or event id → template.

### 8.4 Acceptance (Tamy, after deploy with `call_story` on for admins)
Use `https://fslapp-nyaaa.azurewebsites.net`, logged in as an admin. Golden values are spec §10. O2/O3/O5 must be settled first.

1. Report Card → WNY 100 Fleet → **2026-09-28** → build it if it isn't built yet. Then type **`SA-1074304`** in the top-nav search
   box → the SA report modal opens as today → click **Story** in the search results instead → the story page loads.
   - Expected: 3 picks in 6 min (OPTIMIZER_CHURN), Lynn Pilarski release, S3 68.7 min BUSY flagged, blocking job **SA-1074246**
     on scene 72 min.
   - Texts at +30/+50 marked "Sent", with the "Sent ≠ delivered" label visible.
   - Arrival 94.4 min, PTA 60 missed by 34. Verdict **CAPACITY_SHORT** from the day snapshot. Screenshot.
2. In the story page's own box, type **`05173612`**, then **`084-20260928-05173612`** → the same story each time (the URL `q` changes;
   the content is identical).
3. Type **`05211381`** (source call ID) → SA-1073520.
   - Expected: rank 2 063 BISON shown "closed (inferred)"; Arthur Yates Jr.; 30.0 min drive SLOW, not stuck.
   - PTA met 26 min early. "Member not opted in to texts", no SMS rows. Verdict **GOOD**, flag BYPASSED_OPTIMIZER, no stuck chips.
4. Report Card Gantt for 9/28 → click the **SA-1074927** bar → **Open call story**.
   - Expected: Katie Kelsey shown as **call taker**; Paige White pull-back (C11, **BOUNCED**); 16.7 min lost.
   - Marquan logged in / no absence / no open job (C10). Verdict BOUNCED, matching the Gantt call panel.
   - Browser Back returns to the same Gantt state.
5. Type **`SA-1067245`** (076DO, 9/24).
   - Expected: 076DO declined in 33 s, 630 in 36 s (C02), Anthony Tabb Jr rejected "Out of Area".
   - **48.1 min NO_OWNER** (S7, C04 headline). **26 min PARKED_IN_SPOT** in 000- ST SPOT with "different region than the matrix" (C05 + C19).
   - **PTA: original 90 missed by 15 (graded), re-based 120 met, "PTA re-based" chip** (C16).
   - "No 'still working' text: timer restarted 4 times" (C17). First Garage/PTA text 82 min after the call.
   - On Location from history ("ActualStartTime empty" note). Drop-off leg collapsed. Verdict NOT_GRADED_TOWBOOK.
6. Pick a completed call on a day **not** built (for example yesterday, another garage) → "Decision not graded: garage-day not built"
   + **Build garage-day** → after the build, the verdict appears **without reloading the story from Salesforce**. Kathy confirms
   in the logs: the second compose shows `sf_calls=0`.
7. Reload any story → instant. Logs show `cache=hit`, `sf_calls=0`. Each first load shows `sf_calls` ≤ 10.
8. Pick a call from August (before 9/1) → "Detailed text log starts 1 Sep 2026", rows say "Text sent (type unknown)".
9. **Write summary** on SA-1067245 → every number and name in the paragraph appears in the bullets above (hover shows events).
   Reload → identical text (cached).
10. Regression of the SA report fixes: open the SA report modal for SA-1067245 → the cascade starts at **076DO**, a separate
    "Accepted" step, response time from On Location. Log in as a **contractor** test user → the modal still opens for their own
    calls; there is no Story link, `/call-story` redirects, and `GET /api/call-story?q=SA-1067245` returns 403.
11. Type `hello`, then `SA-99999999` → a clear "not a call number" / "not found" message, no spinner left behind.

---

## 9. Rollout notes (Kathy)
- **Env vars:** none. **Migrations:** none. Story raw bundles, segment files and AI outputs go to the slice 1 file store
  (`/home/fslapp/report_card/`, subfolder `stories/`). Same append-only rule. Size: about 20–60 KB per story, 24 h reuse; Kathy watches the folder.
- **Flag:** `call_story` default off → on for admins → supervisors after Tamy signs off. **Rollback:** flag off (instant), then
  revert the commit. The SA report fixes are a separate commit, so they can be reverted alone.
- **Packaging:** no new Python or npm dependencies. `main.py` +1 line (580/600).
- **Order:** SA report fixes commit → story backend (flag off) → frontend → flag on for admins → Tamy steps 1–11.
- **Monitoring:** the per-story log line (`sf_calls`, `ms`, `cache`, `snapshot_used`), plus a daily count of stories and SF calls.
- **Release notes:** `RELEASE_NOTES.md` entry + tag per the usual process.
- When ops_002 (Postgres) lands, the file store helpers move behind the same functions. No story code changes.
