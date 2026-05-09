# Design: Driver Revenue — Switch to WOLI Cost Fields

**Date:** 2026-05-08
**Feature:** Garage Dashboard → Revenue Tab → Revenue per Driver

---

## What Was Built

Changed the revenue calculation for the Garage Driver Revenue tab to use WOLI cost fields (`Basic_Cost__c + Plus_Cost__c + Premier_Cost__c + RV_Cost__c + Other_Cost__c`) instead of `Total_Amount_Invoiced__c`. This makes revenue data available immediately after call completion rather than waiting for the billing invoice cycle, giving complete coverage for any selected date range.

---

## Files Modified

| File | What Changed | Lines +/- |
|---|---|---|
| `routers/garages_revenue.py` | Billing WOLI query + accumulation in `_compute_revenue()` and `_compute_driver_daily()` | +12 / -6 |
| `routers/garages_revenue_export.py` | Updated two label strings describing revenue source | +2 / -2 |
| `doc/fslapp/METRICS_KNOWLEDGE_BASE.md` | Added Driver Revenue section | +50 / 0 |

---

## Design Decisions

### Why cost fields instead of Total_Amount_Invoiced__c
`Total_Amount_Invoiced__c` requires the billing cycle to run (Facility Invoice creation). For recent calls this is $0 even though all cost data is available. The cost fields are written immediately when the billing WOLI is created, right after call completion.

### Why filter PricebookEntryId != null
Every WO has two categories of WOLIs: service WOLIs (WorkType set, PricebookEntry null, always $0) and billing WOLIs (WorkType null, PricebookEntry set, has cost). The service WOLI is what SA.ParentRecordId points to. Filtering `PricebookEntryId != null` selects only billing WOLIs. No change to query structure — just different field selection and a skip condition in the accumulation loop.

### Tax handling
`Tax_Amount__c` is embedded inside `Basic_Cost__c` (not additive). Verified from invoiced records: `Basic_Cost__c` alone equals `Total_Amount_Invoiced__c` for single-tier calls. Summing `Basic + Plus + Premier + RV + Other` gives the correct total.

---

## Assumptions

- Billing WOLIs are always created before or at the same time as SA completion
- The cost field total matches what will eventually be invoiced (barring WOA adjustments)
- WOAs (post-invoice adjustments) are edge cases and not reflected in either approach until re-invoiced

---

## Constraints

- Revenue still shows $0 for WOs where billing WOLIs haven't been created yet (very early in the call lifecycle)
- WOA adjustments (over/under billing corrections) are not reflected — this is unchanged from the previous approach
- Only meaningful for On-Platform Contractor garages; Fleet garages don't produce billing WOLIs

---

## API Contract

No change to endpoints or response shape. Same fields returned. Numbers will be higher for recent date ranges (previously $0 for un-invoiced calls, now shows estimated amounts).

- `GET /api/garages/{territory_id}/driver-revenue?start_date=&end_date=`
- `GET /api/garages/{territory_id}/driver-revenue/{driver}/daily?start_date=&end_date=`

---

## Cache Strategy

No change. `cached_query_persistent` with `max_stale_hours=26`. Bust with `?bust=true` on the main endpoint.
