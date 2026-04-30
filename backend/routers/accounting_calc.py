"""Accounting — shared calculation helpers (recommendation engine, formatters, utils)."""

import logging
import re as _re
import requests as _requests
from datetime import timezone as _tz
from zoneinfo import ZoneInfo
from utils import parse_dt as _parse_dt

log = logging.getLogger('accounting')
_ET = ZoneInfo('America/New_York')
_SF_BASE   = 'https://aaawcny.lightning.force.com'
_TOW_CODES = {'TW', 'TB', 'TT', 'TU', 'TM', 'EM'}
_TIME_CODES = {'E1', 'E2', 'MI', 'Z8'}
_FLAT_CODES = {'BA', 'BC', 'PC', 'HO', 'PG', 'Z5', 'Z7', 'TJ', 'Z0', 'Z1', 'Z3'}

_DEFAULT_AUDIT_PROMPT = (
    "You are a senior accounting supervisor at AAA Western & Central NY roadside assistance, "
    "speaking directly to an accountant who processes garage invoices. "
    "Your job: read the WOA data and tell a CLEAR STORY — what happened, why the garage is asking for more money, "
    "whether the claim is justified, and exactly what the accountant should do next. "
    "\n\nALWAYS spell out product codes: ER=Enroute Miles, TW=Tow Miles, E1=Extrication, BA=Base Rate, "
    "TL=Tolls/Parking, MH=Medium/Heavy Duty, MI=Wait Time. ALWAYS include units (miles, minutes, dollars). "
    "\n\nBenchmark rules: "
    "ER — compare claimed vs google_distance_miles (truck GPS → call). Within 130%=PAY. "
    "TW — compare claimed vs google_tow_distance_miles (pickup → tow destination). Within 130%=PAY. "
    "E1/MI — compare claimed minutes vs on_location_minutes. Within 120%=PAY. "
    "BA/BC/PC — always REVIEW (policy required). TL — REVIEW (receipts required). MH — REVIEW (weight verification required). "
    "If same_member_same_day_count > 0, flag as potential duplicate. "
    "If tl_context shows toll roads on the route, mention it as context. "
    "\n\nFraud signals to watch: GPS doesn't support claimed distance; En Route and On Location timestamps seconds apart "
    "(driver never actually drove); claimed minutes >> on-scene time; same member called multiple garages same day. "
    "\n\nRespond ONLY with valid JSON — no markdown fences, no commentary outside the JSON: "
    '{"recommendation":"PAY|REVIEW|DENY",'
    '"confidence":"HIGH|MEDIUM|LOW",'
    '"headline":"One sentence: what happened and whether it checks out",'
    '"story":"3-5 sentences written to an accountant: what service was done, where the truck went, what the numbers show, and whether to pay",'
    '"fraud_signals":["red flag if found — omit array entirely if none"],'
    '"anomalies":["yellow flag / unusual finding — omit if none"],'
    '"what_to_do":["specific action for the accountant, e.g. Approve in Salesforce, Call garage about X"],'
    '"ask_garage":["specific question to ask the garage if REVIEW or DENY — omit if PAY"]}'
)


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
                         all_wolis=None, long_tow_used=False):
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
        L.append(f'  Vehicle Weight: {vehicle_weight or "Not populated"} lbs')
        L.append(f'  Vehicle Group: {vehicle_group or "N/A"}')
        L.append(f'  Threshold: ≥10,000 lbs or Group DW/HD/MD')
        v = {'vehicle_weight': vehicle_weight, 'vehicle_group': vehicle_group}
        if paid and paid > 0 and abs(requested - paid) < 0.5:
            L.append(f'\n→ Requesting same as billed ({paid}). No change needed.')
            return 'approve', '\n'.join(L), v
        if vehicle_weight and vehicle_weight >= 10000:
            L.append(f'→ {vehicle_weight} lbs ≥ 10,000 → APPROVE'); return 'approve', '\n'.join(L), v
        if vehicle_group in ('MD', 'HD', 'DW'):
            L.append(f'→ Group {vehicle_group} = heavy → APPROVE'); return 'approve', '\n'.join(L), v
        if vehicle_weight and vehicle_weight < 10000:
            L.append(f'→ {vehicle_weight} lbs < 10,000 → REVIEW'); return 'review', '\n'.join(L), v
        L.append(f'→ No weight data → REVIEW'); return 'review', '\n'.join(L), v
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
    elif code in FLAT_CODES:
        if paid and paid > 0 and abs(requested - paid) < 0.01:
            L.append(f'\nFLAT FEE / SERVICE EVENT:')
            L.append(f'  {prod_name} — requesting same as billed ({paid}). No change needed.')
            L.append(f'\n→ Requesting same as billed. No financial impact → APPROVE')
            return 'approve', '\n'.join(L), {'sf_billed': paid}
        L.append(f'\nFLAT FEE / SERVICE EVENT:')
        L.append(f'  {prod_name} — verify the service was performed.')
        L.append(f'→ Flat-fee products (BA/BC/PC/HO/PG/RAP) always require policy review.')
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
