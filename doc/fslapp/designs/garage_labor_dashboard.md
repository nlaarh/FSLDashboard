# Technical Spec — Garage Labor & Revenue Dashboard

**Date:** 2026-05-07  
**Status:** Design — not implemented  
**Source of truth:** `/tmp/Transit_Auto_Executive_Report.pdf` (8-page model)  
**Reference data pipeline:** `/tmp/driver_stats_query.py` (validated against live SF data Apr 8 – May 7, 2026)

---

## 1. Scope

### What Already Exists in GarageDetail

| Tab | Sub-tab | What It Shows |
|-----|---------|---------------|
| Schedule | — | 4-week SA schedule grid |
| Dashboard → Performance | — | ATA vs PTA by work type, weekly trend, volume breakdown |
| Dashboard → Operations | — | Scorecard, satisfaction scores, decomposition, bonus tiers |
| Dispatch | — | Today's simulation map |
| Satisfaction | — | Survey breakdown, trend, member comments |

### What This Spec Adds

A new **"Labor & Revenue"** tab on `GarageDetail`, containing three sections:

1. **Driver Performance Table** — calls completed, avg ATA, on-time %, satisfaction per driver (PDF pages 2 & 6)
2. **Driver Revenue & Hours** — per-driver attributed billing, hours worked (AssetHistory), revenue/hour (PDF page 8)
3. **Invoice Summary** — confirmed paid invoices from `ERS_Facility_Invoice__c`, weekly run breakdown by territory variant (076DO vs 076D) (PDF page 7)

**Garage type gate:** Towbook garages show a read-only notice ("Driver-level data not available — off-platform garage"). Only On-Platform garages (Fleet + On-Platform Contractor) render the full tab. See Section 6.

---

## 2. PDF → Feature Mapping

| PDF Page | Section | Data Source | App Destination |
|----------|---------|-------------|-----------------|
| 2 | KPI banner (calls, completion, satisfaction, on-time %) | SA + Survey_Result__c | Already in Operations tab — reuse |
| 3 | Volume by work type | SA.WorkType.Name | Already in Performance tab — reuse |
| 4 | ATA vs PTA by work type | SA + SAHistory | Already in Performance tab — reuse |
| 5 | Weekly call volume trend | SA.CreatedDate by week | Already in Performance tab — reuse |
| 6 | Driver roster table (calls, ATA, sat, on-time) | SA + AssignedResource + Survey | **New** — Driver Performance section |
| 7 | Invoice runs, 076DO vs 076D amounts, confirmed paid | ERS_Facility_Invoice__c + WOLI | **New** — Invoice Summary section |
| 8 | Driver revenue bar + revenue/hour bar + hours table | WOLI + AssetHistory | **New** — Driver Revenue & Hours section |

Pages 2–5 are already served by the existing dashboard. This spec only implements what's new (pages 6–8 equivalent).

---

## 3. Data Pipeline — Discoveries from the PDF Build

These are **verified constraints** from building `/tmp/driver_stats_query.py`. Any implementation must respect them.

### 3a. Revenue Attribution — Territory Mismatch Problem

**Problem:** `WorkOrderLineItem.ServiceTerritoryId` is NOT the territory that completed the call. Mulesoft may dispatch a bounced call to Transit Auto even though the WO was assigned to a different territory originally. Filtering WOLIs by `ServiceTerritoryId = garage_id` misses bounced calls and over/under-counts revenue.

**Correct approach:**
1. Query SAs WHERE `ServiceTerritoryId = garage_id` AND `Status = 'Completed'` → get `SA.ParentRecordId` (= WOLI ID)
2. Fetch those specific WOLIs by ID
3. Follow WOLI → WO to get billing amounts: `Total_Amount_Invoiced__c` on WOLI

Never filter WOLIs directly by territory. Always follow the SA → WOLI → WO chain.

### 3b. Billing WOLIs Are Created at Invoice Run Time

`WorkOrderLineItem.Total_Amount_Invoiced__c` is populated when the weekly invoice is generated (Wednesdays), not when the call completes. Calls from the current billing week have `Total_Amount_Invoiced__c = 0` until the next Wednesday run.

**Impact for the app:** Show confirmed paid (invoiced WOLIs only) with a clear "pending at next run" note for the current partial week. Do not estimate pending amounts — show TBD.

### 3c. AssetHistory for Driver Hours — All Trucks Required

**Problem:** `ServiceTerritory` is NOT a filterable field on `AssetHistory`. You cannot query AssetHistory WHERE territory = garage. You must:
1. Query ALL `Asset WHERE RecordType.Name = 'ERS Truck'` (955 trucks, no IsActive filter — that column doesn't exist on Asset)
2. Fetch AssetHistory for all of them, filtering by `Field = 'ERS_Driver__c'` and date range
3. Filter in Python: only keep events where the driver name (old or new value) matches a known Transit Auto driver

The garage's driver list comes from `ServiceTerritoryMember` where `ServiceTerritoryId = garage_id AND IsActive = true → ServiceResource.Name`.

### 3d. Session Reconstruction from AssetHistory

Each driver shift = one pair of AssetHistory events on the same truck:
- **Login**: `NewValue = driver_name`, `OldValue = null or previous_driver`
- **Logout**: `OldValue = driver_name`, `NewValue = null or next_driver`

Rules:
- Sort events per (AssetId, driver_name) ascending by CreatedDate
- Pair consecutive login/logout events
- Cap sessions at **16 hours** — any session > 16h is a data error (e.g., missed logout)
- Discard **open sessions** (login with no subsequent logout within the date window)
- Driver name cleanup: strip ` 076DO` / ` 076D` suffixes using regex `r'\s*076D[O]?\s*'` before matching

### 3e. Revenue Scaling

Attributed WOLI amounts (from SA→WOLI chain) sum to a number that may not equal the exact total paid on invoices. The invoice total is authoritative (`ERS_Facility_Invoice__c` SUM). Apply a scale factor:

```
scale = invoice_total_confirmed / sum_of_attributed_woli_amounts
driver_revenue_scaled = driver_attributed_woli_total × scale
```

This preserves relative proportions while making the total reconcile to confirmed paid. Document the scale factor in the UI ("amounts scaled to match $X confirmed invoices").

### 3f. Invoice Structure

Each garage billing account has **two territory variants**:
- `076DO` = tow/heavy service calls
- `076D` = light service calls (battery, tire, lockout, fuel)

Each weekly Wednesday run creates **two separate** `ERS_Facility_Invoice__c` records (one per variant). Query by `ERS_Facility__c IN (facility_id_DO, facility_id_D)`.

**Facility Account IDs are not stored in ServiceTerritory** — they must be looked up from `Account` linked to the territory via `ServiceTerritory.ERS_Facility_Account__c` (or equivalent). Verify the correct join field with `sf_describe ServiceTerritory` before implementing.

---

## 4. New Backend Endpoints

### New file: `backend/routers/garages_labor.py`

Keeps all labor/revenue logic separate. Register in `main.py` alongside the other garage routers.

---

### `GET /api/garages/{territory_id}/driver-stats`

**Purpose:** All driver-level data for the Labor tab — calls, hours, revenue, revenue/hour.

**Query params:**
| Param | Default | Notes |
|-------|---------|-------|
| `start_date` | first of current month | YYYY-MM-DD |
| `end_date` | today | YYYY-MM-DD |

**Pipeline:**

```
Step 1: Get garage's active drivers
  ServiceTerritoryMember WHERE ServiceTerritoryId = territory_id AND IsActive = true
  → ServiceResource.Name, ServiceResource.Id, ServiceResource.ERS_Driver_Type__c
  Filter: ERS_Driver_Type__c IN ('Fleet Driver', 'On-Platform Contractor Driver')

Step 2: Get completed SAs for this garage in date range
  ServiceAppointment WHERE ServiceTerritoryId = territory_id
    AND Status = 'Completed'
    AND CreatedDate >= start AND CreatedDate <= end
    AND WorkType.Name NOT LIKE '%Drop%'   (exclude Tow Drop-Off)
  Fields: Id, ParentRecordId, CreatedDate, ActualStartTime, ERS_PTA__c,
          WorkType.Name, ERS_Dispatch_Method__c

Step 3: Get AssignedResource → driver per SA
  AssignedResource WHERE ServiceAppointmentId IN (sa_ids)
  Group by ServiceAppointmentId, keep most recent (CreatedDate DESC) per SA
  → maps SA → ServiceResource.Name

Step 4: Get Towbook On-Location times (for non-Fleet SAs)
  sf_client.get_towbook_on_location(towbook_sa_ids)

Step 5: Attribution — get billing WOLIs
  Via SA.ParentRecordId → WOLI IDs → fetch in batches of 200
  WOLI fields: Id, Total_Amount_Invoiced__c
  Keep only WOLIs where Total_Amount_Invoiced__c > 0

Step 6: Get survey results
  Survey_Result__c WHERE ERS_Work_Order_Number__c IN (wo_numbers)
  Fields: ERS_Overall_Satisfaction__c, ERS_Work_Order_Number__c

Step 7: Driver hours from AssetHistory
  a) Get ALL Asset IDs WHERE RecordType.Name = 'ERS Truck' (no territory filter, no IsActive)
  b) Fetch AssetHistory WHERE AssetId IN (...) AND Field = 'ERS_Driver__c'
        AND CreatedDate >= start AND CreatedDate <= end
     Process in batches of 200 truck IDs
  c) Filter to this garage's drivers (from Step 1)
  d) Reconstruct sessions: pair login/logout per (asset, driver), cap at 16h, discard open

Step 8: Aggregate per driver
  {
    name: str,
    calls: int,
    avg_ata_min: float | null,      # Fleet: ActualStartTime-CreatedDate; Towbook: SAHistory On Location
    pct_on_time: float | null,      # arrivals ≤ CreatedDate + ERS_PTA__c (skip PTA ≤0 or ≥999)
    totally_satisfied_pct: float | null,
    attributed_revenue: float,      # pre-scale WOLI total
    hours_worked: float,            # from AssetHistory sessions
    shift_days: int,                # distinct calendar dates with at least one session
  }

Step 9: Apply scale factor (if confirmed invoice total available)
  scale = invoice_total / sum(attributed_revenue) — if invoice total is 0, scale = 1.0
  revenue_scaled per driver = attributed_revenue × scale

Step 10: Revenue/hour
  revenue_per_hour = revenue_scaled / hours_worked   (null if hours_worked = 0)
```

**Response shape:**
```json
{
  "garage_id": "0HhPb...",
  "garage_name": "Transit Auto Detail",
  "period": {"start": "2026-04-08", "end": "2026-05-07"},
  "garage_type": "on_platform",
  "total_calls": 847,
  "total_revenue_confirmed": 549831.24,
  "invoice_scale_factor": 1.727,
  "pending_note": "May 6-7 calls not yet invoiced — TBD at next run ~May 14",
  "drivers": [
    {
      "name": "John Smith",
      "calls": 62,
      "avg_ata_min": 41.2,
      "pct_on_time": 78.5,
      "totally_satisfied_pct": 88.2,
      "revenue_confirmed": 38420.10,
      "revenue_per_hour": 89.4,
      "hours_worked": 430.0,
      "shift_days": 22
    }
  ]
}
```

**Cache key:** `garage_driver_stats_{territory_id}_{start_date}_{end_date}`  
**TTL:** 3600s (1h). Stale-while-revalidate pattern (same as scorecard).

---

### `GET /api/garages/{territory_id}/invoices`

**Purpose:** Confirmed paid invoice history from `ERS_Facility_Invoice__c`.

**Query params:**
| Param | Default | Notes |
|-------|---------|-------|
| `start_date` | 90 days ago | YYYY-MM-DD |
| `end_date` | today | YYYY-MM-DD |

**Pipeline:**
```
1. Resolve territory → Facility Account IDs (DO + D variants)
   Use ServiceTerritory → ERS_Facility_Account__c chain
   Verify join field via sf_describe ServiceTerritory before coding

2. Query ERS_Facility_Invoice__c
   WHERE ERS_Facility__c IN (facility_id_DO, facility_id_D)
     AND CreatedDate >= start AND CreatedDate <= end
   ORDER BY CreatedDate ASC
   Fields: Id, Name, CreatedDate, ERS_Facility__c

3. For each invoice, sum WOLI amounts
   WorkOrderLineItem WHERE Facility_Invoice__c IN (invoice_ids)
   GROUP BY Facility_Invoice__c
   SUM(Total_Amount_Invoiced__c) → amount per invoice
   (Use batch queries — potentially large WOLI count)

4. Tag each invoice as '076DO' or '076D' based on ERS_Facility__c match
```

**Response shape:**
```json
{
  "garage_id": "0HhPb...",
  "invoices": [
    {
      "id": "a0XPb...",
      "name": "INV-002279",
      "date": "Apr 9",
      "tag": "076DO",
      "amount": 44821.50
    }
  ],
  "total_confirmed": 549831.24,
  "pending_note": "Current partial week TBD at next Wednesday run"
}
```

**Cache key:** `garage_invoices_{territory_id}_{start_date}_{end_date}`  
**TTL:** 3600s.

---

## 5. New Frontend Components

### New file: `frontend/src/components/GarageLabor.jsx`

Rendered by `GarageDashboard` when `activeTab === 'labor'`. Receives `garageId`, `garageName`, `startDate`, `endDate`, `refreshKey` as props (same pattern as `GaragePerformance`).

**Sections (top to bottom):**

#### 5a. Invoice Summary Card
- Header row: "Confirmed Paid — [period]" | total badge
- Table: Run Date | 076DO Amount | 076D Amount | Run Total
- Footer note: "Pending: [current week] — TBD at next invoice run"
- Source note below table (small gray text): "Source: ERS_Facility_Invoice__c → WorkOrderLineItem.Total_Amount_Invoiced__c"

#### 5b. Driver Revenue Bar Chart
- Horizontal bar chart (sorted by revenue desc)
- X-axis: dollar amount (scaled to confirmed paid)
- Bars colored by on-time % (green ≥80%, amber 60–80%, red <60%)
- Footnote: "Revenue attributed via SA → WOLI chain, scaled to $[X] confirmed invoices (factor: [Y])"

#### 5c. Revenue / Hour Bar Chart
- Same sorted order as revenue bar
- X-axis: $/hr
- Only drivers with hours_worked > 0 shown
- Footnote: "Hours from AssetHistory.ERS_Driver__c login/logout events on all 955 ERS trucks. Sessions capped at 16h."

#### 5d. Driver Detail Table
- Columns: Driver | Calls | Avg ATA | On-Time % | Satisfaction | Hours | Shift Days | Revenue | $/hr
- Sortable by any column (client-side)
- Null handling: show "—" for any null metric (e.g., no hours data if driver only worked in different month)
- Color coding on On-Time % and Satisfaction cells (green/amber/red thresholds same as rest of app)

**Loading/error states:** Same pattern as `GaragePerformance` (spinner while fetching, red error card on failure).

---

## 6. Garage Type Handling

The labor tab is only meaningful for On-Platform garages (Fleet + On-Platform Contractor). Towbook garages have no individual driver tracking in SF.

**How to detect:**
```python
# is_fleet_territory() already exists in utils.py — checks if garage is Fleet
# For On-Platform Contractors, ServiceTerritory has ERS_Driver_Type mapping
# Simplest: if any active ServiceTerritoryMember with ERS_Driver_Type__c IN ('Fleet Driver','On-Platform Contractor Driver') exists → show labor tab
```

In the frontend, `GarageLabor` should check `garage_type` in the API response:
- `"on_platform"` → show full tab
- `"towbook"` → show a card: "Driver-level labor and revenue data is not available for off-platform (Towbook) garages. Revenue for this garage can be found in the Invoice Summary below." Then show only the Invoice Summary section (invoices endpoint still works for Towbook — billing records exist for both).

---

## 7. Wiring Into GarageDetail

### Add tab to `GarageDetail.jsx`

```jsx
// Add to TABS array
{ key: 'labor', label: 'Labor & Revenue', icon: DollarSign }
```

### Add tab handler

```jsx
{tab === 'labor' && (
  <GarageDashboard garageId={id} garageName={garageName} initialTab="labor" />
)}
```

Or, simpler: add `'labor'` as a third sub-tab inside `GarageDashboard` alongside `performance` and `operations`, using the same date range controls already there.

**Recommended:** Add as a third sub-tab in `GarageDashboard` (avoids duplicating the date range picker and refresh logic). The outer tab in `GarageDetail` remains "Dashboard".

---

## 8. Caching Strategy

| Endpoint | Cache Key | TTL | Pattern |
|----------|-----------|-----|---------|
| `/driver-stats` | `garage_driver_stats_{id}_{start}_{end}` | 3600s | stale-while-revalidate |
| `/invoices` | `garage_invoices_{id}_{start}_{end}` | 3600s | standard TTL |

Both are expensive queries (AssetHistory across 955 trucks + WOLI batch fetch). Do NOT reduce TTL below 1h. The stale-while-revalidate pattern serves cached data immediately and refreshes in background — use `cache.stale_while_revalidate()` (same as scorecard).

Cache invalidation: the admin "flush historical" button already invalidates `perf_` prefix. Add `garage_driver_stats_` and `garage_invoices_` to the historical flush list in `admin.py`.

---

## 9. File Size Budget

| File | Current Lines | After This Spec |
|------|--------------|-----------------|
| `garages_labor.py` | new | ~280 lines (two endpoints) |
| `GarageLabor.jsx` | new | ~350 lines (three sections + table) |
| `GarageDetail.jsx` | 168 | ~175 lines (one new import + tab entry) |
| `GarageDashboard.jsx` | 162 | ~175 lines (add third sub-tab) |

All under 600-line ceiling.

---

## 10. Key Constraints — Do Not Skip

1. **Never filter WOLIs by territory** — always follow SA.ParentRecordId → WOLI chain
2. **No `Asset.IsActive` filter** — that column does not exist on Asset in this org (SF error confirmed)
3. **AssetHistory requires all-trucks query** — no territory filter available, must filter in Python
4. **Pending billing = $0 in SF** — do not estimate; show TBD with next run date
5. **Session cap = 16h** — discard sessions over 16h as data errors
6. **Discard open sessions** — login event with no logout in the date window does not count
7. **Name cleanup** — strip ` 076DO` / ` 076D` from driver names before matching or displaying
8. **Scale revenue to invoices** — attributed WOLI totals will not exactly match invoice totals; always apply scale factor and document it in the UI
9. **PTA sentinels** — skip ERS_PTA__c ≤ 0 or ≥ 999 for on-time % calculation
10. **Drop-Off exclusion** — filter `'drop' in WorkType.Name.lower()` on all SA queries

---

## 11. Open Questions (Resolve Before Implementing)

1. **Facility Account IDs are hardcoded in the PDF script** (`001Pb00001IkRXoIAN`, `001Pb00001IkRYYIA3`). For a generic garage endpoint these must be looked up dynamically. Confirm the join field: `sf_describe ServiceTerritory` → find the field linking territory to the billing Account. Could be `ERS_Facility_Account__c` or a related field. If no direct link exists on ServiceTerritory, it may require going through `ERS_Territory_Priority_Matrix__c` or an Account custom field.

2. **On-Platform Contractor detection** — is there a reliable flag on `ServiceTerritory` to distinguish On-Platform from Towbook without querying STMs? If not, the STM query (Step 1 of the pipeline) can double as the type detection gate.

3. **Revenue/hour threshold** — what is the expected range for a healthy driver? From the Transit Auto data: $51–$135/hr. Confirm with supervisors before setting color thresholds.

4. **Scope of "Labor" tab visibility** — should this tab show for ALL garages, or only contractor garages (not Fleet)? Fleet drivers are employees — revenue attribution to individuals may not be appropriate for that context.
