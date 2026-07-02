"""Contractor portal — payment history and billing recommendations.

Scoped to the authenticated contractor's assigned SF ServiceTerritories.
All endpoints read-only: no DML, no SF mutations.
"""

import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Request, Query

import users as _users
from routers.auth import get_request_username
from sf_client import sf_query_all, sanitize_soql
from routers.accounting_photos import fetch_photos
from routers.accounting_list import _fetch_photo_wo_ids
from routers.accounting_calc import _fmt_et, _safe_float
from repositories import driver_collection as _dc_repo
from utils import parse_dt as _parse_dt

log = logging.getLogger("contractor")

router = APIRouter()

_DAYS_BACK = 90
_MAX_RECS = 200


# ── Auth helper ───────────────────────────────────────────────────────────────

def _require_contractor_facilities(request: Request) -> list[str]:
    """Return Facility_ID__c codes for the contractor's assigned garages.

    ServiceTerritory is a region that can span multiple facilities; filtering
    by ServiceTerritoryId would leak WOs from sibling facilities in the same
    region. We derive the exact facility codes from the garage names stored in
    the DB (format: "076DO - TRANSIT AUTO DETAIL" → "076DO") so SOQL can filter
    on Facility_ID__c instead.
    """
    username = get_request_username(request)
    user = _users.get_user(username) if username else None
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    role = user.get("role", "")
    if role not in ("superadmin", "admin", "contractor"):
        raise HTTPException(status_code=403, detail="Contractor access only")
    garages = _users.get_user_garages(username) if username else []
    if not garages:
        raise HTTPException(status_code=400, detail="No territories assigned to this account")
    facility_ids = [g["name"].split(" - ")[0].strip() for g in garages if " - " in g.get("name", "")]
    if not facility_ids:
        raise HTTPException(status_code=400, detail="No facilities resolved for this account")
    return facility_ids


def _facility_in_clause(facility_ids: list[str]) -> str:
    """Build a SOQL IN clause for Facility_ID__c values."""
    safe = [sanitize_soql(f) for f in facility_ids]
    return "'" + "','".join(safe) + "'"


def _cutoff_date(days: int = _DAYS_BACK) -> str:
    """Return an ISO date string N days ago, UTC."""
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.strftime("%Y-%m-%d")


# ── GET /api/contractor/wo-payments ──────────────────────────────────────────

@router.get("/api/contractor/wo-payments")
def contractor_wo_payments(
    request: Request,
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date: str = Query(..., description="YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=50000),
):
    """Paginated WOLI payment history for contractor territories."""
    facility_ids = _require_contractor_facilities(request)
    f_clause = _facility_in_clause(facility_ids)

    try:
        datetime.strptime(start_date, "%Y-%m-%d")
        datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD")

    soql = f"""
        SELECT Id, WorkOrderId, WorkOrder.WorkOrderNumber, WorkOrder.Facility_ID__c,
               WorkOrder.CreatedDate, WorkOrder.Status,
               WorkOrder.ServiceTerritory.Name, WorkOrder.WorkType.Name,
               PricebookEntry.Name, PricebookEntry.ProductCode,
               Quantity, UnitPrice, TotalPrice,
               Basic_Cost__c, Plus_Cost__c, Premier_Cost__c, RV_Cost__c, Other_Cost__c
        FROM WorkOrderLineItem
        WHERE WorkOrder.Facility_ID__c IN ({f_clause})
          AND WorkOrder.CreatedDate >= {start_date}T00:00:00Z
          AND WorkOrder.CreatedDate <= {end_date}T23:59:59Z
          AND PricebookEntryId != null
        ORDER BY WorkOrder.CreatedDate DESC
        LIMIT 50000
    """
    rows = sf_query_all(soql)

    items = []
    for r in rows:
        wo = r.get("WorkOrder") or {}
        pbe = r.get("PricebookEntry") or {}
        basic = r.get("Basic_Cost__c") or 0
        plus  = r.get("Plus_Cost__c") or 0
        prem  = r.get("Premier_Cost__c") or 0
        rv    = r.get("RV_Cost__c") or 0
        other = r.get("Other_Cost__c") or 0
        row_total = round(basic + plus + prem + rv + other, 2)
        items.append({
            "wo_number": wo.get("WorkOrderNumber") or "",
            "facility": wo.get("Facility_ID__c") or "",
            "territory_name": (wo.get("ServiceTerritory") or {}).get("Name") or "",
            "call_type": (wo.get("WorkType") or {}).get("Name") or "",
            "created_date": wo.get("CreatedDate") or "",
            "status": wo.get("Status") or "",
            "product_code": pbe.get("ProductCode") or "",
            "product_name": pbe.get("Name") or "",
            "quantity": r.get("Quantity"),
            "unit_price": r.get("UnitPrice"),
            "total_price": row_total,
            "basic_cost": r.get("Basic_Cost__c"),
            "plus_cost": r.get("Plus_Cost__c"),
            "premier_cost": r.get("Premier_Cost__c"),
            "rv_cost": r.get("RV_Cost__c"),
            "other_cost": r.get("Other_Cost__c"),
            "wo_id": r.get("WorkOrderId") or "",
            "woli_id": r.get("Id") or "",
        })

    total = len(items)
    total_payment = round(sum((x.get("total_price") or 0) for x in items), 2)

    start_idx = (page - 1) * page_size
    page_items = items[start_idx: start_idx + page_size]

    return {
        "items": page_items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_payment": total_payment,
    }


# ── GET /api/contractor/calls ─────────────────────────────────────────────────

@router.get("/api/contractor/calls")
def contractor_calls(
    request: Request,
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date: str = Query(..., description="YYYY-MM-DD"),
):
    """WO-centric calls log for contractor territories. Returns all matching WOs."""
    facility_ids = _require_contractor_facilities(request)
    f_clause = _facility_in_clause(facility_ids)

    try:
        datetime.strptime(start_date, "%Y-%m-%d")
        datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD")

    soql = f"""
        SELECT Id, WorkOrderNumber, Coverage__c, Resolution_Code__c,
               Status, CreatedDate, Facility_ID__c, Facility_Name__c,
               ServiceTerritory.Name, Trouble_Code__c, Type__c,
               Basic_Cost__c, Plus_Cost__c, Premier_Cost__c, RV_Cost__c, Other_Cost__c
        FROM WorkOrder
        WHERE Facility_ID__c IN ({f_clause})
          AND CreatedDate >= {start_date}T00:00:00Z
          AND CreatedDate <= {end_date}T23:59:59Z
        ORDER BY CreatedDate DESC
    """
    rows = sf_query_all(soql)

    items = []
    for r in rows:
        items.append({
            "wo_id": r["Id"],
            "wo_number": r.get("WorkOrderNumber") or "",
            "call_type": r.get("Type__c") or "",
            "coverage": r.get("Coverage__c") or "",
            "resolution_code": r.get("Resolution_Code__c") or "",
            "status": r.get("Status") or "",
            "created_date": r.get("CreatedDate") or "",
            "facility": r.get("Facility_ID__c") or "",
            "facility_name": r.get("Facility_Name__c") or "",
            "territory_name": (r.get("ServiceTerritory") or {}).get("Name") or "",
            "notes": r.get("Notes__c") or "",
            "description": r.get("Description") or "",
            "customer_name": r.get("Customer_Name__c") or "",
            "trouble_code": r.get("Trouble_Code__c") or "",
            "total_cost": round(sum(filter(None, [
                r.get("Basic_Cost__c"), r.get("Plus_Cost__c"), r.get("Premier_Cost__c"),
                r.get("RV_Cost__c"), r.get("Other_Cost__c")
            ])), 2),
        })

    # Stamp has_photos on every item using the same batch query as accounting list
    all_wo_ids = [i["wo_id"] for i in items if i.get("wo_id")]
    photo_ids = _fetch_photo_wo_ids(all_wo_ids)
    for i in items:
        i["has_photos"] = i.get("wo_id", "") in photo_ids

    return {
        "items": items,
        "total": len(items),
    }


# ── GET /api/contractor/calls/{wo_id} ────────────────────────────────────────

@router.get("/api/contractor/calls/{wo_id}")
def contractor_call_detail(
    wo_id: str,
    request: Request,
):
    """Full detail for a single WO: SA, WOLIs, photos."""
    facility_ids = _require_contractor_facilities(request)
    safe_wo_id = sanitize_soql(wo_id)

    # Fetch SA
    sa_rows = sf_query_all(f"""
        SELECT Id, AppointmentNumber, ServiceNote, Status,
               ERS_PTA__c, ActualStartTime, SchedStartTime,
               ERS_Dispatch_Method__c, ERS_Membership_Level_Coverage__c
        FROM ServiceAppointment
        WHERE ERS_Work_Order__c = '{safe_wo_id}'
        LIMIT 1
    """)
    sa = sa_rows[0] if sa_rows else None

    # Fetch WOLIs
    woli_rows = sf_query_all(f"""
        SELECT Id, LineItemNumber, PricebookEntry.Name, PricebookEntry.ProductCode,
               Quantity, UnitPrice, TotalPrice,
               Basic_Cost__c, Plus_Cost__c, Premier_Cost__c, RV_Cost__c, Other_Cost__c
        FROM WorkOrderLineItem
        WHERE WorkOrderId = '{safe_wo_id}'
          AND PricebookEntryId != null
    """)
    wolis = []
    for w in woli_rows:
        pbe = w.get("PricebookEntry") or {}
        basic = w.get("Basic_Cost__c") or 0
        plus  = w.get("Plus_Cost__c") or 0
        prem  = w.get("Premier_Cost__c") or 0
        rv    = w.get("RV_Cost__c") or 0
        other = w.get("Other_Cost__c") or 0
        wolis.append({
            "id": w.get("Id") or "",
            "line_item_number": w.get("LineItemNumber") or "",
            "product_code": pbe.get("ProductCode") or "",
            "product_name": pbe.get("Name") or "",
            "quantity": w.get("Quantity"),
            "unit_price": w.get("UnitPrice"),
            "total_price": round(basic + plus + prem + rv + other, 2),
            "basic_cost": w.get("Basic_Cost__c"),
            "plus_cost": w.get("Plus_Cost__c"),
            "premier_cost": w.get("Premier_Cost__c"),
            "rv_cost": w.get("RV_Cost__c"),
            "other_cost": w.get("Other_Cost__c"),
        })

    # Photos need ALL WOLIs including 00000001/00000002 which have no PricebookEntry.
    # The billing WOLI query above filters PricebookEntryId != null and misses them.
    all_woli_rows = sf_query_all(f"""
        SELECT Id, LineItemNumber
        FROM WorkOrderLineItem
        WHERE WorkOrderId = '{safe_wo_id}'
    """)
    photos = fetch_photos(wo_id, all_woli_rows, is_fleet=False)

    return {
        "wo_id": wo_id,
        "sa": sa,
        "wolis": wolis,
        "photos": photos,
    }


# ── GET /api/contractor/calls/{wo_id}/audit ───────────────────────────────────

_STATUS_TRANSITIONS = [
    'None', 'Scheduled', 'Assigned', 'Dispatched', 'Accepted', 'Declined',
    'En Route', 'On Location', 'In Progress', 'Completed', 'Cannot Complete', 'Canceled',
]

# Experience Cloud community site — contractors have NO Lightning access, so any
# record link surfaced to a contractor must point here. Salesforce resolves the
# record by Id and redirects to the canonical slugged URL.
_SF_COMMUNITY_BASE = "https://aaawcny.my.site.com/aaawcnyspp/s"


@router.get("/api/contractor/calls/{wo_id}/audit")
def contractor_call_audit(wo_id: str, request: Request):
    """Return WO detail in the same shape as the accounting audit endpoint.

    Contractor-scoped: no WOA, no AI, no distance verification.
    Enables direct reuse of AccountingAuditPanel on the frontend.
    """
    facility_ids = _require_contractor_facilities(request)
    safe_id = sanitize_soql(wo_id)

    # Fetch WO + SA + SAHistory + WOLIs in separate queries (no sf_parallel here to keep it simple)
    wo_rows = sf_query_all(f"""
        SELECT Id, WorkOrderNumber, WorkType.Name, Coverage__c, Resolution_Code__c,
               Status, CreatedDate, Facility_ID__c, Facility_Name__c, Trouble_Code__c,
               ServiceTerritory.Name, ServiceTerritoryId,
               Basic_Cost__c, Plus_Cost__c, Premier_Cost__c, RV_Cost__c, Other_Cost__c,
               Tax, GrandTotal, Total_Amount_Invoiced__c,
               Vehicle_Make__c, Vehicle_Model__c, Customer_Name__c, Notes__c
        FROM WorkOrder
        WHERE Id = '{safe_id}'
        LIMIT 1
    """)
    wo = wo_rows[0] if wo_rows else {}

    # Scope check: verify this WO belongs to one of the contractor's facilities
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")
    if wo.get('Facility_ID__c') not in facility_ids:
        raise HTTPException(status_code=403, detail="Access denied: work order not in your facilities")

    sa_rows = sf_query_all(f"""
        SELECT Id, AppointmentNumber, ServiceNote, Status, SchedStartTime,
               ERS_PTA__c, ActualStartTime, ERS_Dispatch_Method__c,
               ERS_Membership_Level_Coverage__c, WorkType.Name
        FROM ServiceAppointment
        WHERE ERS_Work_Order__c = '{safe_id}'
        ORDER BY SchedStartTime ASC
        LIMIT 5
    """)
    sa = sa_rows[0] if sa_rows else {}

    sah_rows = sf_query_all(f"""
        SELECT ServiceAppointmentId, CreatedDate, OldValue, NewValue
        FROM ServiceAppointmentHistory
        WHERE ServiceAppointmentId IN (
            SELECT Id FROM ServiceAppointment WHERE ERS_Work_Order__c = '{safe_id}'
        )
          AND Field = 'Status'
        ORDER BY CreatedDate ASC
        LIMIT 200
    """)

    woli_rows = sf_query_all(f"""
        SELECT Id, LineItemNumber, PricebookEntry.Name, PricebookEntry.ProductCode,
               Quantity, UnitPrice, TotalPrice, Status,
               Basic_Cost__c, Plus_Cost__c, Premier_Cost__c, RV_Cost__c, Other_Cost__c
        FROM WorkOrderLineItem
        WHERE WorkOrderId = '{safe_id}'
    """)

    # Build SA timeline
    sa_timeline = []
    _prev_ts = None
    for h in sah_rows:
        nv = h.get('NewValue', '')
        if nv in _STATUS_TRANSITIONS:
            cur_ts = _parse_dt(h.get('CreatedDate'))
            elapsed = round((_parse_dt(h.get('CreatedDate')) - _prev_ts).total_seconds()) if (_prev_ts and cur_ts) else None
            sa_timeline.append({
                'time': _fmt_et(h.get('CreatedDate')),
                'from': h.get('OldValue') or '',
                'to': nv,
                'elapsed_seconds': elapsed,
            })
            if cur_ts:
                _prev_ts = cur_ts

    # Build woli_items in accounting audit shape.
    # TotalPrice/UnitPrice are $0 for contractor WOs; derive from coverage-tier fields.
    wo_tax = _safe_float(wo.get('Tax')) or 0
    woli_items = []
    for w in woli_rows:
        pbe = w.get('PricebookEntry') or {}
        product_name = pbe.get('Name') or ''
        product_code = pbe.get('ProductCode') or (product_name.split(' - ')[0].strip() if ' - ' in product_name else '')
        basic = _safe_float(w.get('Basic_Cost__c')) or 0
        plus  = _safe_float(w.get('Plus_Cost__c')) or 0
        prem  = _safe_float(w.get('Premier_Cost__c')) or 0
        rv    = _safe_float(w.get('RV_Cost__c')) or 0
        other = _safe_float(w.get('Other_Cost__c')) or 0
        coverage_total = round(basic + plus + prem + rv + other, 2)
        subtotal = _safe_float(w.get('TotalPrice')) or coverage_total
        raw_unit = _safe_float(w.get('UnitPrice')) or 0
        qty = w.get('Quantity') or 1
        unit_price = raw_unit if raw_unit else (round(subtotal / qty, 2) if subtotal and qty else 0)
        woli_items.append({
            'id': w.get('Id') or '',
            'name': w.get('LineItemNumber') or '',
            'product': product_name,
            'code': product_code,
            'quantity': w.get('Quantity'),
            'unit_price': unit_price,
            'subtotal': subtotal,
            'tax': None,
            'grand_total': subtotal,
            'status': w.get('Status') or '',
        })
    total_subtotal = sum(i['subtotal'] for i in woli_items)
    if wo_tax and total_subtotal > 0:
        for item in woli_items:
            tax_share = round(wo_tax * item['subtotal'] / total_subtotal, 2)
            item['tax'] = tax_share
            item['grand_total'] = round(item['subtotal'] + tax_share, 2)

    # woli_rows already has all WOLIs (no PricebookEntryId filter) — use directly
    photos = fetch_photos(wo_id, woli_rows, is_fleet=False)

    territory = wo.get('ServiceTerritory') or {}
    vehicle = ' '.join(filter(None, [wo.get('Vehicle_Make__c'), wo.get('Vehicle_Model__c')]))

    return {
        'wo_id': wo_id,
        'wo_number': wo.get('WorkOrderNumber') or '',
        'territory_name': territory.get('Name') or '',
        'woa_status': None,
        'evidence': {
            'coverage': wo.get('Coverage__c') or '',
            'dispatch_code': wo.get('Trouble_Code__c') or '',
            'resolution_code': wo.get('Resolution_Code__c') or '',
            'facility_id': wo.get('Facility_ID__c') or '',
            'status_quality': 'OK',
            'vehicle_make': wo.get('Vehicle_Make__c') or '',
            'vehicle_model': wo.get('Vehicle_Model__c') or '',
            'wo_type': (wo.get('WorkType') or {}).get('Name') or '',
            'membership_level_coverage': sa.get('ERS_Membership_Level_Coverage__c') or '',
        },
        'wo_pricing': (lambda _bc=(_safe_float(wo.get('Basic_Cost__c')) or 0),
                             _pc=(_safe_float(wo.get('Plus_Cost__c')) or 0),
                             _oc=(_safe_float(wo.get('Other_Cost__c')) or 0),
                             _tax=(_safe_float(wo.get('Tax')) or 0): {
            'tax': _tax or None,
            # GrandTotal on WO = tax only in SF; compute true total from cost components
            'grand_total': round(_bc + _pc + _oc + _tax, 2),
            'basic_cost': _bc or None,
            'plus_cost': _pc or None,
            'other_cost': _oc or None,
            'total_invoiced': round(_bc + _pc + _oc + _tax, 2),
        })(),
        'woli_items': woli_items,
        'sa_timeline': sa_timeline,
        'secondary_sa_timelines': [],
        'sf_urls': {
            'woa': None,
            'wo': f'{_SF_COMMUNITY_BASE}/workorder/{wo_id}',
            'sa': f'{_SF_COMMUNITY_BASE}/serviceappointment/{sa.get("Id")}' if sa.get('Id') else None,
            'facility': None,
        },
        'service_notes': {
            'woa_description': None,
            'woa_internal_notes': None,
            'agent_comments': wo.get('Notes__c') or None,
            'driver_instructions': None,
            'system_notes': None,
            'sa_service_notes': [
                {'sa_number': s.get('AppointmentNumber', ''), 'note': s.get('ServiceNote')}
                for s in sa_rows if s.get('ServiceNote')
            ],
        },
        'photos': photos,
        'recommendation': None,
        'cache_status': 'fresh',
    }


# ── GET /api/contractor/pending-woas ─────────────────────────────────────────

@router.get("/api/contractor/pending-woas")
def contractor_pending_woas(
    request: Request,
    start_date: str = Query(default=None, description="YYYY-MM-DD (default: 90 days ago)"),
    end_date: str = Query(default=None, description="YYYY-MM-DD (default: today)"),
):
    """Pending (Status=New) WOAs for contractor facilities within date range."""
    facility_ids = _require_contractor_facilities(request)
    f_clause = _facility_in_clause(facility_ids)

    now = datetime.now(timezone.utc)
    if not start_date:
        start_date = now.strftime("%Y-%m-01")
    if not end_date:
        end_date = now.strftime("%Y-%m-%d")

    try:
        datetime.strptime(start_date, "%Y-%m-%d")
        datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD")

    soql = f"""
        SELECT Id, Name, Work_Order__c, Work_Order__r.WorkOrderNumber,
               Work_Order__r.Facility_ID__c, Work_Order__r.ServiceTerritory.Name,
               Work_Order__r.Type__c, Work_Order__r.CreatedDate,
               Status__c, CreatedDate
        FROM ERS_Work_Order_Adjustment__c
        WHERE Work_Order__r.Facility_ID__c IN ({f_clause})
          AND Status__c = 'New'
          AND CreatedDate >= {start_date}T00:00:00Z
          AND CreatedDate <= {end_date}T23:59:59Z
        ORDER BY CreatedDate DESC
        LIMIT 500
    """
    rows = sf_query_all(soql)

    items = [
        {
            "woa_id": r.get("Id"),
            "woa_name": r.get("Name"),
            "wo_id": r.get("Work_Order__c"),
            "wo_number": (r.get("Work_Order__r") or {}).get("WorkOrderNumber") or "",
            "facility": (r.get("Work_Order__r") or {}).get("Facility_ID__c") or "",
            "territory": ((r.get("Work_Order__r") or {}).get("ServiceTerritory") or {}).get("Name") or "",
            "call_type": (r.get("Work_Order__r") or {}).get("Type__c") or "",
            "created_date": r.get("CreatedDate") or "",
        }
        for r in rows
    ]

    # Stamp has_photos so the WOA tab shows the camera icon like Work Orders / Recommendations
    photo_ids = _fetch_photo_wo_ids([i["wo_id"] for i in items if i.get("wo_id")])
    for i in items:
        i["has_photos"] = i.get("wo_id", "") in photo_ids

    return {"items": items, "total": len(items)}


# ── Driver Collection ─────────────────────────────────────────────────────────
#
# Completed calls where the tech should have collected payment from the member.
# A WorkOrder may match more than one reason → one emitted row per matched reason.
# Reasons are discriminated by Resolution_Code__c (NOT Trouble_Code__c).

_DC_BATTERY_CODES = ("G306", "G307", "G308")
_DC_TIREJECT_CODE = "G103"
_DC_FUEL_CODES = ("G401", "G402")

_DC_REASON_TOW = "Tow Overmiles"
_DC_REASON_BATTERY = "Battery Sold"
_DC_REASON_TIREJECT = "TireJECT Install"
_DC_REASON_FUEL = "Fuel Delivery – Basic Member"
_DC_REASON_PRIVATE = "Private Service"

_DC_REASON_TO_CALL_TYPE = {
    _DC_REASON_TOW:      "Tow Pick-Up",
    _DC_REASON_BATTERY:  "Battery",
    _DC_REASON_TIREJECT: "Tire",
    _DC_REASON_FUEL:     "Fuel Delivery",
    _DC_REASON_PRIVATE:  "Private Service",
}

# Valid (wo_id, reason) audit reasons the POST endpoint will accept.
_DC_VALID_REASONS = {
    _DC_REASON_TOW, _DC_REASON_BATTERY, _DC_REASON_TIREJECT, _DC_REASON_FUEL,
    _DC_REASON_PRIVATE,
}


def _dc_is_basic(wo: dict) -> bool:
    """Basic coverage if Entitlement_Master__r.Name='Basic Coverage' OR Coverage__c='B'."""
    em_name = ((wo.get("Entitlement_Master__r") or {}).get("Name") or "").strip()
    coverage = (wo.get("Coverage__c") or "").strip()
    return em_name == "Basic Coverage" or coverage == "B"


def _dc_matched_reasons(wo: dict) -> list[tuple[str, str]]:
    """Return list of (reason, amount) the WO matches. Amounts are literal strings."""
    out = []
    res = (wo.get("Resolution_Code__c") or "").strip()
    over_mileage = _safe_float(wo.get("ERS_Est_Tow_Over_Mileage_Cost__c")) or 0

    if (wo.get("Type__c") or "").strip() == "Private Service":
        out.append((_DC_REASON_PRIVATE, "Private Service"))
        return out  # private service: only this reason, skip other checks
    if wo.get("Tow_Call__c") and over_mileage > 0:
        out.append((_DC_REASON_TOW, f"${over_mileage:,.2f}"))
    if res in _DC_BATTERY_CODES:
        out.append((_DC_REASON_BATTERY, "Verify Battery Sold"))
    if res == _DC_TIREJECT_CODE:
        out.append((_DC_REASON_TIREJECT, "$34.99"))
    if res in _DC_FUEL_CODES and _dc_is_basic(wo):
        out.append((_DC_REASON_FUEL, "2-3 Gallons of Gas"))
    return out


@router.get("/api/contractor/driver-collection")
def contractor_driver_collection(
    request: Request,
    start_date: str = Query(default=None, description="YYYY-MM-DD (default: month start)"),
    end_date: str = Query(default=None, description="YYYY-MM-DD (default: today)"),
):
    """Completed calls where the tech should have collected payment from the member.

    Scoped to the contractor's facilities. Emits one row per matched collection
    reason; the audit-verified flag is merged in per logged-in contractor.
    """
    facility_ids = _require_contractor_facilities(request)
    f_clause = _facility_in_clause(facility_ids)
    username = get_request_username(request)

    now = datetime.now(timezone.utc)
    if not start_date:
        start_date = now.strftime("%Y-%m-01")
    if not end_date:
        end_date = now.strftime("%Y-%m-%d")

    try:
        datetime.strptime(start_date, "%Y-%m-%d")
        datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD")

    soql = f"""
        SELECT Id, WorkOrderNumber, Service_Resource__r.Name,
               Type__c, Dispatch_Code__c, Resolution_Code__c,
               Tow_Call__c, ERS_Est_Tow_Over_Mileage_Cost__c,
               Entitlement_Master__r.Name, Coverage__c, CreatedDate
        FROM WorkOrder
        WHERE Facility_ID__c IN ({f_clause})
          AND Status IN ('Completed', 'Closed')
          AND (
                Resolution_Code__c IN ('G306','G307','G308','G103','G401','G402')
                OR (Tow_Call__c = true AND ERS_Est_Tow_Over_Mileage_Cost__c > 0)
                OR Type__c = 'Private Service'
              )
          AND CreatedDate >= {start_date}T00:00:00Z
          AND CreatedDate <= {end_date}T23:59:59Z
        ORDER BY CreatedDate DESC
        LIMIT 5000
    """
    rows = sf_query_all(soql)

    verified = _dc_repo.get_verified_keys(username) if username else set()

    items = []
    for r in rows:
        # Exclude cancelled (X*) and unable/NSR (R*) calls. Filter on the
        # returned picklist value in Python — SOQL value≠label makes a
        # LIKE 'X%' WHERE clause unreliable.
        res_code = (r.get("Resolution_Code__c") or "").strip().upper()
        if res_code.startswith("X") or res_code.startswith("R"):
            continue
        coverage_label = (
            (r.get("Entitlement_Master__r") or {}).get("Name")
            or r.get("Coverage__c") or ""
        )
        wo_id = r.get("Id") or ""
        for reason, amount in _dc_matched_reasons(r):
            items.append({
                "wo_id": wo_id,
                "wo_number": r.get("WorkOrderNumber") or "",
                "service_resource_name": (r.get("Service_Resource__r") or {}).get("Name") or "",
                "reason": reason,
                "amount": amount,
                "call_type": _DC_REASON_TO_CALL_TYPE.get(reason, r.get("Type__c") or ""),
                "dispatch_code": r.get("Dispatch_Code__c") or "",
                "resolution_code": r.get("Resolution_Code__c") or "",
                "coverage": coverage_label,
                "created_date": r.get("CreatedDate") or "",
                "audit_verified": (wo_id, reason) in verified,
            })

    # Stamp has_photos so the Driver Collection tab shows the camera icon too
    photo_ids = _fetch_photo_wo_ids(list({i["wo_id"] for i in items if i.get("wo_id")}))
    for i in items:
        i["has_photos"] = i.get("wo_id", "") in photo_ids

    return {"items": items, "total": len(items)}


@router.post("/api/contractor/driver-collection/audit")
def contractor_driver_collection_audit(request: Request, body: dict):
    """Persist the contractor's verification of a (wo_id, reason) collection row."""
    facility_ids = _require_contractor_facilities(request)  # auth + role gate
    username = get_request_username(request)
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")

    wo_id = (body.get("wo_id") or "").strip()
    reason = (body.get("reason") or "").strip()
    verified = bool(body.get("verified"))

    if not wo_id or reason not in _DC_VALID_REASONS:
        raise HTTPException(status_code=400, detail="wo_id and a valid reason are required")

    _dc_repo.set_verified(username, wo_id, reason, verified)
    return {"ok": True}
