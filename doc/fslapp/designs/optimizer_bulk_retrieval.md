# Optimizer Bulk Retrieval — Design & Plan

**Date:** 2026-04-28
**Status:** Designed, not implemented. Waiting on Beta toggle confirmation + DevTools capture.
**Goal:** Populate DuckDB with optimizer request/response JSON for all 127K runs in `FSL__Optimization_Request__c`.

---

## What we learned (the hard truth)

After 5 parallel research agents, the FSL optimizer architecture is now fully mapped:

### Where data lives
- **Run metadata** → `FSL__Optimization_Request__c` (queryable via SOQL once FLS granted)
- **Decisions / winners** → `AssignedResource` + `ServiceAppointmentHistory` (already queryable)
- **Candidates considered (LOSERS) + exclusion reasons + scoring** → **NOT in any SF object**. Only generated as JSON when "Retrieve Files" is clicked.
- **Pre/post KPI snapshot (territoryKpis)** → FSL Cloud only. Not in SF.

### Why losers/exclusions aren't in SF
~6 MB candidate eval log × 127,871 runs ≈ **750 GB**. Would blow SF storage limits. By design, FSL keeps candidate evaluation ephemeral (in-memory in FSL Cloud) and only persists deltas (`SchedStartTime` changes, `AssignedResource` upserts, `ServiceAppointmentHistory` rows).

### Why "Retrieve Files" still works for old runs
The button doesn't read from a SF table. It triggers a callout to FSL Cloud which **regenerates** the JSON by re-snapshotting current SF state. Verified: a Feb 14 run could be retrieved on Apr 28 (74+ day window).

### Why the button currently errors
"We couldn't retrieve your files. Try again, or ask your Salesforce admin."
→ The Beta setting **"Generate activity reports and retrieve optimization request files"** must be ON.
→ Location: App Launcher → Field Service Admin → Field Service Settings tab → Scheduling → General Logic.
→ Source: https://help.salesforce.com/s/articleView?id=service.pfs_optimization_request_files_set_up.htm

---

## The Plan — Option 2b: Capture & Replay

The "Retrieve Files" button fires an Aura POST to a hidden FSL controller. Reverse engineer it once, then replay from Python with the user's session cookie. No browser needed during the loop.

### Step 1 — Enable Beta toggle (admin action)
1. Confirm enabled: App Launcher → Field Service Admin → Field Service Settings → Scheduling → General Logic
2. Check "Generate activity reports and retrieve optimization request files" → Save
3. Verify: open Optimization Center → Optimization Request Files → enter recent run ID → click Retrieve → succeeds → ContentVersion `Request_*.json` + `Response_*.json` appear

### Step 2 — Capture the Aura request (one-time, ~30 seconds)
1. Open `https://aaawcny.lightning.force.com/lightning/n/FSL__OptimizationCenter` in Chrome
2. F12 → **Network** tab → check "Preserve log" → filter `aura`
3. Type a known run ID (e.g. `a1uPb000009dFZtIAM`), click "Retrieve Files"
4. Find POST to `aura?r=N&aura.ApexAction.execute=1`
5. Right-click → **Copy → Copy as cURL (bash)**
6. Save the cURL to `/tmp/retrieve_capture.sh`

### Step 3 — Identify the controller
The Aura body will look like:
```
message={"actions":[{
  "descriptor":"aura://ApexActionController/ACTION$execute",
  "params":{
    "namespace":"FSL",
    "classname":"<HIDDEN_CONTROLLER>",   # ← we need this name
    "method":"<HIDDEN_METHOD>",          # ← and this
    "params":{"<paramName>":"a1uPb..."}, # ← payload shape
    "cacheable":false
  }
}]}
aura.token=<csrf>
aura.context=<context>
```

The hidden classname will be in `FSL` namespace — likely `OptimizationCenter` or similar (LWC bundle `FSL.optimizationCenter` references this).

### Step 4 — Build the Python loop

```python
"""
Bulk retrieve FSL optimizer JSON files via Aura action replay.
Run after Beta toggle is ON. Files materialize as ContentVersion
where existing optimizer_sync.py picks them up.
"""
import os, time, json, requests, urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Captured from DevTools (Step 2) ──
SF_INSTANCE = "https://aaawcny.lightning.force.com"
SESSION_COOKIE = os.environ["SF_SID"]    # extracted from cURL Cookie header
AURA_TOKEN     = os.environ["AURA_TOKEN"] # csrf, from form body
AURA_CONTEXT   = os.environ["AURA_CONTEXT"]
CONTROLLER     = "FSL.OptimizationCenter"  # ← fill in from Step 3
METHOD         = "retrieveFiles"            # ← fill in from Step 3
PARAM_NAME     = "optimizationRequestId"    # ← fill in from Step 3

def build_aura_message(run_id: str) -> str:
    msg = {
        "actions": [{
            "id": "1;a",
            "descriptor": "aura://ApexActionController/ACTION$execute",
            "callingDescriptor": "UNKNOWN",
            "params": {
                "namespace": "FSL",
                "classname": CONTROLLER,
                "method": METHOD,
                "params": {PARAM_NAME: run_id},
                "cacheable": False,
                "isContinuation": False,
            }
        }]
    }
    return urllib.parse.urlencode({
        "message": json.dumps(msg),
        "aura.context": AURA_CONTEXT,
        "aura.token": AURA_TOKEN,
    })

def retrieve_one(run_id: str) -> tuple[str, bool, str]:
    try:
        r = requests.post(
            f"{SF_INSTANCE}/aura?r=24&aura.ApexAction.execute=1",
            cookies={"sid": SESSION_COOKIE},
            data=build_aura_message(run_id),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        if r.status_code != 200:
            return run_id, False, f"HTTP {r.status_code}"
        data = r.json()
        action = data.get("actions", [{}])[0]
        state  = action.get("state")
        if state == "SUCCESS":
            return run_id, True, "ok"
        err = action.get("error", [{}])[0].get("message", "unknown")
        return run_id, False, f"{state}: {err}"
    except Exception as e:
        return run_id, False, str(e)

def main():
    # 1. Read all run IDs that don't already have ContentVersion files
    import sf_client  # existing project module
    sf = sf_client.get_session()
    existing = set()
    for r in sf.query_all("SELECT Title FROM ContentVersion "
                          "WHERE Title LIKE 'Request_%a1u%.json'"):
        existing.add(r["Title"].replace("Request_", "").replace(".json", ""))

    runs = [r["Id"] for r in sf.query_all(
        "SELECT Id FROM FSL__Optimization_Request__c "
        "WHERE FSL__Status__c = 'Completed' "
        "ORDER BY CreatedDate DESC")]
    todo = [rid for rid in runs if rid not in existing]
    print(f"To retrieve: {len(todo)} runs")

    # 2. Fire requests with rate limiting (10/sec → ~3.5h for 127K)
    ok = fail = 0
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(retrieve_one, rid): rid for rid in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            rid, success, msg = fut.result()
            if success: ok += 1
            else:
                fail += 1
                print(f"  FAIL {rid}: {msg}")
            if i % 100 == 0:
                print(f"  Progress: {i}/{len(todo)} | ok={ok} fail={fail}")
            time.sleep(0.05)  # rate limit
    print(f"Done. ok={ok} fail={fail}")

if __name__ == "__main__":
    main()
```

### Step 5 — Existing pipeline takes over
- Files appear as `ContentVersion` records authored by `cloud@00ddo000001bxm7mak`
- `optimizer_sync.py` already polls ContentVersion every N minutes for `Request_*.json` / `Response_*.json`
- `optimizer_parser.py` parses → DuckDB
- No downstream changes needed

---

## Operational caveats

| Risk | Mitigation |
|---|---|
| Session cookie expires (2-12h) | Re-capture cURL when expired; loop is restartable (skips already-fetched runs) |
| Rate limits / FSL Cloud throttling | Start at 10/sec, monitor for 429s, back off |
| Some old runs may genuinely be unretrievable | Log failures; manual review |
| FSL Cloud quota for callouts | Unknown; may need batches over multiple days |
| Beta toggle gets turned off mid-run | Status check before each batch |

---

## When this is needed

**Only if** the user wants:
- Loser/exclusion data (territory/skill/absent reasons per driver per SA)
- Pre/post KPI snapshots (territoryKpis from response.json)
- Full pre-decision candidate pool

**Not needed** if:
- Forward-only is acceptable (Beta ON → new runs auto-capture)
- Decisions only (winner + estimated travel time) is enough → already queryable from `AssignedResource`

---

## Decision log

- 2026-04-28: Confirmed via 5 research agents that loser data is NOT in any SF object (1,017-record sample, all 162 FSL entities scanned, no Big Objects, no hidden archive).
- 2026-04-28: Confirmed retention is at least 74 days (Feb 14 run still retrievable Apr 28).
- 2026-04-28: Beta toggle currently OFF — confirmed via "We couldn't retrieve your files" error in UI.
- 2026-04-28: User has FLS now on `FSL__Optimization_Request__c` custom fields, but JSON-storage fields (`FSL__Result_Json__c`, `FSL__CandidatesIds_Json__c`, `FSL__Result__c`) are NULL on every run — staging fields, not persistent.

---

## Alternative for forward-only loser capture (no JSON)

If JSON bulk retrieval isn't pursued, a **complementary Async Apex capture job** can be added:

- On SA creation (or via scheduled batch), call `FSL.GradeSlotsService.getGradedMatrix(false)` per SA
- Returns `AdvancedGapMatrix.resourceIDToScheduleData` — map of every eligible resource → grade scores
- Persist to a custom object (e.g. `Driver_Grading_Snapshot__c` with SA, Resource, Grade, RunDate)
- **MUST be async** — synchronous triggers fail with "uncommitted work pending" (Known Issue `a028c00000qQ5qaAAC`)
- Limitation: only ELIGIBLE drivers are returned. Excluded drivers (territory/skill/absent fail) are silently dropped — no exclusion reason exposed.

Related but less useful:
- `FSL.ScheduleService.getAppointmentInsights(policyId, saId)` — returns `blockedSlots`, `blockingRules`, `resourcesEvaluated` (count only). Diagnoses unscheduable SAs but not per-driver verdicts.
- "Get Appointment Candidates" REST API — same data as getGradedMatrix.

This forward-only approach captures eligibility + grades for new SAs, but does NOT include territory/skill/absent exclusion reasons (which are still only in the Request.json from the bulk retrieval path).

## Final research conclusion (2026-04-28)

After 6 parallel research agents covering: org schema, Apex source, internet docs, FSL release notes Spring '23 → Winter '26, FSL MVP blogs, Salesforce StackExchange, GitHub SFS repos, Tableau CRM Field Service Analytics:

**No public, documented, or undocumented API exposes per-driver exclusion verdicts for historical optimizer runs.**

Confirmed by FSL MVP Rohit Arora's troubleshooting series — gap acknowledged with no workaround. Architectural justification is the storage cost (~128 GB for 127K runs).

Hierarchy of completeness:
1. **Best (full data):** Bulk-retrieve JSON files via Aura replay (Option 2b in this doc) — works within FSL Cloud retention window (≥74 days verified)
2. **Forward-only (eligibility):** `getGradedMatrix` async capture per SA creation — eligible drivers + grades but no exclusion reasons
3. **Closest reconstruction:** Replay exclusion logic in Python against current SF state — works for any run but suffers time-travel error (driver skills/territories/absences may have changed)
4. **Forfeit:** Old runs outside retention window are permanently inaccessible

## References

- Existing parser: `apidev/FSLAPP/backend/optimizer_parser.py`
- Existing sync: `apidev/FSLAPP/backend/optimizer_sync.py`
- Salesforce help: https://help.salesforce.com/s/articleView?id=service.pfs_optimization_request_files_set_up.htm
- Research artifacts: `/tmp/fsl_persistence_deep.md`, `/tmp/fsl_storage_objects.md`, `/tmp/fsl_candidates_search.md`, `/tmp/fsl_apex_map.md`, `/tmp/sf_optimizer_research.md`, `/tmp/fsl_blackbox_research.md`
- Known Issue: `a028c00000qQ5qaAAC` (synchronous getGradedMatrix throws "uncommitted work pending")
- FSL MVP source: Rohit Arora "SFS Optimization Troubleshooting" series
- GitHub: iampatrickbrinksma/SFS-Utils (canonical FSL utilities reference)
