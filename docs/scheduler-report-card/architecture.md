# Scheduler Report Card: Architecture (Phase 1 + Auditor Mode + Policy Diagnosis + Phase 3 Twin / 3b Sandbox design)

Owner: Dan (architecture) · Metrics and verdict rules: Henry (`metrics-spec.md`, same folder) · Build: Ruby · QA: Tamy · Release: Kathy
Status: DRAFT for user approval · 2026-10-03 · Henry's `metrics-spec.md` (m1 / r1 / e1) folded in: §3–§7 of the spec are the source for 5.3, 6 and 7 here
Call Story (type a call, see what happened and why): designed separately in `call-story-architecture.md` (same folder).

**Pilot:** 100 - WESTERN NEW YORK FLEET (`0HhPb00000007qGKAQ`). Validation day: Mon 2026-09-28 (90 SAs, all Fleet).
Secondary: 076DO 2026-08-31 (On-Platform contractors). Towbook example: 076DO 2026-09-24. 076DO can't be the
scheduler pilot: it moved to Towbook on 2026-09-01.

---

## 1. Goal

For one garage and one **past** Eastern-time day, show what the scheduler did and how well
it did it: a driver-day Gantt, metric scorecards, a garage → driver → call drill-down, a
deterministic **verdict on every SA decision** (auditor mode), and an AI verdict written only
from a deterministic fact sheet. Across many days and garages, a **Patterns** view shows where
the scheduler succeeds and fails, with AI recommendations written only from aggregated pattern
facts.

Each garage-day is built from Salesforce **once** and stored as an immutable snapshot in
Postgres. Metrics, SA verdicts, patterns and narratives are all recomputed from snapshots.
Re-scoring, changing thresholds or re-wording never touches Salesforce again.

Metric meaning, verdict codes and threshold values belong to Henry. This design defines the
**slots** they plug into (sections 6 and 7), not the formulas.

### Design principles
1. **Layers, each recomputable from the one before it.** Snapshot (raw facts) → metrics + SA
   verdicts (versioned) → patterns (SQL aggregates) → narrative (AI, cached by fact hash).
2. **One Salesforce build per garage-day.** Queries run sequentially, past days only. Backfill is
   nightly and rate-limited.
3. **Append-only storage.** Rebuilds and re-scores add rows. Nothing is overwritten or deleted.
4. **Channel is a per-SA fact captured at build time.** Never derived from the garage's current
   setup (5.3).
5. **Thresholds are config, versioned and immutable.** Every verdict row records the rules version
   that produced it, so results from different runs are comparable.
6. **Graceful degradation.** Every metric or verdict can be "not applicable, with a reason", and the
   page still renders (Towbook days, missing optimizer data, missing GPS).

---

## 2. Placement: its own page, not a GarageDetail tab

**Decision:** a new page at `/report-card` with two views:
- **Day**: `/report-card?garage=<territoryId>&date=YYYY-MM-DD[&driver=<key>][&sa=<SA number>]`
- **Patterns**: `/report-card/patterns?garages=<id,id>&from=&to=&rules=<version>[&cell=…]`

GarageDetail gets a header link into it.

Why not a fifth tab in `GarageDetail.jsx`:
- `GarageDetail` is also mounted in the **contractor portal** (`/contractor/garage/:id`,
  `App.jsx:86`). This report exposes other drivers' workloads and dispatcher behaviour, so it is
  internal-only.
- The existing tabs are about this week or today. The report card is a past-day forensic view
  with its own pickers, plus a multi-garage Patterns view. Neither fits under one garage.
- Phase 2 (map replay sharing the Gantt's time scrubber) needs the full viewport.

The existing `/api/garages/{id}/simulate` and the Dispatch Map tab stay untouched.

**Navigation:** a "Report Card" link in `Layout.jsx`'s top nav, shown only when the feature
flag is on **and** the user has the permission (section 10). A GarageDetail header link to
`/report-card?garage={id}` follows the same gate and is hidden in the contractor layout.

---

## 3. Files

### Backend (new). Every file stays under 600 lines.
| File | Purpose | Target |
|---|---|---|
| `backend/routers/report_card.py` | Day routes: day payload, build, status, day verdict (9.1). | ~250 |
| `backend/routers/report_card_patterns.py` | Patterns, examples, pattern insight, rules versions, backfill admin (9.2, 9.3). | ~280 |
| `backend/report_card_build.py` | Salesforce pull plan (5.2), sequential only, completeness checks. | ~350 |
| `backend/report_card_snapshot.py` | Raw bundle → snapshot JSON (4). Pure, no I/O. Owns `SNAPSHOT_SCHEMA_VERSION`. | ~400 |
| `backend/report_card_metrics.py` | Metric registry + Henry's formulas (6). Pure. Owns `METRICS_VERSION`. | ~400 |
| `backend/report_card_verdicts.py` | SA feature extraction + verdict rule functions (7). Pure. Thresholds injected from a rules version. | ~450 |
| `backend/report_card_patterns.py` | Whitelisted GROUP BY builders, lift/support math, pattern fact sheet (8). | ~300 |
| `backend/report_card_ai.py` | Fact sheet → prompt → validated output, template fallback; day + pattern prompts (11). | ~300 |
| `backend/report_card_backfill.py` | Nightly queue worker: leader lock, time window, pacing, SF-limit guard (12). | ~250 |
| `backend/repositories/report_card.py` | Snapshot / metrics / day-verdict persistence. | ~250 |
| `backend/repositories/report_card_audit.py` | SA verdict rows, rules versions, backfill queue, pattern insights, aggregate SQL. | ~350 |
| `infra/postgres/migrations/ops_002_scheduler_report_card.sql` | Additive DDL + `schema_migrations` row (13). | ~200 |
| `backend/tests/test_report_card_*.py` + `backend/tests/fixtures/report_card/*.json` | Section 14. | n/a |

### Backend (changed, small)
| File | Change |
|---|---|
| `backend/main.py` (578 lines) | Two router includes and one line to start the backfill thread (`report_card_backfill.start()`, a no-op unless the flag and env enable it). About +4 lines. **No startup DDL** (13.1). |
| `backend/feature_flags.py` | `'scheduler_report_card': False`. |
| `backend/permissions.py` | `"scheduler.report_card": {"superadmin","admin","executive","ers-director"}` (view). `"scheduler.report_card_admin": {"superadmin","admin"}` (rules versions, backfill, forced rebuild). Henry or the user confirms whether `supervisor` gets view access. Never `contractor`. |
| `backend/optimizer_retention.py` | Comment only: `ops.src_*` must never be added to `PURGE_TABLES`. |

Explicitly **not** reused as-is:
- `simulator.simulate_day`. It queries in parallel, uses **UTC** day bounds, takes today's
  roster (`IsActive = true`), and labels channel from `ERS_Dispatch_Method__c`. Henry also measured
  (spec §9) that it has no on-shift gate and no GPS age limit, and its skill gate reads WorkType
  `SkillRequirement` (0 rows). Together these halve closest-picked (22% vs 44% on 9/28).
  `dispatch_utils.classify_dispatch` and `_SYSTEM_USERS` are also not used (they lump the FSL engine in
  with integrations); the report card uses the B4 actor classes. The builder reuses
  its *logic* (closest-eligible evaluation, reassignment reasons) through the pure helpers.
- `dispatch_utils.fetch_gps_history`. It is parallel. The builder uses sequential
  `sf_batch.batch_soql_query` with the same SOQL and reuses the parsing.

Reused directly: `dispatch_utils.parse_assign_events`, `build_truck_login_hist`, `gps_at_time`,
`utils.haversine`, `utils._ET`, `utils.load_ai_settings`, `utils.call_openai_simple`,
`sf_batch.batch_soql_query`, `sf_client.sanitize_soql`, `sf_client.sf_rest_get` (limits check),
`cache.fs_lock_acquire/release` (backfill leader), `simulator._build_reassign_reasons`
(promote to `dispatch_utils.py` only if it stays under 600 lines; it is at 509).

### Frontend (new)
```
frontend/src/pages/SchedulerReportCard.jsx        shell: Day | Patterns view switch, URL state     (~200)
frontend/src/components/reportcard/
  -- Day view --
  DayView.jsx               pickers, build/poll, layout of the day
  ReportCardPickers.jsx     garage select (existing /api/garages) + MiniDatePicker, max = yesterday ET
  BuildStatus.jsx           not built / building (poll) / failed + retry / provisional banner
  ChannelBanner.jsx         channel mix; Towbook or mixed explanation (5.3)
  ScorecardGrid.jsx         renders metric tiles generically from the registry response
  MetricTile.jsx            value, n, "not applicable: reason", popover → spec_ref
  VerdictSummary.jsx        count of SAs per verdict code for the day; click filters the Gantt
  DayGantt.jsx              axis, rows, needle; colour by source | verdict toggle          (~300)
  GanttRow.jsx              one driver: shift band, absences, per-SA segments
  useTimeScale.js           minute ↔ % mapping, DST-safe ET ticks; shared with Phase 2 replay
  DriverPanel.jsx           driver drill-down
  CallPanel.jsx             one SA: timeline, assign events, candidates, VERDICT + evidence;
                            "Open full SA report" → existing SAReportModal (explicit click)
  AiVerdictCard.jsx         structured day verdict with fact citations, "template" badge
  -- Patterns view --
  PatternsView.jsx          filters + coverage + matrix + examples + insight
  PatternFilters.jsx        garages (multi), date range, rules version, channel, row/column dimension
  CoverageBar.jsx           built garage-days vs requested (patterns are only as good as coverage)
  PatternMatrix.jsx         heatmap: row dim × column dim, cell = failure rate (n shown), click → examples
  PatternExamples.jsx       example SAs for a cell → link to Day view (?garage&date&sa)
  PatternInsightCard.jsx    AI recommendations with fact citations
frontend/src/components/AdminReportCard.jsx       rules versions (view, clone-and-edit JSON, activate),
                                                  backfill queue (enqueue range, status, pause)
```

### Frontend (changed)
| File | Change |
|---|---|
| `frontend/src/api.js` | Day: `fetchReportCardDays`, `fetchReportCard`, `buildReportCard`, `fetchReportCardStatus`, `fetchReportCardVerdict`. Patterns: `fetchPatterns`, `fetchPatternExamples`, `fetchPatternInsight`. Admin: `fetchRulesVersions`, `createRulesVersion`, `activateRulesVersion`, `fetchBackfill`, `enqueueBackfill`, `pauseBackfill`. |
| `frontend/src/App.jsx` | `/report-card` and `/report-card/patterns` routes inside the main `Layout` only. |
| `frontend/src/components/Layout.jsx` | Nav link (gated). |
| `frontend/src/pages/Admin.jsx` (481 lines) | One tab entry that mounts `AdminReportCard` (admin permission). |
| `frontend/src/pages/GarageDetail.jsx` | Header link (gated). No new tab. |

### Gantt: port vs. build fresh
**Build fresh in JSX; borrow the visual grammar from the Towbook `StudioGantt.tsx`.** Do not port the code.
- `StudioGantt.tsx` (351 lines) and `StudioSimulationReportModal.tsx` (1,261 lines, already over our
  limit) are tied to `ScenarioDoc`/`StudioUnit` types, `chainSlots`/`projectUnit`, `tfs-*` CSS,
  Material Symbols and a live sim clock. Porting means porting that whole model.
- What we take, as ideas only (read-only, nothing changes in that repo): one row per driver; a
  **thin line for travel** and a **solid block for on-scene time**; `pct(minute)` absolute
  positioning over a padded span; hour ticks; a clock needle. That needle becomes the Phase 2
  scrubber.
- Plain absolutely-positioned `div`s + Tailwind. About 40 rows × about 300 bars needs no canvas
  or virtualisation. No new npm dependency.

Gantt encoding (legend always visible):
- Shift band: light background (shift, or truck login → logout, 5.2). Absence and lunch: hatched.
- Per SA (spec §4 segments): **queued** `t_asg → t_disp` (dashed), **dispatched** `t_disp → t_acc/t_er`,
  **en route** `t_er → t_ol` (thin), **on scene** `t_ol → t_end` (solid); **idle** = on-shift time with zero
  open jobs; **off shift / absence** grey with the absence Type. Overlapping bars on one row = stacking.
  Assignments made before truck login are drawn and flagged (8 on 9/28).
- Colour mode toggle: **by assignment source** (system / human / FSL engine / unknown) or
  **by verdict** (Henry's palette per code). Red outline = PTA missed. Cancelled = hollow with ✕.
- Tow Drop-Off segments are drawn (real driver time), tagged, and never counted in metrics or
  verdicts.

---

## 4. Snapshot JSON shape (`schema_version: 1`)

One JSON document per garage-day version in `ops.src_snapshot.payload` (JSONB). Times are ISO-8601
**UTC**. Eastern conversion uses `America/New_York` at compute and render time. Compact tuples are
used only where volume matters (GPS, candidates).

```jsonc
{
  "schema_version": 1,
  "builder_version": "rc-build-1.0",
  "territory": { "id": "0Hh…", "name": "…", "lat": 43.1, "lon": -77.6 },
  "service_date": "2026-08-24",                    // Eastern calendar day
  "window": {                                      // DST-safe: 23h / 24h / 25h
    "day_start_utc": "2026-08-24T04:00:00Z",
    "day_end_utc":   "2026-08-25T04:00:00Z",
    "carryover_from_utc": "2026-08-23T22:00:00Z"   // created before day start, still open at it
  },
  "built_at": "2026-10-03T14:02:11Z",
  "provisional": false,                            // built < 24h after day_end

  "channel_summary": {
    "by_channel": { "fleet": 71, "on_platform_contractor": 9, "towbook": 0, "unknown": 2 },
    "mode": "fsl" | "towbook" | "mixed"
  },

  "drivers": [{
    "id": "0Hn…",                                  // ServiceResource Id, or "tb:<Off_Platform_Driver__c>"
    "name": "…",
    "driver_type": "Fleet Driver",                 // ServiceResource.ERS_Driver_Type__c, verbatim
    "channel": "fleet" | "on_platform_contractor" | "towbook" | "unknown",
    "territory_type": "P" | "S" | null,            // ServiceTerritoryMember that day
    "member_effective": ["2025-01-01", null],
    "home_base": { "lat": 43.0, "lon": -77.5 },    // ServiceTerritoryMember lat/lon (FSL home base; twin + Max-Travel-From-Home rule)
    "resource_priority": null,                     // ServiceResource priority/efficiency fields (names per sf_describe) for Resource Priority objective
    "skills": ["Tow", "Battery"],                  // current skills (no history in SF), caveat
    "skill_levels": { "Tow": 1 },                  // ServiceResourceSkill.SkillLevel (Skill Level objective)
    "shifts":   [],                                // Shift is effectively empty (spec S8); Q5 optional, off by default
    "logins":   [{ "start": "…Z", "end": "…Z", "source": "AssetHistory", "truck_id": "02i…",
                  "truck_caps": ["Tire","Lockout"] }],  // Asset.ERS_Truck_Capabilities__c: CURRENT value, no history (flagged)
    "absences": [{ "start": "…Z", "end": "…Z", "type": "Lunch" }],
    "start_position": { "lat": 43.0, "lon": -77.5, "ts": "…Z", "source": "gps" | "depot" },
    "gps": [[1724486400, 43.01, -77.52], …]        // [epoch_s, lat, lon], downsampled (5.4)
  }],

  "sas": [{
    "id": "08p…", "number": "SA-…",
    "woli_id": "1WL…",                              // ParentRecordId is the WOLI
    "work_type": "Tow Pick-Up", "is_drop_off": false,
    "call_class": "tow" | "battery" | "light",
    "in_day": true,                                 // false = carryover context only
    "status": "Completed",
    "lat": 43.1, "lon": -77.6, "city": "…", "postal_code": "14620",
    "created": "…Z", "sched_start": "…Z", "sched_end": "…Z",
    "earliest_start": "…Z", "due_date": "…Z",       // VRPTW windows (Phase 3)
    "duration_planned_min": 40, "pta_min": 45,
    "priority": 3,                                  // ERS_Dynamic_Priority__c (optimizer uses it; twin needs it)
    "required_skills": ["Tow"],                     // WOLI SkillRequirement (spec S9). WorkType SkillRequirement has 0 rows
    "pta_due": "…Z",                                // ERS_PTA_Due__c (spec S7); skip PTA <= 0 or >= 999
    "channel": "fleet",                              // spec §3: AR.ServiceResource.ERS_Driver_Type__c; no AR → last assigned driver in history
    "dispatch_method_formula": "…",                 // ERS_Dispatch_Method__c, audit only, never used
    "final_driver_id": "0Hn…",
    "decision": {                                    // spec S3/S4/B3/B4
      "final": { "ts": "…Z", "actor": "Paige White", "actor_profile": "Membership User", "actor_class": "HUMAN" },
      "first": { "ts": "…Z", "actor": "Mulesoft Integration", "actor_class": "INTEGRATION" },
      "n_pre_dispatch_picks": 6, "pullbacks": 1, "reassign_after_dispatch": 1,
      "ar_creator": { "name": "Mulesoft Integration", "created": "…Z" },  // audit only: "record creator", NOT the decider
      "scheduling_policy": null                      // FSL__Scheduling_Policy_Used__c: null on all 9/28 SAs, kept for completeness
    },
    "events": [                                      // assignment name-rows only (Id rows dropped), status rows, territory rows
      { "ts": "…Z", "field": "assigned", "driver_id": "0Hn…", "driver": "…", "actor": "…", "actor_profile": "…", "actor_class": "FSL_ENGINE" },
      { "ts": "…Z", "field": "status", "value": "Dispatched", "actor_class": "DRIVER" },
      { "ts": "…Z", "field": "territory", "from": "053…", "to": "100…" }   // history field `ServiceTerritory` (S5)
    ],
    "territory_moves": { "in": 1, "out": 0 },        // out-moves come from the region pull (Q12); out-SAs are listed, not graded here
    "milestones": {                                  // spec B2, first occurrence in SAHistory Status
      "t_first": "…Z", "t_asg": "…Z", "t_disp": "…Z", "t_acc": "…Z", "t_er": "…Z",
      "t_ol": "…Z", "t_end": "…Z", "end_status": "Completed",
      "arrival": "…Z", "arrival_source": "actual_start" | "history"   // S6: Towbook always history 'On Location'
    },
    "dispatch_geo": { "lat": 43.0, "lon": -77.5 },
    "candidate_sets": [                              // spec B6: at EVERY assignment event (≤ ~7 per SA)
      { "event_idx": 0, "ts": "…Z",
        "c": [[ "0Hn…", 43.0, -77.5, 4.2, 1, 1, 2, 6 ]] }   // [driver_id, lat, lon, miles, qualified, on_truck_not_absent, open_jobs, gps_age_min]
    ],
    "excluded_counts": { "not_on_truck": 9, "absent": 1, "not_qualified": 3, "stale_gps": 1 },    "cancel_reason": null
  }],

  "config": {                                       // policy diagnosis (7.6)
    "as_of": "build_time" | "daily_capture",         // see 7.6: SF keeps no history of policy config
    "captured_at": "…Z",
    "territory_flags": { "RSO_Automation_Active__c": true, "ERS_Auto_Schedule__c": true },
    "policies_used": [                               // from FSL__Optimization_Request__c.FSL__Scheduling_Policy__c that day (Q13); SA policy field is null
      { "id": "a22Pb0000088ISzIAM", "name": "Copy of Highest Priority", "seen_in_runs": 451,
        "objectives": [{ "goal": "ASAP High Priority", "weight": 120000 }, { "goal": "ASAP", "weight": 60000 },
                       { "goal": "Minimize Travel", "weight": 10 }],
        "work_rules": [{ "name": "…", "type": "Match Skills", "params": { … } }],
        "flags": { "daily_optimization": false, "commit_mode": "…" } }
    ],
    "membership_types": { "P": 18, "S": 6, "R": 0 }, // from drivers[].territory_type
    "final_by_class": { "INTEGRATION": 39, "HUMAN": 31, "FSL_ENGINE": 20 }  // 9/28 example (spec M09)
  },
  "optimizer_sf": {                                 // spec §10: SF optimizer trail, kept by FSL since 2024-12 (Q13)
    "requests": [{ "id": "a1x…", "ts": "…Z", "type": "In-Day" | "RSO", "policy_id": "a22…", "status": "…" }],
    "logs": [{ "ts": "…Z", "reason": "Idle Territory Optimization", "resource_id": "0Hn…" }],  // Optimization_Log__c
    "fsl_engine_attribution": { "events": 48, "matched_to_request": 48 }   // FSL_ENGINE picks within −1/+3 min of a request
  },
  "optimizer_pg": { "available": false, "reason": "no opt_runs in Postgres retention window" },  // optional extra detail only
  "travel_basis": { "distance": "haversine_miles", "speed_mph": 25, "source": "utils.TRAVEL_SPEED_MPH" },
  "completeness": {
    "sa_count_expected": 84, "sa_count_loaded": 84,
    "history_rows": 1210, "ar_rows": 80, "gps_points_raw": 9120, "gps_points_kept": 2410,
    "warnings": ["2 SAs have no AssignedResource (canceled before assignment)"]
  }
}
```

`candidate_sets` follow spec B6: active member that day (S10, no `IsActive` filter), on truck and not in a
`ResourceAbsence` (S8), qualified = WOLI skills ⊆ driver skills ∪ the logged-in truck's capabilities (S9),
GPS fix ≤ 30 min old and ≤ decision + 5 min (S11). `open_jobs` = spec B5 (final-driver SAs with
`t_asg ≤ t < t_end`, carryover included). One set is stored per assignment event, so verdicts use the
**decision-time** set (`t_asg`) and the first-pick view stays available. Jobs in **other** territories are
invisible (verified 0 on 9/28, not guaranteed): a caveat. LATE_DESPITE_CAPACITY also samples free
candidates every 2 min in `[created, t_asg]`. That sampling is done at build time and stored as
`evidence.free_capacity_samples`, so no re-pull is needed.

**Phase 3 readiness.** Baselines (closest-available, balanced greedy, hindsight VRPTW with
OR-Tools), the Shadow Scheduler Twin (section 18) and stress scenarios need: SA locations,
times, windows, durations, priority and skills; driver shifts, logins, absences, skills and skill
levels, home bases, resource priority, start positions; GPS; and the travel basis. All are in v1.
Phase 3 adds tables keyed on `snapshot_id` and never mutates the snapshot.

**Phase 2 readiness.** `drivers[].gps` + `sas[].milestones` drive the replay. GPS is excluded
from the main page payload.

---

## 5. Build pipeline

### 5.1 Trigger, idempotency, concurrency
- **Triggers:** (a) a user clicks **Build report** on an unbuilt garage-day (`POST …/build`,
  `202`, page polls every 3 s for up to 3 min); (b) the **backfill worker** (section 12). Both call
  the same `build_garage_day()`. Nothing builds silently on page load.
- **Past days only:** `date >= today (ET)` → `422`. Older than `REPORT_CARD_MAX_LOOKBACK_DAYS`
  (default 540, about the SF field-history window) → `422`. The build records what history it found.
- **Provisional:** built less than 24 h after `day_end_utc` → `provisional=true`. Any permitted user
  may rebuild once while provisional. Otherwise rebuild is admin-only (`?force=true`). Backfill only
  builds days ≥ 2 days old, so its snapshots are final.
- **Single-builder guard:** a partial unique index allows one `status='building'` row per
  `(territory_id, service_date)` across all workers and instances.
  `INSERT … ON CONFLICT DO NOTHING RETURNING id`. If nothing is returned, return the running build's
  status. If a current `ready` snapshot exists and `force` is false, return it.
- **Execution:** daemon `threading.Thread` (pattern from `dispatch_trends_monthly.py`) behind a
  module-level `threading.Semaphore(1)`. One build at a time per process, whether the user or
  the backfill started it.
- **Stale reclaim:** `building` rows older than 15 min → `failed` (`'stale build reclaimed'`).

### 5.2 Salesforce query plan (sequential; one garage, one day)
All filters are server-side and bounded by territory + ET window. Ruby runs `sf_describe` on every
custom field before coding (project rule).

| # | Object | Filter | Key fields | Volume (Fleet garage-day) |
|---|---|---|---|---|
| 0 | `ServiceAppointment` `SELECT COUNT()` | same as Q1 | — | 1 call |
| 1 | `ServiceAppointment` | `ServiceTerritoryId = :t AND CreatedDate >= carryover_from AND CreatedDate < day_end AND RecordType.Name = 'ERS Service Appointment'` | Id, number, ParentRecordId (WOLI), WorkType.Name, Status, times incl. ActualStartTime, lat/lon, PostalCode, ERS_PTA__c, ERS_PTA_Due__c, ERS_Spotting_Datetime__c, ERS_Dynamic_Priority__c, FSL__Duration_In_Minutes__c, EarliestStartTime, DueDate, Off_Platform_Driver__c (+__r.Name), Off_Platform_Truck_Id__c, ERS_Dispatched_Geolocation__c, ERS_Dispatch_Method__c (stored only) | 80–230 rows |
| 2 | `ServiceAppointmentHistory` | `ServiceAppointmentId IN (:ids)` batched 200; `Field IN ('ERS_Assigned_Resource__c','Status','ServiceTerritory')` | SAId, Field, Old/NewValue, CreatedDate, CreatedBy.Name, CreatedBy.Profile.Name | 1–3k rows |
| 3 | `AssignedResource` | `ServiceAppointmentId IN (:ids)` batched | ServiceResourceId, .Name, .ERS_Driver_Type__c (channel), CreatedDate, CreatedBy.Name (audit "record creator" only) | ≈ SA count |
| 3b | `WorkOrderLineItem` → `SkillRequirement` | `RelatedRecordId IN (:woli_ids)` batched | RelatedRecordId, Skill.MasterLabel | ≈ SA count |
| 4 | `ServiceTerritoryMember` | `ServiceTerritoryId = :t AND EffectiveStartDate <= day_end AND (EffectiveEndDate = null OR EffectiveEndDate >= day_start)` (no `IsActive` filter, S10) | resource, name, ERS_Driver_Type__c, TerritoryType, dates, Latitude/Longitude (home base), resource priority fields (per describe) | 10–110 |
| 4b | `ServiceResource` | drivers in assignment history not on the roster (borrowed or ex-members) | Id, Name, ERS_Driver_Type__c, RelatedRecordId (User, for DRIVER actor class) | 0–10 |
| 4c | `ServiceResourceSkill` | members | ServiceResourceId, Skill.MasterLabel, SkillLevel | 50–300 |
| 5 | `Shift` | members, overlap | — | **off by default** (spec S8: effectively empty org-wide) |
| 6 | `AssetHistory` | `Field='ERS_Driver__c' AND Asset.RecordType.Name='ERS Truck'`, window ±2h, client-filtered to members (pattern from `sa_report.py:466`; reuse `build_truck_login_hist` / `is_on_truck`) | AssetId, Old/NewValue, CreatedDate | low thousands org-wide |
| 6b | `Asset` | trucks seen in Q6 for members | Id, Name, ERS_Truck_Capabilities__c (current value, flagged) | 10–40 |
| 7 | `ResourceAbsence` | members, overlap | resource, start, end, Type | 0–20 |
| 8 | `ServiceResourceHistory` | lat/lon fields, members, window −2h/+1h, sequential batches. **No `COUNT()` on this object** (spec §14: 26–39 s and one failure) | resource, field, NewValue, CreatedDate | 5–20k rows; the slowest step |
| 10 | `ServiceTerritory` | `Id = :t` | name, lat/lon, ParentTerritoryId, RSO_Automation_Active__c, ERS_Auto_Schedule__c | 1 |
| 11 | Policy config | `FSL__Scheduling_Policy__c` + `FSL__Scheduling_Policy_Goal__c` (goal, weight) + `FSL__Scheduling_Policy_Work_Rule__c` → `FSL__Work_Rule__c` (type + parameters per describe), for policies seen in Q13. **Org-wide and small: cached once per calendar day** (`ops.src_policy_capture`), so usually 0 calls per build | 3–4 calls/day |
| 12 | Outbound moves (region) | `ServiceAppointmentHistory WHERE Field='ServiceTerritory' AND CreatedDate in window AND ServiceAppointment.ServiceTerritory.ParentTerritoryId = :region`, OldValue filtered in Python (spec §11 Q2). **One pull per region-day, cached and shared by all garages in that region** (backfill orders jobs by region-day to reuse it) | SAId, Old/NewValue, CreatedDate, CreatedBy | about 1k rows per region-day |
| 13 | SF optimizer trail | `FSL__Territory_Optimization_Request__c` for :t in window → `FSL__Optimization_Request__c` (type, policy, status, start); `Optimization_Log__c` for :t in window (spec §10) | as listed | 3 light queries; about 300–800 rows |

**About 18–35 SF API calls per build** (Henry's two full validation days used about 60 calls together),
run sequentially and recorded as `sf_calls` on the row. Cost per page view after that: **zero**.
Towbook-mode days skip Q4c, Q6, Q6b, Q8 and Q13. This is the lightest
plan that answers the question: a per-call timeline needs rows, not aggregates, but they are
bounded to one territory-day and taken once.

### 5.3 Channel rule (Henry, 2026-10-03)
- Per SA `channel` = mapping of `AssignedResource.ServiceResource.ERS_Driver_Type__c` at build time (spec §3):
  `Fleet Driver` → `fleet`; `On-Platform Contractor Driver` → `on_platform_contractor`;
  `Off-Platform Contractor Driver` (placeholder `Towbook-<code>`) → `towbook`. With no AR (canceled calls),
  the last assigned driver in history decides; with neither → `unknown`. The mapping lives in the rules
  JSON (`channel_map`), so a new driver type is a config change.
- Towbook days: the person who did the work is `Off_Platform_Driver__c` / `Off_Platform_Truck_Id__c`.
- On-Platform contractors: "idle" is an upper bound (spec C3: non-AAA work is invisible). Labelled on screen.
- **Never** `ERS_Dispatch_Method__c` / `ERS_Facility_Dispatch_Method__c`. They are formulas on the
  facility's *current* method and relabel history (076DO went Towbook on 2026-09-01). The value is
  stored as `dispatch_method_formula` for audit only.
- Day mode: `fsl` / `towbook` / `mixed`.
  - `towbook` day: **workload-only.** Gantt + workload metrics where Henry marks them applicable.
    No scheduler grade, no closest-driver, no scheduler verdict codes (SA verdict
    `NOT_GRADED_TOWBOOK`), workload-only AI prompt.
  - `mixed` day: grades on the FSL Platform subset; the banner shows the Towbook count excluded.
- Channel is frozen in the snapshot, so later channel changes never rewrite old report cards or
  pattern history.

### 5.4 GPS downsampling
Keep a point if ≥ 120 s since the last kept point or moved ≥ 0.1 mi. Always keep the nearest point at
or before each assignment event. Candidates are computed from **raw** GPS before downsampling.

### 5.5 Optimizer data: SF trail first, Postgres optional
- **Primary (always): the SF optimizer trail** (Q13). `FSL__Optimization_Request__c` has kept about 292k rows
  since 2024-12-13, plus `FSL__Territory_Optimization_Request__c` and `Optimization_Log__c`. It is snapshotted
  per garage-day, so FSL_ENGINE attribution (spec B4: `Platform Integration User` = FSL optimizer, 48/48
  events within −1/+3 min of a request on 9/28) and the policy actually used **never depend on Postgres
  retention**.
- **Optional: Postgres `optimizer.*`** for extra per-decision detail when rows still exist (the default
  3-day retention means usually not). `available:false` is normal and nothing depends on it.

### 5.6 Completeness and failure handling
- `sf_query_all` can stop silently if a page errors. Q0 `COUNT()` must equal Q1 loaded rows. Retry Q1
  once, then fail (`'SA count mismatch 84 vs 61'`). Nothing is marked `ready` without a match.
- Any exception → `status='failed'`, `error` (≤ 1,000 chars), `sf_calls` so far. The previous
  current snapshot stays current.
- SF circuit breaker open → fail fast, `'Salesforce unavailable'`. The backfill worker then stops
  for the night (12.3).

### 5.7 After build (one pipeline, same code for user and backfill builds)
1. In one transaction: `status='ready'`, flip `is_current` from the old version to the new one.
2. Compute metrics for `METRICS_VERSION` → `ops.src_metrics`.
3. Compute SA verdicts for the **active** rules version → `ops.src_sa_verdict` (section 7).
4. The day verdict (AI) is lazy, generated on first view.

Steps 2–3 are pure CPU over the payload (well under 1 s for about 150 SAs).

---

## 6. Metrics plug-in contract (Henry's spec)

`report_card_metrics.py` holds a registry, with one function per metric in `metrics-spec.md`. The API
and UI are generic, so a new metric is one function + one registry entry, with no frontend change.

```python
METRICS_VERSION = "m1"   # bump on any formula change → recompute from snapshots, no SF

@metric(id="M01", family="load_balance", scope=("garage", "driver"),
        label="…from spec…", unit="ratio|pct|count|minutes|miles",
        channels=("fleet", "on_platform_contractor"),
        needs=("gps",),                       # optional data dependencies
        spec_ref="metrics-spec.md#m01")
def m01(snap: Snapshot, scope_key: str | None, rules: Rules) -> MetricResult: ...
```

`MetricResult`:
```jsonc
{ "id": "M01", "value": 0.42, "display": "0.42",
  "numerator": 21, "denominator": 50, "n": 50,
  "applicable": true, "reason": null,
  "band": "good" | "watch" | "bad" | null,     // band thresholds come from the rules version (7.2)
  "drill": { "sa_ids": ["08p…"], "driver_ids": ["0Hn…"] },
  "spec_ref": "metrics-spec.md#m01" }
```

The registry's applicability gate (channel, `needs`, Tow Drop-Off, `in_day`) runs **before** the
formula. Formulas receive `snap.scored_sas()` with exclusions already applied, so no formula can
forget the Gold Rules.

**m1 registry = spec §5:** M01–M21 plus T01 (load, stacking, source, outcome, bounce, closest, quality,
towbook). Metrics marked T apply on Towbook days. Bands come from the rules version (`metric_bands`). Changes the
spec forces on this design:
- "Source" means the **final decision actor class** (spec S4/B4: actor on the last
  `ERS_Assigned_Resource__c` name-row), with first-pick class alongside. `AR.CreatedBy` appears only as an audit
  column labelled "record creator" (it differed from the final actor on 25/82 SAs on 9/28).
- M12/M13 by source are confounded (the optimizer touches calls already in trouble). The UI shows n, never
  ranks under n = 30, and the AI prompt forbids "the optimizer performs worse" claims.
- M17–M20 distances are straight-line. The screen shows the basis (AR's own estimate is 1.42× the
  straight line, which points to road routing).
- Bounce = pullback (status → Spotted after Dispatched/Accepted/En Route) or a driver change after
  dispatch. Optimizer reshuffles before dispatch are `OPTIMIZER_CHURN`, not bounces.
- Headline tile: **M20 "qualified driver available but not picked"** (spec §8).

Golden values for Tamy (spec §6, real data, checked in acceptance, not unit tests): WNY 100 on 9/28:
90 SAs; PTA met 65/82; M17 38/87; M20 (a) 3/80, (b) 0/80; M09 final Integration 39 / Human 31 / FSL 20.

---

## 7. Auditor mode: per-SA decision verdicts

### 7.1 What a verdict is (codes from spec §7.1)
Every SA gets **one primary code** (first match in precedence) plus **all matched flags**, judged at the
**final decision** (`t_asg`) against the decision-time candidate set.

| # | Primary code | Failure? |
|---|---|---|
| 1 | `NOT_GRADED_TOWBOOK` | not graded |
| 2 | `NOT_GRADED_CANCELED_PRE_ASSIGN` | not graded |
| 3 | `INBOUND_CASCADE` | context |
| 4 | `BOUNCED` | **yes** |
| 5 | `NOT_GRADED_INSUFFICIENT_DATA` | not graded |
| 6 | `STACKED` | **yes** |
| 7 | `FAR_PICK` | **yes** |
| 8 | `LATE_DESPITE_CAPACITY` | **yes** |
| 9 | `LATE_EXECUTION` | context (driver side) |
| 10 | `CAPACITY_SHORT` | context (capacity) |
| 11 | `GOOD_NO_ARRIVAL` | no |
| 12 | `GOOD` | no |

**Flags** (non-exclusive pattern dimensions): `BYPASSED_OPTIMIZER` (final actor INTEGRATION, HUMAN or
GARAGE_DISPATCHER), `HUMAN_FINAL`, `OPTIMIZER_CHURN`, `SLOW_RELEASE`, `MISSED_REBALANCE`,
`SKILL_MISMATCH`, `ASSIGNED_OFF_SHIFT`. `BYPASSED_OPTIMIZER` is a flag, not a code, because it says *who*
decided, not *how well* (as a code it would hide 70 of 90 decisions on 9/28).

Spec 9/28 distribution (golden check): GOOD 54, CAPACITY_SHORT 10, BOUNCED 7, INBOUND_CASCADE 7,
GOOD_NO_ARRIVAL 6, LATE_DESPITE_CAPACITY 2, LATE_EXECUTION 2, INSUFFICIENT_DATA 2, STACKED 0, FAR_PICK 0.
Failure rate 9/81 = 11%. 076DO 8/31: 48%.

What verdicts can't see, shown on screen (spec §7.5): availability is observed, not counterfactual;
contractor non-AAA work; skills and truck capabilities are current values; distances are straight-line;
open jobs in other territories.

### 7.2 Rules versions: thresholds are config, never code
- Code: `report_card_verdicts.py` has **one pure function per code and flag** (spec §7.2 logic):
  `fn(features: SaFeatures, params: dict) -> Match | None`. No expression language, no `eval`.
- Config: `ops.src_rules` rows, **immutable**. Exactly one is `is_active`. Editing = clone → change → new
  version → (optionally) activate. Old verdict rows keep their version.
- Every verdict row carries `rules_version` **and** `engine_version`. Comparable means both match.
- Validation on save: JSON schema (known codes, numeric ranges, precedence covers every code); unknown keys
  are rejected.
- **Seed `r1` = spec §7.6 verbatim**, plus three blocks this design adds:
  ```jsonc
  {
    /* … spec §7.6: precedence, failure_codes, context_codes, actors, candidate, params, bands,
         metric_bands, min_support … */
    "channel_map": { "Fleet Driver": "fleet", "On-Platform Contractor Driver": "on_platform_contractor",
                     "Off-Platform Contractor Driver": "towbook" },
    "user_pending": {                      // spec §13 assumptions awaiting the user; config, never code
      "pta_target": 0.85,                  // drives metric_bands.M13 (placeholder until the business target is given)
      "human_class_source": "profile",     // "profile" (Membership User) | "dispatcher_roster" (existing core.dispatchers table, sf_user_id)
      "pullback_is_bounce": true
    },
    "diagnosis_map": [ /* 7.6 */ ]
  }
  ```
- Actor classes (spec B4) are evaluated in order: FSL_ENGINE (`Platform Integration User`, `FSL System
  User`), INTEGRATION (Mulesoft, Replicant, IT System User), TOWBOOK_SYNC, DRIVER (actor name matches a roster
  ServiceResource, or Fleet Driver profile; this catches e.g. a driver whose User profile is Membership User),
  GARAGE_DISPATCHER (Partner Community User, not a driver), HUMAN, OTHER. The lists are rules config, so a new
  account is a new version, not a deploy. **This replaces the earlier draft's "system accounts" list, which
  would have flagged the optimizer's own picks as bypass.**
- AI driver anonymisation is **not** a scoring rule, so it lives in the settings table
  (`report_card_ai.anonymise_drivers`, default `true`, user-pending) and is recorded in each AI output's
  fact sheet.

### 7.3 Features (dimensions) per SA, computed once (spec §7.3)
| Feature | Source |
|---|---|
| `hour_et`, `dow`, `service_date`, `decision_ts` | `t_asg` in `America/New_York` |
| `call_class`, `work_type`, `primary_skill` | work type; WOLI skills |
| `final_actor`, `final_actor_class`, `first_actor_class`, `ar_creator` | B3/B4 |
| `driver_id`, `driver_type`, `channel` | final driver |
| `n_pre_dispatch_picks`, `pullbacks`, `reassign_after_dispatch` | B2/B3 |
| `terr_moves_in`, `terr_moves_out` | S5 / Q12 |
| `pick_miles`, `pick_open_jobs`, `closest_q_miles`, `closest_free_q_miles`, `extra_miles` | decision-time candidate set |
| `idle_q_closer_count`, `less_loaded_q_closer_count` | candidate set (M20) |
| `pick_qualified`, `assigned_off_shift` | S9, S8 |
| `queue_wait_min`, `release_min`, `decide_min` | milestones |
| `on_shift_drivers`, `open_sas_at_decision`, `demand_level` | open scored SAs ÷ on-shift drivers; bands [0, 0.5, 1, 2] |
| `distance_band` | `pick_miles`; bands [0, 3, 7, 15, 30] |
| `zone`, `geohash6` | postal code; geohash |
| outcome: `pta_met`, `response_min`, `arrival_source` | S6/S7 |

### 7.4 Storage: a real table, not a blob
`ops.src_sa_verdict`, one row per `(snapshot_id, sa_id, rules_version)`, with the dimensions above
as typed columns, so patterns are plain indexed `GROUP BY`s across months and garages. The full
evidence (the numbers each rule saw) is stored as a small JSONB per row for the call panel.
DDL in 13.2.

Which rows count in patterns: the view `ops.src_sa_verdict_current` joins to
`src_snapshot.is_current`, so a rebuilt day never double-counts. Pattern queries always filter on
**one** `rules_version`.

### 7.5 Re-scoring when rules change
Activating a new rules version does **not** recompute anything automatically. An admin clicks
"Re-score coverage with r2". This enqueues `rescore` jobs in the backfill queue (12). Each job reads
a snapshot payload from Postgres, computes verdicts for `r2`, and inserts rows. **Zero SF calls.**
At about 150 SAs per garage-day, 1,000 garage-days re-score in a few minutes of CPU, paced so it never
starves request workers. The Patterns view shows per-version coverage, so nobody compares r1 and r2
on different day sets by accident.

### 7.6 Policy diagnosis: from finding to config cause
Goal: the verdict says *why the configuration allows the failure*. For example: "Stacking (26 SAs): policy
'Copy of Highest Priority' has no balance objective (this org has no balance goal type), and travel weighs
10 against ASAP 60000. Examples: SA-1020203, SA-1020212".

- **Captured config** (snapshot `config`, Q11): the policies actually seen that day, with objectives +
  weights, work rules + parameters, territory automation flags, and membership type counts.
- **As-of caveat:** Salesforce keeps no history of policy goals or weights unless field history is enabled
  on those objects. So:
  1. A daily policy capture (`ops.src_policy_capture`, one hash-versioned row per day when the config
     changes) starts with Phase 1. From then on, snapshots reference the capture valid on the service date
     (`as_of: daily_capture`).
  2. Backfilled days from before the first capture use the build-time config, labelled
     `as_of: build_time`. The UI and AI caveat it ("config as of 2026-10-03; may differ from that day").
- **Henry's mapping table**, versioned inside the rules version (`thresholds.diagnosis_map`, so it is
  immutable and comparable like thresholds):
  ```jsonc
  [{ "id": "D01", "finding": { "verdict": "STACKED", "min_share": 0.10 },
     "config_check": "objective_weight", "args": { "goal": "balance*", "op": "==", "value": 0 },
     "cause": "Policy '{policy}' has no balance objective (weight {weight})",
     "lever_id": "L01" },
   { "id": "D02", "finding": { "flag": "BYPASSED_OPTIMIZER", "min_share": 0.30 },
     "config_check": "path_share", "args": { "classes": ["INTEGRATION","HUMAN","GARAGE_DISPATCHER"], "op": ">=", "value": 0.5 },
     "cause": "{share} of final decisions were made outside the FSL optimizer, so no policy was evaluated",
     "lever_id": "L02" },
   { "id": "D03", "finding": { "verdict": "FAR_PICK", "actor_class": "FSL_ENGINE", "min_share": 0.05 },
     "config_check": "objective_ratio", "args": { "num": "Minimize Travel", "den": "ASAP", "op": "<", "value": 0.01 },
     "cause": "Policy '{policy}' weighs travel {num_w} vs ASAP {den_w}: it picks soonest, not closest",
     "lever_id": "L04" },
   { "id": "D04", "finding": { "flag": "OPTIMIZER_CHURN", "min_share": 0.10 },
     "config_check": "territory_flag", "args": { "flag": "RSO_Automation_Active__c", "value": true },
     "cause": "In-Day/RSO re-optimisation reshuffles undispatched SAs ({share} with ≥ 3 picks)",
     "lever_id": "L05" }]  /* Henry finalises the table; lever ids from spec §12 */
  ```
  `config_check` names a **fixed set of pure Python predicates** (`objective_weight`, `objective_ratio`,
  `has_work_rule`, `work_rule_param`, `territory_flag`, `membership_type_share`, `path_share`), with no free-form
  expressions. The engine evaluates every row deterministically and emits **finding → cause pairs**:
  `{diagnosis_id, finding_fact_id, cause_text (filled from config values), config_refs, example_sa_ids (≤ 5,
  highest-evidence first), lever_id}`.
- **Where it shows:** the Day view gets a "Why the configuration allows this" card under VerdictSummary
  (each pair links to its example SAs on the Gantt). The Patterns view aggregates pairs across days
  ("D01 fired on 41 of 60 days").
- **AI:** pairs go into the day and pattern fact sheets as facts (`kind: "diagnosis"`). The model may
  only state causes present as pairs. The validator rejects config claims (policy names, weights, rule
  names) that don't appear in a pair or in the `config` facts.
- **Bypass honesty:** when most final decisions are made outside the optimizer (`final_by_class`), the
  diagnosis says so first. Tuning a policy can't fix calls that never reach it.

---

## 8. Patterns view

### 8.1 What it answers
Across the selected garages × date range × rules version: where does the scheduler succeed and
fail? Example: "most failures are STACKED between 14–17h on tow calls assigned by account X."

### 8.2 Interaction
1. Filters: garages (multi), date range (max 400 days), rules version (default active), channel
   (default FSL Platform), verdict set considered "failure" (default = all non-GOOD graded codes;
   Henry may define).
2. **CoverageBar**: built garage-days / requested garage-days, scored under this rules version. Unbuilt
   days are listed with an admin "enqueue backfill" shortcut. If coverage is below 60%, a warning
   banner appears on every number.
3. **PatternMatrix**: pick a row and a column dimension (for example, `hour_et` × `call_class`). Each cell
   shows the failure rate and its `n`. Cells with `n` below the rules' `min_support` (default 20) are greyed
   out and never highlighted. Toggle: failure rate | count | top verdict code.
4. **Top patterns list**: the highest-lift single and two-dimension cells (8.3), each with n,
   rate, baseline rate and lift.
5. Click a cell or pattern → **PatternExamples**: up to 25 SAs (stratified across days) with verdict,
   evidence summary, and a link into the Day view at that SA.
6. **PatternInsightCard**: AI recommendations from the pattern fact sheet (11.3).

### 8.3 Pattern math (deterministic, `report_card_patterns.py`)
- Dimensions are a **whitelist** mapped to columns. Never interpolate user input into SQL.
- Per cell: `n`, `failures`, `rate = failures/n`, `baseline = overall rate in filter`,
  `lift = rate / baseline`, `share_of_failures = failures / total_failures`.
- Top patterns: all 1-D cells and 2-D cells over a fixed pair list (spec §7.3: hour × final_actor_class,
  demand_level × hour, call_class × final_actor_class, driver × hour; plus hour × call_class and
  distance_band × call_class). Keep cells with `n ≥ min_support`, rank by `share_of_failures × (lift − 1)`, top 10.
  A Wilson lower bound on `rate` keeps small cells from ranking on noise.
- Driver-level patterns are shown, but the AI prompt receives **driver names only where Henry
  approves**. Default: anonymised as "Driver A/B" in AI input, real names in the UI for permitted
  users.

---

## 9. API contract

All routes: auth (existing middleware); feature flag `scheduler_report_card` (404 when off);
`permissions.require_feature("scheduler.report_card")` (403); `_check_territory_access` for every
territory id. Admin routes additionally require `scheduler.report_card_admin`. Ids go through
`sanitize_soql`; dates match `^\d{4}-\d{2}-\d{2}$`.

### 9.1 Day
| Method | Route | Responses |
|---|---|---|
| GET | `/api/report-card/{territory_id}/days?from=&to=` (≤ 92 days) | `200 [{date, status, is_current, provisional, built_at, sa_count, day_mode}]` (Postgres only) |
| GET | `/api/report-card/{territory_id}/{date}` | `200` body below · `404 {"status":"not_built"}` · `202 {"status":"building","started_at"}` · `409 {"status":"failed","error"}` · `422` (today/future/too old) · `503` (not provisioned) |
| POST | `/api/report-card/{territory_id}/{date}/build[?force=true]` | `202 {"status":"building","snapshot_id"}` · `200` (already ready) · `403` (force, not admin, not provisional) · `422` |
| GET | `/api/report-card/{territory_id}/{date}/status` | `200 {"status","started_at","finished_at","error","sf_calls"}` |
| GET | `/api/report-card/{territory_id}/{date}/verdict` | `200` day AI verdict (11.4) · `404` |

Day payload (GPS excluded):
```jsonc
{
  "snapshot": { "id": 17, "built_at": "…", "provisional": false, "schema_version": 1,
                "builder_version": "rc-build-1.0", "metrics_version": "m1",
                "rules_version": "r1", "engine_version": "e1",
                "day_mode": "fsl", "channel_summary": {…}, "completeness": {…},
                "optimizer_available": false },
  "territory": {…}, "service_date": "2026-08-24", "window": {…},
  "scorecard": { "garage": [MetricResult], "drivers": { "0Hn…": [MetricResult] } },
  "metric_catalog": [{ "id", "label", "family", "unit", "spec_ref" }],
  "verdict_catalog": [{ "code": "STACKED", "label": "…", "colour": "…", "is_failure": true }],
  "sa_verdicts": { "08p…": { "code": "STACKED", "flags": ["FAR_PICK"], "evidence": {…} } },
  "verdict_counts": { "GOOD": 51, "STACKED": 12, "…": 0 },
  "drivers": [ /* minus gps */ ],
  "sas": [ /* full */ ]
}
```
About 450 KB of JSON, fetched once per view. Lazy recompute: if metrics for the running `METRICS_VERSION`,
or verdicts for the active rules version, are missing for this snapshot, the GET computes and stores
them (pure CPU). Drill-down is client-side from this payload. "Open full SA report" reuses the
existing endpoint on an explicit click only.

Compression: `GZipMiddleware(minimum_size=1000)` scoped by path check to `/api/report-card/*`, or a
pre-gzipped `Response` in the router if Kathy prefers no middleware change.

### 9.2 Patterns
| Method | Route | Responses |
|---|---|---|
| GET | `/api/report-card/patterns?territory_ids=a,b&from=&to=&rules=r1&channel=fsl&rows=hour_et&cols=call_class&failure_codes=…` | `200` below · `400` (unknown dimension, range > 400 days, > 50 garages) |
| GET | `/api/report-card/patterns/examples?…same filters…&cell=hour_et:15,final_actor_class:INTEGRATION&limit=25` | `200 [{sa_id, sa_number, territory_id, service_date, verdict, flags, evidence_summary, link}]` |
| GET | `/api/report-card/patterns/insight?…same filters…` | `200` pattern AI insight (11.3) |
| GET | `/api/report-card/coverage?territory_ids=&from=&to=&rules=` | `200 {requested, built, scored, missing:[{territory_id,date,reason}]}` |

Patterns response:
```jsonc
{ "filters": {…}, "rules_version": "r1", "engine_version": "e1",
  "coverage": { "requested": 180, "built": 171, "scored": 171, "pct": 95.0 },
  "totals": { "n": 24310, "failures": 6120, "baseline_rate": 0.252 },
  "matrix": { "rows": "hour_et", "cols": "call_class",
              "cells": [{ "r": 15, "c": "tow", "n": 812, "failures": 401, "rate": 0.494,
                          "lift": 1.96, "top_code": "STACKED", "low_support": false }] },
  "top_patterns": [{ "dims": { "hour_et": "14-17", "call_class": "tow", "final_actor": "Mulesoft Integration" },
                     "n": 640, "failures": 352, "rate": 0.55, "lift": 2.18,
                     "share_of_failures": 0.058, "top_code": "STACKED", "fact_id": "P3" }],
  "by_code": { "STACKED": 2410, "FAR_PICK": 1320, "…": 0 } }
```
Query cost: one indexed aggregate over `src_sa_verdict_current` (at most about 2M rows/year in the
all-garages worst case). Results are cached in-process for 10 min by the filter hash
(`cache.cached_query`), because the data only changes when builds or re-scores land.

### 9.3 Admin (rules + backfill)
| Method | Route | Purpose |
|---|---|---|
| GET | `/api/report-card/rules` | list versions, active flag, created by/at, notes |
| POST | `/api/report-card/rules` | create a new version `{based_on, thresholds, notes}` → validated, immutable |
| POST | `/api/report-card/rules/{version}/activate` | pointer change; returns coverage that has not been re-scored |
| POST | `/api/report-card/rules/{version}/rescore` | enqueue `rescore` jobs for the current snapshots in a range |
| GET | `/api/report-card/backfill` | queue summary + recent jobs + worker state (window, paused, tonight's count) |
| POST | `/api/report-card/backfill` | enqueue `{territory_ids, from, to, priority}` → `build` jobs for missing garage-days only |
| POST | `/api/report-card/backfill/pause` · `/resume` | settings-table toggle (no deploy) |

---

## 10. Frontend behaviour

- **URL is the source of truth** in both views (garage/date/driver/sa; garages/from/to/rules/rows/cols/cell).
- **Day view** states: not built → "Build report (about 1 min, reads Salesforce once)"; building → spinner +
  elapsed (poll 3 s, stop at 3 min); failed → error + Retry; ready → ChannelBanner → ScorecardGrid →
  VerdictSummary → DayGantt → AiVerdictCard. Clicking a row or tile opens DriverPanel; a bar opens
  CallPanel (with verdict + evidence); a metric tile or verdict count highlights its SAs on the Gantt.
- **Patterns view**: PatternFilters → CoverageBar → PatternMatrix + top patterns → PatternExamples →
  PatternInsightCard. Every example links to the Day view at that SA.
- **Gating**: `features.scheduler_report_card` plus `user.features` from `/api/auth/me` (the pattern in
  `GarageDashboard.jsx:79`). Admin pieces need `scheduler.report_card_admin`.
- **Render cost**: one fetch per garage-day; Gantt memoised on `snapshot.id`; the patterns fetch is
  debounced (400 ms) on filter changes; no polling once ready.

---

## 11. AI: fact sheets → narratives (day verdict and pattern recommendations)

The same machinery is used twice. The AI never computes numbers.

### 11.1 Shared rules
- Inputs are **deterministic fact sheets** built by code. Canonical JSON (sorted keys) → `sha256`
  → cache key `(fact_sheet_hash, prompt_version, model)` in `ops.src_ai_output`. Identical facts are
  never re-billed.
- No API key → **template output** (deterministic sentences from facts, `source:'template'`). The
  page never breaks.
- Prompt: "Use only the facts provided. Every number you write must appear in a cited fact. Cite
  fact ids. Do not compute, add, average or estimate. Do not attribute cause to capacity vs
  scheduler beyond what verdict facts state." Output: **JSON only**, temperature 0.2.
- Validator: parse; every `fact_refs` id exists; regex-extract every number in all text fields,
  and each must match a cited fact's `value`/`display` (formatting tolerance: `31%` ↔ `0.31` ↔ `31`).
  Fail → one retry listing the failures → still fails → template, `validation.passed=false`, logged.
- Rendered as structured React, never raw HTML (no `dangerouslySetInnerHTML`, unlike
  `satisfaction_day`).
- Provider: `call_openai_simple` is OpenAI-only. If `load_ai_settings()` returns `anthropic`, use the
  dispatcher in `chatbot_providers.py` if it exposes one, else the template. Ruby confirms this at plan
  review.

### 11.2 Day fact sheet
Garage metrics (`MetricResult`s), verdict counts, **finding → config-cause pairs (7.6) with example SAs**,
captured policy config facts (policy names, objectives + weights, work rules), rule-selected findings (top driver shares, largest
stacking episode, worst FAR_PICK by extra miles), not-applicable list, caveats (provisional, skills
not historical, optimizer absent). Towbook days use the workload-only prompt.

### 11.3 Pattern fact sheet → recommendations
Built from the 9.2 aggregates only:
```jsonc
{ "scope": { "garages": ["…"], "from": "…", "to": "…", "rules_version": "r1", "channel": "fsl" },
  "coverage": { "pct": 95.0, "garage_days": 171 },
  "totals": { "n": 24310, "failure_rate": 0.252 },
  "facts": [
    { "id": "P1", "kind": "code_share", "code": "STACKED", "value": 0.39, "display": "39%" },
    { "id": "P3", "kind": "pattern", "dims": { "hour_et": "14-17", "call_class": "tow",
      "final_actor": "Mulesoft Integration" }, "n": 640, "rate": 0.55, "display_rate": "55%",
      "lift": 2.18, "share_of_failures": 0.058, "top_code": "STACKED" }
  ],
  "recommendation_library": [ /* spec §12 L01–L11: lever, triggering codes/flags, owner, FSL-native? */ ] }
```
Output: `{ headline, recommendations: [{ text, fact_refs, lever_id, expected_effect_note }] }`.
The model may only recommend levers from `recommendation_library` (spec §12), applied to cited patterns,
and must state the lever's owner and whether it is FSL-native (e.g. L01 is an external Mulesoft change; a
balance objective is not native in this org).
That keeps recommendations operational and reviewable, not invented. Cached by hash in
`ops.src_ai_output` (`kind='pattern'`). The UI shows coverage and rules version next to every
recommendation.

### 11.4 Day verdict shape
```jsonc
{ "source": "ai" | "template", "model": "gpt-4o", "prompt_version": "day-v1",
  "generated_at": "…", "validation": { "passed": true, "retries": 0 },
  "headline": "…",
  "sections": [{ "title": "What happened", "bullets": [{ "text": "…", "fact_refs": ["F1","F7"] }] }],
  "fact_sheet": { … } }
```

---

## 12. Backfill: many past days, gently

SF field history (assignment, status, GPS) persists for about 18 months, but optimizer data does not
(3 days). Verdicts for old days therefore come from SF history only, which is by design (5.5).

### 12.1 Queue
`ops.src_job_queue` (DDL 13.2): one row per job, `kind IN ('build','rescore')`. A unique key on
`(kind, territory_id, service_date, rules_version)` makes enqueueing idempotent. Statuses:
`queued → running → done | failed | skipped`. `attempts` goes up to 3, with `last_error`. Enqueueing a
range only creates `build` jobs for garage-days with no current snapshot. `skipped` is used when a
user built it first.

### 12.2 Worker (`report_card_backfill.py`)
- Started from `main.py` (one line). It is a no-op unless `REPORT_CARD_BACKFILL_ENABLED=true` (env,
  default off **locally and in prod** until Kathy enables it) **and** the feature flag is on **and**
  it is not paused in settings.
- **Leader only:** `cache.fs_lock_acquire('report_card_backfill', max_age=…)`, the same mechanism
  as the nightly trends job, so one worker runs across all gunicorn workers and instances.
- **Window:** `REPORT_CARD_BACKFILL_WINDOW_ET` default `01:00-05:00` (lowest dispatch volume). It
  checks the clock before each job and stops at the window end.
- **Pacing:** strictly one job at a time through the same build semaphore as user builds. Sleep
  `REPORT_CARD_BACKFILL_GAP_S` (default 60 s) between builds. Cap of
  `REPORT_CARD_BACKFILL_MAX_PER_NIGHT` (default 40 builds). Rescore jobs make no SF calls, get a
  short gap (2 s), and don't count toward the cap.
- **Order:** priority, then newest day first (recent history is most useful and most at risk of
  history expiry), then garage.
- **Daily incremental:** each night it enqueues **D-2** for an allowlist
  (`report_card_backfill_garages` in settings; pilot garage first), so final, non-provisional
  snapshots accumulate automatically.

### 12.3 Salesforce guards (stop for the night if any trip)
- Before each build: one `sf_rest_get('limits')` call. Stop if `DailyApiRequests.Remaining` is below
  `REPORT_CARD_BACKFILL_MIN_API_PCT` (default 30%) of max.
- Circuit breaker open, or `sf_client.get_stats()['rate_waits']` increased during the last build →
  stop.
- 3 consecutive job failures → stop and log; jobs stay queued for tomorrow.

### 12.4 Load math
40 builds × ≤ 35 calls = **≤ 1,400 calls/night**, spread over ≥ 40 min at well under 1 call/s,
plus 40 limits checks (builds are ordered by region-day so the Q12 outbound-moves pull is shared). Backfilling 180 days for the pilot takes about 5 nights. All about 40 FSL garages × 180
days (7,200 garage-days) at 40/night is about 6 months. To go faster, raise the cap in steps after Kathy
reviews limits usage; never run builds in parallel.

---

## 13. Postgres

### 13.1 Convention: admin-applied migration, no startup DDL
The repo has `infra/postgres/init-schema.sql` (admin-applied, idempotent, tracked in
`public.schema_migrations`) and `_ensure_*()` runtime DDL in `main.py`. **This feature uses only
an admin-applied file**:
- Startup DDL runs whenever anyone boots the backend locally, against **production**.
- `main.py` is at 578/600 lines.
- The `ops` schema already exists, reserved for "daily ops / dispatch insights". Whether the app
  role has `CREATE` there is **unverified**.

The migration is **purely additive** (IF NOT EXISTS; no ALTER of existing objects, no DROP). Kathy
applies it as AAD admin: `fslapp-pg-backup` backup → show the SQL → user "yes" → apply → verify. The
routers return `503 "report card storage not provisioned"` until then, so deploying code first is
harmless.

### 13.2 DDL (`infra/postgres/migrations/ops_002_scheduler_report_card.sql`)
(Kathy confirms `ops` version numbering in `schema_migrations` first.)

```sql
SET search_path = ops, public;

-- 1. Snapshots: one row per build attempt of a garage-day. Append-only.
CREATE TABLE IF NOT EXISTS ops.src_snapshot (
  id               BIGSERIAL PRIMARY KEY,
  territory_id     TEXT        NOT NULL,
  territory_name   TEXT,
  service_date     DATE        NOT NULL,
  schema_version   SMALLINT    NOT NULL,
  builder_version  TEXT        NOT NULL,
  status           TEXT        NOT NULL CHECK (status IN ('building','ready','failed')),
  is_current       BOOLEAN     NOT NULL DEFAULT FALSE,
  provisional      BOOLEAN     NOT NULL DEFAULT FALSE,
  day_mode         TEXT,
  trigger          TEXT        NOT NULL CHECK (trigger IN ('user','backfill')),
  requested_by     TEXT        NOT NULL,
  started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at      TIMESTAMPTZ,
  build_ms         INTEGER,
  sf_calls         INTEGER,
  sa_count         INTEGER,
  driver_count     INTEGER,
  payload_bytes    INTEGER,
  payload          JSONB,
  error            TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS src_snapshot_one_building
  ON ops.src_snapshot (territory_id, service_date) WHERE status = 'building';
CREATE UNIQUE INDEX IF NOT EXISTS src_snapshot_one_current
  ON ops.src_snapshot (territory_id, service_date) WHERE is_current;
CREATE INDEX IF NOT EXISTS src_snapshot_territory_date
  ON ops.src_snapshot (territory_id, service_date DESC);

-- 2. Metrics per snapshot per formula version.
CREATE TABLE IF NOT EXISTS ops.src_metrics (
  snapshot_id      BIGINT      NOT NULL REFERENCES ops.src_snapshot(id),
  metrics_version  TEXT        NOT NULL,
  rules_version    TEXT        NOT NULL,              -- bands come from rules
  computed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  scorecard        JSONB       NOT NULL,
  fact_sheet       JSONB       NOT NULL,
  fact_sheet_hash  TEXT        NOT NULL,
  PRIMARY KEY (snapshot_id, metrics_version, rules_version)
);

-- 3. Rules versions: immutable thresholds config. One active.
CREATE TABLE IF NOT EXISTS ops.src_rules (
  rules_version    TEXT        PRIMARY KEY,
  engine_version   TEXT        NOT NULL,
  based_on         TEXT        REFERENCES ops.src_rules(rules_version),
  thresholds       JSONB       NOT NULL,
  is_active        BOOLEAN     NOT NULL DEFAULT FALSE,
  created_by       TEXT        NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  notes            TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS src_rules_one_active ON ops.src_rules (is_active) WHERE is_active;

-- 4. Per-SA verdicts: typed dimensions for cross-day/garage aggregation.
CREATE TABLE IF NOT EXISTS ops.src_sa_verdict (
  snapshot_id       BIGINT      NOT NULL REFERENCES ops.src_snapshot(id),
  sa_id             TEXT        NOT NULL,
  rules_version     TEXT        NOT NULL REFERENCES ops.src_rules(rules_version),
  engine_version    TEXT        NOT NULL,
  territory_id      TEXT        NOT NULL,
  service_date      DATE        NOT NULL,
  sa_number         TEXT,
  verdict           TEXT        NOT NULL,              -- primary code
  flags             TEXT[]      NOT NULL DEFAULT '{}', -- all matched codes
  is_failure        BOOLEAN     NOT NULL,
  graded            BOOLEAN     NOT NULL,              -- false for NOT_GRADED_*
  channel           TEXT        NOT NULL,
  hour_et           SMALLINT,
  dow               SMALLINT,
  call_class        TEXT,
  work_type         TEXT,
  primary_skill     TEXT,
  decision_ts       TIMESTAMPTZ,
  final_actor       TEXT,
  final_actor_class TEXT,
  first_actor_class TEXT,
  ar_creator        TEXT,                              -- audit only
  n_pre_dispatch_picks SMALLINT,
  pullbacks         SMALLINT,
  reassign_after_dispatch SMALLINT,
  terr_moves_in     SMALLINT,
  terr_moves_out    SMALLINT,
  pick_qualified    BOOLEAN,
  assigned_off_shift BOOLEAN,
  queue_wait_min    REAL,
  release_min       REAL,
  decide_min        REAL,
  driver_id         TEXT,
  driver_type       TEXT,
  zone              TEXT,                              -- postal code
  geohash6          TEXT,
  distance_band     TEXT,
  pick_miles        REAL,
  closest_q_miles   REAL,
  closest_free_q_miles REAL,
  idle_q_closer_count SMALLINT,
  less_loaded_q_closer_count SMALLINT,
  extra_miles       REAL,
  demand_level      TEXT,
  open_sas_at_decision SMALLINT,
  on_shift_drivers  SMALLINT,
  pick_open_jobs    SMALLINT,
  pta_met           BOOLEAN,
  response_min      REAL,
  arrival_source    TEXT,
  evidence          JSONB       NOT NULL,
  computed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (snapshot_id, sa_id, rules_version)
);
CREATE INDEX IF NOT EXISTS src_sav_rules_terr_date ON ops.src_sa_verdict (rules_version, territory_id, service_date);
CREATE INDEX IF NOT EXISTS src_sav_rules_verdict   ON ops.src_sa_verdict (rules_version, verdict);
CREATE INDEX IF NOT EXISTS src_sav_sa_number       ON ops.src_sa_verdict (sa_number);
CREATE INDEX IF NOT EXISTS src_sav_rules_actor     ON ops.src_sa_verdict (rules_version, final_actor_class, hour_et);
CREATE INDEX IF NOT EXISTS src_sav_flags_gin       ON ops.src_sa_verdict USING GIN (flags);

-- Daily org-wide policy config capture (7.6; Phase 3 twin reads it too).
CREATE TABLE IF NOT EXISTS ops.src_policy_capture (
  id           BIGSERIAL PRIMARY KEY,
  captured_on  DATE        NOT NULL,
  config_hash  TEXT        NOT NULL,
  config       JSONB       NOT NULL,     -- policies, goals+weights, work rules+params, territory flags
  captured_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (config_hash, captured_on)
);

-- Region-day outbound-move cache (Q12), shared by all garages in a region.
CREATE TABLE IF NOT EXISTS ops.src_region_moves (
  region_id    TEXT NOT NULL,
  service_date DATE NOT NULL,
  rows         JSONB NOT NULL,
  pulled_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (region_id, service_date)
);
CREATE INDEX IF NOT EXISTS src_sav_date_brin       ON ops.src_sa_verdict USING BRIN (service_date);

-- Only rows from current snapshots count in patterns.
CREATE OR REPLACE VIEW ops.src_sa_verdict_current AS
  SELECT v.* FROM ops.src_sa_verdict v
  JOIN ops.src_snapshot s ON s.id = v.snapshot_id AND s.is_current;

-- 5. AI outputs (day verdicts and pattern recommendations), cached by facts.
CREATE TABLE IF NOT EXISTS ops.src_ai_output (
  kind             TEXT        NOT NULL CHECK (kind IN ('day','pattern')),
  fact_sheet_hash  TEXT        NOT NULL,
  prompt_version   TEXT        NOT NULL,
  model            TEXT        NOT NULL,
  source           TEXT        NOT NULL CHECK (source IN ('ai','template')),
  output           JSONB       NOT NULL,
  validation       JSONB       NOT NULL,
  fact_sheet       JSONB       NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (kind, fact_sheet_hash, prompt_version, model)
);

-- 6. Backfill / rescore job queue.
CREATE TABLE IF NOT EXISTS ops.src_job_queue (
  id               BIGSERIAL PRIMARY KEY,
  kind             TEXT        NOT NULL CHECK (kind IN ('build','rescore')),
  territory_id     TEXT        NOT NULL,
  service_date     DATE        NOT NULL,
  rules_version    TEXT        NOT NULL DEFAULT '',   -- '' for build jobs
  priority         SMALLINT    NOT NULL DEFAULT 5,
  status           TEXT        NOT NULL DEFAULT 'queued'
                   CHECK (status IN ('queued','running','done','failed','skipped')),
  attempts         SMALLINT    NOT NULL DEFAULT 0,
  last_error       TEXT,
  enqueued_by      TEXT        NOT NULL,
  enqueued_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at       TIMESTAMPTZ,
  finished_at      TIMESTAMPTZ,
  snapshot_id      BIGINT      REFERENCES ops.src_snapshot(id),
  UNIQUE (kind, territory_id, service_date, rules_version)
);
CREATE INDEX IF NOT EXISTS src_job_queue_pick
  ON ops.src_job_queue (status, priority, service_date DESC) WHERE status = 'queued';

-- Grants: DML for the app identity, but no DELETE (append-only by design).
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fslapp-nyaaa') THEN
    GRANT SELECT, INSERT, UPDATE ON
      ops.src_snapshot, ops.src_metrics, ops.src_rules, ops.src_sa_verdict,
      ops.src_ai_output, ops.src_job_queue, ops.src_policy_capture, ops.src_region_moves TO "fslapp-nyaaa";
    GRANT SELECT ON ops.src_sa_verdict_current TO "fslapp-nyaaa";
    GRANT USAGE, SELECT ON SEQUENCE ops.src_snapshot_id_seq, ops.src_job_queue_id_seq, ops.src_policy_capture_id_seq TO "fslapp-nyaaa";
  END IF;
END $$;

INSERT INTO public.schema_migrations (schema_name, version, description)
VALUES ('ops', '002-scheduler-report-card',
        'Scheduler Report Card + auditor mode: snapshots, metrics, rules, SA verdicts, AI outputs, job queue (additive)')
ON CONFLICT DO NOTHING;
```
The initial rules row (`r1`, from Henry's spec) is inserted by a separate tiny seed file
`ops_003_scheduler_rules_seed.sql` once Henry's values are final, so schema review isn't blocked on
threshold numbers. Rules rows are never updated except the `is_active` pointer, and that only through
the activate endpoint, in one transaction.

Rollback = revert the code. The tables stay, unused, which is harmless. Dropping them would be a
separately approved action.

### 13.3 Size estimate and retention
Per Fleet garage-day (about 150 SAs, 25 drivers). Ruby records real `payload_bytes` on the first pilot
build and this table gets revised:

| Item | Raw | Stored |
|---|---|---|
| Snapshot payload (SAs about 375 KB + GPS about 225 KB + meta) | about 0.6 MB | about 150–250 KB (TOAST about 3×) |
| SA verdict rows: 150 × about 350 B + index | — | about 70 KB |
| Metrics + AI rows | — | about 25 KB |
| **Total per garage-day, one rules version** | | **about 250–350 KB** |

Growth: pilot garage, daily + 180-day backfill: **about 60 MB**, then about 120 MB/year. Worst case all about 40
FSL garages every day: about **5 GB/year** (+ about 1 GB/year per additional rules version kept re-scored). Fine
for the flexible server; Kathy watches storage.

Retention: **current snapshots and their verdicts are kept indefinitely** (beyond 30 days, per the user). `ops.src_*`
is never added to `optimizer_retention.PURGE_TABLES`. A future, separately approved cleanup could
prune superseded (`is_current=false`) snapshots and verdict rows for retired rules versions older
than 180 days (backup → preview → approval). Nothing automatic in v1.

---

## 14. Test plan hooks (Tamy and Ruby)

No test boots the backend against production, writes to production Postgres, or calls Salesforce.

**Unit (pytest, `backend/tests/`, existing `conftest.py` `pg_pool` mock):**
- Fixtures `fixtures/report_card/`: `raw_bundle_fleet.json`, `raw_bundle_towbook.json`,
  `raw_bundle_mixed.json`, `raw_bundle_dst_fall_back.json`, all **synthetic** (fake Ids and names). A
  real capture, if wanted, is anonymised in the scratchpad before it is committed.
  `rules_r1_test.json` holds known thresholds for deterministic verdict tests.
- `test_report_card_snapshot.py`: Tow Drop-Off tagged and excluded; Towbook `on_location` from
  history; channel from `ERS_Driver_Type__c` even when `ERS_Dispatch_Method__c` disagrees; 25 h
  (2026-11-01) and 23 h (2026-03-08) windows; COUNT mismatch raises; carryover `in_day=false`;
  `open_jobs` per candidate.
- `test_report_card_metrics.py`: one test per Henry metric against hand-computed values from the
  spec; not-applicable for Towbook days and missing optimizer data.
- `test_report_card_decisions.py`: final decider = actor on the last assignment name-row, not AR creator;
  Id rows dropped; clear rows = unassign; actor class order (a driver whose profile is Membership User
  → DRIVER; Platform Integration User → FSL_ENGINE); pullback vs pre-dispatch churn; qualified = WOLI ⊆ SR
  skills ∪ truck caps; GPS older than 30 min excluded; a candidate set stored per event.
- `test_report_card_verdicts.py`: one hand-built SA per verdict code hits exactly that primary
  code; precedence respected; the same snapshot + rules gives byte-identical rows (determinism); changing
  one threshold in a cloned rules JSON flips the expected SA and nothing else; Towbook SA →
  `NOT_GRADED_TOWBOOK`; an unknown key in rules JSON is rejected.
- `test_report_card_patterns.py`: dimension whitelist rejects unknown/injection input; lift,
  support and Wilson math on a fixture table; `min_support` hides small cells.
- `test_report_card_ai.py`: the validator rejects a number not in the facts; a pattern recommendation
  with a lever outside the library is rejected; template fallback without a key; hash stable
  regardless of key order.
- `test_report_card_build.py`: recorder for `sf_query_all`. It asserts **no `sf_parallel`**, ≤ 35 calls,
  no `COUNT()` on `ServiceResourceHistory`, a region-moves cache hit on the second garage of the same region,
  and that every SA query has the territory + window filter.
- `test_report_card_backfill.py`: fake clock and fake limits. The worker stops outside the window,
  at the nightly cap, below the API-remaining threshold, and on breaker open. Enqueue is idempotent.
  Rescore jobs make zero SF calls.
- `test_report_card_api.py`: TestClient on a bare `FastAPI()` with repos and build monkeypatched.
  Checks: 422 for today/future; 404 when the flag is off; 403 for contractor; 403 for admin routes as viewer;
  202 → 200 build flow; 503 when not provisioned.

**Acceptance (Tamy, after deploy; flag on for admins only; pilot = 100 - WESTERN NEW YORK FLEET):**
1. Log in as an admin at `https://fslapp-nyaaa.azurewebsites.net`, click **Report Card** in the top nav.
2. Pick "100 - WESTERN NEW YORK FLEET" and **2026-09-28** → "not built" → **Build report** → spinner →
   report within about 2 min. Screenshot. Compare with spec §6.1/§7.4 golden values: 90 SAs; PTA met 65/82;
   M20 3/80 and 0/80; verdicts GOOD 54 / CAPACITY_SHORT 10 / BOUNCED 7 / INBOUND_CASCADE 7. Henry signs
   off any difference. Also open yesterday for the same garage (provisional banner).
3. Reload → instant, no spinner. Kathy confirms from logs that there were **no SF calls** on reload.
4. Today isn't selectable. Typing today's date in the URL gives a clear "past days only" message.
5. Driver row → driver panel (spec §6.1 driver table, e.g. Mike Klotz max open 3); bar → call panel. Check
   SA-1074747: 7 picks, `OPTIMIZER_CHURN`, final actor Paige White, not a bounce. Check SA-1074927: BOUNCED
   (pullback). Check SA-1074934: INBOUND_CASCADE from 053. "Open full SA report" opens the existing modal.
6. Click the BOUNCED count in VerdictSummary → only those 7 SAs highlight; switch Gantt to "colour by
   verdict". Henry spot-checks 3 verdicts against Salesforce.
7. AI verdict: every number appears in a cited fact (hover). Reload → identical (cached).
8. 076DO **2026-09-24** → Towbook banner, workload-only, verdicts `NOT_GRADED_TOWBOOK`, T01 = 25 drivers
   (top 15). 076DO **2026-08-31** → On-Platform day, graded, contractor "idle is an upper bound" label,
   STACKED 26 / FAR_PICK 15, examples SA-1020203 (STACKED) and SA-1020257 (FAR_PICK).
9. Admin → Report Card → enqueue backfill for the pilot garage, last 14 days. The next morning, the queue shows
   ≤ 40 done, built only between 01:00–05:00 ET, about 60 s apart (timestamps). Screenshot.
10. **Patterns**: pilot garage, last 14 days, `hour_et × call_class` → coverage ≥ 90%, cells show n,
    a low-n cell is greyed out; click the darkest cell → examples → open one in the Day view → same verdict.
11. Pattern recommendations cite pattern facts; each lever is from Henry's library.
12. Admin clones r1 → r2 with one threshold changed → activate → re-score 14 days → Patterns with r1
    vs r2 shows both, each with its own coverage, and no SF calls in logs during the re-score.
13. Contractor test user: no nav link; `/report-card` redirects; every API returns 403.
14. Postgres (read-only, Kathy): one `is_current` row per built garage-day; `payload_bytes` vs 13.3
    estimate; `src_sa_verdict` row count = scored SAs × rules versions.

---

## 15. Risks and edge cases

| Risk | Mitigation |
|---|---|
| SF load (user builds + backfill) | Sequential, one build at a time per process, ≤ about 35 calls/build, past days only, snapshot reused forever; backfill windowed 01–05 ET, 60 s gaps, 40/night cap, stops on limits/breaker/rate waits |
| `sf_query_all` silent page loss | Q0 COUNT check; no `ready` without a match |
| Channel relabelled by formula fields | Channel from `AssignedResource.ServiceResource.ERS_Driver_Type__c`, frozen per SA (5.3) |
| Garage changes channel / mixed day | `day_mode`, per-SA channel, Towbook = workload-only + `NOT_GRADED_TOWBOOK`, mixed = FSL subset graded |
| Optimizer calibration data | Corpus built from SF's own optimizer trail (since 2024-12), 18.5. Verify the request/response files persist |
| Optimizer data absent (3-day retention; all backfilled days) | Optional block; dependent metrics/verdicts "not applicable"; SF-history logic for assignment source |
| Verdicts not comparable across runs | `rules_version` + `engine_version` on every row; immutable rules; patterns filter one version; per-version coverage |
| Threshold edits silently change history | Rules rows are immutable; activation is a pointer; re-score is explicit and additive |
| CAPACITY_SHORT judged without counterfactual | Labelled "observed availability" in evidence and AI caveats; Phase 3 refines |
| Open jobs in other territories invisible | Caveat in evidence; Henry decides if a bounded cross-territory AR query is needed |
| Patterns on thin coverage | CoverageBar, < 60% warning, `min_support`, Wilson bound |
| AI invents numbers or remedies | Fact sheets only; number validator; retry; template fallback; recommendations restricted to Henry's lever library |
| Driver names in AI input | Anonymised by default in pattern prompts (Henry/user decide) |
| UTC vs Eastern day | Window from `ZoneInfo('America/New_York')`; 23/25 h days tested |
| Towbook fake `ActualStartTime` | `on_location` from SAHistory; source recorded |
| Tow Drop-Off double count | Tagged; excluded by registry/verdict gate before any rule |
| Roster drift | `ServiceTerritoryMember` effective dates for that day |
| SAs bounced **out** of the garage are invisible to `ServiceTerritoryId = :t` | Q12 region-day pull, cached and shared; counted and listed (M15-out), not graded in this garage |
| Shift object empty (spec S8) | On-shift = truck login minus absence; Q5 off |
| `AR.CreatedBy` is not the decider (spec S3) | Final decision = last assignment-history actor; AR creator kept as audit |
| `Platform Integration User` mistaken for an integration | Actor classes in rules config: it is FSL_ENGINE (48/48 timing match). User confirms with the FSL admin (spec §13 #2) |
| Membership User profile includes drivers/non-dispatchers | DRIVER class checked before HUMAN; `human_class_source` can switch to the dispatcher roster (user-pending) |
| Truck capabilities and skills are current, not historical | Stored as current, caveated on screen and in the AI prompt |
| GPS pull slow (spec §14: 26–39 s, one failure) | No `COUNT()` on SR history; one retry per batch; build timeout 10 min |
| User-pending assumptions (PTA target, dispatcher roster, AI anonymisation) | All config (`user_pending` in rules, settings key for AI); changing one = new version, no deploy |
| Worker recycled mid-build / mid-backfill | 15-min stale reclaim; jobs return to `queued` with attempts++; leader lock expires |
| Startup DDL on production | None added; admin-applied additive migration; 503 until provisioned; backfill env-off by default, so local boots never start it |
| Contractor data exposure | Internal Layout only; permission + territory checks on every route, server-side |
| File size limits | 11 backend modules, about 25 components, each < 600 lines; `main.py` +4 lines |
| Stale git worktree metadata | `git worktree list` shows 2 entries under `/Users/abdennourlaaroubi/...` (OneDrive sync artefacts). Not used; the user decides on `git worktree prune` |

---

## 16. Rollout notes (Kathy)

- **Env vars (all optional, safe defaults):** `REPORT_CARD_MAX_LOOKBACK_DAYS=540`,
  `REPORT_CARD_BACKFILL_ENABLED=false`, `REPORT_CARD_BACKFILL_WINDOW_ET=01:00-05:00`,
  `REPORT_CARD_BACKFILL_GAP_S=60`, `REPORT_CARD_BACKFILL_MAX_PER_NIGHT=40`,
  `REPORT_CARD_BACKFILL_MIN_API_PCT=30`, `REPORT_CARD_CORPUS_MAX_CALLS_PER_NIGHT=600` (Phase 3a). No secrets.
  AI uses the existing keys. Phase 3b `SBX_*` secrets live **only** in the separate job container, never in
  App Service settings.
- **Migrations:** `ops_002_scheduler_report_card.sql` (schema) and later `ops_003_scheduler_rules_seed.sql`
  (Henry's r1). Both are additive. Apply as AAD admin after a `fslapp-pg-backup` backup and the user's explicit
  yes. Verify via `schema_migrations` and `has_table_privilege('fslapp-nyaaa','ops.src_snapshot','INSERT')`.
- **Order:** deploy code (flag off) → migration → seed → flag on for admins → Tamy steps 1–8 → enable
  backfill env for the pilot allowlist → steps 9–12 the following days.
- **Packaging:** no new Python or npm dependencies. Optional `GZipMiddleware` (Starlette built-in), scoped.
- **Rollback:** flag off (instant, no deploy) → set backfill env false → revert the commit if needed. Tables
  remain, unused.
- **Monitoring:** `sf_calls` per snapshot row; backfill summary log line per night (built, failed, stop
  reason, API remaining %).
- **Release notes:** `RELEASE_NOTES.md` entry + tag per the usual process.

---

## 17. Phase 2/3 hooks (not built now)

- **Phase 2 replay:** `GET /api/report-card/{t}/{date}/tracks` → `drivers[].gps` + `sas[].milestones`.
  `useTimeScale.js` exposes `{minute, setMinute}` so the Gantt needle and the map share one scrubber.
  The map uses react-leaflet + `mapIcons.js`. Verdict colours carry over to map markers.
- **Phase 3 counterfactuals:** full design in section 18 (Shadow Scheduler Twin). In short: `backend/report_card_baselines.py` (OR-Tools hindsight VRPTW,
  background job kind `baseline` in the same queue, never in a request). New table
  `ops.src_baseline (snapshot_id, baseline_kind, params_hash, scenario_json, result JSONB, PK (snapshot_id, baseline_kind, params_hash))`.
  Regret becomes a metric family and a verdict input (engine version bump), so `CAPACITY_SHORT` vs
  scheduler loss becomes counterfactual instead of observed. Stress scenarios (+X% volume, −N drivers, storm
  mix, shift changes) are `scenario_json` transforms over a copy of the snapshot. The original is never
  modified.

---

## 18. Phase 3: Shadow Scheduler Twin (design now, build later)

### 18.1 Goal and hard boundary
Simulate how the FSL scheduler/optimizer **would** have behaved under historical demand (for example
the Jan–Apr 2026 winter), using **current** drivers, shifts and skills, with volume optionally
scaled per territory or zone. Then compare the as-is policy, proposed policy changes, a balanced online
greedy, and a hindsight VRPTW bound.

**Boundary:** Salesforce is read-only. The twin never calls FSL Schedule / Optimize / Get
Candidates / Appointment Booking, and never writes to WOs, SAs, ARs or anything else. Its only SF
contact is read-only SELECTs for demand, roster and policy, taken once and cached as
Postgres artefacts (like report-card snapshots). Every simulation run is an offline job over
Postgres data.

### 18.2 Components
| Component | File (future) | Responsibility |
|---|---|---|
| Policy capture | `backend/twin/policy_capture.py` | Read-only SOQL: `FSL__Scheduling_Policy__c`, `FSL__Scheduling_Policy_Goal__c` (+ `FSL__Service_Goal__c` record type/name, `FSL__Weight__c`), `FSL__Scheduling_Policy_Work_Rule__c` (+ `FSL__Work_Rule__c` record type and parameter fields, all per `sf_describe`). Normalised to a policy JSON → `ops.twin_policy_version` (hash-versioned, immutable). Also takes the policy from each optimizer request blob (`SchedulingPolicy`, `Objectives`, `WorkRules` are already in the request JSON that `optimizer_parser.parse_run` reads) as the **as-run** truth |
| Work rules as filters | `backend/twin/rules.py` | One pure filter per supported FSL rule type: Match Skills (+ skill level), Match Territory / Working Territories (Primary/Secondary/Relocation), Service Resource Availability (shift, absences, travel to/from), Maximum Travel From Home, Match Boolean/Fields, Count rules (capacity). Unsupported rule types are reported, not silently skipped (see 18.8) |
| Objectives as score | `backend/twin/objectives.py` | One scorer per FSL service goal: ASAP, Minimize Travel, Minimize Overtime, Resource Priority, Preferred Resource, Skill Level. Each normalised 0–100 across the candidate slot set (FSL's documented relative scoring), then the weighted sum uses the captured weights. Proposed objectives (for example "balance") are twin-only scorers flagged `fsl_native=false` |
| Slot model | `backend/twin/schedule_state.py` | Per-driver timeline: committed jobs, travel legs, availability. Candidate slot = insert at the earliest feasible gap (FSL evaluates slots, not just drivers). Event-driven clock: SA created → candidate slots → policy picks → commit |
| Travel model | `backend/twin/travel.py` | Pluggable `travel(a, b, t)`: `aerial` (haversine × speed) or `aerial_calibrated` (haversine × fitted detour factor, speed by hour). Basis chosen by calibration step 0 (18.4). Street routing (OSRM self-hosted) only if calibration shows FSL uses SLR and aerial calibrated is not enough |
| Bypass model | `backend/twin/bypass.py` | Final decisions made outside the FSL engine (INTEGRATION / HUMAN / GARAGE_DISPATCHER; 70 of 90 on 9/28). Modelled as a closest-available heuristic (the mechanism `ERS_DriverAssignmentAudit.cls` audits), calibrated against snapshot history (18.4 B) |
| Policies (pluggable) | `backend/twin/policies/` | `fsl_as_is` (captured policy), `fsl_proposed` (cloned policy JSON with edits), `bypass_heuristic`, `balanced_greedy` (online: min over candidates of travel + λ·open_jobs, λ config), `vrptw_hindsight` (OR-Tools routing, all calls known in advance) |
| Demand builder | `backend/twin/demand.py` | Read-only, **sequential, one month at a time** (never parallel month pulls), per territory: SA fields only (no history/GPS). `Id, CreatedDate, lat/lon, PostalCode, WorkType, ERS_PTA__c, ERS_Dynamic_Priority__c, FSL__Duration_In_Minutes__c, ServiceTerritoryId, Status`. Tow Drop-Off is folded into its Pick-Up as one tow job (cycle ≈ 115 min per `CYCLE_TIMES`), never counted separately. Report-card snapshots are reused where they exist (zero SF). Result → `ops.twin_demand_set` |
| Supply builder | `backend/twin/supply.py` | Current roster per territory: members (type, home base), skills + levels, resource priority, shift pattern (from recent `Shift` rows or truck-login history, so a day-of-week template is derived), typical absences/lunch. → `ops.twin_supply_set`, hash-versioned. Editable copies for "what if −N drivers / new shift" |
| Scenario + scaling | `backend/twin/scenario.py` | `{demand_set, supply_set, scale: {territory/zone: k}, policy_ids[], bypass_mix, seeds}`. Scaling ×k > 1 = bootstrap resample of that zone's calls with time jitter (±15 min) and location jitter within zone; k < 1 = thinning. Seeded, so runs reproduce |
| Simulator | `backend/twin/sim.py` | Discrete-event engine. Durations: per call class empirical distribution from report-card snapshots (FSL Platform only; Towbook times are fake), else planned duration. Response = travel + queue. Produces per-SA outcomes |
| Metrics | `backend/twin/outputs.py` | Per hour × zone × territory: PTA met %, simulated ATA (mean/p90), stacking (max/mean open jobs per driver), idle %, utilisation, unassigned. **Drivers needed**: bisection on added drivers per hour block until the PTA target (Henry/user) is met, using the fast policies only |
| Job runner | `backend/twin/run_job.py` (CLI) | Runs one queued sim/calibration job. Executed outside the web app (18.7) |

### 18.3 Data needed, and where it comes from
| Need | Source | Status in this design |
|---|---|---|
| SA location, created time, work type → skills, duration, PTA, priority | report-card snapshot `sas[]` (4) or twin demand set | Fields added to the snapshot: `priority`. Rest already present |
| Actual on-scene durations | snapshot `milestones` (FSL Platform; Towbook uses history 'On Location') | Present |
| Driver shifts, logins, absences | snapshot `drivers[]` (historical); supply set (current) | Present |
| Skills + skill levels | snapshot / supply set | `skill_levels` added to the snapshot |
| Home base, resource priority | `ServiceTerritoryMember` lat/lon, ServiceResource fields (per describe) | Added to snapshot Q4 + `drivers[].home_base`, `resource_priority` |
| Start positions / GPS | snapshot `drivers[].gps`, `start_position` | Present |
| Policy objectives, weights, work rules | SF policy objects (read-only) + optimizer request JSON (as-run) | New: `ops.twin_policy_version` |
| FSL's actual decisions (calibration truth) | SF `FSL__Optimization_Request__c` + Request/Response JSON files (since 2024-12) | Corpus job 18.5; Postgres `optimizer.*` optional |
| Real-world assigner behaviour (bypass) | snapshot `decision`, `candidate_sets`, `src_sa_verdict.final_actor_class` | Present (Phase 1 auditor) |
| FSL engine runs and policy actually used | snapshot `optimizer_sf` (Q13) | Present |
| Travel basis | `travel_basis` in snapshot; calibration result | Present; value set by calibration |

### 18.4 Calibration: the credibility number
Calibration is a job over stored data that produces `ops.twin_calib_run` rows keyed by
`(twin_engine_version, policy_version, travel_basis, corpus window)`.

**Step 0: travel basis.** For optimizer winners, FSL provides its own `EstimatedTravelTime` and
`FSL__EstimatedTravelDistanceTo__c` (`optimizer_parser.py:250`). Compare them with haversine from
each plausible origin (previous job end, GPS at run time, home base). Fit
`fsl_distance ≈ f · haversine` and `time ≈ distance / v(hour)`. Henry's first evidence: AR estimated
distance ÷ straight line = **1.42 median (IQR 1.22–1.67, n = 78)** on 9/28, which suggests road routing.
- `f` ≈ 1.0 → FSL uses aerial distance.
- `f` ≈ 1.2–1.5 with high variance → street-level routing.

The best-fitting origin also tells us where FSL thinks the driver starts. Henry also checks the
org's FSL "Street Level Routing" setting read-only. Result: the `travel_basis` used by all later
calibration.

**A. Optimizer path (twin vs FSL).** For each captured optimizer case: rebuild the candidate set
from the run's request (resources, territories, skills, absences, existing schedule) → twin
filters → twin scores → ranking.
- **Top-1 agreement:** twin's #1 = FSL's winner. **This is the headline number.**
- **Winner rank / MRR:** where FSL's winner sits in the twin's ranking (rank 1/2/3/≥4 histogram,
  mean reciprocal rank).
- **Feasibility agreement:** FSL's winner passes the twin's filters (catches missing work rules).
- **Unscheduled agreement:** SAs FSL left unscheduled vs the twin.
- Why not full rank correlation: FSL does not expose scores or rankings for losing candidates.
  The non-winner distances and the eligible/excluded labels in `opt_driver_verdicts` are
  **FSLAPP's own estimates** (home haversine ÷ 25 mph, `optimizer_parser.py:303`), not FSL
  output. Rank correlation against them would compare the twin with ourselves.
- Segmented by hour, call class, territory, candidate-set size and policy, so we can see *where*
  the twin diverges.

**B. Bypass path (twin vs real assigners).** For each snapshot SA assigned by an integration or human
account: does `bypass_heuristic` pick the same driver from the decision-time `candidate_sets`? There's no retention
problem here: snapshots persist and backfill to about 18 months.

**C. Path mix.** Share of assignments by path (optimizer / integration / human / FSL engine) by
territory × hour × call class, from `src_sa_verdict.final_actor_class`. Simulations use this mix by
default. The toggle **"What if all went through the optimizer"** sets mix = 100% `fsl_*` policy.

**UI.** Shown on every simulation result:

> "Twin agrees with FSL on **X%** of optimizer decisions (top-1, n = …, policy *Copy of Highest Priority* vH, travel *aerial-calibrated*, cases 2026-10-05 → 2026-12-31). Bypass model matches real integration picks on **Y%** (n = …)."

If X is below a configured threshold (default 70%, the user/Henry decide), results carry a
"low-fidelity twin" watermark and the AI is not allowed to recommend policy changes from them.

### 18.5 Calibration corpus: Salesforce is the system of record (no longer blocked by Postgres retention)
**Update from Henry's spec §10:** FSL keeps the optimizer trail in Salesforce:
- `FSL__Optimization_Request__c`: about 292k rows since 2024-12-13.
- `FSL__Territory_Optimization_Request__c`: links a run to its territory.
- `Optimization_Log__c`: trigger reason per run.
- Each run's `Request_…` / `Response_…` JSON files, attached via `ContentDocumentLink` → `ContentVersion`.
  `optimizer_sync._batch_get_content_versions` already reads these.

So the calibration corpus is built **from Salesforce, read-only, on our schedule**. The Postgres purges
(`optimizer_retention.py`, default 3 days via `FSLAPP_RETENTION_DAYS`; `optimizer_sync` `purge_old_runs(30)`)
no longer threaten it.

How it is built (job kind `corpus` in the 12.2 worker, same window, pacing and SF guards):
1. Run list per garage-day, already in the snapshot (`optimizer_sf.requests`, Q13). No extra query.
2. **Select only informative runs:** those matched to an FSL_ENGINE assignment event in that day's snapshot
   (48 events on WNY 9/28), plus a small random sample of no-change runs as negatives. This cuts about 450
   runs/day to about 30–60.
3. For each selected run, sequentially: one `ContentDocumentLink` lookup (batched), then download
   `Request_` and `Response_`. Parse them with the existing pure `optimizer_parser.parse_run` plus a new
   digest function, store the **digest**, and drop the raw file:
   - `ops.twin_calib_run`: run id, territory, ts, type, policy id, objectives + weights, work rules,
     `FSL__Commit_Mode__c`, etc.
   - `ops.twin_calib_case`: per deliberated SA: winner, FSL travel estimate, priority, duration, windows,
     WOLI skills, pinned flag. The candidate pool is rebuilt from the request's `Resources`: home lat/lon,
     territories, skills, absences, existing schedule.
4. Idempotent by run id. Runs whose files are missing are recorded `files_missing`, not retried.

**To verify before relying on it** (Henry or Kathy, read-only, small):
- Do the `Request_`/`Response_` files persist as long as the request rows? Count `ContentDocumentLink` for a
  sample of 2025 request ids. Files may be cleaned up even if records are kept.
- Do request skills include truck capabilities? If not, the request's own skill set will not reproduce
  spec S9 qualification, and the twin must add truck caps from AssetHistory (spec §9 note).

Postgres-side (optional, no longer blocking): the earlier "copy before purge" idea is kept only as a cheap
extra for allowlisted territories if `optimizer.*` is being synced at all. **To verify (Kathy, read-only):**
the actual `FSLAPP_RETENTION_DAYS` in Azure app settings, what (if anything) schedules
`optimizer_retention`, and `SELECT max(run_at), count(*) FROM optimizer.opt_runs`
(`optimizer_blob_sync.start()` is commented out in `main.py`). No purge logic or retention value changes.

SF load and size:
- About 30–60 runs × (2 downloads + share of 1 link query) ≈ **70–130 calls per territory-day**, heavier
  than a snapshot build. It therefore has its own nightly cap (`REPORT_CARD_CORPUS_MAX_CALLS_PER_NIGHT`,
  default 600) and its own API-headroom check.
- About 60 pilot-territory days (enough for > 2,000 FSL-engine decisions) is about 10 nights.
- Files can be MB-sized; downloads are streamed and digested, never stored raw.
- Digest size: about 1–2 KB per case + about 20–50 KB per run → **about 1–3 MB per territory-day**, about 0.5–1 GB per
  territory-year if run daily. The corpus is therefore sampled (default: 60 days per policy version per
  territory, refreshed when the policy hash changes), not built for every day.

### 18.6 Simulation runs
- **Demand:** a demand set (e.g. pilot area, 2026-01-01 → 2026-04-30), built once from SF by sequential
  month pulls (about 4–8 calls per territory-month) or from existing snapshots. Scaling ×k per territory
  or postal zone (18.2).
- **Supply:** current supply set, or an edited copy (−N drivers, new shift template, added skills).
- **Policies compared** in one scenario, with the same demand and seeds:
  1. `fsl_as_is` (captured policy, current weights) with the path mix from 18.4 C;
  2. `fsl_as_is`, 100% optimizer (toggle);
  3. `fsl_proposed` (e.g. a balance objective added; λ or weights from the scenario);
  4. `balanced_greedy`;
  5. `vrptw_hindsight`: OR-Tools routing per territory-day, time windows `[created, created + PTA]`
     soft with lateness penalty, vehicle shifts as time windows, skills as allowed-vehicle sets.
     Labelled "hindsight best-found within T s", a bound to compare against, not proven optimal and
     not achievable online.
- **Outputs** (`ops.twin_sim_result`, typed columns like `src_sa_verdict`): per run × territory × zone ×
  hour: n, PTA met %, ATA mean/p90, stacking, idle %, utilisation, unassigned, drivers needed for target.
  Per-SA outcomes are kept as a compact sample (`ops.twin_sim_sa`, optional) for drill-down.
- **Regret** (feeds Phase 1 verdicts later, engine bump): `scheduler_loss` = as-is − balanced/proposed
  at the same capacity; `capacity_short` = what remains even under the hindsight bound.
- **UI:** a third view, **Simulate**: scenario builder (demand range, garages, scaling map, supply
  edits, policies) → run → side-by-side policy comparison (hour × zone heatmaps, PTA curves, drivers-
  needed table). The calibration banner (18.4) always shows. AI recommendations use the same fact-sheet
  plus validator machinery as section 11, from run outputs only.

### 18.7 Execution and storage
- Runs are **offline jobs** in `ops.src_job_queue` (kinds `corpus`, `calibrate`, `simulate`), stored in
  Postgres. Corpus capture is light and can run in the web app's 12.2 worker. **Calibrate and simulate
  run outside the App Service process**: an Azure Container Apps Job reusing the
  `infra/postgres/backup-job.bicep` pattern, so CPU-heavy OR-Tools work never slows the live
  dashboard. The job image gets `ortools` (a large wheel), which keeps it out of the App Service zip
  deploy. Kathy owns this infra choice.
- Limits per job: VRPTW time limit (default 60 s per territory-day), max scenario size (e.g. ≤ 10
  territories × 120 days), cancellation flag.
- The daily policy capture is already in the Phase 1 migration (`ops.src_policy_capture`); the twin's
  `twin_policy_version` adds proposed (edited) policies on top of it.
- New tables (Phase 3 migration, additive, admin-applied, same conventions as 13):
  `twin_policy_version`, `twin_calib_run`, `twin_calib_case`, `twin_calib_request`, `twin_supply_set`,
  `twin_demand_set` (JSONB payload + summary columns), `twin_scenario`, `twin_sim_run`,
  `twin_sim_result`, `twin_sim_sa`. Size: a 4-month, 5-territory demand set is about 70k SAs × about 150 B ≈ 10 MB;
  results per run about 1–5 MB.

### 18.8 Risks: what we can't replicate exactly
| FSL internal / gap | Effect | Mitigation |
|---|---|---|
| Optimizer is a proprietary metaheuristic (global search, time-boxed, ES&O vs legacy engine) | The twin's greedy-per-event pick differs from batch global moves | Calibrate separately for real-time scheduling vs batch optimization runs; report agreement per mode |
| Exact objective normalisation/scoring formulas are not public in full | Weighted sums differ near ties | Measure winner-rank; tie-aware top-1 (count a "tie within ε" separately) |
| Street-level routing / traffic / predictive travel | Travel time error | Step 0 fit; OSRM only if needed; report travel-error distribution |
| Apex custom work rules / custom objectives / RSO Apex (`FSL.OAAS.ResourceDayOptimization`) | Unmodelled constraints | Policy capture lists every rule; unsupported ones are shown in the UI with the share of decisions affected |
| External integration (Mulesoft/IT System User) selection algorithm is not in any repo | The bypass path is a heuristic | Calibrate against snapshot history (18.4 B); show Y% |
| Priority-based unscheduling, pinned SAs, scheduling horizon, commit mode | Different bumping behaviour | Captured from request JSON (`FSL__Pinned__c`, `ERS_Dynamic_Priority__c`, `FSL__Commit_Mode__c`) where the corpus has it |
| Human behaviour: declines, bounces, late logins, cancellations, GPS staleness | Optimistic sim | Replay historical cancellation/decline rates by call class as stochastic events; seeds + confidence bands |
| A "balance" objective may not exist natively in FSL | A proposed policy might not be deployable as-is | Flag `fsl_native=false`; a recommendation must say whether it needs a custom objective/Apex (Henry verifies) |
| Current skills/shifts applied to old demand | Cross-period mismatch (e.g. a winter mix vs a summer roster) | Explicit in the scenario label; supply edits allow seasonal rosters |
| Duration and demand scaling assumptions | Bias in scaled zones | Bootstrap from the same zone/hour/call class; sensitivity runs (k ± 10%) |
| Calibration files missing in SF for older runs | Smaller corpus | 18.5 verification; `files_missing` recorded; until enough cases exist, show "uncalibrated" and block policy recommendations |
| Compute load | Dashboard slowdown | Separate job container; time limits; queue |

---

## 19. Phase 3b: Real-engine validation in a sandbox (design only)

### 19.1 Goal
For a few chosen scenario days (for example the worst Jan–Apr 2026 days), load the demand into a **UAT/full
sandbox**, run the **real** FSL scheduler/optimizer there, read the results back, and compare them with the
shadow twin on the same inputs. This is the strongest check that the twin behaves like FSL, beyond top-1
agreement on historical runs. **Never production.**

### 19.2 Rejected option: production Apex savepoint/rollback around GradeSlots/GetSlots
The idea was to deploy Apex to production that sets a `Database.setSavepoint()`, inserts SAs, calls
`FSL.GradeSlotsService` / `FSL.AppointmentBookingService.GetSlots`, reads grades, then rolls back. Rejected:
1. It needs a **production deployment** of new Apex. That's a change to the live dispatch org and outside
   our read-only boundary.
2. **Side effects escape the rollback:** inserting SAs/WOs fires triggers and flows. Platform events
   published "immediately", `@future`/queueable jobs, outbound messages and integration callouts can be
   queued or delivered regardless of the rollback (some publish behaviours are not transactional).
   Mulesoft/Replicant/Towbook integrations and member SMS could fire.
3. **Enhanced Scheduling and Optimization runs off-platform:** its callouts can't see uncommitted DML, and
   Apex can't make callouts after uncommitted DML in the same transaction anyway. So for ESO-backed
   scheduling, the rollback approach either errors or evaluates without the inserted records.
4. Locks and sharing recalculation on live territories during dispatch hours. That is a risk to real dispatch.

### 19.3 Components (separate from everything else)
| Component | Where | Notes |
|---|---|---|
| `sandbox_client.py` | `backend/twin/sandbox/` (never imported by the web app or `sf_client`) | Its own OAuth client and token cache. Reads **only** `SBX_*` settings |
| `loader.py` | same | Builds sandbox records from a scenario (demand set + supply edits) and inserts them via Composite/Bulk API 2.0 |
| `runner.py` | same | Triggers scheduling in the sandbox (19.5) and polls completion |
| `reader.py` | same | Reads back AssignedResource, SA sched times, `FSL__Optimization_Request__c` and the response files for the run |
| `compare.py` | same | Feeds the identical scenario to the twin and computes agreement (top-1, winner rank, KPI deltas) → `ops.twin_sandbox_result` |
| `cleanup.py` | same | Deletes only records tagged with the run's tag, in the sandbox, after a preview (19.6) |
| Execution | the Phase 3 Container Apps Job (18.7) | Never the App Service. The App Service has no `SBX_*` secrets |

### 19.4 Isolation from production credentials (hard guards)
1. **Separate config and secret store.** `SBX_TOKEN_URL`, `SBX_CONSUMER_KEY/SECRET`, `SBX_USERNAME`,
   `SBX_PASSWORD`, `SBX_ORG_ID` exist only in the job's secrets. The job's environment has **no** `SF_*`
   production variables, and `sandbox_client` refuses to start if any `SF_*` variable is present.
   `backend/sf_client.py` reads `FSLAPP/.env` (production) at import, so the sandbox package must never import
   it, directly or indirectly. A unit test asserts that.
2. **Write guard, checked before any write in every run** (not cached):
   - `SELECT Id, IsSandbox, InstanceName, OrganizationType FROM Organization` must return
     `IsSandbox = true` **and** `Id = SBX_ORG_ID` (an allowlisted sandbox org id).
   - The token response `instance_url` must not equal the production instance (a hard-coded deny-list,
     including the `login.salesforce.com` token endpoint; sandboxes use `test.salesforce.com` or their My
     Domain `--<sandbox>.sandbox.my.salesforce.com`).
   - Any mismatch → abort, log and alert. The guard lives in the client's only write method, so no code
     path bypasses it.
3. **Least privilege in the sandbox:** a dedicated integration user with a permission set limited to the
   objects the loader writes. Kathy and the Salesforce admin own the sandbox user. No credentials are shared
   with the production read user.
4. **Never real people.** Records use a synthetic Account/Contact ("TWIN REPLAY", 555-01xx numbers, no real
   member data or addresses beyond the call lat/lon), so sandbox flows can't message a member.

### 19.5 Loader and run
- **Prerequisites** (Salesforce admin, one-time, in the sandbox):
  - Email deliverability set to "System email only" or "No access".
  - Integration named credentials (Mulesoft, Replicant, Towbook, SMS) pointed to mocks or disabled.
  - Confirm the ERS automation bypass setting (if one exists) for the replay user.
  - The roster: a **full** sandbox carries production ServiceResources, territories, policies and skills. A
    partial sandbox needs the supply set loaded too.
  - Prefer a dedicated sandbox, or agreed time windows, so other UAT work isn't disturbed.
- **Time shift:** FSL won't schedule into the past. A scenario day is mapped to a future date (same day of week,
  same local times). Shifts/availability for that date are created for the replay drivers (truck-login
  equivalents → `Shift` or operating hours, whichever the sandbox policy's availability rules read).
- **Records per call:** WorkOrder → WorkOrderLineItem (with SkillRequirements) → ServiceAppointment, tagged
  with `TWIN-<run_id>` in a text field (Subject/Description; no metadata change needed), in arrival order.
- **Two modes:**
  - **Batch:** load the whole day, then run a territory optimization with the policy under test (as-is or
    proposed). The engine's best plan with all calls known, comparable to the twin's batch mode and the VRPTW
    bound.
  - **Online replay:** insert calls in arrival order and call scheduling per SA. This needs a tiny sandbox-only
    Apex REST endpoint wrapping `FSL.ScheduleService.schedule(policyId, saId)`. It is deployed to the sandbox
    only, never to production. Compressed clock: wall-clock "now" differs from the scenario clock, so ASAP
    is relative to real time. That is a known fidelity limit, recorded with results.
- **Read back:** assignments, scheduled start/end, unscheduled reasons, and the run's response file.
  Comparison runs the twin on the identical scenario JSON.

### 19.6 Cleanup
- Every record carries the run tag. Cleanup runs per run, in reverse dependency order (AR → SA → WOLI → WO →
  Shifts → synthetic Account/Contact if unused), via Bulk API delete, **in the sandbox only** (same write
  guard).
- It is still a delete, so per the user's rules it follows **preview → approval**: counts per object are
  shown, the user says yes for that run, then it deletes. Afterwards, counts are verified to be zero.
- Backstop: the next sandbox refresh wipes everything. Runs are also scheduled shortly before planned
  refreshes when possible.

### 19.7 Cost
| Item | Estimate |
|---|---|
| Sandbox API calls | Separate limits from production (zero production API use). Per territory-day: about 150 calls × 3–4 records via Composite (about 25 requests) + online mode about 150 schedule calls + read-back about 10 → about 200 calls |
| Sandbox storage | SF counts about 2 KB per record → 150 calls × 4 records × 2 KB ≈ 1.2 MB per territory-day; 20 days × 5 territories ≈ 120 MB (trivial in a full sandbox; matters in a Developer Pro 1 GB sandbox) |
| Run time | Batch: minutes. Online: about 150 × 2–5 s ≈ 5–15 min per territory-day |
| People | One-time sandbox setup with the Salesforce admin (deliverability, integrations, user, Apex REST class deploy to the sandbox): about 1–2 days. Per study: scenario selection (Henry), approval of each cleanup (user) |
| Licences | Sandbox FSL licences mirror production; no new cost expected (admin confirms) |
| Risk cost | A misconfigured sandbox integration could reach real systems. Mitigated by prerequisites, synthetic contacts and dry-run first (one call, observe for 24 h) |

### 19.8 Output
`ops.twin_sandbox_result (sandbox_run_id, scenario_id, mode, policy_version, twin_engine_version,
top1_agreement, winner_rank_hist, kpi_deltas JSONB, notes)`. The Simulate view's credibility banner gains a
second line: "Real-engine check in sandbox: twin matched FSL on X% of N decisions (batch) / Y% (online), runs
…". When sandbox and historical calibration disagree, both are shown, never averaged.
