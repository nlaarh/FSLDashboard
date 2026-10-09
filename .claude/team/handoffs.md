# Team Handoff Log

Newest first. One entry per handoff.

Format:
## YYYY-MM-DD HH:MM — <From> → <To>
- **Need:**
- **Context:**
- **Status:** open | picked up | done

## 2026-10-08 — Dan → Ruby (A, B, C), Henry, Tamy, Kathy (Replay v2 design)
- **Need:** Ruby: build from `.claude/team/replay_v2_design.md` in 3 workstreams on separate files (A speed backend, B member contact + driver load, C game engine + progressive UI); A1 (composite helper) merges first. Henry: before B1, confirm the "on his plate at accept" status set (Dispatched/Accepted/En Route/On Location) and approve the 4 insight wordings (design 4); give Tamy one WO with an inbound member text. Tamy: acceptance in design 8. Kathy: flag `replay_member_contact` (default off), no migrations/env vars.
- **Context:** Measured read-only on SA-1067245: story 9 SF calls / 1.35 s; map 3 calls / 35.2 s cold (ServiceResourceHistory 34.9 s cold, 0.33 s warm). Composite prototype: 7 story queries in 1 request, 0.35-0.46 s. Snapshot GPS covers 96% of non-Towbook calls (3,742/3,894). Extras prototype: 2 composite requests, ~0.3 s each; VoiceCall format verified on WO 05195032. Scripts in session scratchpad only.
- **Status:** open (owner approval of design + one question on who may read text bodies)

## 2026-10-04 — Ruby → Henry, Tamy, Kathy (r2 + builder 1.1 + GPS retry)
- **Need:** Henry: r2 is in and is the default (metrics-spec 7.7). Rebuilt 9/28 with rc-build-1.1: PTA met r1 65/82, r2 64/82, the only flip is SA-1075021, 0 code changes, matching your table. 8/31 rebuilt: r2 = r1 (124/185). The other 18 ROI days in ~/.fslapp/report_card are still rc-build-1.0: under r2 they show "rebuild needed" (409 rules_unavailable), never r1 silently; ?rules=r1 still works. Tamy: rules selector on /report-card (r2 original PTA / r1 final PTA) and the rebuild-needed state. Kathy: GPS history read now cools down 20 s and retries the failed batch in halves down to 5 drivers (076DO 2026-08-03 timeout); still sequential.
- **Context:** report_card_build.py (ERS_PTA__c in Q2, split retry), report_card_snapshot.py (pta_initial_min/src/due, pta events, rc-build-1.1), report_card_verdicts.py (RULES_R2_DELTA, DEFAULT_RULES='r2', supports/RulesNotAvailable), routers/report_card.py (?rules=). 132 report-card and flag tests pass.
- **Status:** open

## 2026-10-04 — Ruby → Tamy, Henry (Findings panel rewritten for ops directors)
- **Need:** Tamy: re-test the Findings panel. Titles are now plain English and lead with member impact; cards are ordered by member impact (minutes past PTA on the finding's calls) and show "Cost members N waiting minutes on M late calls"; actions read "Owner: action"; codes are small grey tags. Henry: "member impact" is the product owner's definition (sum of minutes past ERS_PTA_Due__c on late calls in the finding); a call can count in more than one finding. Please confirm or refine it in the spec.
- **Context:** The model now writes only title, text and headline for a diagnosis id it chooses; the server attaches severity, owner, action, cause, tags, impact and evidence. The validator also rejects verdict/flag/lever codes and internal terms (RSO, In-Day) in prose, and requires the headline's "The biggest lever:" sentence. 120 report-card and flag tests pass. Screenshots: scratchpad rc4_*.png.
- **Status:** open

## 2026-10-04 — Ruby → Henry, Tamy, Kathy, Dan (B4a auto-schedule, 5B impact, rebuilds, Call Story, SA-report fixes)
- **Need:** Henry: B4a + 5B are in (rules r2 + builder rc-build-1.2). 8/31 under r2: BYPASSED_OPTIMIZER 134 = 47 garage-portal + 45 AAA dispatchers + 42 IT System User without stamp; 28 FSL_AUTO_SCHEDULE finals. 9/28: 31 (all 39 integration finals are FSL auto-schedule). New 8/31 headline: rebalance (L03), integration finding = 42 IT System User picks, ranked 5th by member impact. Please confirm the 10% / n>=3 trigger I used for the IT System User finding. All 40 stored days are now rc-build-1.2 (38 rebuilt one at a time, 638 calls; the GPS split-retry recovered 076DO 08-03). Tamy: Call Story built behind flag `call_story` (off); SA-report fixes 1/3/4/5 are a separate change set (sa_report.py, sa_report_timeline.py, dispatch_utils.py, SAReportTimeline.jsx, tests/test_sa_report_fixes.py). Kathy: demo backend on :8000 needs a restart to pick these up. Dan: Call Story deviations listed in my report (call_story_compose.py added; SA input resolves in 2 calls until the ERS_Work_Order__r relationship is described; Q7 logs and Q8 blocking pull not implemented; G4 not implemented).
- **Context:** Call Story golden tests use a synthetic 10.4 bundle; the 4 real golden captures and the sf_describe checks (matrix object, Mobile_Phone__c, MessagingPlatformKey format) are still pending a Salesforce window.
- **Status:** open

## 2026-10-04 — Ruby → Tamy, Henry, Kathy (flag override + AI findings)
- **Need:** Tamy: test the Findings panel on /report-card (9/28 WNY and 8/31 076DO are built locally), and the template path with no AI key. Henry: (1) confirm the garage-portal rule: a roster member with profile Partner Community User who makes an assignment is GARAGE_DISPATCHER (Todd Kryszak, 46 finals on 8/31, as in spec 6.2), while their status updates stay DRIVER. (2) Review the deterministic diagnosis rules in backend/report_card_facts.py (10A.2 mapped to L01–L13). Kathy: FSLAPP_FEATURE_OVERRIDES is local-only; it is ignored when WEBSITE_SITE_NAME is set and must never go into Azure settings or a committed file. The local ANTHROPIC_API_KEY has no credit (Anthropic returns 400 "credit balance is too low"); if production's AI provider is Anthropic, the chatbot and findings will fall back too.
- **Context:** 8/31 verdicts match Henry exactly (GOOD 80, BOUNCED 35, STACKED 26, LDC 17, FAR 15; failures 93/195). AI output for both days validated first time with gpt-4o. 121 report-card and flag tests pass.
- **Status:** open

## 2026-10-04 — Dan → Henry, Ruby, Tamy, Kathy (Call Story design)
- **Need:** Henry: settle O1 (r1 grades the re-based PTA; the story grades the original per the user's decision; r2 `pta_basis`?), O2 (golden 10.2 S6 56.5 min is SLOW under the 60-min floor, not STUCK), O3 (golden 10.3 S3 is CRITICAL under `critical_if_pta_passed`, not STUCK), O5 (pooled all-channel fallback for S7/S8/S9). Ruby: build only after the user approves; SA-report fixes 1/3/4/5 as a separate commit, bug 2 superseded. Tamy: acceptance steps in §8.4. Kathy: no env vars or migrations; new `stories/` folder in the report-card file store; flag `call_story`.
- **Context:** docs/scheduler-report-card/call-story-architecture.md. User decisions on spec §14 recorded in §0 (D1–D5). Typical story 7 SF calls, worst case 10, hard cap 12; baselines come from report-card snapshots only (0 SF calls) and need 56-day coverage (O6, user decision).
- **Status:** open (needs the user's approval)

## 2026-10-03 — Ruby → Henry, Tamy (slice 1 follow-ups)
- **Need:** Henry: h1 health + S9-T are in (report_card_health.py, report_card_verdicts.py). Saved 9/28 snapshot gives 4 healthy / 6 watch / 2 unhealthy and SKILL_MISMATCH = 1 (SA-1075493); every H1/H2/H4/H6 value and band matches your table. One input differs: Jacob's H5 is 0, not 1. His 82.9-min pull-back (SA-1075417) happened while he had another open job (SA-1075257), and §5A counts only drivers with 0 open jobs at dispatch. His badge is unchanged (unhealthy, scheduler); only the execution lens reads good instead of watch. Please confirm the definition. Tamy: Gantt redesigned (one work lane per driver, stacking strip with open-job count, waiting rail, hover tooltips, health badge names its lens).
- **Context:** 90 report card tests pass, including a golden h1 test that runs when the local 9/28 snapshot exists. Screenshots: session scratchpad rc2_*.png.
- **Status:** open

## 2026-10-03 — Henry → Ruby, Dan, Tamy
- **Need:**
  - **Ruby: replace the interim driver health with h1.** See metrics-spec.md §5A. It uses two lenses (workload =
    scheduler, execution = driver), returns `health_owner`, and drops M08 p90 and M13 from the badge. The config
    JSON is in §5A. 9/28 result: 4 healthy / 6 watch / 2 unhealthy.
  - **Ruby: SKILL_MISMATCH.** Your 5 was the correct reading of the old rule; my 3 was wrong. Implement S9-T: a
    pre-login pick is qualified by the first truck logged into within 30 min of the decision and before En Route;
    otherwise `unknown` and no flag. Correct 9/28 count = 1 (SA-1075493).
  - **Ruby:** fix the 5 SA-report bugs in call-story-spec.md §11 before reusing that code.
  - **Dan:** design the Call Story from docs/scheduler-report-card/call-story-spec.md (inputs, query plan, events,
    stuck segments with baselines, grid/SPOT, SMS, cause codes, response shape §13).
  - **Tamy:** the 4 golden calls in §10 are the acceptance tests (SA-1073520, SA-1074927, SA-1074304, SA-1067245).
- **Context:**
  - call-story-spec.md is new. metrics-spec.md gained §5A and S9-T, and the §7.4 SKILL_MISMATCH count is corrected.
  - Scripts: docs/scheduler-report-card/validation/call_story/ and validation/driver_health/. h1 was computed
    offline from ~/.fslapp/report_card/0HhPb00000007qGKAQ_2026-09-28.snapshot.json.
- **Status:** open. The Call Story needs the user's answers to call-story-spec §14 (grid meaning, PTA promise, SMS
  delivery access).

## 2026-10-03 — Ruby → Tamy, Henry, Dan, Kathy
- **Need:** Tamy: test Scheduler Report Card slice 1 (Day view + Gantt) on branch feature/scheduler-report-card (uncommitted, not deployed). Henry: confirm the interim driver-health rule (worst band of M06, M08 p90, M13; n >= 3) and the SKILL_MISMATCH 5 vs 3 difference (Jacob Schaich assigned 18:38/18:40 UTC, truck login 18:41:38, so no truck caps at decision time). Dan/Kathy: storage is an interim JSON file store (~/.fslapp/report_card locally, /home/fslapp/report_card on Azure), no DDL; Kathy's ops_002 migration can replace it later.
- **Context:** Builder reproduces Henry's 9/28 WNY numbers exactly (90 SAs, PTA 65/82, verdicts GOOD 54 / CAPACITY_SHORT 10 / BOUNCED 7 / INBOUND 7 / GOOD_NO_ARRIVAL 6 / LDC 2 / LE 2 / INSUFFICIENT 2, M17 38/87, M19 36/43, M20 3/80 and 0/80, failure 9/81) in 16 sequential SOQL calls. Tests: backend/tests/test_report_card_*.py (79 pass). Flag `scheduler_report_card` default off; permission `scheduler.report_card` (never contractor).
- **Status:** open

## 2026-10-03 — Henry → Dan, Ruby, Kathy
- **Need:** Dan: adopt metrics-spec.md §3–§7 into the design. Key changes: final decision maker = last ERS_Assigned_Resource__c history actor (not AR.CreatedBy); Platform Integration User = FSL engine; "qualified" = WOLI skills ⊆ SR skills + logged-in truck capabilities; store candidates at every assignment event; pilot garage = 100 WNY Fleet (076DO went Towbook 9/1); add region-level outbound-bounce pull; snapshot the SF optimizer trail (FSL__Optimization_Request__c, FSL__Territory_Optimization_Request__c, Optimization_Log__c). Kathy: Postgres opt_* coverage check still open (I did not query prod Postgres). Ruby: validation scripts in docs/scheduler-report-card/validation/ are the reference for numbers.
- **Context:** docs/scheduler-report-card/metrics-spec.md; validation outputs output_100_2026-09-28.txt and output_076DO_2026-08-31.txt.
- **Status:** open (needs the user's approval of §13 assumptions)

## 2026-10-03 — Dan → Ruby (after user approval), Kathy, Henry
- **Update:** Henry's metrics-spec.md folded into architecture.md (§5.2–§7); policy diagnosis (§7.6) and sandbox validation (§19) added. Remaining verifications: SF optimizer Request/Response files persist since 2024-12? request skills include truck caps? (§18.5)

- **Need:** Henry: fill the plug-in slots in `docs/scheduler-report-card/architecture.md` §6 (metric registry), §7 (verdict codes, precedence, rule logic, r1 thresholds JSON, failure set, ERS_Driver_Type__c → channel mapping), §11.3 (recommendation lever library); answer open questions (Shift populated?, track SAs bounced OUT?, supervisor access?, driver names in AI input?, FSL SLR setting, is a balance objective FSL-native?). Kathy (read-only): actual FSLAPP_RETENTION_DAYS in Azure, what schedules optimizer_retention, is optimizer.* still being synced (max(run_at)), daily pilot-territory row counts — needed for §18.5 calibration corpus. Ruby: build only after the user approves the design.
- **Context:** Design covers snapshot JSON, 6 additive `ops.src_*` tables (admin-applied migration, no startup DDL), sequential SF build ≤30 calls, Day + Patterns views, AI from fact sheets only, nightly gentle backfill.
- **Status:** open

## 2026-10-04 — Henry → Ruby, Dan, user
- **Update:** ROI baseline written: `docs/scheduler-report-card/roi-baseline.md` (20 garage-days built with Ruby's builder, scored r1; scripts in `docs/scheduler-report-card/validation/roi/`). Call-story open items settled: O1 (r2 = original-promise PTA, metrics-spec §7.7), O2 + O3 (goldens 10.2/10.3 corrected, severity rule tightened in call-story-spec §5.3/§12), O5 (level-4 pooled S7/S8/S9 recorded, first data n=76), O7 (prod flows verified via Tooling API; match on trigger logic; prod adds logging and fixed the 80-min phone check; always-true OR re-check exists in prod).
- **Need:** Ruby: (1) r2 needs `'ERS_PTA__c'` added to the Q2 SAHistory `Field IN (...)` in `report_card_build.py` + `pta_initial_min` in the snapshot (builder rc-build-1.1); `rules_for('r2')` = r1 + `pta_basis: "initial"`, 5 s window, chain same-second rows. (2) GPS read (`ServiceResourceHistory`) timed out at 45 s on 076DO 2026-08-03 with 126 drivers; consider a cool-down retry + smaller batches (my script used 40 ids + 60 s retry; 0 further failures). Dan: §8.1 rows updated; O4 and O6 still need the user. User: unit-cost inputs U1–U9 (roi-baseline §8). Flow owner (Kathleen Osuch): Check_SA_Status OR → AND in the 3 not-accepted SMS flows (safety net, no member impact today).
- **Context:** Snapshots in ~/.fslapp/report_card/ (append-only). ~420 sequential read-only SF calls, no Postgres, no DML.
- **Status:** open (unit costs from user; r2 build by Ruby after approval)

## 2026-10-04 (later) — Henry → Ruby, Dan, user
- **Update:** (1) Integration-account verdict in metrics-spec §4 B4a: Mulesoft + Replicant driver picks are FSL auto-schedule (ERS_SA_AutoSchedule sets FSL__Auto_Schedule__c → managed FSL.BatchScheduleServiceAppointments runs as that user; 179/179 + 68/68 picks inside those batch runs, last 2 days). IT System User is mixed: 167 of 286 driver picks have no FSL batch/stamp → decided outside Salesforce code (likely MuleSoft; unconfirmed). FSL__Scheduling_Policy_Used__c is never populated org-wide (0/45,725 in Aug), so it is not evidence of bypass. (2) Member impact defined in metrics-spec §5B (original promise; member cancels after the promise count to cancel time; overlap rule; one-call dominance note). (3) ROI extension: 800 Central Fleet + 421 Action Towing appended (roi-baseline §11); channel split replicates.
- **Need:** Ruby: (a) the 8/31 headline "send integration picks through the FSL scheduler (162 of 195)" is wrong. 162 = 47 garage dispatcher + 45 AAA dispatcher + 42 IT System User + 28 FSL auto-schedule. Add class FSL_AUTO_SCHEDULE (integration pick 0–60 s after SA.Auto_Schedule_Requested__c; pull that field in Q1), exclude it from BYPASSED_OPTIMIZER, reword L01/L02 to "IT System User picks without auto-schedule", and stop citing the empty policy field. (b) report_card_facts impact: switch to due_initial + member-cancel rule (§5B). Integration team (via user): what decides IT System User's unstamped picks?
- **Context:** docs/scheduler-report-card/validation/roi/integ*.py; snapshots ~/.fslapp/report_card/ (40 garage-days). No DML, no Postgres.
- **Status:** open

## 2026-10-08 — Henry → Dan, Ruby, user
- **Update:** Read-only feasibility for 3 Work Order Replay additions. (1) Driver's other jobs: YES. SA.ERS_Assigned_Resource__c (FSL) / SA.Off_Platform_Driver__c (Towbook, 99.97% filled) + SAHistory Status trail; jobs a driver held then lost (~40% of FSL assignments get removed) only via a window scan of SAHistory ERS_Assigned_Resource__c. (2) Customer texts: YES. SMS_Send_Log__c.Messaging_End_User__c (84% of WOs) → MessagingSession (Origin InboundInitiated) → Connect API /connect/conversation/{ConversationIdentifier}/entries for text bodies (SOQL ConversationEntry.Message is empty); 127/136 inbound sessions linked to 1 WO. (3) Member calls: YES, by phone+time. VoiceCall.FromPhoneNumber ('+1 xxx xxx xxxx') vs WO Mobile_Phone__c/Callback_Phone__c; ToPhoneNumber = line name (MCC ERS New / Replicant Return / INEED); WorkOrderId__c (= call key) only ~10%; Task calls unlinked. 38/1,001 ERS WOs on 10/07 had a member call ≥15 min after creation.
- **Need:** User approval of approach + callback definition; Dan: design panel; Ruby: build lazily (separate fetch), not inside the 12-call story pull.
- **Context:** scratch pulls only (no repo files); no DML, no Postgres; ~45 sequential SF calls.
- **Status:** open

## 2026-10-08 (late) — Henry → Dan, Ruby-B, Tamy, owner
- **Update:** Replay v2 workstream B definitions written in `replay_v2_design.md` § "Henry: definitions and test cases". Key changes to Dan's §4: (1) measure "ahead" at the moment the call was **given** to the driver, not at Accepted (FSL drivers accept only when ready to roll, so "at accept" is ~always 0); Towbook's order is Accepted (garage) → Dispatched (driver). (2) Towbook driver = `Off_Platform_Driver__c` only; its `ERS_Assigned_Resource__c` is the garage placeholder. (3) Group tow legs by WO but count a drop-off in En Route/On Location as "Towing", or towing drivers look free. (4) "after" = later jobs the driver reached before this member. (5) Callbacks: CallType 'Inbound' only (Transfers are legs of one call) and only 'MCC ERS…' lines. (6) Channel enum needs `on_platform`. Insight wording rewritten and approved.
- **Need:** Ruby-B: build B1 from §H2–H4 (`rules.py` in my scratchpad is a reference). Tamy: test with T1 05195827 (Towbook, all three), T2 05194934 (Fleet), T3 05195668 (On-Platform), optional T4 05194797 (towing rule). Owner: may switch `replay_member_contact` on once Tamy passes.
- **Context:** 10/07 full-day pull (1,560 SAs, 15,175 history rows, counts verified); ~20 sequential read-only SELECTs; no DML, no Postgres.
- **Status:** open

## 2026-10-09 — Ruby → Tamy (branch perf/batch-2, three commits, nothing pushed)
- **Update:** Speed batch 2 built from Dan's sf_query_audit. (1) Watchlist: one combined read (appointments + drivers + history + work order via ParentRecord), served from one snapshot (copy <=30 s as is, <=60 s served while ONE background rebuild runs, older waits); contractors served from the same snapshot; screen shows "updated Ns ago". (2) `backend/ref_data.py`: shared reads for Command Center, Ops Brief, Scheduler Insights, PTA advisor, driver map (trucks/members 10 min, drivers 2 min because they carry GPS, appointments + assignments 60 s, 8-week baseline 6 h). (3) Hidden tabs stop polling on Watchlist, Queue, Live Dispatch, On-Route, Contractor Dispatch.
- **Need:** Tamy: compare each screen with production before/after (steps in the hand-off message). Watchlist: same alerts, same order, same counts; "updated Ns ago" counts up to ~30-60 then resets. Hidden tab: open Network, switch tabs for 2 min, no calls; switch back, one call at once.
- **Context:** equality proofs ran live (SELECT only) against the old code from origin/main; scripts in the session scratchpad, not in the repo.
- **Status:** open

## 2026-10-09 — Ruby → Tamy (branch feature/garage-live, from perf/release, two commits, nothing pushed)
- **Update:** New Command Center tab "Garage Live" (`?tab=garage-live&garage=<id>`): one garage's open tickets and drivers on the light Esri map (trucks glide between 60 s refreshes), hover/click cards, Replay button (existing call map), and a right-side "Needs attention" drawer ranked by simple rules in `backend/garage_live_rules.py` (all thresholds in one dict, `THRESHOLDS`). Endpoint `GET /api/garage-live/{garage_id}` reads only the shared Watchlist snapshot and `ref_data`; answer cached 20 s per garage. Contractors: own garages only, no Replay, other garages' calls hidden.
- **Need:** Tamy: open Command Center > Garage Live; pick 100 - WESTERN NEW YORK FLEET, 421 - ACTION TOWING OF ROCHESTER (On-Platform) and 076DO - TRANSIT AUTO DETAIL (Towbook: tickets only, "no driver GPS", no driver names). Reload (garage stays), leave and return (last garage opens with no click), hover a truck and a pin, click a drawer line (map flies and glows), Replay opens and Back returns to Garage Live, phone width. Compare tickets and flags with the Watchlist for the same garage.
- **Context:** Salesforce cost per refresh is flat in viewers (shared caches): ~3 requests/min for the Watchlist snapshot + ~0.5/min drivers, the same reads the Watchlist screen already causes; skills for the "closer driver" line are read once per call / driver. QA used a scratch API on :8010 (stubbed auth, no Postgres).
- **Status:** open
