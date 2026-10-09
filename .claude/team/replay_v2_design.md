# Replay v2 — design (Dan, 2026-10-08)

Status: owner-approved scope; Ruby builds from this. Covers the Work Order Replay and Garage Replay.
Branch base: `fix/replay-click-and-500` (keep its uncommitted fixes; do not revert anything).

## 1. Goal

A replay opens in about 1 second, can be clicked at once, and plays like a game: trucks drive smoothly on roads at
60 fps, with speeds up to 300×. Member calls, member texts and the driver's other jobs load afterwards, so they never
slow down the first picture. Salesforce use per opened call drops from 12 calls to 3–4, and that includes the new data.

## 2. What is slow today (measured 2026-10-08, read-only, call SA-1067245 / WO 05164342, 9/24)

| Endpoint | SF calls | Wall time | Notes |
|---|---|---|---|
| `/api/call-story/replay` (story) | 9 (37 of 44 cached stories show 10) | 1.35 s SF + 0.4 s norms (cold) | 9 serial queries, about 0.11–0.24 s each. Resolving an SA# alone costs 2. |
| `/api/call-story/replay-map` | 3 | **35.2 s cold**, 0.4 s warm | `ServiceResourceHistory` GPS: **34.9 s on first read**, 0.33 s when the same query is repeated. The object has 13.4M rows. The cold cost is on Salesforce's side and hits every newly opened call. |
| `/api/report-card/{t}/{d}/replay` | 0 | file read | snapshot |
| `/api/report-card/{t}/{d}/call-flags` | 4 per 200 calls | — | unchanged |

Why the screen feels blocked:
- `WoReplayStage` waits for the map before it autoplays ("plays by itself when ready"), so it sits idle for up to 35 s.
- `buildTimeline` depends on `tracks`, so when the map arrives the step lengths change and the animation jumps.
- Both clocks call `setState` on every frame (`useStepClock`: 60 fps; `useReplayClock`: 30 fps). Each tick re-renders
  the whole 479-line stage, or in the Garage view `ReplayBody` + `DayGantt` + the roster. The main thread stays busy,
  so clicks lag.
- `GarageReplay` mounts `ReplayPanel` in two places: before the day replay arrives, then again inside `ReplayBody`.
  When the day replay lands, the call's stage unmounts, remounts and restarts.

Prototypes run during design (scratchpad only, all read-only):
- One `/composite` request holding 3 queries returned exactly what the 7 serial story queries return (same WO,
  2 SAs, 6 texts, 205 history rows, 1 AR). It took **0.35–0.46 s**.
- In the saved snapshots, **3,742 of 3,894** non-Towbook calls (96%) have every driver who held the call on the
  roster with at least 2 GPS points. For those calls the map needs **0** Salesforce calls.
- Every `ERS_Assigned_Resource__c` history change in the sample (12 of 12) is written as an id row plus a name row
  with the same timestamp. That means the map's `ServiceResource` name→id query is not needed.
- Driver jobs + status trail + WO phones in one composite request: 0.34 s. VoiceCall + MessagingSession in one: 0.32 s.
- VoiceCall check on WO 05195032 (10/07): `FromPhoneNumber` format is `+1 999 999 9999`. The original call came
  **2 min before** the WO was created. Two "MCC ERS Replicant Return" callbacks came about 2 h 20 min later.
- All new fields were checked with describe calls, and all of them can be filtered on: `SMS_Send_Log__c.Messaging_End_User__c`,
  `WorkOrder.Mobile_Phone__c` / `Callback_Phone__c` (stored as 10 bare digits), `SA.ERS_Assigned_Resource__c`,
  `SA.Off_Platform_Driver__c` (Contact), the VoiceCall fields, `MessagingSession.{Origin, MessagingEndUserId, ConversationId}`,
  `MessagingEndUser.MessagingPlatformKey` and `Conversation.ConversationIdentifier`.
- Child relationship names: `WorkOrder.Service_Appointments_del__r` (SA via ERS_Work_Order__c),
  `SMS_Send_Logs__r` and `Work_Order_Survey_Results__r`.

## 3. Salesforce plan (after)

### 3.1 Shared helper (workstream A, step A1; must be done first)
- `sf_client.py`: `sf_composite_query(named: dict[str, str]) -> dict[str, dict]`. It POSTs `/composite` with
  `allOrNone: false`, one GET `/services/data/{SF_API_VERSION}/query?q=...` per entry (`referenceId` = the key), and
  returns `{key: {'status': int, 'body': ...}}`. **Load-bearing detail:** URL-encode the SOQL, then put any
  `@{ref.records[0].Id}` back unencoded. If the reference is encoded, Salesforce returns `INVALID_QUERY_FILTER_OPERATOR`
  (seen in the prototype). Limit: 5 query subrequests per request.
- `report_card_build.Puller.composite(named) -> dict[str, list]`. It counts **1** call. For any result with
  `done: false` it follows `nextRecordsUrl` (+1 call per page, same loop as `sf_query_all`). A subrequest that is not
  200 raises `CompositeError(key, body)`. Child subqueries (`X__r`) with `done: false` also raise `CompositeError`, and
  the caller falls back. Salesforce documents a composite request as one call against the daily API limit.

### 3.2 Story (`call_story_pull.pull_story`): 9–10 → **1** call (+ the existing optional matrix 0–2 / optimizer 0–1)
One composite request:
- `wo`: `SELECT {WO_FIELDS}, (SELECT {SA_FIELDS}, ServiceTerritory.Latitude, ServiceTerritory.Longitude FROM
  Service_Appointments_del__r ORDER BY CreatedDate), (SELECT <today's SMS fields>, Messaging_End_User__c FROM
  SMS_Send_Logs__r ORDER BY CreatedDate), (SELECT Name, ERS_Overall_Satisfaction__c, ERS_Survey_Completed_Date__c FROM
  Work_Order_Survey_Results__r) FROM WorkOrder WHERE <resolve filter> LIMIT 3`
  Resolve filter by input type: sa → `Id IN (SELECT ERS_Work_Order__c FROM ServiceAppointment WHERE AppointmentNumber='SA-x')`;
  id 08p → same with `Id='x'`; id 1WL → `Id IN (SELECT WorkOrderId FROM WorkOrderLineItem WHERE Id='x')`;
  0WO → `Id='x'`; call_key → `ERS_Call_Key__c='x'`; wo → `WorkOrderNumber='x' OR ERS_Source_Call_ID__c='x'` (2+ rows → `Ambiguous`, same payload as today);
  source → `ERS_Source_Call_ID__c='x'`.
- `hist`: today's history SELECT with `WHERE ServiceAppointmentId IN (SELECT Id FROM ServiceAppointment WHERE ERS_Work_Order__c = '@{wo.records[0].Id}') ORDER BY CreatedDate, Id`
- `ar`: today's AssignedResource SELECT with the same semi-join.

After the request, rebuild **the same `raw` dict shape as today** (`wo` without child keys, `sas`, `history`,
`assigned`, `sms`, `survey`), so `compose()` and everything after it stay unchanged. Keep the ≥1000-row history COUNT
check, the RecordType/NotSupported checks and the pre-9/1 `MessagingSession` path as they are.
**Fallback:** on `CompositeError` (or 0 WO rows → `NotFound`), log a warning and run today's sequential code. That
code stays as the slow path. Do not delete `resolve()`.
`raw['sf_calls']` keeps counting through the Puller. Phones are **not** added to this query: the raw is saved to the
file store, and phones must never be stored.

### 3.3 Map (`wo_replay_map.pull_map`): 3 → **0** (snapshot) or **1** (GPS only)
1. Driver ids: pair the id row and name row of `ERS_Assigned_Resource__c` in `raw['history']` by
   `(ServiceAppointmentId, CreatedDate)`. Use the `ServiceResource` name query only for names still unpaired.
2. Garage coordinates: read them from the member SA's `ServiceTerritory.Latitude/Longitude` (now in the story raw). The `ServiceTerritory` query is no longer needed.
3. GPS, snapshot first: new arg `snapshot_for(tid, date)` (the router passes `store.load_snapshot`). Territories =
   the member SA's `ServiceTerritoryId` plus the id rows of `Field='ServiceTerritory'` in history, at most 3. Date = the
   ET date of the SA's CreatedDate (`utils.to_eastern`). Use a snapshot driver's `gps` only when
   `snap['built_at'] >= window end` and the driver has at least `MIN_PINGS` points inside the window. Mark it `source: 'snapshot'`.
4. Only drivers still missing GPS go to `ServiceResourceHistory`, in one query as today. Narrow the window **per driver**: from
   their first assignment − 30 min to their last un-assignment, or the member SA's On Location, + 5 min.
5. Closed calls: also `cache.disk_put(f'cs_map:{wo_id}', out, ttl=7*86400)`, so a reopen after a restart is instant.
6. Roads (not Salesforce): see 3.6.

### 3.4 New data (`/api/call-story/extras`): **2** calls, about 0.7 s, after the story
Round 1, one composite request with 3 queries (no references):
- `phones`: `SELECT Mobile_Phone__c, Callback_Phone__c FROM WorkOrder WHERE Id='{wo}'`. Kept in memory only, never returned, cached or logged.
- `jobs`: `SELECT Id, AppointmentNumber, ERS_Work_Order__c, WorkType.Name, Status, CreatedDate, Latitude, Longitude,
  ERS_Assigned_Resource__c, Off_Platform_Driver__c FROM ServiceAppointment WHERE <driver filter> AND CreatedDate >= {T0-12h}
  AND CreatedDate <= {T1+1h} AND RecordType.Name = 'ERS Service Appointment' ORDER BY CreatedDate LIMIT 200`.
  The driver filter is `ERS_Assigned_Resource__c IN (<ids of drivers who were Dispatched/Accepted on the member SA>)`, and/or
  `Off_Platform_Driver__c = '<member SA's Off_Platform_Driver__c>'` for Towbook. Both fields are lookups (indexed).
  T0 = first assignment on the member SA. T1 = the member SA's On Location, else its end, else now.
- `trail`: `SELECT ServiceAppointmentId, NewValue, CreatedDate FROM ServiceAppointmentHistory WHERE Field='Status' AND
  ServiceAppointmentId IN (SELECT Id FROM ServiceAppointment WHERE <same filter as jobs>) ORDER BY CreatedDate`.
Round 2, one composite request with 2 queries. Skipped (0 calls) when there are no phones and no messaging end user:
- `calls`: `SELECT Id, CallStartDateTime, CallEndDateTime, CallDurationInSeconds, CallAcceptDateTime, ToPhoneNumber,
  CallType, User.Name FROM VoiceCall WHERE FromPhoneNumber IN ('+1 585 831 9725','+15858319725', ...both phones) AND
  CreatedDate >= {created-30m} AND CreatedDate <= {W_END} ORDER BY CallStartDateTime LIMIT 50`.
- `sessions`: `SELECT Id, CreatedDate, StartTime, EndTime, Status, Owner.Name, Conversation.ConversationIdentifier,
  MessagingChannel.MasterLabel, MessagingChannel.DeveloperName FROM MessagingSession WHERE Origin='InboundInitiated' AND
  CreatedDate >= {created-30m} AND CreatedDate <= {W_END} AND (MessagingEndUserId IN (<Messaging_End_User__c ids from
  raw['sms']>) [OR MessagingEndUserId IN (SELECT Id FROM MessagingEndUser WHERE MessagingPlatformKey='+1{digits}')]) LIMIT 50`.
  Use the platform-key branch only when the SMS log has no end user (16% of WOs; all pre-9/1 calls). Keep a row only
  when its channel label or developer name contains "ERS SMS" (case-insensitive). Henry's name for the channel is not
  yet tied to a specific field, so filter in Python.
`W_END` = the last terminal status time on the member leg + 60 min. For an open call it is now. It is never more than created + 24 h.

### 3.5 Message thread (`/api/call-story/text-thread`): **1** call per click
`sf_rest_get(f'/connect/conversation/{ConversationIdentifier}/entries', {'startTimestamp': ms(created-30m), 'endTimestamp': ms(W_END)})`
(read-only GET). The ConversationIdentifier comes from the **server-side** cached extras raw, never from the browser.
Clean each body with `case_trail.clean_text` (it unescapes `&amp;` and strips tags). Map `ActorType` EndUser → member,
Agent → agent, System/Bot → system. Before mapping the response, Ruby logs the key names from one real response in the
scratch harness, because the entry shape has not been seen in code yet.

### 3.6 Roads (OSRM, not Salesforce)
- New `backend/osrm.py`: `route(points: list[tuple[lat, lon]], timeout=8) -> {'coords': [[lat, lon]...], 'miles',
  'minutes', 'snapped': [[lat, lon] per waypoint]} | None`. It uses the public server already used by the contractor
  map, flips lon/lat in one place, and keeps the result on disk via `cache.disk_put('osrm:' + sha1(rounded points), ttl=7d)`.
  `contractor_dispatch._osrm_leg` becomes a 3-line wrapper around `osrm.route([a, b])` with the same return shape, so
  the logic is not duplicated.
- New `backend/wo_replay_roads.py`: `moving_runs(track)` splits a track into runs of pings more than 0.25 mi apart,
  each run 2–25 points. `snap_runs(track, budget_s=6, max_requests=6)` returns
  `[{'t': [ping times], 'i': [vertex index of each ping], 'c': [[lat, lon]...]}]`. To find `i`, scan forward to the
  nearest vertex of each `snapped` waypoint. Anything over the budget stays a straight line. Thin `c` to at most 1500 vertices.
- `pull_map` adds `drivers[k].road` and `roads.garage_to_member` (one route). The frontend uses the second one for the
  estimated Towbook vehicle and for drivers with no GPS.

### 3.7 Cache keys and lifetimes
| Key | Where | TTL |
|---|---|---|
| `cs_raw:{wo}` / file store | unchanged | closed 24 h / open 120 s |
| `cs_map:{wo}` | memory + disk (closed only) | closed 7 d / open 120 s |
| `cs_extras:{wo}` | memory (closed: + disk). Contains no phones and no message bodies. | closed 24 h / open 120 s |
| `cs_extras_conv:{wo}` (conversation ids) | memory only | same as extras |
| `cs_thread:{wo}` (message bodies) | **memory only, never disk** | 1 h |
| `osrm:{sha1}` | disk | 7 d |

## 4. API contracts

All routes are read-only, on GET. Gates: flag `call_story` + permission `scheduler.replay` + the territory check, all
via `get_story`, as today. Extras and thread also need the new flag **`replay_member_contact`** (default off in
`feature_flags.DEFAULT_FEATURES`). Errors are the same as the story's: 400/404/409/422/429/503. A cache miss goes
through `_rate_limit`. Times are ISO UTC strings, plus epoch seconds where the player needs them. ET appears only in the UI.

**`GET /api/call-story/replay?q=`** (existing) adds:
`header.where = {member: {lat, lon} | null, garage: {name, lat, lon} | null}` (member rounded to 4 decimals, garage
to 5), and `meta = {sf_calls, cache, ms}`. The data comes from the story raw, which is free.

**`GET /api/call-story/replay-map?q=`** (existing) adds: `drivers[k].source: 'snapshot'|'salesforce'`,
`drivers[k].road: [{t, i, c}]` (may be `[]`), `roads: {garage_to_member: {c, miles, minutes} | null}`, and
`sf_calls`. Everything else stays the same.

**`GET /api/call-story/extras?q=`** (new, `routers/replay_extras.py`)
```json
{ "window": {"from": "...Z", "to": "...Z"},
  "calls": [{"id": "c1", "ts": "...Z", "end": "...Z", "answered_at": "...Z|null", "duration_s": 160,
             "line": "MCC ERS Replicant Return", "kind": "original|callback", "min_after_create": 141.0,
             "agent": "J. Smith|null", "direction": "inbound|outbound"}],
  "inbound_texts": [{"id": "t1", "ts": "...Z", "end": "...Z|null", "min_after_create": 22.5, "agent": "...|null"}],
  "thread_available": true,
  "driver_load": [{"driver": "Anthony Tabb Jr | Towbook Driver", "channel": "fleet|towbook",
                   "accepted_at": "...Z|null",
                   "current": {"sa": "SA-1", "work_type": "Tow", "status": "On Location"} ,
                   "ahead": [{"sa": "SA-2", "work_type": "Battery", "status_at_accept": "Dispatched",
                              "on_location": "...Z|null", "lat": 42.1, "lon": -78.1}],
                   "after": [{"sa": "SA-3", "work_type": "Tow", "taken_at": "...Z", "lat": 42.2, "lon": -78.2}],
                   "jobs_in_window": 4}],
  "insights": [{"code": "CALLED_BACK", "level": "info|warn|bad", "text": "...", "ts": "...Z|null"}],
  "notes": ["No phone number on this work order, so member calls cannot be matched."],
  "sf_calls": 2, "cache": "hit|miss" }
```
Rules (pure, `replay_extras.py`):
- A **callback** is a call that starts at least 15 min after WO creation (owner-approved). An earlier call is the original call.
- **On his plate at accept time A** is a non-drop-off SA on another WO whose last Status at or before A, from the trail, is in
  {Dispatched, Accepted, En Route, On Location}. **Henry confirms this status set before B1 is coded.**
  `current` is the one that is En Route or On Location. `ahead` is the rest. Towbook On Location comes from the trail, never `ActualStartTime`.
- **after** is another WO whose first Dispatched/Accepted trail time falls between A and the member SA's On Location.
- Tow legs are grouped by `ERS_Work_Order__c`, and Tow Drop-Off SAs never count or get pins. Towbook drivers are never
  named. Henry's measured limit: jobs later taken away from the driver are not seen (`ERS_Assigned_Resource__c` is current-holder only).
- Insights: at most 4, worst level first. The wording below is **Henry's to approve**:
  CALLED_BACK "Member called back {n}× while waiting (first {m} min after the call came in)" (warn when n≥2 or when a
  callback came after the promise time, then bad); TEXTED_IN "Member texted in {n}×"; DRIVER_AHEAD "When {driver}
  accepted, {n} job(s) were ahead of this member"; DRIVER_MORE_AFTER "{driver} took {n} more job(s) before reaching this member".
- Never in the response: a phone number, a street address, or a message body.

**`GET /api/call-story/text-thread?q=`** (new): `{"entries": [{"ts": "...Z", "who": "member|agent|system", "text": "..."}], "sf_calls": 1}`.
It returns 409 `load_extras_first` when the extras are not cached. Every miss is logged:
`log.info('text thread viewed user=%s wo=%s')`.

## 5. Frontend: progressive loading and the game engine

### 5.1 Loading order (no waiting on the slowest part)
1. **0 ms:** the stage shell renders. The map can be panned, and the controls show a light "loading" state.
2. **Story (~0.5–1 s):** steps, timeline ticks, the member pin and the garage (from `header.where`). **Autoplay starts here.**
3. **Map (0–35 s):** trucks fade in when their tracks arrive. The timeline length **does not change**, because the
   clock now runs in real time and no longer uses per-step durations.
4. **Extras (~0.7 s, started after the story):** contact icons pop onto the timeline and the member pin, the "other
   jobs" pins appear, and the insights strip fills in.
5. **Click:** the text thread loads.

`GarageReplay`: render **one** `<ReplayPanel key={number}>` in a fixed slot above the day map, whatever state the day
replay is in. Remove the second mount inside `ReplayBody`. The call's stage then never restarts when the day replay lands.

### 5.2 Engine (60 fps, no React render per frame)
`components/replay/useReplayEngine.js`:
```js
const engine = useReplayEngine({ start, end, events /* epoch s, sorted */, initial, speed: 60, busy /* t => bool */ })
engine.subscribe(fn)            // fn(t) on every animation frame while playing, and once after each seek; returns unsubscribe
engine.play() / pause() / toggle() / seek(t) / setSpeed(x) / next() / prev()
engine.ref.current              // { t, playing, speed, boosted }
useEngineState(engine, hz = 4)  // React state {t, playing, speed, boosted}: at most 4 renders/s, plus at once on play/pause/seek/speed
useEngineIndex(engine)          // index of the last event at or before t; re-renders only when it changes
export const SPEEDS = [1, 10, 60, 300]   // real seconds per wall second; default 60
```
- **Quiet gaps:** when the next event is more than 10 real minutes away and `busy(t)` is false (no truck moving),
  play at speed × 5 and show the HUD badge "Fast-forwarding quiet time".
- **Keys:** Space plays/pauses, ←/→ go to the previous/next event, Shift+←/→ move 5 min, 1–4 pick a speed.
- **Reduced motion:** no autoplay and no pulsing.

`components/replay/roadPath.js`: `buildPath(track, roadRuns) -> { at(t) -> {lat, lon, heading} | null }`.
It precomputes cumulative distances per run and uses binary search. Between the pings of a run it interpolates
distance along the road. Outside runs it uses today's straight `positionAt`. `buildLeg(coords, t0, t1)` handles timed
estimated legs (Towbook garage→member between the trail's En Route and On Location).

### 5.3 Work Order stage (`WoReplayStage.jsx` rewrite, ≤ 400 lines)
- **Imperative layers** (`woreplay/stageLayers.js`): trucks get a divIcon built once. Each frame does `setLatLng` and
  sets the `.hdg` element's CSS rotate. **Never call `setIcon` per frame.** The trail polyline updates at 10 Hz.
- **Member pin with waiting timer:** the `.wait` text updates every frame. Its class changes `ok → due-soon (≤10 min
  to promise) → late (pulsing red glow)` and is written only when the state changes. The timer stops at On Location.
- **Contact marks** sit around the member pin: phone (`PhoneCall`), callback (`PhoneIncoming`), outbound text
  (`MessageSquareText`), inbound text (`MessageCircleReply`). Each pops in (CSS `rp-pop`) when t reaches it. A click opens the panel.
- **Other-jobs pins:** grey numbered pins. At the accept time, "ahead" pins glow amber.
- **Camera:** "Follow truck" (default; lerp toward the acting truck when it leaves the middle 60% of the view) or
  "Show all". A user drag switches to Free, and a button switches back. This replaces Auto camera + zoom ratio.
- **Event effects run on wall time:** when `useEngineIndex` changes, the HUD sphere pulse plays a 900 ms CSS/SVG
  `animateMotion`, the message card updates, and `EventToasts.jsx` shows a small toast (top-right under the HUD,
  at most 3, 3.5 s each, framer-motion; red when flagged). At 300× the effects stay readable.
- **Keep:** the HUD channel bar, the flow drawer (it now also hosts `ContactPanel` when a mark is open), full screen,
  and "Pause at problems" (renamed from "Hold at each message"). In `woReplayModel.js`, remove
  `buildTimeline/stepAt/realTimeAt/STEP_S` and delete `useStepClock.js`.
- **Controls row:** Prev event · Play/Pause · Next event · scrubber (event ticks + contact icons, clickable) · 1×/10×/60×/300× · Camera · Full screen.

### 5.4 Garage Replay
`ReplayBody` switches to the engine. `DayReplayMap` subscribes and moves driver markers every frame. Status colours,
the roster, the counts and the `DayGantt` playhead update from `useEngineState` (4 Hz). Calls past their promise get
the `rp-pulse` ring. `ReplayPlayer` gets the new speeds plus Prev/Next call buttons. `useReplayClock.js` is deleted.
The day map does not get road paths in this version (too many OSRM requests).

### 5.5 Below the stage: tabs, not a stack (owner rule)
`ReplayTabs.jsx` with URL state `?rtab=`: **What went wrong** (TakeawaysCard) · **Member contact · n** · **Driver's
other jobs · n** · **Right driver?** (the decision block moves out of ReplayPanel). `InsightStrip` sits above the tabs.
Each callout has "Show", which seeks the engine to its `ts`. Opening a call, a text or a job always takes one click.

## 6. Risks and edge cases
- **Composite:** at most 5 queries per request (we use 3) and at most 2 semi-joins per query (we use 1). Child rows past one page fall back to the slow path.
- **Cold GPS (35 s)** still happens for calls not in a built snapshot (Work Order tab, unbuilt days, or the 4% of
  drivers off the roster). It no longer blocks anything, and the 7-day disk cache makes reopening free.
- **Provisional snapshots:** use one only when `built_at` is at or after the window end.
- **Towbook:** no GPS. The estimated vehicle follows the OSRM road, timed by the trail's En Route → On Location
  (never `ActualStartTime`). Towbook drivers are never named.
- **Tow Drop-Off:** excluded from job counts and pins (the map pins only the pick-up).
- **DST:** the backend works only in UTC. The ET date for the snapshot comes from `to_eastern`. The UI formats with `timeZone: 'America/New_York'`.
- **Privacy:** phones stay in memory inside the extras pull only. Message bodies are fetched only on click, kept only
  in the memory cache, and each view is logged. Agent names are internal staff names.
- **Empty data:** every section returns `[]` with a plain note. An open call uses `W_END = now` and a 120 s cache.
- **Pre-9/1 calls:** no messaging end user, so the platform-key fallback is used. Outbound calls to the member (agent dialling out) are not matched in v2.
- **OSRM** is a public server with no SLA. Any failure falls back to straight lines, with a 6 s total budget per map.
- **Load:** hover prefetch now costs 1 call instead of 9–10. Extras and map may run at the same time for one user (2 concurrent requests). That is acceptable.

## 7. Workstreams (separate files; merge order A1 → B and A in parallel → C wires B last)

**A — Speed (backend), owner Ruby-A**
`sf_client.py`, `report_card_build.py`, `call_story_pull.py`, `wo_replay_map.py`, `wo_replay.py`, `routers/call_story.py`,
`routers/contractor_dispatch.py` (wrapper only), new `osrm.py`, new `wo_replay_roads.py`.
Tests: update `test_call_story.py`, `test_wo_replay_map.py`, `test_wo_replay.py`, `test_call_story_api.py`. New:
`test_sf_composite.py`, `test_osrm.py`, `test_wo_replay_roads.py`.
Steps: A1 composite helper + Puller.composite (merge first, about half a day) → A2 story fast path + fallback → A3 map
(history ids, territory coordinates, snapshot GPS, per-driver window, disk cache) → A4 OSRM + roads → A5 `header.where` + `meta` → A6 router logging (`sf_calls`, ms).

**B — Member contact and driver load (full stack), owner Ruby-B**
Backend: new `replay_extras_pull.py` (the 2 composites), `replay_extras.py` (pure rules + insights), `replay_thread.py`,
`routers/replay_extras.py`; one line each in `main.py` (include router) and `feature_flags.py` (`replay_member_contact: False`).
Tests: new `test_replay_extras.py` (fixture modelled on WO 05195032: original call 2 min before creation + 2
callbacks), `test_replay_extras_pull.py` (fake `Puller.composite`), `test_replay_thread.py`.
Frontend: `api.js` (`fetchCallStoryExtras`, `fetchCallStoryTextThread`), `reportcard/prefetch.js` (`loadStoryExtras`
90 s, `loadTextThread` 60 s), new `woreplay/contactMarks.js` (pure: `contactMarks(steps, extras) -> [{id, ts, type, title, detail}]`;
outbound texts come from the existing `sms` steps), `ContactPanel.jsx`, `DriverLoadCard.jsx`, `InsightStrip.jsx`, `ReplayTabs.jsx`.
**First commit = stubs of these 5 frontend files with their final props**, so C can import them on day 1.
B1 (pure rules) can start before A1 lands. B2 needs `Puller.composite`.

**C — Game engine and progressive UI (frontend), owner Ruby-C**
New `replay/useReplayEngine.js`, `replay/roadPath.js`, `woreplay/stageLayers.js`, `woreplay/EventToasts.jsx`. Rewrite
`woreplay/WoReplayStage.jsx`; edit `woReplayModel.js`, `ReplayPanel.jsx`, `reportcard/GarageReplay.jsx`,
`replay/DayReplayMap.jsx`, `replay/ReplayPlayer.jsx`, `replay/DriverDayCard.jsx` (seek API), `reportcard/DayGantt.jsx`
(playhead only), `index.css` (`rp-pulse`, `rp-pop`, `rp-glow`). Delete `useStepClock.js` and `useReplayClock.js`.
Steps: C1 engine + roadPath → C2 GarageReplay single mount + day map on the engine → C3 stage rewrite → C4 ReplayPanel
progressive (falls back to `locations.wo/garage` until A5 lands) → C5 wire B's stubs (props `marks`, `onMark`,
`driverJobs`; `jump` becomes `{ts, n}`).

Every file stays under 600 lines. `WoReplayStage` must be at or under 400.

## 8. Acceptance (Tamy; the user's clicks, scratch harness)
Use the scratch harness: real routers, auth/flags/cache stubbed, Vite on 5199, Playwright + Chrome. Salesforce reads
are real and read-only. **Never boot the backend** (it runs DDL against production Postgres).
1. Replay → Garage → 076DO → 9/24. Click SA-1067245 while the day map is still loading. The call plays within about
   1 s, and Pause and Next event respond at once. When the day map arrives, the call's clock keeps going (no restart).
   Evidence: story response `meta.sf_calls = 1`; map `drivers[].source` and `sf_calls`.
2. Pick a 100 WNY Fleet call on 9/28. The map shows `sf_calls: 0`, `source: 'snapshot'`, and the truck appears with no wait.
3. 300× → a 2-hour call plays in about 25 s. Next event jumps, toasts appear, and the truck follows streets. Once the
   promise passes, the member timer turns red and pulses. Chrome performance trace while playing: no long task over 50 ms.
4. Turn `replay_member_contact` on. Work Order tab → 05195032: 1 phone icon before the call starts, and 2 callback icons at
   12:32 PM and 12:39 PM ET. Click one: "MCC ERS Replicant Return", the duration, and the agent. Insight reads
   "Member called back 2× …". Member contact tab count = 3.
5. A WO with an inbound text (Henry supplies the number): click the chat icon. The thread loads in member/agent bubbles,
   with no `&amp;` visible. Check the Network panel: the bodies were not requested before the click.
6. "Driver's other jobs" tab on SA-1067245: the jobs ahead at accept time are listed, and drop-offs are not counted.
7. Regression: Day tab, Gantt, case trail and call flags are unchanged. `cd backend && ../.venv/bin/python3 -m pytest
   tests -q` gives 484 passing + the new tests.

## 9. Rollout (Kathy)
No migrations, no new env vars, no new packages (framer-motion, leaflet and lucide are already installed; OSRM is
already used by the contractor map). One new flag, `replay_member_contact`, default off. Disk cache keys use the existing
cache directory. Ship A first: speed only, low risk, already behind `call_story`. Then C. Then B with its flag off;
the owner switches it on in Admin after Henry approves the insight wording. Rollback: revert the PR; for B, switching the flag off is enough.

## Henry: definitions and test cases (2026-10-08)

Evidence: all ERS SAs created 10/07 ET (1,560 SAs, 15,175 Status / `ERS_Assigned_Resource__c` / `Off_Platform_Driver__c`
history rows, counts checked against `SELECT COUNT()`), plus targeted pulls for the 3 test WOs. About 20 sequential
read-only SELECTs. Scripts: scratchpad `henry_v2/` (`rules.py` is the reference implementation of the rules below).

### H1. What the trail actually looks like (this changes two of Dan's rules)
Most common Status order per channel on 10/07 (non-drop-off legs):
- **Fleet (n=113) and On-Platform (n=181):** Spotted → Assigned → **Dispatched → Accepted** → En Route → On Location → Completed.
  The driver taps Accept only when he is ready to roll: Accepted → En Route median **0.3 min**. So at "Accepted" the driver
  has almost nothing ahead (Fleet 4 of 107, On-Platform 11 of 159). "Ahead at accept" would nearly always say 0. **Wrong moment.**
- **Towbook (n=588):** Spotted → Assigned → **Accepted → Dispatched** → En Route. The order is reversed. "Accepted" is written by
  *Integrations Towbook* 20 s after Assigned: the **garage** accepted the call. "Dispatched" (median 1.7 min later) is when the
  garage gave it to a driver. At least 79 of 588 also show a second Accepted after Dispatched (the driver acknowledging in Towbook).
- **Towbook `ERS_Assigned_Resource__c` is the garage placeholder** (e.g. "Towbook-626"), the same on every call of that garage.
  Filtering Towbook jobs by it counts the whole garage. The Towbook driver is **`SA.Off_Platform_Driver__c` only**
  (per driver, e.g. 076DO had 22 distinct drivers on 10/07). It is **not history-tracked** (0 history rows of 588), so it is current-holder only.
- **Tow legs:** the pick-up goes Completed and the drop-off goes En Route in the **same second** (median 0.0 min, n=329 Towbook,
  105 On-Platform). While the driver hauls a car, the only active leg is the drop-off. If drop-offs are ignored completely, a
  driver who is towing looks free. Counting the towing leg changed the "ahead" count on 71 of 557 Towbook calls and 8 of 159 On-Platform calls on 10/07.

### H2. Definitions (replace Dan's §4 bullets "On his plate" and "after")
**Driver D of the member call**
- Fleet / On-Platform: member SA's `ERS_Assigned_Resource__c` (final holder). Channel from `ERS_Assigned_Resource__r.ERS_Driver_Type__c`:
  'Fleet Driver' → `fleet`, 'On-Platform Contractor Driver' → `on_platform`. The response enum must have three values:
  `fleet | on_platform | towbook` (On-Platform was 291 SAs on 10/07, more than Fleet's 113).
- Towbook ('Off-Platform Contractor Driver', or resource name starts "Towbook"): member SA's `Off_Platform_Driver__c`. Never named in the UI ("the Towbook driver").
  If it is empty (2 of 922 on 10/07), return `driver_load: []` with the note "The Towbook garage did not report which driver took this call."

**A = the moment the call was given to D** (replaces "accepted")
- Fleet / On-Platform: the last `ERS_Assigned_Resource__c` history **id row** (NewValue starts `0Hn`) whose NewValue = D, at or before
  the member's first En Route. It is already in the story raw. Fallback, if no such row: last Dispatched before En Route.
- Towbook: the last **Dispatched** on the member SA at or before its first En Route.
- No A (never given to a driver, e.g. cancelled while Spotted) → no driver-load section.

**A job is "on D's plate" at time t** (grouped by `ERS_Work_Order__c`, never the member's own WO)
- Service / pick-up leg (any work type without "drop" in its name), Status at t (last trail row at or before t):
  - Fleet / On-Platform: Status in {Dispatched, Accepted, En Route, On Location} **and** D held it at t (last
    `ERS_Assigned_Resource__c` id row at or before t = D). Dan's status set is confirmed. Assigned is left out on purpose: the driver
    cannot see it yet (only 2 of 105 Fleet and 5 of 169 On-Platform calls would change).
  - Towbook: Status in {Dispatched, Accepted, En Route, On Location} **and** a Dispatched exists at or before t (an Accepted before
    any Dispatched is the garage's accept, not the driver's).
- Drop-off leg: Status in {En Route, On Location} → the WO is on the plate as **"Towing"**. A drop-off in Assigned/Dispatched/Accepted
  is not counted (it is created with the pick-up, about 40 min before the pick-up arrival).
- One WO counts once. Its label: Towing if the drop-off is active, else the pick-up status.
- `ahead` = WOs on the plate at A. `current` = the one in En Route, On Location or Towing (if several, the most advanced); the rest are
  "waiting to start". Plain labels for the UI: Dispatched/Accepted → "not started", En Route → "driving to it", On Location → "at the job", Towing → "towing".
- Pin = the pick-up / service leg's Latitude/Longitude. Drop-offs never get a pin.

**`after` = jobs that jumped ahead of the member** (replaces "first Dispatched/Accepted between A and On Location")
A WO not on the plate at A, given to D after A (same "given" rule as A, on its pick-up/service leg), **and** where D reached it
(first On Location on that leg) **before** the member's On Location. Jobs given later but served after the member did not delay
anyone and are not counted. Measured 10/07: the loose rule flagged 128 Towbook calls, the strict rule 25. If the member SA has no On
Location (cancelled, open), use the cancel time or now.

**Query changes this needs (same 2 calls)**
- `trail`: `Field IN ('Status','ERS_Assigned_Resource__c')`, plus `OldValue` not needed. The holder check changed the count on 3 of 169 On-Platform calls.
- `jobs` driver filter: Towbook → `Off_Platform_Driver__c = '<D>'` **only**, never `ERS_Assigned_Resource__c`. FSL → `ERS_Assigned_Resource__c = '<D>'` (final holder only, not every driver who touched the call).

**What it shows on 10/07 (one day, calls given to a driver 8 AM–midnight ET)**

| Channel | Calls (n) | Driver had ≥1 job ahead | Avg jobs ahead | A later job was served first |
|---|---|---|---|---|
| Fleet | 105 | 22 (21%) | 0.22 | 0 |
| On-Platform | 169 | 46 (27%) | 0.29 | 2 (1%) |
| Towbook | 557 | 224 (40%) | 0.50 | 25 (4%) |

One day only, no weather or volume adjustment, so these are not rankings. They are a sanity check that the rule returns sensible numbers.

**Limits (put these in `notes`)**
- Fleet / On-Platform: a job D held at A and later lost to another driver is not found (the jobs query uses the current holder).
- Towbook: `Off_Platform_Driver__c` has no history, so if the garage swapped drivers we only see the last one; the holder at A cannot be checked.
- Status times are driver taps. Example: SA-1091742 went En Route → On Location in 7 s, so the real arrival was earlier.

### H3. Member calls: two rule fixes found in the data
1. **Transfers are not callbacks.** VoiceCall has `CallType` 'Inbound' (1,072 on 10/07) and 'Transfer' (24, always with
   `PreviousCallId`). On WO 05195827 one member call shows as 4 rows (1 Inbound + 3 Transfer legs). Count only `CallType = 'Inbound'`;
   show Transfer rows inside their parent call ("transferred to Dispatch ERS Status").
2. **Only ERS lines count.** 10 of 47 calls matched after 15 min on 10/07 went to "MCC Membership" (renewals, billing). Count a callback only
   when `ToPhoneNumber` starts with 'MCC ERS' (New, Replicant Return, INEED). List other-line calls in the Member contact tab as
   "Called the membership line", not in the insight. With both fixes, WOs with a callback on 10/07 went from 37 to 29.
Owner's 15-minute rule is kept as is.

### H4. Insight wording (approved as rewritten; owner may switch the flag on with these)
Use "time(s)" not "×", round minutes, ET clock times, never name a Towbook driver.

| Code | Text | Level |
|---|---|---|
| CALLED_BACK | "The member called AAA back {n} time(s). The first call came {m} min after they asked for help." Add " {k} of these came after the promised arrival time." when k > 0. | info: n = 1, before the promise. warn: n ≥ 2. bad: any callback after the promise and before the driver arrived. |
| TEXTED_IN | "The member texted AAA {n} time(s)." Add " {k} came after the promised arrival time." when k > 0. | info; warn when k > 0. |
| DRIVER_AHEAD | "When this call went to {driver}, they still had {n} other job(s) to finish first." `{driver}` = the name, or "the Towbook driver". If one was already under way, add " One was already {driving to it / at the job / towing}." | info: n = 1. warn: n ≥ 2. |
| DRIVER_MORE_AFTER | "{driver} served {n} member(s) who called later before reaching this member." | warn; bad when this member's arrival was after the promise. |

`{n}` counts inbound sessions for texts (not message count), WOs for jobs. Promise = original PTA (r2, metrics-spec §7.7).
Omit an insight when its n = 0.

### H5. Test work orders for Tamy (all 10/07/2026, all Completed; times ET)
**T1, Towbook, covers all three: WO 05195827 / SA-1091889** (626 Dan's Tire & Auto, Tow; promised about 3:06 PM)
- Created 2:17:26 PM. Given to the Towbook driver (Dispatched) 2:53:02 PM. En Route 6:04 PM. On Location 6:36:42 PM.
- Calls: one member callback 5:20:06 PM (+183 min, MCC ERS Replicant Return, 1,073 s, answered by an agent). Three Transfer rows follow
  (5:22, 5:30, 5:34). Expect **n = 1, level bad** (after the promise). If it says 4, the transfer fix is missing.
- Texts: 1 inbound session at 4:55:56 PM (1 member message), channel "ERS SMS Messaging Channel". Expect TEXTED_IN n = 1, warn.
- Jobs: **ahead = 1**: WO 05195923 (Tow, given 2:49:54 PM, not started). **after = 1**: WO 05196239 (Tow, given 4:55:51 PM, driver
  arrived 5:09:29 PM, before this member). Must **not** count: WO 05196220 (given 5:48 PM, reached 8:27 PM, after this member),
  WO 05195364 (done 1:44 PM) and any of the 5 drop-off SAs. The driver is never named.

**T2, Fleet: WO 05194934 / SA-1091027** (100 Western New York Fleet, Tire; driver Marcus Gibson; promised about 11:08 AM)
- Created 9:36:41 AM. Briefly assigned to another driver at 9:40:37, given to Marcus 9:40:52 AM. Marcus accepted 11:00:43 AM, On Location 11:34:49 AM.
- Jobs: **ahead = 1, current, "driving to it"**: WO 05194878 (Battery; En Route since 9:26 AM, arrived 10:04, finished 11:00:36).
  This is the example where the member waited for the driver's previous job. after = 0.
- Texts: 2 inbound sessions, 10:57:34 AM and 11:36:52 AM (the second is after the driver arrived). Calls: none matched.

**T3, On-Platform: WO 05195668 / SA-1091742** (4652D Val U Auto, Tow; driver Zack Felix; promised about 2:43 PM)
- Created 1:25:48 PM. Given to Zack 1:28:37 PM. Accepted 2:33:47 PM. En Route 3:35:55 PM, On Location 3:36:02 PM (7 s later).
- Jobs: **ahead = 1, current, "driving to it"**: WO 05195136 (Tow pick-up; arrived 1:40 PM, then towing until 2:34 PM). after = 0
  (WO 05196132 was given at 4:42 PM, after this member was reached).
- Texts: **3 inbound sessions**, 2:54:25, 3:19:42 and 3:29:45 PM, all after the promise → TEXTED_IN n = 3, k = 3, warn. Calls: none matched.

**T4 (optional), the Towing rule: WO 05194797 / SA-1090906** (421 Action Towing, On-Platform; driver Michael Hucks)
- Given to him 10:06:20 AM. At that moment WO 05194738's pick-up had gone Completed (10:05:32) and its drop-off was En Route
  (10:05:45, delivered 10:25 AM). Expect **ahead = 1, "towing"**. If it shows 0, drop-offs are being ignored instead of grouped by WO.
