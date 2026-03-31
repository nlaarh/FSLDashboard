# FSLAPP Coding Rules — READ BEFORE EVERY CODE CHANGE

## MANDATORY CHECKLIST (run mentally before writing ANY backend code)

### 1. Tow Drop-Off Exclusion
- **EVERY** SOQL query or Python filter that counts SAs MUST exclude Tow Drop-Off
- SOQL: `AND WorkType.Name != 'Tow Drop-Off'`
- Python: `if 'drop' in wt_name.lower(): continue`
- WHY: Every tow generates paired Pick-Up + Drop-Off SAs. Counting both inflates volume ~25%.
- APPLIES TO: volume counts, completion rates, PTA stats, DOW breakdowns, decline rates, CNW rates, forecasts, scorecards
- DOES NOT APPLY TO: map point visualization (show all SAs on map), SA detail lookups

### 2. Towbook vs Fleet — ALWAYS differentiate
- **Towbook garages have NO Fleet drivers** (`has_fleet_drivers = False`)
- Towbook drivers ARE visible: `Off_Platform_Driver__r.Name` on SA, `ERS_PTA__c` has actual PTA
- NEVER say "we can't see Towbook drivers" — we CAN via FSL and ERS fields
- ActualStartTime is UNRELIABLE for Towbook (midnight bulk update) — never use for ATA
- For Towbook PTA: use actual `ERS_PTA__c` from live SAs, NOT simulation

### 3. Work Type Differentiation — NEVER use same value for all types
- **Tow, Winch, Battery, Light are fundamentally different services**
- Cycle times: Tow=115m, Battery=38m, Light=33m, Winch=40m
- PTA promises differ by type — a tow PTA of 120m does NOT apply to battery
- When filtering live SAs for projected PTA: FILTER BY CALL TYPE FIRST
- Fallback scaling from default: tow=1.0, winch=0.75, light=0.70, battery=0.65
- If projected values come out identical for all 4 types → BUG. Stop and fix.

### 4. DST-Aware Time Conversion
- NEVER hardcode UTC offset (UTC-5 or UTC-4)
- ALWAYS use `ZoneInfo('America/New_York')` for Eastern time
- SOQL `HOUR_IN_DAY()` returns UTC — must convert to Eastern before comparing
- EDT: Mar-Nov (UTC-4), EST: Nov-Mar (UTC-5)

### 5. Case-Insensitive String Comparisons
- Salesforce picklist values may have inconsistent casing
- ALWAYS use `.lower()` when comparing satisfaction, status, reason fields
- Example: 'Totally Satisfied' vs 'Totally satisfied' — use `.lower() == 'totally satisfied'`

### 6. Deployment Safety
- Build frontend: `npm run build` in frontend/
- Copy: `cp -r frontend/dist backend/static`
- Deploy: `git push origin main` → GitHub Actions
- Verify: `curl https://fslapp-nyaaa.azurewebsites.net/api/health`
- NEVER delete output.tar.zst, NEVER use VFS for Python

## PAST MISTAKES (never repeat)
1. Used same PTA pool for all call types in Towbook projection (3x)
2. Said "we can't see Towbook drivers" when FSL/ERS fields provide this data (2x)
3. Hardcoded UTC-5 instead of DST-aware conversion (1x)
4. Case-sensitive CSAT comparison missed all 'Totally Satisfied' records (1x)
5. Counted Tow Drop-Off in volume totals inflating numbers ~25% (1x, 9 endpoints)
6. Conflated PTA Advisor (076D) issues with Garage view (076DO) issues (1x)
