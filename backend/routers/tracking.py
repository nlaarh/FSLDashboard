"""Tracking router — on-route dashboard and live driver tracking (Uber-like customer view)."""

import time, math as _math, uuid as _uuid
from pathlib import Path
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse

from sf_client import sf_query_all, sf_parallel, sanitize_soql
from utils import parse_dt as _parse_dt, to_eastern as _to_eastern, is_fleet_territory, haversine
import cache

router = APIRouter()


def _haversine_mi(lat1, lon1, lat2, lon2):
    R = 3958.8  # Earth radius in miles
    dlat = _math.radians(lat2 - lat1)
    dlon = _math.radians(lon2 - lon1)
    a = _math.sin(dlat/2)**2 + _math.cos(_math.radians(lat1)) * _math.cos(_math.radians(lat2)) * _math.sin(dlon/2)**2
    return round(R * 2 * _math.atan2(_math.sqrt(a), _math.sqrt(1-a)), 1)


# ── On-Route Dashboard — list all active/en-route SAs ───────────────────────

# ── Disk-backed tracking tokens (shared across gunicorn workers on Azure) ──
# Azure /home is shared storage; locally uses ~/.fslapp/tracking/
import json as _json, os as _os
_ON_AZURE = bool(_os.environ.get('WEBSITE_SITE_NAME'))
_TOKEN_DIR = Path('/home/fslapp/tracking') if _ON_AZURE else Path(_os.path.expanduser('~/.fslapp/tracking'))
_TOKEN_DIR.mkdir(parents=True, exist_ok=True)
_tracking_rate_limit: dict[str, float] = {}  # token -> last_request_time


def _token_path(token: str) -> Path:
    return _TOKEN_DIR / f"{token}.json"


def _save_token(token: str, data: dict):
    _token_path(token).write_text(_json.dumps(data))


def _load_token(token: str) -> dict | None:
    p = _token_path(token)
    if not p.exists():
        return None
    try:
        data = _json.loads(p.read_text())
        if time.time() > data.get('expires_at', 0):
            p.unlink(missing_ok=True)
            return None
        return data
    except Exception:
        return None


def _delete_token(token: str):
    _token_path(token).unlink(missing_ok=True)
    _tracking_rate_limit.pop(token, None)


def _all_tokens() -> dict[str, dict]:
    """Load all active (non-expired) tokens from disk."""
    result = {}
    now = time.time()
    for p in _TOKEN_DIR.glob("*.json"):
        tok = p.stem
        try:
            data = _json.loads(p.read_text())
            if now > data.get('expires_at', 0):
                p.unlink(missing_ok=True)
            else:
                result[tok] = data
        except Exception:
            pass
    return result


def _purge_expired_tokens():
    """Lazy purge of expired tracking tokens from disk."""
    now = time.time()
    for p in _TOKEN_DIR.glob("*.json"):
        try:
            data = _json.loads(p.read_text())
            if now > data.get('expires_at', 0):
                p.unlink(missing_ok=True)
        except Exception:
            pass


@router.get("/api/onroute")
async def onroute_list():
    """Return all currently en-route/dispatched SAs with assigned driver info. Cached 60s."""
    def _fetch_onroute():
        # 1. All active SAs
        sas = sf_query_all("""
            SELECT Id, AppointmentNumber, Status, CreatedDate,
                   Street, City, State, Latitude, Longitude,
                   ServiceTerritoryId, ServiceTerritory.Name,
                   WorkType.Name, ERS_PTA__c,
                   ERS_Dispatch_Method__c,
                   Phone, Mobile_Phone__c,
                   FSL__Emergency__c, ERS_Priority_Group__c
            FROM ServiceAppointment
            WHERE Status IN ('En Route','Travel')
            ORDER BY CreatedDate DESC
        """)
        if not sas:
            return []

        # 2. Batch-fetch AssignedResource for all SA IDs
        sa_ids = [sa['Id'] for sa in sas]
        ar_map = {}  # sa_id -> {resource_id, resource_name}
        for i in range(0, len(sa_ids), 200):
            batch = sa_ids[i:i+200]
            id_list = ",".join(f"'{s}'" for s in batch)
            ars = sf_query_all(f"""
                SELECT ServiceAppointmentId, ServiceResourceId, ServiceResource.Name
                FROM AssignedResource
                WHERE ServiceAppointmentId IN ({id_list})
            """)
            for ar in ars:
                sa_ref = ar.get('ServiceAppointmentId')
                sr = ar.get('ServiceResource') or {}
                if sa_ref:
                    ar_map[sa_ref] = {
                        'resource_id': ar.get('ServiceResourceId'),
                        'resource_name': sr.get('Name', '?'),
                    }

        # 3. Build response (exclude Tow Drop-Off — car already picked up)
        results = []
        for sa in sas:
            wt = (sa.get('WorkType') or {}).get('Name', '')
            if 'drop' in wt.lower():
                continue
            ar = ar_map.get(sa['Id'])
            cd = _parse_dt(sa.get('CreatedDate'))
            et = _to_eastern(cd) if cd else None
            pta = sa.get('ERS_PTA__c')

            # Check if tracking token already exists
            token_url = None
            for tok, val in _all_tokens().items():
                if val['sa_id'] == sa['Id']:
                    token_url = f"/track/{tok}"
                    break

            dm = (sa.get('ERS_Dispatch_Method__c') or '').strip()
            driver_nm = ar['resource_name'] if ar else 'Unassigned'
            t_name = (sa.get('ServiceTerritory') or {}).get('Name', '')
            is_fleet = is_fleet_territory(t_name)

            # Urgency: P1 = child/pet locked in car, P2 = high priority, or FSL Emergency flag
            priority_group = sa.get('ERS_Priority_Group__c') or ''
            is_emergency = sa.get('FSL__Emergency__c', False)
            is_urgent = is_emergency or priority_group in ('Priority Group 1', 'Priority Group 2')
            urgent_reason = None
            if priority_group == 'Priority Group 1':
                urgent_reason = 'Child or pet locked in vehicle'
            elif is_emergency:
                urgent_reason = 'Marked as emergency'
            elif priority_group == 'Priority Group 2':
                urgent_reason = 'High priority call'

            # Customer phone
            cust_phone = sa.get('Phone') or sa.get('Mobile_Phone__c') or ''

            results.append({
                'sa_id': sa['Id'],
                'sa_number': sa.get('AppointmentNumber', '?'),
                'status': sa.get('Status', '?'),
                'created_time': et.strftime('%I:%M %p') if et else '?',
                'created_iso': cd.isoformat() if cd else None,
                'address': f"{sa.get('Street') or ''}, {sa.get('City') or ''}".strip(', '),
                'territory_name': (sa.get('ServiceTerritory') or {}).get('Name', '?'),
                'work_type': wt,
                'dispatch_method': dm or '?',
                'is_fleet': is_fleet,
                'pta_minutes': float(pta) if pta else None,
                'driver_name': driver_nm,
                'driver_id': ar['resource_id'] if ar else None,
                'has_driver': ar is not None,
                'tracking_url': token_url,
                'customer_phone': cust_phone,
                'is_urgent': is_urgent,
                'urgent_reason': urgent_reason,
            })
        # Sort: urgent first, then Fleet, then Towbook
        results.sort(key=lambda r: (0 if r['is_urgent'] else 1, 0 if r['is_fleet'] else 1, r['created_iso'] or ''))
        return results

    return cache.cached_query('onroute_list', _fetch_onroute, ttl=60)


# ── Live Driver Tracking (Uber-like customer view) ──────────────────────────

@router.post("/api/track/create")
async def track_create(request: Request):
    """Generate a tracking token for a Service Appointment. Auth required (dispatcher)."""
    body = await request.json()
    sa_id = body.get("sa_id")
    sa_number = body.get("sa_number")
    if not sa_id and not sa_number:
        raise HTTPException(400, "Provide sa_id or sa_number")

    # Build WHERE clause
    if sa_id:
        where = f"Id = '{sanitize_soql(sa_id)}'"
    else:
        where = f"AppointmentNumber = '{sanitize_soql(sa_number)}'"

    sa_query = f"""
        SELECT Id, AppointmentNumber, Status, Latitude, Longitude,
               Street, City, State, WorkType.Name,
               ERS_Dispatch_Method__c,
               Contact.Name, Contact.Phone, Contact.MobilePhone,
               ParentRecordId
        FROM ServiceAppointment
        WHERE {where}
        LIMIT 1
    """
    sa_rows = sf_query_all(sa_query)
    if not sa_rows:
        raise HTTPException(404, "Service Appointment not found")
    sa = sa_rows[0]

    valid_statuses = {'dispatched', 'accepted', 'en route', 'travel'}
    if (sa.get('Status') or '').lower() not in valid_statuses:
        raise HTTPException(400, f"SA status is '{sa.get('Status')}' — must be Dispatched, Accepted, or En Route")

    # Get assigned resource + driver phone
    ar_query = f"""
        SELECT ServiceResourceId, ServiceResource.Name,
               ServiceResource.RelatedRecord.Phone,
               ServiceResource.ERS_Driver_Type__c,
               ServiceResource.LastKnownLatitude, ServiceResource.LastKnownLongitude
        FROM AssignedResource
        WHERE ServiceAppointmentId = '{sanitize_soql(sa['Id'])}'
        ORDER BY CreatedDate DESC LIMIT 1
    """
    ar_rows = sf_query_all(ar_query)
    if not ar_rows:
        raise HTTPException(400, "No driver assigned to this SA")

    sr_id = ar_rows[0]['ServiceResourceId']
    sr = ar_rows[0].get('ServiceResource') or {}
    driver_name = sr.get('Name', 'Driver')
    driver_phone = (sr.get('RelatedRecord') or {}).get('Phone')
    driver_type = sr.get('ERS_Driver_Type__c', '')

    # Block Towbook — contractors have no GPS, tracking is meaningless
    dispatch_method = (sa.get('ERS_Dispatch_Method__c') or '').lower()
    is_towbook = (dispatch_method == 'towbook'
                  or (driver_name or '').lower().startswith('towbook')
                  or 'off-platform' in (driver_type or '').lower())
    if is_towbook:
        raise HTTPException(400, "Live tracking is not available for contractor (Towbook) dispatches — only Fleet drivers have GPS positions.")

    # Block if driver has no GPS (can't track what we can't see)
    driver_lat = sr.get('LastKnownLatitude')
    driver_lon = sr.get('LastKnownLongitude')
    if not driver_lat or not driver_lon:
        raise HTTPException(400, "Driver has no GPS position yet. Try again in a few minutes after the driver's location updates.")

    # Get truck unit number (Asset where ERS_Driver__c = this SR)
    truck_query = f"""
        SELECT Name, SerialNumber, ERS_Color__c
        FROM Asset
        WHERE RecordType.Name = 'ERS Truck'
          AND ERS_Driver__c = '{sanitize_soql(sr_id)}'
        LIMIT 1
    """
    truck_rows = sf_query_all(truck_query)
    truck = truck_rows[0] if truck_rows else {}
    truck_unit = truck.get('SerialNumber', '')
    truck_color = truck.get('ERS_Color__c', '')

    # Get vehicle info from WorkOrder (these fields are on WO, not SA)
    vehicle_info = {}
    wo_id = sa.get('ParentRecordId')
    if wo_id:
        try:
            wo_rows = sf_query_all(
                f"SELECT Vehicle_Make__c, Vehicle_Model__c, License_Plate__c"
                f" FROM WorkOrder WHERE Id = '{sanitize_soql(wo_id)}' LIMIT 1"
            )
            if wo_rows:
                vehicle_info = wo_rows[0]
        except Exception:
            pass

    # ETA check — skip tracking if driver is already very close (< 5 min)
    driver_lat = sr.get('LastKnownLatitude')
    driver_lon = sr.get('LastKnownLongitude')
    cust_lat = sa.get('Latitude')
    cust_lon = sa.get('Longitude')
    if driver_lat and driver_lon and cust_lat and cust_lon:
        dist = _haversine_mi(float(driver_lat), float(driver_lon), float(cust_lat), float(cust_lon))
        eta_min = dist / 25 * 60  # 25 mph assumed
        if eta_min < 5:
            raise HTTPException(400, f"Driver is already ~{eta_min:.0f} min away ({dist:.1f} mi) — too close for tracking")

    # Check for existing active token for this SA
    _purge_expired_tokens()
    for tok, val in _all_tokens().items():
        if val['sa_id'] == sa['Id']:
            return {"token": tok, "url": f"/track/{tok}", "expires_at": datetime.fromtimestamp(val['expires_at'], tz=timezone.utc).isoformat()}

    # Generate new token
    token = _uuid.uuid4().hex[:12]
    expires_at = time.time() + 3 * 3600  # 3 hours

    _save_token(token, {
        'sa_id': sa['Id'],
        'sa_number': sa.get('AppointmentNumber'),
        'driver_resource_id': sr_id,
        'driver_name': driver_name,
        'driver_phone': driver_phone,
        'driver_type': driver_type,
        'truck_unit': truck_unit,
        'truck_color': truck_color,
        'customer_lat': sa.get('Latitude'),
        'customer_lon': sa.get('Longitude'),
        'customer_street': sa.get('Street'),
        'customer_city': sa.get('City'),
        'customer_name': (sa.get('Contact') or {}).get('Name', ''),
        'customer_phone': (sa.get('Contact') or {}).get('MobilePhone') or (sa.get('Contact') or {}).get('Phone', ''),
        'vehicle_make': vehicle_info.get('Vehicle_Make__c', ''),
        'vehicle_model': vehicle_info.get('Vehicle_Model__c', ''),
        'vehicle_plate': vehicle_info.get('License_Plate__c', ''),
        'work_type': (sa.get('WorkType') or {}).get('Name', ''),
        'created_at': time.time(),
        'expires_at': expires_at,
    })

    # Build full URL from request headers (works behind Azure reverse proxy)
    scheme = request.headers.get('x-forwarded-proto', 'https' if request.url.scheme == 'https' else 'http')
    host = request.headers.get('x-forwarded-host') or request.headers.get('host') or 'localhost:8000'
    full_url = f"{scheme}://{host}/track/{token}"

    return {
        "token": token,
        "url": f"/track/{token}",
        "full_url": full_url,
        "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
    }


def _get_tracking_position(token_data: dict) -> dict:
    """Fetch current driver position and SA status from SF. Cached 15s."""
    cache_key = f"track_pos_{token_data['sa_id']}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    sa_id = token_data['sa_id']
    sr_id = token_data['driver_resource_id']

    # Parallel fetch: SA status + driver GPS
    sa_soql = f"SELECT Status FROM ServiceAppointment WHERE Id = '{sanitize_soql(sa_id)}' LIMIT 1"
    sr_soql = f"""SELECT LastKnownLatitude, LastKnownLongitude, LastKnownLocationDate
                  FROM ServiceResource WHERE Id = '{sanitize_soql(sr_id)}' LIMIT 1"""
    results = sf_parallel(
        sa_status=lambda q=sa_soql: sf_query_all(q),
        driver_gps=lambda q=sr_soql: sf_query_all(q),
    )

    sa_rows = results.get('sa_status') or []
    sr_rows = results.get('driver_gps') or []

    sa_status = sa_rows[0].get('Status', '') if sa_rows else ''
    sr = sr_rows[0] if sr_rows else {}

    driver_lat = sr.get('LastKnownLatitude')
    driver_lon = sr.get('LastKnownLongitude')
    gps_date = sr.get('LastKnownLocationDate')

    # Calculate GPS age
    gps_age_seconds = None
    if gps_date:
        gps_dt = _parse_dt(gps_date)
        if gps_dt:
            gps_age_seconds = int((datetime.now(timezone.utc) - gps_dt).total_seconds())

    # Calculate distance and ETA
    cust_lat = token_data.get('customer_lat')
    cust_lon = token_data.get('customer_lon')
    distance_miles = haversine(driver_lat, driver_lon, cust_lat, cust_lon) if all([driver_lat, driver_lon, cust_lat, cust_lon]) else None
    eta_minutes = round(distance_miles / 25 * 60) if distance_miles else None

    # Determine tracking status
    status_lower = sa_status.lower()
    if status_lower in ('on location', 'on site'):
        tracking_status = 'arrived'
    elif status_lower in ('completed', 'canceled', 'cancelled'):
        tracking_status = 'completed'
    elif status_lower in ('dispatched', 'accepted', 'en route', 'travel'):
        tracking_status = 'en_route'
    else:
        tracking_status = 'expired'

    # Determine if GPS will never be available (Towbook)
    driver_name_lower = (token_data.get('driver_name') or '').lower()
    driver_type_lower = (token_data.get('driver_type') or '').lower()
    is_contractor = driver_name_lower.startswith('towbook') or 'off-platform' in driver_type_lower
    no_gps_reason = None
    if not driver_lat and not driver_lon:
        if is_contractor:
            no_gps_reason = 'contractor'  # will never have GPS
        else:
            no_gps_reason = 'waiting'     # Fleet, GPS not yet updated

    result = {
        'status': tracking_status,
        'sa_status': sa_status,
        'no_gps_reason': no_gps_reason,
        'driver': {
            'name': token_data.get('driver_name', 'Driver'),
            'phone': token_data.get('driver_phone'),
            'type': token_data.get('driver_type', ''),
            'truck_unit': token_data.get('truck_unit', ''),
            'truck_color': token_data.get('truck_color', ''),
            'lat': driver_lat,
            'lon': driver_lon,
            'gps_age_seconds': gps_age_seconds,
        },
        'customer': {
            'lat': cust_lat,
            'lon': cust_lon,
            'street': token_data.get('customer_street'),
            'city': token_data.get('customer_city'),
            'name': token_data.get('customer_name', ''),
            'phone': token_data.get('customer_phone', ''),
        },
        'vehicle': {
            'make': token_data.get('vehicle_make', ''),
            'model': token_data.get('vehicle_model', ''),
            'plate': token_data.get('vehicle_plate', ''),
        },
        'distance_miles': distance_miles,
        'eta_minutes': eta_minutes,
        'work_type': token_data.get('work_type', ''),
        'sa_number': token_data.get('sa_number', ''),
    }

    cache.put(cache_key, result, ttl=15)
    return result


@router.get("/api/track/{token}/position")
async def track_position(token: str):
    """Public endpoint — returns driver position for a tracking token."""
    _purge_expired_tokens()
    token_data = _load_token(token)
    if not token_data:
        return JSONResponse(status_code=410, content={"status": "expired", "message": "This tracking link has expired"})

    # Rate limit: 1 call per 10 seconds per token
    now = time.time()
    last = _tracking_rate_limit.get(token, 0)
    if now - last < 10:
        return JSONResponse(status_code=429, content={"error": "Too many requests. Try again in a few seconds."})
    _tracking_rate_limit[token] = now

    result = _get_tracking_position(token_data)

    # Invalidate token on completion
    if result['status'] in ('completed', 'expired'):
        _delete_token(token)

    return result


_static_dir = Path(__file__).resolve().parent.parent / "static"


@router.get("/track/{token}")
async def track_page(token: str):
    """Serve standalone tracking HTML page (no auth required)."""
    # Validate token exists (don't serve page for invalid tokens)
    _purge_expired_tokens()
    if not _load_token(token):
        return HTMLResponse("""<!DOCTYPE html><html><head><meta charset="UTF-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Tracking Expired</title>
        <style>body{font-family:system-ui;background:#0f172a;color:#94a3b8;display:flex;
        align-items:center;justify-content:center;min-height:100vh;margin:0}
        .msg{text-align:center}.msg h1{font-size:1.5rem;color:#e2e8f0;margin-bottom:.5rem}</style>
        </head><body><div class="msg"><h1>Tracking Link Expired</h1>
        <p>This tracking link is no longer active.</p></div></body></html>""")

    track_html = _static_dir / "track.html"
    if track_html.is_file():
        return FileResponse(track_html)
    return HTMLResponse("<h1>Tracking page not found</h1>", status_code=500)
