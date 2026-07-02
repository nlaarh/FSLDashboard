"""Contractor billing recommendations — MH, PG-fuel, ER-miles, tow-miles, TL-tolls.

All endpoints look at the last 90 days, max 200 records each.
Uses the same auth helper from contractor.py.
"""

import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request, Query

from sf_client import sf_query_all, sanitize_soql
from routers.contractor import (
    _require_contractor_facilities,
    _facility_in_clause,
    _cutoff_date,
    _DAYS_BACK,
    _MAX_RECS,
)
from routers.accounting_calc import _get_hdv_vehicles, _norm_vehicle, _get_fuel_limits
from routers.accounting_list import _fetch_photo_wo_ids

log = logging.getLogger("contractor.recommendations")


def _stamp_photos(items: list) -> list:
    """Add has_photos to each item in-place using the same batch photo check as the calls list."""
    wo_ids = [i["wo_id"] for i in items if i.get("wo_id")]
    if wo_ids:
        photo_ids = _fetch_photo_wo_ids(wo_ids)
        for i in items:
            i["has_photos"] = i.get("wo_id", "") in photo_ids
    return items

router = APIRouter()


_RECS_MAX_DAYS_BACK = 60  # Contractors may not request WOAs older than 60 days


def _was_serviced(wo: dict) -> bool:
    """Return False for calls where no service was rendered.

    X-prefix resolution codes (e.g. X001 = Gone on Arrival) and R199
    (not completed) indicate the truck arrived but no service was delivered.
    """
    res = (wo.get("Resolution_Code__c") or "").upper()
    return not (res.startswith("X") or res == "R199")


def _tow_was_completed(wo: dict) -> bool:
    """Return False when the tow portion did NOT happen, so MH (medium duty),
    Tow Miles, and Tolls charges must not be recommended. Two cases, matched on
    the resolution-code prefix:
      • G* — driver fixed the vehicle on the spot ('go'), no tow   (e.g. WO-04806885 = G411)
      • R* — unable to complete / no service rendered              (e.g. WO-04815339 = R002 'NSR')
    ER Miles and PG Fuel are NOT affected (the driver still drove to the scene).

    IMPORTANT: filter in PYTHON, not SOQL. The Resolution_Code__c picklist's
    stored value differs from its displayed code, so SOQL LIKE/prefix filters
    are unreliable (LIKE 'R%' matches WOs that display as 'G306'). The value the
    REST API returns here is the clean displayed code, so startswith() is safe.
    """
    res = (wo.get("Resolution_Code__c") or "").upper()
    return not (res.startswith("G") or res.startswith("R"))


def _is_duplicated_call(wo: dict) -> bool:
    """Return True for duplicated calls (WO Subject = 'This is a duplicated call').

    Duplicated calls have NO enroute miles — the driver is already on location when
    the call is created — so they must not be recommended for ER (Enroute) WOAs.
    """
    return "duplicated call" in (wo.get("Subject") or "").lower()


def _enroute_eligible(wo: dict) -> bool:
    """ER (Enroute Miles) eligibility — ER-SPECIFIC, looser than _was_serviced.

    A driver earns enroute miles whenever they actually drove toward the call, even
    if it was cancelled while EN ROUTE. Verified against the org:
      • X002 = 'Cancel En Route' → driver went en route ~99% of the time → KEEP (payable).
      • X001 = cancelled, driver never moved (~92% never went en route) → EXCLUDE.
      • R199 = not completed → EXCLUDE.
    G* and other R* are kept (the driver still drove to the scene). Duplicated calls
    are excluded separately via _is_duplicated_call().

    NOTE: this is ER-only. MH / Tow Miles / Tolls still exclude ALL X codes (via
    _was_serviced + _tow_was_completed) because no tow was completed.
    """
    res = (wo.get("Resolution_Code__c") or "").upper()
    return res not in ("X001", "R199")


def _date_clause(start_date: str | None, end_date: str | None) -> str:
    """Build SOQL date filter. If neither provided, defaults to last 90 days.
    Clamps start_date to no more than 60 days ago — WOA requests must be timely."""
    max_start = _cutoff_date(_RECS_MAX_DAYS_BACK)
    if not start_date and not end_date:
        start_date = max_start
    if start_date and start_date < max_start:
        start_date = max_start
    parts = []
    if start_date:
        parts.append(f"AND CreatedDate >= {start_date}T00:00:00Z")
    if end_date:
        parts.append(f"AND CreatedDate <= {end_date}T23:59:59Z")
    return " ".join(parts)


_SF_COMMUNITY_ROOT = "https://aaawcny.my.site.com/aaawcnyspp"


def _woa_new_url(wo_id: str) -> str:
    # Opens the parent Work Order in the community portal so the contractor
    # can click "New Adjustment" — the standard quick-action form shows the
    # Work Order field clearly, unlike the flow which hides it.
    return f"{_SF_COMMUNITY_ROOT}/s/workorder/{wo_id}"


def _actioned_status(woli_list: list[dict], woa_set: set[str], code: str) -> str | None:
    """Return why a recommendation is already actioned, or None if it still needs action.

    Reuses the same suppression detection used when include_actioned is False:
    a WOA already submitted ('woa_submitted') takes precedence over a paid/active
    WOLI ('paid'). Returns None when neither applies (rec still actionable).
    """
    if code in woa_set:
        return "woa_submitted"
    if _has_code(woli_list, code):
        return "paid"
    return None


# ── Shared WOLI fetcher for a set of WO IDs ──────────────────────────────────

def _fetch_wolis_for_wo_ids(wo_ids: list[str]) -> dict[str, list[dict]]:
    """Return {wo_id: [woli_row, ...]} for up to 200 WOs at a time."""
    if not wo_ids:
        return {}
    result: dict[str, list[dict]] = defaultdict(list)
    for i in range(0, len(wo_ids), 200):
        batch = wo_ids[i: i + 200]
        id_csv = "','".join(sanitize_soql(x) for x in batch)
        rows = sf_query_all(f"""
            SELECT Id, WorkOrderId, PricebookEntry.ProductCode, Quantity, Status
            FROM WorkOrderLineItem
            WHERE WorkOrderId IN ('{id_csv}')
              AND PricebookEntryId != null
        """)
        for r in rows:
            result[r.get("WorkOrderId", "")].append(r)
    return result


def _has_code(woli_list: list[dict], code: str) -> bool:
    """Return True if any active (non-cancelled) WOLI has the given ProductCode with qty > 0."""
    return any(
        (r.get("PricebookEntry") or {}).get("ProductCode") == code
        and (r.get("Quantity") or 0) > 0
        and (r.get("Status") or "").lower() not in ("cancelled", "canceled")
        for r in woli_list
    )


def _fetch_woa_product_codes(wo_ids: list[str]) -> dict[str, set[str]]:
    """Return {wo_id: set of product codes} for any WOA already submitted for that WO.

    Uses Product__r.Name (e.g. 'ER - Enroute Miles') matched by 2-char prefix.
    If any WOA exists for a product on a WO, the recommendation is suppressed.
    """
    if not wo_ids:
        return {}
    result: dict[str, set[str]] = defaultdict(set)
    for i in range(0, len(wo_ids), 200):
        batch = wo_ids[i: i + 200]
        id_csv = "','".join(sanitize_soql(x) for x in batch)
        try:
            rows = sf_query_all(f"""
                SELECT Work_Order__c, Product__r.Name
                FROM ERS_Work_Order_Adjustment__c
                WHERE Work_Order__c IN ('{id_csv}')
                  AND Status__c NOT IN ('Rejected', 'Cancelled', 'Canceled')
            """)
            for r in rows:
                wo_id = r.get("Work_Order__c") or ""
                prod = ((r.get("Product__r") or {}).get("Name") or "")
                if wo_id and prod:
                    result[wo_id].add(prod[:2].upper())
        except Exception as e:
            log.warning(f"WOA product code fetch failed: {e}")
    return dict(result)


# ── GET /api/contractor/recommendations/mh ───────────────────────────────────

@router.get("/api/contractor/recommendations/mh")
def contractor_recs_mh(
    request: Request,
    start_date: str = Query(None, description="YYYY-MM-DD"),
    end_date: str = Query(None, description="YYYY-MM-DD"),
    include_actioned: bool = Query(False, description="Include already-actioned recs, tagged"),
):
    """Completed WOs serviced on a vehicle in ref_heavy_duty_vehicles (Postgres)
    that have no MH WOLI — possible missed medium/heavy-vehicle charge."""
    facility_ids = _require_contractor_facilities(request)
    f_clause = _facility_in_clause(facility_ids)
    date_filter = _date_clause(start_date, end_date)

    # Load approved HD/MD vehicle list from Postgres
    hdv_list = _get_hdv_vehicles()
    if not hdv_list:
        return {"items": [], "warning": "Approved heavy-duty vehicle list is empty — add vehicles in Admin → HD Vehicles"}

    approved_set = {(_norm_vehicle(v["make"]), _norm_vehicle(v["model"])) for v in hdv_list}

    # Fetch completed tow calls with a vehicle make — only tow calls are eligible for MH charge
    wo_rows = sf_query_all(f"""
        SELECT Id, WorkOrderNumber, Facility_ID__c, CreatedDate,
               Vehicle_Make__c, Vehicle_Model__c, Resolution_Code__c, Status,
               Service_Resource__r.Name,
               ServiceTerritory.Name
        FROM WorkOrder
        WHERE Facility_ID__c IN ({f_clause})
          {date_filter}
          AND Status IN ('Completed', 'Closed')
          AND Tow_Call__c = true
          AND Vehicle_Make__c != null
        ORDER BY CreatedDate DESC
        LIMIT 50000
    """)

    if not wo_rows:
        return {"items": []}

    # Keep WOs whose vehicle (make+model) exactly matches the approved HD list
    # and where service was actually rendered (skip X-code calls like Gone on Arrival)
    hd_wo_ids = []
    hd_wo_map = {}
    for wo in wo_rows:
        if not _was_serviced(wo) or not _tow_was_completed(wo):
            continue
        nm = _norm_vehicle(wo.get("Vehicle_Make__c") or "")
        nmod = _norm_vehicle(wo.get("Vehicle_Model__c") or "")
        if (nm, nmod) in approved_set:
            hd_wo_ids.append(wo["Id"])
            hd_wo_map[wo["Id"]] = wo

    if not hd_wo_ids:
        return {"items": []}

    woli_by_wo = _fetch_wolis_for_wo_ids(hd_wo_ids)
    woa_codes = _fetch_woa_product_codes(hd_wo_ids)

    items = []
    for wo_id in hd_wo_ids:
        actioned = _actioned_status(woli_by_wo.get(wo_id, []), woa_codes.get(wo_id, set()), "MH")
        if actioned and not include_actioned:
            continue
        wo = hd_wo_map[wo_id]
        items.append({
            "wo_number": wo.get("WorkOrderNumber") or "",
            "facility": wo.get("Facility_ID__c") or "",
            "service_resource": (wo.get("Service_Resource__r") or {}).get("Name") or "",
            "territory_name": (wo.get("ServiceTerritory") or {}).get("Name") or "",
            "created_date": wo.get("CreatedDate") or "",
            "vehicle_make": wo.get("Vehicle_Make__c") or "",
            "vehicle_model": wo.get("Vehicle_Model__c") or "",
            "wo_status": wo.get("Status") or "",
            "wo_id": wo_id,
            "already_actioned": actioned,
            "sf_new_woa_url": _woa_new_url(wo_id),
        })
        if len(items) >= _MAX_RECS:
            break

    return {"items": _stamp_photos(items)}


# ── GET /api/contractor/recommendations/pg-fuel ──────────────────────────────

@router.get("/api/contractor/recommendations/pg-fuel")
def contractor_recs_pg_fuel(
    request: Request,
    start_date: str = Query(None, description="YYYY-MM-DD"),
    end_date: str = Query(None, description="YYYY-MM-DD"),
    include_actioned: bool = Query(False, description="Include already-actioned recs, tagged"),
):
    """WOs eligible for PG fuel reimbursement (L402/L403, Plus/Premier coverage) but no PG WOLI."""
    facility_ids = _require_contractor_facilities(request)
    f_clause = _facility_in_clause(facility_ids)
    date_filter = _date_clause(start_date, end_date)

    fuel_limits = _get_fuel_limits()
    eligible_codes = [c for c in ("L402", "L403") if c in fuel_limits]
    if not eligible_codes:
        return {"items": [], "warning": "No fuel dispatch codes configured"}

    eligible_coverage = ("Plus", "Premier", "PLUS", "PREMIER")
    code_clause = "'" + "','".join(eligible_codes) + "'"
    cov_clause = "'" + "','".join(eligible_coverage) + "'"

    wo_rows = sf_query_all(f"""
        SELECT Id, WorkOrderNumber, Facility_ID__c, CreatedDate,
               Dispatch_Code__c, Coverage__c, Entitlement_Master__r.Name, Status,
               Service_Resource__r.Name,
               ServiceTerritory.Name
        FROM WorkOrder
        WHERE Facility_ID__c IN ({f_clause})
          {date_filter}
          AND Status IN ('Completed', 'Closed')
          AND Dispatch_Code__c IN ({code_clause})
          AND Coverage__c IN ({cov_clause})
        ORDER BY CreatedDate DESC
        LIMIT 50000
    """)

    if not wo_rows:
        return {"items": []}

    wo_ids = [wo["Id"] for wo in wo_rows]
    woli_by_wo = _fetch_wolis_for_wo_ids(wo_ids)
    woa_codes = _fetch_woa_product_codes(wo_ids)

    items = []
    for wo in wo_rows:
        wo_id = wo["Id"]
        actioned = _actioned_status(woli_by_wo.get(wo_id, []), woa_codes.get(wo_id, set()), "PG")
        if actioned and not include_actioned:
            continue
        dispatch_code = wo.get("Dispatch_Code__c") or ""
        fuel_type = "Gas" if dispatch_code == "L402" else "Diesel"
        max_amount = fuel_limits.get(dispatch_code)
        entitlement_master_rec = wo.get("Entitlement_Master__r") or {}
        items.append({
            "wo_number": wo.get("WorkOrderNumber") or "",
            "facility": wo.get("Facility_ID__c") or "",
            "service_resource": (wo.get("Service_Resource__r") or {}).get("Name") or "",
            "territory_name": (wo.get("ServiceTerritory") or {}).get("Name") or "",
            "created_date": wo.get("CreatedDate") or "",
            "dispatch_code": dispatch_code,
            "coverage": wo.get("Coverage__c") or "",
            "entitlement_master": entitlement_master_rec.get("Name") or "",
            "fuel_type": fuel_type,
            "max_reimbursement": max_amount,
            "wo_status": wo.get("Status") or "",
            "wo_id": wo_id,
            "already_actioned": actioned,
            "sf_new_woa_url": _woa_new_url(wo_id),
        })
        if len(items) >= _MAX_RECS:
            break

    return {"items": _stamp_photos(items)}


# ── GET /api/contractor/recommendations/er-miles ─────────────────────────────

@router.get("/api/contractor/recommendations/er-miles")
def contractor_recs_er_miles(
    request: Request,
    start_date: str = Query(None, description="YYYY-MM-DD"),
    end_date: str = Query(None, description="YYYY-MM-DD"),
    include_actioned: bool = Query(False, description="Include already-actioned recs, tagged"),
):
    """WOs with at least one WOLI but no ER (enroute miles) WOLI.

    Also checks SA history: if driver reached On Location before En Route was
    logged, that signals the driver may not have tapped En Route — ER miles
    may never have been captured.
    """
    facility_ids = _require_contractor_facilities(request)
    f_clause = _facility_in_clause(facility_ids)
    date_filter = _date_clause(start_date, end_date)

    wo_rows = sf_query_all(f"""
        SELECT Id, WorkOrderNumber, Facility_ID__c, CreatedDate,
               ERS_Estimated_En_Route_Miles__c, Resolution_Code__c, Status, Subject,
               Service_Resource__r.Name,
               ServiceTerritory.Name
        FROM WorkOrder
        WHERE Facility_ID__c IN ({f_clause})
          {date_filter}
          AND Status IN ('Completed', 'Closed')
        ORDER BY CreatedDate DESC
        LIMIT 50000
    """)

    if not wo_rows:
        return {"items": []}

    wo_ids = [wo["Id"] for wo in wo_rows]
    woli_by_wo = _fetch_wolis_for_wo_ids(wo_ids)
    woa_codes = _fetch_woa_product_codes(wo_ids)

    # Keep only WOs that had service rendered, have at least one WOLI, and aren't actioned.
    candidates = [
        wo for wo in wo_rows
        if _enroute_eligible(wo)  # driver drove (keeps X002 Cancel En Route; drops X001/R199)
        and not _is_duplicated_call(wo)  # duplicated calls have no enroute miles
        and woli_by_wo.get(wo["Id"])
        and (
            include_actioned
            or _actioned_status(woli_by_wo.get(wo["Id"], []), woa_codes.get(wo["Id"], set()), "ER") is None
        )
    ]

    if not candidates:
        return {"items": []}

    # Fetch SA history to detect On-Location-before-Enroute anomaly.
    # Cross-object filter on SAHistory is not supported in all SF orgs — fall back
    # to empty history if the query fails so the rest of the endpoint still works.
    candidate_ids = [wo["Id"] for wo in candidates[:500]]
    history_rows = []
    try:
        id_csv = "','".join(sanitize_soql(x) for x in candidate_ids)
        history_rows = sf_query_all(f"""
            SELECT ServiceAppointmentId, NewValue, CreatedDate,
                   ServiceAppointment.ERS_Work_Order__c
            FROM ServiceAppointmentHistory
            WHERE ServiceAppointment.ERS_Work_Order__c IN ('{id_csv}')
              AND Field = 'Status'
              AND NewValue IN ('En Route', 'On Location')
            ORDER BY ServiceAppointmentId, CreatedDate ASC
            LIMIT 50000
        """)
    except Exception as e:
        log.warning(f"contractor_recs_er_miles: SA history query failed (skipping): {e}")

    # Build {wo_id: {status: first_ts}} from history
    wo_status_ts: dict[str, dict] = defaultdict(dict)
    for h in history_rows:
        sa = h.get("ServiceAppointment") or {}
        wo_id = sa.get("ERS_Work_Order__c") or ""
        status = h.get("NewValue") or ""
        ts = h.get("CreatedDate") or ""
        if wo_id and status and status not in wo_status_ts[wo_id]:
            wo_status_ts[wo_id][status] = ts

    items = []
    for wo in candidates:
        wo_id = wo["Id"]
        statuses = wo_status_ts.get(wo_id, {})
        enroute_ts = statuses.get("En Route")
        onloc_ts = statuses.get("On Location")

        # Determine AI summary
        if onloc_ts and enroute_ts and onloc_ts <= enroute_ts:
            ai_summary = (
                "Driver reached On Location before En Route was logged — "
                "ER miles may not have been captured by the system."
            )
        elif not enroute_ts and onloc_ts:
            ai_summary = (
                "No En Route status found in SA history. "
                "Driver may have skipped the En Route tap — ER miles likely missing."
            )
        else:
            ai_summary = (
                "No ER (enroute miles) line item found on this completed work order."
            )

        items.append({
            "wo_number": wo.get("WorkOrderNumber") or "",
            "facility": wo.get("Facility_ID__c") or "",
            "service_resource": (wo.get("Service_Resource__r") or {}).get("Name") or "",
            "territory_name": (wo.get("ServiceTerritory") or {}).get("Name") or "",
            "created_date": wo.get("CreatedDate") or "",
            "estimated_er_miles": wo.get("ERS_Estimated_En_Route_Miles__c"),
            "enroute_ts": enroute_ts,
            "on_location_ts": onloc_ts,
            "ai_summary": ai_summary,
            "wo_status": wo.get("Status") or "",
            "wo_id": wo_id,
            "already_actioned": _actioned_status(woli_by_wo.get(wo_id, []), woa_codes.get(wo_id, set()), "ER"),
            "sf_new_woa_url": _woa_new_url(wo_id),
        })
        if len(items) >= _MAX_RECS:
            break

    return {"items": _stamp_photos(items)}


# ── GET /api/contractor/recommendations/tow-miles ────────────────────────────

@router.get("/api/contractor/recommendations/tow-miles")
def contractor_recs_tow_miles(
    request: Request,
    start_date: str = Query(None, description="YYYY-MM-DD"),
    end_date: str = Query(None, description="YYYY-MM-DD"),
    include_actioned: bool = Query(False, description="Include already-actioned recs, tagged"),
):
    """Completed tow WOs with no TW (tow miles) WOLI — a tow happened but tow
    miles may not have been billed.

    Resolution-code exclusions are applied in PYTHON via _tow_was_completed()
    (G* fixed-on-spot and R* unable-to-complete are skipped). We do NOT filter
    resolution codes in SOQL: the picklist's stored value differs from its
    displayed code, so LIKE/IN prefix filters are unreliable.
    """
    facility_ids = _require_contractor_facilities(request)
    f_clause = _facility_in_clause(facility_ids)
    date_filter = _date_clause(start_date, end_date)

    wo_rows = sf_query_all(f"""
        SELECT Id, WorkOrderNumber, Facility_ID__c, CreatedDate,
               Resolution_Code__c, Tow_Miles__c, ERS_Estimated_Tow_Miles__c,
               Dispatch_Code__c, Status,
               Service_Resource__r.Name,
               ServiceTerritory.Name
        FROM WorkOrder
        WHERE Facility_ID__c IN ({f_clause})
          {date_filter}
          AND Status IN ('Completed', 'Closed')
          AND Tow_Call__c = true
        ORDER BY CreatedDate DESC
        LIMIT 50000
    """)

    if not wo_rows:
        return {"items": []}

    wo_ids = [wo["Id"] for wo in wo_rows]
    woli_by_wo = _fetch_wolis_for_wo_ids(wo_ids)
    woa_codes = _fetch_woa_product_codes(wo_ids)

    items = []
    for wo in wo_rows:
        if not _was_serviced(wo) or not _tow_was_completed(wo):
            continue
        wo_id = wo["Id"]
        actioned = _actioned_status(woli_by_wo.get(wo_id, []), woa_codes.get(wo_id, set()), "TW")
        if actioned and not include_actioned:
            continue
        items.append({
            "wo_number": wo.get("WorkOrderNumber") or "",
            "facility": wo.get("Facility_ID__c") or "",
            "service_resource": (wo.get("Service_Resource__r") or {}).get("Name") or "",
            "territory_name": (wo.get("ServiceTerritory") or {}).get("Name") or "",
            "created_date": wo.get("CreatedDate") or "",
            "resolution_code": wo.get("Resolution_Code__c") or "",
            "tow_miles": wo.get("Tow_Miles__c"),
            "estimated_tow_miles": wo.get("ERS_Estimated_Tow_Miles__c"),
            "wo_status": wo.get("Status") or "",
            "wo_id": wo_id,
            "already_actioned": actioned,
            "sf_new_woa_url": _woa_new_url(wo_id),
        })
        if len(items) >= _MAX_RECS:
            break

    return {"items": _stamp_photos(items)}


# ── GET /api/contractor/recommendations/tl-tolls ─────────────────────────────

@router.get("/api/contractor/recommendations/tl-tolls")
def contractor_recs_tl_tolls(
    request: Request,
    start_date: str = Query(None, description="YYYY-MM-DD"),
    end_date: str = Query(None, description="YYYY-MM-DD"),
    include_actioned: bool = Query(False, description="Include already-actioned recs, tagged"),
):
    """WOs with estimated tow miles > 30 and no TL (tolls/parking) WOLI."""
    facility_ids = _require_contractor_facilities(request)
    f_clause = _facility_in_clause(facility_ids)
    date_filter = _date_clause(start_date, end_date)

    wo_rows = sf_query_all(f"""
        SELECT Id, WorkOrderNumber, Facility_ID__c, CreatedDate,
               ERS_Estimated_Tow_Miles__c, Tow_Miles__c, Resolution_Code__c, Status,
               Service_Resource__r.Name,
               ServiceTerritory.Name
        FROM WorkOrder
        WHERE Facility_ID__c IN ({f_clause})
          {date_filter}
          AND Status IN ('Completed', 'Closed')
          AND Tow_Call__c = true
          AND ERS_Estimated_Tow_Miles__c > 30
        ORDER BY CreatedDate DESC
        LIMIT 50000
    """)

    if not wo_rows:
        return {"items": []}

    wo_ids = [wo["Id"] for wo in wo_rows]
    woli_by_wo = _fetch_wolis_for_wo_ids(wo_ids)
    woa_codes = _fetch_woa_product_codes(wo_ids)

    items = []
    for wo in wo_rows:
        if not _was_serviced(wo) or not _tow_was_completed(wo):
            continue
        wo_id = wo["Id"]
        actioned = _actioned_status(woli_by_wo.get(wo_id, []), woa_codes.get(wo_id, set()), "TL")
        if actioned and not include_actioned:
            continue
        est_miles = wo.get("ERS_Estimated_Tow_Miles__c") or 0
        items.append({
            "wo_number": wo.get("WorkOrderNumber") or "",
            "facility": wo.get("Facility_ID__c") or "",
            "service_resource": (wo.get("Service_Resource__r") or {}).get("Name") or "",
            "territory_name": (wo.get("ServiceTerritory") or {}).get("Name") or "",
            "created_date": wo.get("CreatedDate") or "",
            "estimated_tow_miles": est_miles,
            "actual_tow_miles": wo.get("Tow_Miles__c"),
            "wo_status": wo.get("Status") or "",
            "wo_id": wo_id,
            "already_actioned": actioned,
            "sf_new_woa_url": _woa_new_url(wo_id),
        })
        if len(items) >= _MAX_RECS:
            break

    return {"items": _stamp_photos(items)}
