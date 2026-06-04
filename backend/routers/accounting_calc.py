"""Accounting — shared calculation helpers (recommendation engine, formatters, utils)."""

import logging
import re
import re as _re
import threading
import requests as _requests
from datetime import timezone as _tz
from zoneinfo import ZoneInfo
from utils import parse_dt as _parse_dt

log = logging.getLogger('accounting')
_ET = ZoneInfo('America/New_York')
_SF_BASE   = 'https://aaawcny.lightning.force.com'
_TOW_CODES = {'TW', 'TB', 'TT', 'TU', 'TM', 'EM'}
_TIME_CODES = {'E1', 'E2', 'MI', 'Z8'}
_FLAT_CODES = {'BA', 'BC', 'PC', 'HO', 'Z5', 'Z7', 'TJ', 'Z0', 'Z1', 'Z3'}  # PG handled separately

_DEFAULT_AUDIT_PROMPT = (
    "You are a senior accounting investigator at AAA Western & Central NY roadside assistance, "
    "reading a Work Order Adjustment (WOA) — a garage disputing what they were paid. "
    "Your job: read the data and surface FACTS, red flags, and anomalies. "
    "Do NOT make a pay/deny verdict — that is handled separately by the rule engine. "
    "\n\nALWAYS spell out product codes: ER=Enroute Miles, TW=Tow Miles, E1=Extrication, BA=Base Rate, "
    "TL=Tolls/Parking, MH=Medium/Heavy Duty, MI=Wait Time. ALWAYS include units (miles, minutes, dollars). "
    "\n\nKEY FIELDS: "
    "product = the specific service claimed. "
    "woa_description = the garage's own explanation (read carefully — is it consistent with GPS/timing data?). "
    "internal_notes = accounting team notes already on file. "
    "product_not_on_wo = true means the claimed product was not on the original Work Order — flag it. "
    "\n\nFraud signals to watch: GPS-recorded miles much lower than claimed; En Route and On Location timestamps "
    "seconds apart (driver never actually drove to the scene); claimed minutes >> on-scene time; "
    "same member called multiple garages same day; woa_description mentions discrepancies or flags the driver. "
    "\n\nMH RULE (Medium/Heavy Duty): Follow this decision tree — NEVER tell the accountant to look up or verify weight. "
    "Threshold: ≥10,000 lbs GVWR OR vehicle_group in (MD, HD, DW). "
    "Step 1: If vehicle.weight ≥10,000 lbs → state 'Vehicle qualifies for MH: [weight] lbs ≥ 10,000'. Done. "
    "Step 2: If vehicle.group is MD/HD/DW → state 'Vehicle qualifies for MH: group [group]'. Done. "
    "Step 3: If vehicle.weight is null/0 → compute estimated_gvw_lbs from vehicle.make + vehicle.model. "
    "  Use your knowledge of published GVWR specs (Ram 2500=10000, F-250=10000, F-350=14000, Ram 3500=14000, semi=80000, F-150=7050). "
    "  If estimated_gvw_lbs ≥10,000 → state 'Vehicle qualifies for MH based on make/model: [Make Model] has a GVWR of ~[N] lbs ≥ 10,000'. "
    "  If estimated_gvw_lbs <10,000 → state 'Vehicle does not qualify: [Make Model] GVWR ~[N] lbs < 10,000'. "
    "  Only if make+model is completely unknown → note 'SF weight field is empty and make/model is unknown'. "
    "NEVER say 'verify weight' or 'check axles' when you can determine the answer from make/model. "
    "\n\nRespond ONLY with valid JSON — no markdown fences, no commentary outside the JSON: "
    '{"headline":"One sentence: what service was claimed and the key finding",'
    '"story":"3-5 sentences for the accountant: what service was done, what GPS/timing data shows, key facts to know",'
    '"fraud_signals":["red flag if found — omit array entirely if none"],'
    '"anomalies":["yellow flag / unusual finding — omit if none"],'
    '"what_to_do":["specific action for the accountant, e.g. Verify GPS trace in SF, Call garage about X"],'
    '"ask_garage":["specific question to ask the garage if something is unclear — omit if everything is consistent"],'
    '"estimated_gvw_lbs":null}'
    "\n\nestimated_gvw_lbs: integer GVWR in lbs based on vehicle_make + vehicle_model in the data. "
    "Use published specs (e.g. Ford F-350 = 14000, Ram 2500 = 10000, semi = 80000, F-150 = 7050). "
    "Return null for passenger cars or if make/model is unknown."
)


# ── Heavy Duty Vehicle approved list cache ───────────────────────────────────
# Loaded once from Postgres. Never expires on its own — call invalidate_hdv_cache()
# whenever the ref_heavy_duty_vehicles table is modified (add/edit/delete/import).

_hdv_cache: list[dict] | None = None   # None = not yet loaded
_hdv_cache_lock = threading.Lock()


def _load_hdv_cache() -> list[dict]:
    """Load approved vehicles from Postgres into the module-level cache."""
    try:
        import db_adapter
        with db_adapter.reader() as db:
            db.execute("SELECT make, model FROM ref_heavy_duty_vehicles WHERE approved = true ORDER BY make, model")
            rows = db.fetchall()
        log.info("[hdv_cache] loaded %d approved vehicles", len(rows))
        return rows
    except Exception as e:
        log.warning("[hdv_cache] load failed: %s", e)
        return []


def _get_hdv_vehicles() -> list[dict]:
    """Return the cached approved vehicle list, loading it on first call."""
    global _hdv_cache
    if _hdv_cache is None:
        with _hdv_cache_lock:
            if _hdv_cache is None:
                _hdv_cache = _load_hdv_cache()
    return _hdv_cache


def invalidate_hdv_cache() -> None:
    """Clear the cache so the next audit reloads from Postgres."""
    global _hdv_cache
    with _hdv_cache_lock:
        _hdv_cache = None


# ── Fuel Reimbursement limits cache ─────────────────────────────────────────
# Loaded once from Postgres. Call invalidate_fuel_cache() after table edits.

_fuel_cache: dict | None = None   # None = not yet loaded
_fuel_cache_lock = threading.Lock()


def _load_fuel_cache() -> dict:
    """Load fuel reimbursement limits from Postgres. Returns {dispatch_code: amount_usd}."""
    try:
        import db_adapter
        with db_adapter.reader() as db:
            db.execute("SELECT dispatch_code, amount_usd FROM ref_fuel_reimbursement ORDER BY dispatch_code")
            rows = db.fetchall()
        result = {r['dispatch_code']: float(r['amount_usd']) for r in rows}
        log.info("[fuel_cache] loaded %d fuel limits", len(result))
        return result
    except Exception as e:
        log.warning("[fuel_cache] load failed: %s", e)
        return {}


def _get_fuel_limits() -> dict:
    """Return cached fuel limits dict, loading on first call."""
    global _fuel_cache
    if _fuel_cache is None:
        with _fuel_cache_lock:
            if _fuel_cache is None:
                _fuel_cache = _load_fuel_cache()
    return _fuel_cache


def invalidate_fuel_cache() -> None:
    """Clear the fuel limits cache so the next call reloads from Postgres."""
    global _fuel_cache
    with _fuel_cache_lock:
        _fuel_cache = None
    log.info("[hdv_cache] invalidated")


def _norm_vehicle(s: str) -> str:
    """Normalize vehicle make/model string: lowercase, strip non-alphanumeric."""
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def _match_hdv_approved(make: str, model: str) -> tuple[str, str]:
    """
    Check whether make+model appears on the approved heavy duty vehicle list.
    Returns (confidence, description) where confidence is:
      'exact'    — normalized make+model matched an entry exactly
      'fuzzy'    — partial/prefix match (e.g. "F-350 XLT" ~ "F-350")
      'no_match' — not found on the list
      'unavailable' — list could not be loaded
    """
    vehicles = _get_hdv_vehicles()
    if not vehicles:
        return 'unavailable', 'Approved vehicle list could not be loaded'

    nm = _norm_vehicle(make)
    nmod = _norm_vehicle(model)

    # Pass 1 — exact match on normalized make AND model
    for v in vehicles:
        if _norm_vehicle(v['make']) == nm and _norm_vehicle(v['model']) == nmod:
            return 'exact', f"{v['make']} {v['model']}"

    # Pass 2 — fuzzy: make matches AND model prefix matches in either direction
    for v in vehicles:
        vm = _norm_vehicle(v['make'])
        vmod = _norm_vehicle(v['model'])
        make_ok = (not nm or not vm or nm == vm
                   or nm.startswith(vm) or vm.startswith(nm))
        model_ok = (nmod == vmod
                    or nmod.startswith(vmod)
                    or vmod.startswith(nmod))
        if make_ok and model_ok and (nm or nmod):
            return 'fuzzy', f"{v['make']} {v['model']}"

    return 'no_match', f"{make or '?'} {model or '?'} not on approved list"


def _to_et(dt_str):
    dt = _parse_dt(dt_str)
    if not dt:
        return None
    return dt.replace(tzinfo=_tz.utc) if dt.tzinfo is None else dt


def _fmt_et(dt_str):
    dt = _to_et(dt_str)
    return dt.astimezone(_ET).strftime('%m/%d/%Y %I:%M:%S %p') if dt else None


def _fmt_date_et(dt_str):
    dt = _to_et(dt_str)
    return dt.astimezone(_ET).strftime('%m/%d/%Y') if dt else None


def _safe_float(val):
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _google_distance(api_key, origin_lat, origin_lon, dest_lat, dest_lon, origin_str=None):
    if not api_key or None in (dest_lat, dest_lon):
        return None
    if origin_str:
        origin_param = origin_str
    elif origin_lat is not None and origin_lon is not None:
        origin_param = f"{origin_lat},{origin_lon}"
    else:
        return None
    try:
        resp = _requests.get(
            "https://maps.googleapis.com/maps/api/distancematrix/json",
            params={
                "origins": origin_param,
                "destinations": f"{dest_lat},{dest_lon}",
                "key": api_key,
                "units": "imperial",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        element = data.get("rows", [{}])[0].get("elements", [{}])[0]
        if element.get("status") == "OK":
            meters = element["distance"]["value"]
            return round(meters / 1609.344, 2)
    except Exception as e:
        log.warning('Google Distance Matrix failed: %s', e)
    return None


def _calc_recommendation(code, requested, paid, sf_er, sf_est_er, sf_tow, sf_est_tow,
                         on_loc_minutes=None, vehicle_weight=None, vehicle_group=None,
                         all_wolis=None, long_tow_used=False,
                         vehicle_make=None, vehicle_model=None,
                         already_paid_mh=False,
                         dispatch_code=None, coverage_level=None):
    """Pure math recommendation. Returns (rec, step_by_step_reason, verification)."""
    NAMES = {'ER': 'Enroute Miles', 'TW': 'Tow Miles', 'TB': 'Tow Miles Basic',
             'TT': 'Tow Miles Plus (5-30mi)', 'TU': 'Tow Miles Plus (30-100mi)',
             'TM': 'Tow Miles Premier', 'EM': 'Extra Tow Mileage',
             'E1': 'Extrication (1st Truck)', 'E2': 'Extrication (2nd Truck)',
             'Z8': 'RAP Extrication', 'MH': 'Medium/Heavy Duty', 'TL': 'Tolls/Parking',
             'MI': 'Miscellaneous/Wait Time', 'BA': 'Base Rate', 'BC': 'Basic Cost',
             'PC': 'Plus Cost', 'HO': 'Holiday Bonus', 'PG': 'Plus/Premier Fuel',
             'Z5': 'RAP Fuel Delivery', 'Z7': 'RAP Lockout', 'TJ': 'TireJect',
             'Z0': 'RAP Gone on Arrival', 'Z1': 'RAP Flat Tire', 'Z3': 'RAP Battery Boost'}
    TOW_CODES  = _TOW_CODES
    TIME_CODES = _TIME_CODES
    FLAT_CODES = _FLAT_CODES
    L = []
    v = {}
    prod_name = NAMES.get(code, 'Unknown') if code else 'No product on WO'
    L.append(f'PRODUCT: {code or "—"} — {prod_name}')
    L.append(f'GARAGE REQUESTED: {requested}')
    L.append(f'SF BILLED (WOLI): {paid if paid else "Not on WO"}')

    if requested is None:
        L.append('→ No quantity → REVIEW'); return 'review', '\n'.join(L), {}
    if requested < 0:
        L.append(f'→ Negative qty = credit/reduction → REVIEW'); return 'review', '\n'.join(L), {}
    if requested == 0:
        L.append('→ Zero qty → APPROVE'); return 'approve', '\n'.join(L), {}

    if not code:
        L.append(f'\nPRODUCT NOT ON WORK ORDER:')
        L.append(f'  The garage is claiming a product/service that does not appear as a')
        L.append(f'  line item on the original Work Order (e.g. E1 winch time on a WO')
        L.append(f'  that only has enroute miles and base rate).')
        L.append(f'  Auditor: verify in Salesforce what service the garage actually performed')
        L.append(f'  and whether this charge is legitimate for that call.')
        L.append(f'\n→ Manual review required — no matching WOLI to verify against.')
        return 'review', '\n'.join(L), {}

    if code == 'ER':
        if paid and paid > 0 and abs(requested - paid) < 0.01:
            L.append(f'\n→ Requesting same as billed ({paid} mi). No change needed → APPROVE')
            return 'approve', '\n'.join(L), {'sf_billed': paid, 'unit': 'mi'}
        L.append(f'\nDATA FROM SF:')
        L.append(f'  SF Google Estimate: {sf_est_er or "N/A"} mi')
        L.append(f'  SF Recorded Actual: {sf_er or "N/A"} mi')
        baseline = sf_est_er if sf_est_er and sf_est_er > 0 else sf_er if sf_er and sf_er > 0 else None
        src = 'SF Google Estimate' if sf_est_er and sf_est_er > 0 else 'SF Recorded'
        L.append(f'  Baseline: {src} = {baseline or "none"}')
        v = {'sf_google_estimate': sf_est_er, 'sf_recorded': sf_er, 'sf_billed': paid, 'unit': 'mi'}
    elif code in TOW_CODES:
        if paid and paid > 0 and abs(requested - paid) < 0.01:
            L.append(f'\n→ Requesting same as billed ({paid} mi). No change needed → APPROVE')
            return 'approve', '\n'.join(L), {'sf_billed': paid, 'unit': 'mi'}
        L.append(f'\nDATA FROM SF (tow distance):')
        L.append(f'  SF Google Tow Estimate: {sf_est_tow or "N/A"} mi')
        L.append(f'  SF Recorded Tow: {sf_tow or "N/A"} mi')
        baseline = sf_est_tow if sf_est_tow and sf_est_tow > 0 else sf_tow if sf_tow and sf_tow > 0 else None
        src = 'SF Google Estimate' if sf_est_tow and sf_est_tow > 0 else 'SF Recorded'
        L.append(f'  Baseline: {src} = {baseline or "none"}')
        v = {'sf_google_estimate': sf_est_tow, 'sf_recorded': sf_tow, 'sf_billed': paid, 'unit': 'mi'}
    elif code in TIME_CODES:
        L.append(f'\nDATA FROM SF:')
        L.append(f'  On-Location Time: {on_loc_minutes or "N/A"} min')
        L.append(f'  (Completed timestamp - On Location timestamp)')
        v = {'on_location_min': on_loc_minutes, 'sf_billed': paid, 'unit': 'min'}
        if paid and paid > 0 and abs(requested - paid) < 0.5:
            L.append(f'\n→ Requesting same as billed ({paid} min). No change needed.')
            return 'approve', '\n'.join(L), v
        if on_loc_minutes and on_loc_minutes > 0:
            ratio = requested / on_loc_minutes
            L.append(f'\nCALCULATION:')
            L.append(f'  {requested} ÷ {on_loc_minutes} = {ratio:.0%}')
            L.append(f'  Threshold: ≤120% = Approve')
            if ratio <= 1.2:
                L.append(f'→ {ratio:.0%} ≤ 120% → APPROVE'); return 'approve', '\n'.join(L), v
            L.append(f'→ {ratio:.0%} > 120% → REVIEW'); return 'review', '\n'.join(L), v
        L.append(f'→ No on-location time available → REVIEW'); return 'review', '\n'.join(L), v
    elif code == 'MI':
        L.append(f'\nDATA FROM SF:')
        L.append(f'  On-Location Time: {on_loc_minutes or "N/A"} min')
        v = {'on_location_min': on_loc_minutes, 'sf_billed': paid, 'unit': 'min'}
        if paid and paid > 0 and abs(requested - paid) < 0.5:
            L.append(f'\n→ Requesting same as billed ({paid} min). No change needed.')
            return 'approve', '\n'.join(L), v
        if on_loc_minutes and on_loc_minutes > 0:
            L.append(f'\nCALCULATION:')
            L.append(f'  On-scene {on_loc_minutes} min vs claimed {requested} min')
            if on_loc_minutes >= requested * 0.8:
                L.append(f'→ On-scene supports claim → APPROVE'); return 'approve', '\n'.join(L), v
            L.append(f'→ On-scene shorter than claimed → REVIEW'); return 'review', '\n'.join(L), v
        L.append(f'→ No on-location time → REVIEW'); return 'review', '\n'.join(L), v
    elif code == 'MH':
        L.append(f'\nDATA FROM SF:')
        L.append(f'  Vehicle: {vehicle_make or "?"} {vehicle_model or "?"}')
        L.append(f'  Weight (SF): {vehicle_weight or "not populated"} lbs')
        L.append(f'  Group (SF): {vehicle_group or "N/A"}')
        v = {
            'vehicle_make': vehicle_make,
            'vehicle_model': vehicle_model,
            'vehicle_weight': vehicle_weight,
            'vehicle_group': vehicle_group,
        }

        # Rule 1 — quantity must be 1
        if requested is not None and requested != 1:
            L.append(f'  WOA Quantity: {requested} (expected 1)')
            L.append(f'\n→ Quantity is {requested}, not 1 → REVIEW')
            return 'review', '\n'.join(L), v

        # Rule 2 — WO must be a tow call
        _wolis_for_tow = all_wolis or []
        _has_tow = any(w.get('code') in TOW_CODES for w in _wolis_for_tow)
        if not _has_tow:
            v['note'] = 'Work Order is Not a Tow Call'
            L.append(f'\n→ No tow line item on WO → REVIEW')
            return 'review', '\n'.join(L), v

        # Rule 3 — WO must not already have a paid MH WOLI (audit context: explicit flag)
        if already_paid_mh:
            v['note'] = 'WOLI for MH-Medium/Heavy Duty already exists on this work order.'
            L.append(f'\n→ WO already contains a paid MH line item → REJECT')
            return 'reject', '\n'.join(L), v

        # Rule 4 — check WO line items for existing MH payment
        _has_existing_mh = any(
            w.get('code') == 'MH' and (w.get('quantity') or 0) > 0
            for w in (all_wolis or [])
        )
        if _has_existing_mh:
            v['note'] = 'WOLI for MH-Medium/Heavy Duty already exists on this work order.'
            L.append(f'\n→ WO already has a paid MH line item → REVIEW')
            return 'review', '\n'.join(L), v

        # Rule 5 — check approved heavy-duty vehicle list
        confidence, matched_desc = _match_hdv_approved(vehicle_make or '', vehicle_model or '')
        L.append(f'  Approved list: {confidence} — {matched_desc}')

        if confidence == 'exact':
            L.append(f'\n→ Vehicle on approved list (exact match) → APPROVE')
            return 'approve', '\n'.join(L), v
        elif confidence == 'fuzzy':
            L.append(f'\n→ Fuzzy match only — system cannot confidently confirm → REVIEW')
            return 'review', '\n'.join(L), v
        elif confidence == 'unavailable':
            L.append(f'\n→ Approved list unavailable — cannot verify → REVIEW')
            return 'review', '\n'.join(L), v
        else:  # no_match
            L.append(f'\n→ Vehicle not on approved heavy duty list → REJECT')
            return 'reject', '\n'.join(L), v
    elif code == 'TL':
        wolis = all_wolis or []
        has_tow = any(w.get('code') in TOW_CODES for w in wolis)
        L.append(f'\nTOLLS/PARKING:')
        L.append(f'  No receipts in SF — cannot verify amount automatically.')
        L.append(f'  WO has tow: {"YES" if has_tow else "NO"}')
        if has_tow:
            L.append(f'  Tow present → tolls are plausible if route crosses toll road.')
        else:
            L.append(f'  No tow on WO → tolls less likely (unless parking/airport).')
        if paid and paid > 0:
            L.append(f'  Currently billed: ${paid}')
            if abs(requested - paid) < 0.01:
                L.append(f'\n→ Requesting same as billed. No change needed.')
                return 'approve', '\n'.join(L), {'sf_billed': paid, 'unit': '$'}
        if has_tow and requested and requested <= 20:
            L.append(f'\n→ Small toll (${requested}) with tow on WO — plausible. Still request receipt.')
            return 'approve', '\n'.join(L), {'sf_billed': paid, 'unit': '$'}
        L.append(f'\n→ Request receipt from garage to verify ${requested}.')
        return 'review', '\n'.join(L), {'sf_billed': paid, 'unit': '$'}
    elif code == 'PG':
        fuel_limits = _get_fuel_limits()
        v = {'dispatch_code': dispatch_code, 'coverage_level': coverage_level}
        L.append(f'\nPLUS/PREMIER FUEL:')
        L.append(f'  Dispatch Code: {dispatch_code or "N/A"}')
        L.append(f'  Coverage Level: {coverage_level or "blank (RAP)"}')
        L.append(f'  Requested: ${requested}')

        # Rule 1 — dispatch code must be L402 (Gas) or L403 (Diesel)
        if not dispatch_code or dispatch_code not in ('L402', 'L403'):
            v['note'] = f'Dispatch Code ({dispatch_code or "N/A"}) is not L402 or L403.'
            L.append(f'\n→ Dispatch Code not L402/L403 → REVIEW')
            return 'review', '\n'.join(L), v

        # Rule 2 — coverage level must be Plus, Plus RV, Premier, Premier RV, or blank (RAP)
        _approved_coverage = {'PLUS', 'PREMIER', 'PLRV', 'PMRV'}
        _cov_norm = (coverage_level or '').strip().upper()
        if _cov_norm and _cov_norm not in _approved_coverage:
            v['note'] = f'Coverage Level ({coverage_level}) is not eligible for Plus/Premier Fuel reimbursement.'
            L.append(f'\n→ Coverage {coverage_level} not eligible → REVIEW')
            return 'review', '\n'.join(L), v

        # Rule 3 — no existing PG WOLI on WO with payment
        _has_existing_pg = any(
            w.get('code') == 'PG' and (w.get('quantity') or 0) > 0
            for w in (all_wolis or [])
        )
        if _has_existing_pg:
            v['note'] = 'A WOLI for PG – Plus/Premier Fuel already exists on this work order.'
            L.append(f'\n→ Existing PG line item found → REVIEW')
            return 'review', '\n'.join(L), v

        # Rule 4 — quantity must not exceed max allowance
        max_amount = fuel_limits.get(dispatch_code)
        if max_amount is None:
            v['note'] = f'No fuel limit configured for dispatch code {dispatch_code}.'
            L.append(f'\n→ No fuel limit configured for {dispatch_code} → REVIEW')
            return 'review', '\n'.join(L), v
        fuel_type = 'Gas' if dispatch_code == 'L402' else 'Diesel'
        L.append(f'  Max allowance ({fuel_type}, {dispatch_code}): ${max_amount}')
        if requested > max_amount:
            v['note'] = f'Requested ${requested:.2f} exceeds the ${max_amount:.2f} max allowance for {fuel_type} ({dispatch_code}).'
            L.append(f'\n→ ${requested} > max ${max_amount} → REVIEW')
            return 'review', '\n'.join(L), v

        L.append(f'\n→ All criteria met: L402/L403, eligible coverage, no duplicate, ${requested} ≤ ${max_amount} → APPROVE')
        return 'approve', '\n'.join(L), v
    elif code in FLAT_CODES:
        if paid and paid > 0 and abs(requested - paid) < 0.01:
            L.append(f'\nFLAT FEE / SERVICE EVENT:')
            L.append(f'  {prod_name} — requesting same as billed ({paid}). No change needed.')
            L.append(f'\n→ Requesting same as billed. No financial impact → APPROVE')
            return 'approve', '\n'.join(L), {'sf_billed': paid}
        L.append(f'\nFLAT FEE / SERVICE EVENT:')
        L.append(f'  {prod_name} — verify the service was performed.')
        L.append(f'→ Flat-fee products (BA/BC/PC/HO/RAP) always require policy review.')
        return 'review', '\n'.join(L), {'sf_billed': paid}
    else:
        baseline = sf_est_er if sf_est_er and sf_est_er > 0 else sf_er if sf_er and sf_er > 0 else None
        src = 'SF data'
        L.append(f'\nDATA: SF={baseline or "N/A"}')
        v = {'sf_google_estimate': sf_est_er, 'sf_recorded': sf_er, 'sf_billed': paid}

    # Mileage comparison (ER, TW, unknown)
    # WOA.Quantity__c = total the garage claims (NOT additional on top of billed).
    # Compare requested directly against SF baseline.
    L.append(f'\nCALCULATION:')
    if baseline is None or baseline == 0:
        L.append(f'\n→ No SF data to compare against. Cannot verify automatically.')
        return 'review', '\n'.join(L), v

    true_total = requested  # total claimed, not paid + requested
    ratio = true_total / baseline
    pct_over = round((ratio - 1) * 100)

    delta_qty = requested - (paid or 0)
    L.append(f'  Garage claims: {requested} mi  |  SF baseline ({src}): {baseline} mi')
    if paid and paid > 0:
        L.append(f'  Currently billed: {paid} mi  |  Net change if approved: {delta_qty:+.2f} mi')
    L.append(f'  {requested} ÷ {baseline} = {ratio:.0%}')

    approve_threshold = 1.5 if (long_tow_used and code in TOW_CODES) else 1.3
    if long_tow_used and code in TOW_CODES:
        L.append(f'  Long Tow Used → approval threshold raised to 150%')

    if ratio <= 1.0:
        L.append(f'\n→ Total within SF calculated distance. Reasonable.')
    elif ratio <= approve_threshold:
        L.append(f'\n→ {pct_over}% over SF baseline. Within {"long tow " if long_tow_used else ""}normal range.')
    elif ratio <= 1.5:
        L.append(f'\n→ {pct_over}% over SF baseline. Slightly high — verify the route.')
    elif ratio <= 2.0:
        L.append(f'\n→ {ratio:.1f}x SF baseline ({pct_over}% over). Needs verification.')
    else:
        L.append(f'\n→ {ratio:.1f}x SF baseline. Significant discrepancy — investigate.')

    if ratio <= approve_threshold:
        return 'approve', '\n'.join(L), v
    return 'review', '\n'.join(L), v


# ── Keyword helpers (moved here to avoid circular imports) ────────────────────

_DETOUR_KW = {'accident', 'construction', 'detour', 'rerouted', 'road closure', 'closed road',
              'traffic', 'blocked', 'highway closed', 'road work'}
_WAIT_KW   = {'wait time', 'waiting', 'member held', 'held up', 'locked out', 'keys', 'on scene',
              'customer not ready', 'delay'}


def _scan_keywords(text: str) -> list[str]:
    if not text:
        return []
    lower = text.lower()
    return sorted({kw for kw in (_DETOUR_KW | _WAIT_KW) if kw in lower})


def _parse_claimed_minutes(text: str):
    """Extract claimed time from description: '32 minutes', '1 hour', '1.5 hrs'."""
    if not text:
        return None
    m = _re.search(r'(\d+(?:\.\d+)?)\s*(hour|hr|minute|min)', text.lower())
    if not m:
        return None
    val = float(m.group(1))
    return round(val * 60) if m.group(2) in ('hour', 'hr') else round(val)


# ── Google API helpers ────────────────────────────────────────────────────────

def _google_toll_check(api_key: str, origin_lat, origin_lon, dest_lat, dest_lon) -> dict:
    """Check for tolls via Google Routes API v2. Returns structured status dict."""
    if not api_key:
        return {'status': 'no_key'}
    if None in (origin_lat, origin_lon, dest_lat, dest_lon):
        return {'status': 'no_coords'}
    try:
        r = _requests.post(
            'https://routes.googleapis.com/directions/v2:computeRoutes',
            headers={
                'X-Goog-Api-Key': api_key,
                'X-Goog-FieldMask': 'routes.travelAdvisory',
                'Content-Type': 'application/json',
            },
            json={
                'origin': {'location': {'latLng': {'latitude': origin_lat, 'longitude': origin_lon}}},
                'destination': {'location': {'latLng': {'latitude': dest_lat, 'longitude': dest_lon}}},
                'travelMode': 'DRIVE',
                'extraComputations': ['TOLLS'],
            },
            timeout=8,
        )
        if r.status_code == 403:
            err = r.json().get('error', {})
            if err.get('reason') == 'API_KEY_SERVICE_BLOCKED' or 'blocked' in err.get('message', '').lower():
                return {'status': 'api_disabled', 'api': 'routes.googleapis.com'}
        r.raise_for_status()
        routes = r.json().get('routes') or []
        if not routes:
            return {'status': 'no_route'}
        toll_info = (routes[0].get('travelAdvisory') or {}).get('tollInfo') or {}
        prices = toll_info.get('estimatedPrice') or []
        return {
            'status': 'ok',
            'toll_likely': bool(prices),
            'estimated_price': [{'currency': p.get('currencyCode'), 'amount': p.get('units')} for p in prices],
        }
    except Exception as e:
        log.warning('Routes API toll check failed: %s', e)
        return {'status': 'error', 'detail': str(e)[:120]}


def _google_nearby_places(api_key: str, lat, lon, types=None) -> dict:
    """Nearby place search via Google Places API. Returns structured status dict."""
    if not api_key:
        return {'status': 'no_key'}
    if lat is None or lon is None:
        return {'status': 'no_coords'}
    radii = {'airport': 8000, 'parking': 300}
    results_by_type = {}
    for place_type in (types or ['airport', 'parking']):
        try:
            r = _requests.get(
                'https://maps.googleapis.com/maps/api/place/nearbysearch/json',
                params={'location': f'{lat},{lon}', 'radius': radii.get(place_type, 1000),
                        'type': place_type, 'key': api_key},
                timeout=8,
            )
            data = r.json()
            if data.get('status') == 'REQUEST_DENIED':
                return {'status': 'api_disabled', 'api': 'places.googleapis.com'}
            results_by_type[place_type] = [
                {'name': p.get('name'), 'vicinity': p.get('vicinity')}
                for p in data.get('results', [])[:3]
            ]
        except Exception as e:
            log.warning('Places API nearby search failed: %s', e)
            results_by_type[place_type] = None
    return {'status': 'ok', **results_by_type}


def match_best_woli(wolis: list, requested_qty, wo: dict | None = None) -> dict:
    """Find the WOLI entry most likely matching a WOA's requested quantity.

    wolis: list of {id, product, code, quantity, description} dicts.
    wo:    raw SF WorkOrder row for synthetic TW detection.
    Returns the best-match entry, or a synthetic TW dict if the WOA is for unbilled tow miles.
    """
    if not wolis:
        return {}
    named = [w for w in wolis if w.get('product')]
    if not named:
        return wolis[0]
    non_ba = [w for w in named if w.get('code') != 'BA']
    if not non_ba:
        return named[0]

    if requested_qty is not None:
        exact = [w for w in named if w.get('quantity') is not None and abs(w['quantity'] - requested_qty) < 0.01]
        if len(exact) == 1:
            return exact[0]
        if len(non_ba) > 1:
            return sorted(non_ba, key=lambda w: abs((w.get('quantity') or 0) - requested_qty))[0]
        # Single non-BA: detect if this WOA is for TW not yet billed (no TW WOLI on the WO).
        if wo and not any(w['code'] in _TOW_CODES for w in named):
            sf_tow = _safe_float(wo.get('Tow_Miles__c'))
            sf_est_tow = _safe_float(wo.get('ERS_Estimated_Tow_Miles__c'))
            tow_signal = max(sf_tow or 0, sf_est_tow or 0)
            if tow_signal > 0:
                er_woli_qty = non_ba[0].get('quantity') or 0
                er_anchor = max(
                    _safe_float(wo.get('ERS_En_Route_Miles__c')) or 0,
                    _safe_float(wo.get('ERS_Estimated_En_Route_Miles__c')) or 0,
                    er_woli_qty,
                )
                dist_to_tow = abs(requested_qty - tow_signal)
                dist_to_er = abs(requested_qty - er_anchor) if er_anchor > 0.1 else float('inf')
                if dist_to_tow < dist_to_er:
                    return {'product': 'TW - Tow Miles', 'code': 'TW',
                            'quantity': sf_tow if sf_tow and sf_tow > 0.1 else 0,
                            'description': None, 'id': '', '_synthetic': True}
        # Single non-BA fallback: check if quantity is wildly mismatched.
        # If the WOA claims significantly more than the WOLI quantity, the garage is likely
        # claiming a product that doesn't exist on this WO (e.g. E1 winch time on a WO with only ER).
        best_qty = non_ba[0].get('quantity') or 0
        if best_qty > 0 and requested_qty > best_qty * 2.5:
            return {'product': '(not on WO)', 'code': '', 'quantity': None,
                    'description': None, 'id': '', '_synthetic': True, '_no_match': True}
    return non_ba[0]


# ── GVW Estimation ────────────────────────────────────────────────────────────

def _lookup_gvw_by_vehicle(make: str, model: str) -> int | None:
    """Return typical max GVWR (lbs) for common vehicles. None if unknown."""
    combined = f"{make} {model}".lower()
    patterns = [
        # Super heavy duty
        (['f-450','f450'],                                       16500),
        (['f-550','f550'],                                       19500),
        (['f-650','f650','f-750','f750'],                        33000),
        # HD pickups
        (['f-350','f350','ram 3500','3500 hd','silverado 3500','sierra 3500','gmc 3500'], 14000),
        (['f-250','f250','ram 2500','2500 hd','silverado 2500','sierra 2500','gmc 2500'], 10000),
        # LD pickups
        (['f-150','f150','ram 1500','silverado 1500','sierra 1500',
          'tacoma','tundra','colorado','ranger','frontier','titan'],                       7050),
        # Cargo vans
        (['transit 350','transit 250','promaster',
          'express 3500','express 2500','savana'],                                         8600),
        # Semis / Class 8
        (['semi','tractor-trailer','peterbilt','kenworth','freightliner',
          'volvo','mack','international','western star'],                                  80000),
        # Generic box/straight
        (['box truck','straight truck'],                                                   26000),
    ]
    for keywords, gvw in patterns:
        if any(kw in combined for kw in keywords):
            return gvw
    return None


_CLASS_GVW = {1: 6000, 2: 10000, 3: 14000, 4: 16000, 5: 19500, 6: 26000, 7: 33000, 8: 80000}


def estimate_gvw(make: str, model: str, axle_count: float,
                 vehicle_group: str, description: str, sf_weight: float) -> dict | None:
    """Estimate GVW independently from make/model to cross-check SF Weight_lbs__c.
    Never uses sf_weight as the answer — always computes from vehicle identity.
    sf_weight is stored separately so auditors can compare.
    """
    desc = (description or '').lower()

    def _result(gvw, source, confidence):
        r = {'gvw': gvw, 'source': source, 'confidence': confidence}
        if sf_weight and sf_weight > 0:
            r['sf_weight'] = int(sf_weight)
        return r

    # 1. Parse explicit weight from description ("26,000 lbs", "26000 lb")
    m = _re.search(r'(\d{1,3})[,](\d{3})\s*(?:lb|lbs|pound)', desc)
    if not m:
        m = _re.search(r'(\d{5,6})\s*(?:lb|lbs|pound)', desc)
    if m:
        try:
            raw = m.group(0).replace(',', '')
            lbs = int(_re.search(r'\d+', raw).group())
            if 2000 < lbs < 150000:
                return _result(lbs, 'description', 'medium')
        except Exception:
            pass

    # 2. DOT class from description ("class 6", "class 8")
    m = _re.search(r'class\s*([1-8])', desc)
    if m:
        return _result(_CLASS_GVW[int(m.group(1))], 'description_class', 'medium')

    # 3. Keywords for heavy vehicles in description
    if any(kw in desc for kw in ['semi','tractor-trailer','18-wheel','18 wheel','big rig','peterbilt','kenworth','freightliner','volvo truck','mack truck']):
        return _result(80000, 'description_keyword', 'medium')
    if any(kw in desc for kw in ['box truck','straight truck','medium duty','heavy duty','medium-duty','heavy-duty']):
        return _result(26000, 'description_keyword', 'low')
    if any(kw in desc for kw in ['motorhome','motor home','rv ',' rv,','coach']):
        return _result(26000, 'description_keyword', 'low')

    # 4. Make + model lookup
    if make or model:
        gvw = _lookup_gvw_by_vehicle(make or '', model or '')
        if gvw:
            return _result(gvw, 'make_model', 'low')

    # 5. Axle count (3+ axles → at least medium duty)
    if axle_count and axle_count >= 3:
        return _result(26001, 'axle_count', 'low')

    # 6. Vehicle group field
    if vehicle_group:
        grp = vehicle_group.upper()
        if 'HEAVY' in grp:
            return _result(26001, 'vehicle_group', 'low')
        if 'MEDIUM' in grp:
            return _result(14000, 'vehicle_group', 'low')

    return None
