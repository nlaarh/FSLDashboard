# Fleet Dispatch Analysis (updated Mar 5, 2026)

## Deliverables
- `/tmp/fleet_dispatch_v2.csv` — 128 rows: Date, DOW, Fleet, WOs, Auto, Manual, Auto%, Manual%, Top_Dispatchers (Jan 1 - Mar 5, 2026)
- `/tmp/fleet_dispatch_table.csv` — 228 rows (older, weekly approximation)

## Key Finding: Auto-Dispatch Was Turned Off
- **ERS_Auto_Assign__c is UNRELIABLE** — showed 99% auto when reality was 60-65%
- **AssignedResource.CreatedBy is the real audit trail** for system vs manual dispatch
- System users: `{'IT System User', 'Mulesoft Integration', 'Replicant Integration User', 'Platform Integration User'}`

### Timeline (from daily data):
- **100-WNY**: Auto dropped to 0% on Feb 20, recovered ~60% by late Feb
- **800-Central**: Auto dropped to 0% on Feb 20, stayed 0-5% through Mar 3 (2 full weeks!), recovered Mar 4-5

### Top Manual Dispatchers (verified by user)
- **100-WNY**: Paige White (dominant), Jeremy Harrington, Lynn Pilarski, Shawn Gancasz, Kenneth White
- **800-Central**: Jon Carroll, Kateri Filippi, Diana Oakes, Jeffery Sgarlata, Janice Sims

### Non-dispatcher names (NOT in user's list, classified as auto)
- Katie Kelsey(40), Jonathan Curry(37), Laurie Robins(34), Christina Reichel(29), Jermaine Harrison(29), etc.
- These may be dispatchers too — user should review

## CRITICAL: Use Bulk API 2.0 for Large Extracts
- **REST SOQL times out** on cross-object queries (AR→SA→Territory) even with LAST_N_DAYS:90
- **Bulk API 2.0 works perfectly** — 12,938 records extracted in ~30 seconds
- Pattern: POST job → poll state → download CSV results
- Endpoint: `{base}/services/data/v59.0/jobs/query`
- Script: `/tmp/fleet_bulk.py` — working Bulk API template
- **ALWAYS use Bulk API** for AR queries with cross-object filters

## SOQL Lessons
- Daily AR aggregate with cross-object territory filter ALWAYS times out (REST API)
- Weekly/monthly AR aggregates work via REST
- WO daily counts by territory are fast (native ServiceTerritoryId field)
- Fleet territories: `100 - WESTERN NEW YORK FLEET`, `800 - CENTRAL REGION ERS FLEET SERVICES`
