"""Contractor Dispatch + Map.

Two endpoints backing the contractor-facing Dispatch list and live Map:
  GET /api/contractor/dispatch  — call list bucketed like a dispatch board
  GET /api/contractor/map       — active calls + driver positions for the map

Both are gated behind the `contractor_dispatch` feature flag — ON by default,
switchable from the Admin screen (Feature Modules), which persists to the
settings table. When it is off these return 404. See feature_flags.py.

SECURITY: every query is filtered server-side on
`ERS_Work_Order__r.Facility_ID__c IN (<the caller's own facilities>)`.
Filtering on ServiceTerritoryId would leak sibling facilities in the same
region — see the note on _require_contractor_facilities in contractor.py.
"""

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query, Request

import cache
from sf_client import sf_query_all, sanitize_soql
from routers.contractor import _require_contractor_facilities, _facility_in_clause

router = APIRouter()
log = logging.getLogger('contractor_dispatch')

# ERS roadside work types. Everything else (Travel, Personal Lines, branch
# appointments) is a different business line: no coordinates, no facility, and
# it must never appear on a roadside dispatch board.
#
# A tow is two appointments: 'Tow Pick-Up' (where the member is stranded) and
# 'Tow Drop-Off' (the destination shop). Both are the contractor's own work, so
# both belong here — but the UI must mark them differently, because a drop-off's
# coordinates are a repair shop, not a stranded member.
ERS_WORK_TYPES = (
    'Tow Pick-Up', 'Tow Drop-Off', 'Battery', 'Tire', 'Lockout', 'Winch Out',
    'Fuel / Miscellaneous', 'Locksmith', 'EV', 'Jumpstart',
    'Flat Bed', 'Wheel Lift', 'Extrication', 'PVS',
)

# FSL status → dispatch-board bucket.
ACTIVE_STATUSES = ('En Route', 'On Location', 'In Progress')
CURRENT_STATUSES = ('Assigned', 'Dispatched', 'Accepted', 'Checked In') + ACTIVE_STATUSES

WAITING_STATUSES = ('None', 'Scheduled', 'Spotted')
CANCELLED_STATUSES = (
    'Cancel Call - Service En Route', 'Cancel Call - Service Not En Route',
    'Canceled', 'No-Show', 'Abandoned',
)

# The map answers "where does a customer need help right now". Defined as an
# EXCLUSION rather than a whitelist so a status nobody anticipated still shows
# up instead of silently vanishing: only finished and cancelled work is hidden.
# 'Assigned' pins — those calls already carry a named driver, truck and live
# GPS, so they are being worked, not merely queued.
#
# 'Unable to Complete' is hidden too: the driver has left, so the pin is not
# somewhere help is on the way. It still appears on the dispatch board under its
# own bucket, which is where that call needs to be actioned.
MAP_HIDDEN_STATUSES = CANCELLED_STATUSES + ('Completed', 'Cleared', 'Unable to Complete')

# A driver pin means "this truck is out there right now". A resource that has
# not reported GPS in this long is off shift or has closed the app: still
# attached to today's paperwork, but no longer tracking, so plotting its last
# known position would put a ghost truck on the map.
DRIVER_GPS_MAX_AGE_MIN = 30

BUCKETS = {
    'current':   CURRENT_STATUSES,
    'waiting':   WAITING_STATUSES,
    'active':    ACTIVE_STATUSES,
    'completed': ('Completed', 'Cleared'),
    'scheduled': ('Scheduled',),
    'cancelled': CANCELLED_STATUSES,
    'unable':    ('Unable to Complete',),
}


def _require_flag():
    """404 unless the feature is switched on.

    Reads the EFFECTIVE value (defaults + admin's saved overrides), not the
    static default — otherwise switching the module off in Admin would only
    hide the nav links while leaving these endpoints reachable.
    """
    import feature_flags
    if not feature_flags.is_on('contractor_dispatch'):
        raise HTTPException(status_code=404, detail="Not found")


def _in(values) -> str:
    return "'" + "','".join(sanitize_soql(v) for v in values) + "'"


_SA_FIELDS = """
    Id, AppointmentNumber, Status, CreatedDate, SchedStartTime, ActualStartTime,
    ERS_PTA__c, Latitude, Longitude, Street, City, State, PostalCode,
    WorkType.Name, ServiceTerritory.Name, ERS_Facility_Decline_Reason__c,
    Off_Platform_Driver__r.Name, Off_Platform_Truck_Id__c,
    ERS_OffPlatformDriverLocation__Latitude__s,
    ERS_OffPlatformDriverLocation__Longitude__s,
    ERS_Work_Order__c, ERS_Work_Order__r.WorkOrderNumber,
    ERS_Work_Order__r.Facility_ID__c, ERS_Work_Order__r.Facility_Name__c,
    ERS_Work_Order__r.Vehicle_Make__c, ERS_Work_Order__r.Vehicle_Model__c,
    ERS_Work_Order__r.ERS_Month_Year__c, ERS_Work_Order__r.License_Plate__c,
    ERS_Work_Order__r.Coverage__c, ERS_Work_Order__r.Type__c,
    ERS_Work_Order__r.Trouble_Code__c, ERS_Work_Order__r.Customer_Name__c
"""


def _fetch_sas(f_clause: str, statuses=None, exclude_statuses=None) -> list[dict]:
    """Facility-scoped ERS appointments for ONE calendar day. `statuses` None =
    every status.

    Both the board and the map are a garage's *daily* view, so the window is a
    single day — not a rolling one. Note LAST_N_DAYS:1 would be wrong here: it
    means "since the start of yesterday", i.e. two calendar days.
    """
    where = [
        f"ERS_Work_Order__r.Facility_ID__c IN ({f_clause})",
        f"WorkType.Name IN ({_in(ERS_WORK_TYPES)})",
        "CreatedDate = TODAY",
    ]
    if statuses:
        where.append(f"Status IN ({_in(statuses)})")
    elif exclude_statuses:
        where.append(f"Status NOT IN ({_in(exclude_statuses)})")
    soql = f"SELECT {_SA_FIELDS} FROM ServiceAppointment WHERE " + " AND ".join(where) + " ORDER BY CreatedDate DESC"
    return sf_query_all(soql)


def _vehicle(wo: dict) -> str:
    """'2019 Honda CR-V' from the work order's vehicle fields."""
    yr = (wo.get('ERS_Month_Year__c') or '').split(',')[-1].strip()
    parts = [yr, wo.get('Vehicle_Make__c') or '', wo.get('Vehicle_Model__c') or '']
    return ' '.join(p for p in parts if p).strip()


def _address(r: dict) -> str:
    bits = [r.get('Street') or '', r.get('City') or '', r.get('State') or '', r.get('PostalCode') or '']
    return ', '.join(b for b in bits if b)


def _shape(r: dict) -> dict:
    wo = r.get('ERS_Work_Order__r') or {}
    drv = r.get('Off_Platform_Driver__r') or {}
    return {
        'sa_id': r['Id'],
        'sa_number': r.get('AppointmentNumber') or '',
        'wo_number': wo.get('WorkOrderNumber') or '',
        'status': r.get('Status') or '',
        'work_type': (r.get('WorkType') or {}).get('Name') or '',
        # True when this row's location is the tow destination, not the member.
        'is_dropoff': (r.get('WorkType') or {}).get('Name') == 'Tow Drop-Off',
        'reason': wo.get('Trouble_Code__c') or wo.get('Type__c') or '',
        'coverage': wo.get('Coverage__c') or '',
        'vehicle': _vehicle(wo),
        'plate': wo.get('License_Plate__c') or '',
        # None = unknown (off-platform driver, or the truck lookup failed)
        'logged_in': None,
        # Blank on a minority of calls — the UI must not assume it is present.
        'customer': wo.get('Customer_Name__c') or '',
        'address': _address(r),
        'city': r.get('City') or '',
        'account': wo.get('Facility_Name__c') or '',
        'facility': wo.get('Facility_ID__c') or '',
        'territory': (r.get('ServiceTerritory') or {}).get('Name') or '',
        'driver': drv.get('Name') or '',
        'truck': r.get('Off_Platform_Truck_Id__c') or '',
        'created': r.get('CreatedDate') or '',
        'eta': r.get('SchedStartTime') or '',
        'arrived': r.get('ActualStartTime') or '',
        'pta': r.get('ERS_PTA__c'),
        'declined': bool(r.get('ERS_Facility_Decline_Reason__c')),
        'lat': r.get('Latitude'),
        'lon': r.get('Longitude'),
        'driver_lat': r.get('ERS_OffPlatformDriverLocation__Latitude__s'),
        'driver_lon': r.get('ERS_OffPlatformDriverLocation__Longitude__s'),
    }


def _is_placeholder(name: str) -> bool:
    """True for shared dispatch logins rather than a real person.

    Each Towbook garage has one placeholder ServiceResource named
    "Towbook-<facility>" that every call is nominally assigned to. Showing it as
    the driver would be wrong — nobody is called Towbook-420.
    """
    n = (name or '').strip().lower()
    if not n:
        return True
    return n.startswith('towbook-') or n.startswith('000-') or n.startswith('0 smoi') \
        or 'test ers' in n or n in ('locksmith', 'shop .', 'travel user', '100a driver')


def _short_truck(name: str) -> str:
    """'7- RAM FB - 076DO - TRANSIT AUTO DETAIL' → '7- RAM FB'."""
    return (name or '').split(' - ')[0].strip()


def _attach_drivers(items: list[dict]) -> None:
    """Fill driver/truck/driver-GPS in place.

    Two channels, two sources. Off-platform contractors carry driver name, truck
    and GPS on the appointment itself. On-platform drivers carry them on the
    ServiceResource (reached via AssignedResource), with the truck on the Asset
    whose ERS_Driver__c points at that resource. Best-effort: a failure here
    leaves the call rows intact, just without driver detail.
    """
    need = [i for i in items if not i.get('driver')]
    if not need:
        return
    try:
        ars = sf_query_all(f"""
            SELECT ServiceAppointmentId, ServiceResourceId, ServiceResource.Name,
                   ServiceResource.ERS_Driver_Type__c,
                   ServiceResource.LastKnownLatitude, ServiceResource.LastKnownLongitude,
                   ServiceResource.LastKnownLocationDate
            FROM AssignedResource
            WHERE ServiceAppointmentId IN ({_in([i['sa_id'] for i in need])})
        """)
    except Exception as exc:
        log.warning('contractor: driver lookup failed: %s', exc)
        return

    by_sa, res_ids = {}, set()
    for a in ars:
        sr = a.get('ServiceResource') or {}
        by_sa[a['ServiceAppointmentId']] = a
        if a.get('ServiceResourceId'):
            res_ids.add(a['ServiceResourceId'])

    truck_by_res = {}
    if res_ids:
        try:
            for t in sf_query_all(f"""
                SELECT Name, ERS_Driver__c FROM Asset
                WHERE RecordType.Name = 'ERS Truck' AND ERS_Driver__c IN ({_in(sorted(res_ids))})
            """):
                truck_by_res[t['ERS_Driver__c']] = t.get('Name') or ''
        except Exception as exc:
            log.warning('contractor: truck lookup failed: %s', exc)
            truck_by_res = None   # unknown, not "nobody logged in"

    for i in need:
        a = by_sa.get(i['sa_id'])
        if not a:
            continue
        sr = a.get('ServiceResource') or {}
        nm = sr.get('Name') or ''
        # a placeholder login is not a driver — leave blank so the UI shows "unassigned"
        i['driver'] = '' if _is_placeholder(nm) else nm
        i['driver_type'] = sr.get('ERS_Driver_Type__c') or ''
        res_id = a.get('ServiceResourceId')
        # A driver logs IN to a truck, which sets that Asset's ERS_Driver__c, and
        # logging out clears it. So "has a truck" IS "is logged in" — the only
        # such signal in the org. (User.LastLoginDate is useless here: drivers
        # work the mobile app for weeks without a fresh Salesforce login.)
        if truck_by_res is None:
            i['logged_in'] = None            # lookup failed — don't claim either way
        else:
            i['logged_in'] = res_id in truck_by_res
            i['truck'] = i.get('truck') or _short_truck(truck_by_res.get(res_id, ''))
        if i.get('driver_lat') is None:
            i['driver_lat'] = sr.get('LastKnownLatitude')
            i['driver_lon'] = sr.get('LastKnownLongitude')
            i['driver_seen'] = sr.get('LastKnownLocationDate') or ''


def _on_platform_facilities(facility_ids: list[str]) -> list[str]:
    """Subset of the caller's facilities dispatched through FSL.

    Account.Dispatch_Method__c is the channel of record: 'Field Services' is
    on-platform, while 'Towbook', 'Phone' and '3rd Party' are not. The live map
    only means anything on-platform — off-platform drivers have no truck login
    and no ServiceResource GPS, so their pins would be blanks or stale ghosts.
    """
    if not facility_ids:
        return []
    rows = sf_query_all(f"""
        SELECT Facility_Number__c FROM Account
        WHERE Facility_Number__c IN ({_facility_in_clause(facility_ids)})
          AND Dispatch_Method__c = 'Field Services'
    """)
    return [r['Facility_Number__c'] for r in rows if r.get('Facility_Number__c')]


def _gps_is_live(seen: str | None) -> bool:
    """True when a GPS timestamp is recent enough to plot as a live truck.

    A missing timestamp fails closed: we cannot show a driver as tracking when
    Salesforce never recorded when the position was taken.
    """
    if not seen:
        return False
    try:
        t = datetime.fromisoformat(seen.replace('+0000', '+00:00'))
    except ValueError:
        return False
    age_min = (datetime.now(timezone.utc) - t).total_seconds() / 60
    return age_min <= DRIVER_GPS_MAX_AGE_MIN


def _matches(item: dict, q: str) -> bool:
    q = q.lower()
    return any(q in str(item.get(k) or '').lower()
               for k in ('sa_number', 'wo_number', 'vehicle', 'plate', 'address', 'driver', 'account'))


# ── GET /api/contractor/dispatch ─────────────────────────────────────────────

@router.get("/api/contractor/dispatch")
def contractor_dispatch(
    request: Request,
    bucket: str = Query('current', description='current|waiting|active|completed|scheduled|cancelled|unable'),
    q: str = Query('', description='search: call #, WO #, vehicle, plate, address, driver'),
):
    """Today's dispatch-board call list for the caller's own garages, bucketed by status."""
    _require_flag()
    facility_ids = _require_contractor_facilities(request)
    f_clause = _facility_in_clause(facility_ids)

    if bucket not in BUCKETS:
        raise HTTPException(status_code=400, detail=f"Unknown bucket '{bucket}'")

    rows = _fetch_sas(f_clause, statuses=None)
    items = [_shape(r) for r in rows]

    counts = {b: sum(1 for i in items if i['status'] in sts) for b, sts in BUCKETS.items()}

    shown = [i for i in items if i['status'] in BUCKETS[bucket]]
    if q.strip():
        shown = [i for i in shown if _matches(i, q.strip())]
    _attach_drivers(shown)   # only for the rows actually returned

    return {
        'items': shown,
        'counts': counts,
        'total': len(shown),
        'facilities': facility_ids,
        'bucket': bucket,
        'window': 'today',
    }


# ── GET /api/contractor/map ──────────────────────────────────────────────────

@router.get("/api/contractor/map/available")
def contractor_map_available(request: Request):
    """Whether to offer the map at all, so the nav can hide it rather than
    letting a vendor click through to a dead end. Never raises: any problem
    resolving the caller's channel simply means 'do not offer it'."""
    try:
        _require_flag()
        return {'available': bool(_on_platform_facilities(_require_contractor_facilities(request)))}
    except Exception as exc:
        # includes the HTTPExceptions for flag-off / no garages / wrong role
        log.info('contractor: map not offered: %s', exc)
        return {'available': False}


@router.get("/api/contractor/map")
def contractor_map(request: Request):
    """Active calls plus driver positions, scoped to the caller's garages.

    Customer pins come from the appointment's own lat/lon (100% populated on
    real ERS calls). Driver pins come from two different places depending on
    channel: off-platform contractors carry their GPS on the appointment, while
    on-platform drivers carry it on the ServiceResource record.
    """
    _require_flag()
    facility_ids = _require_contractor_facilities(request)

    # The map is an on-platform feature. A Towbook / Phone / 3rd Party vendor
    # has no FSL driver telemetry at all, so rather than show them an empty or
    # misleading map, tell them plainly that it does not apply. A vendor running
    # both channels still gets a map — of their on-platform garages only.
    facility_ids = _on_platform_facilities(facility_ids)
    if not facility_ids:
        raise HTTPException(
            status_code=403,
            detail="The live map is available to on-platform garages only.",
        )
    f_clause = _facility_in_clause(facility_ids)

    rows = _fetch_sas(f_clause, exclude_statuses=MAP_HIDDEN_STATUSES)
    calls = [_shape(r) for r in rows]
    _attach_drivers(calls)

    # One row per driver, not per assignment — a driver running four calls is
    # still one truck on the map. The row shows their most-progressed job and
    # lists the rest.
    rank = {'On Location': 4, 'In Progress': 4, 'En Route': 3,
            'Dispatched': 2, 'Accepted': 2, 'Checked In': 1, 'Assigned': 0}
    stale_drivers = logged_out_drivers = 0
    by_driver: dict[str, dict] = {}
    for c in calls:
        if not c.get('driver') or c.get('driver_lat') is None or c.get('driver_lon') is None:
            continue
        # "logged in and tracking": logged into a truck, and still reporting GPS.
        # logged_in is None for off-platform drivers, who have no truck record —
        # don't drop them on a signal that does not exist for their channel.
        if c.get('logged_in') is False:
            logged_out_drivers += 1
            continue
        if not _gps_is_live(c.get('driver_seen')):
            stale_drivers += 1
            continue
        d = by_driver.get(c['driver'])
        job = {'sa_id': c['sa_id'], 'sa_number': c['sa_number'],
               'status': c['status'], 'work_type': c['work_type'], 'address': c['address']}
        if d is None:
            by_driver[c['driver']] = {
                'name': c['driver'],
                'truck': c.get('truck') or '',
                'type': c.get('driver_type') or 'Off-Platform Contractor Driver',
                'lat': c['driver_lat'], 'lon': c['driver_lon'],
                'last_seen': c.get('driver_seen') or '',
                'status': c['status'],
                'sa_id': c['sa_id'], 'sa_number': c['sa_number'],
                'work_type': c['work_type'], 'destination': c['address'],
                'jobs': [job],
            }
        else:
            d['jobs'].append(job)
            if rank.get(c['status'], -1) > rank.get(d['status'], -1):
                d.update(status=c['status'], sa_id=c['sa_id'], sa_number=c['sa_number'],
                         work_type=c['work_type'], destination=c['address'])
    drivers = sorted(by_driver.values(), key=lambda d: -rank.get(d['status'], -1))
    for d in drivers:
        d['job_count'] = len(d['jobs'])

    plotted = [c for c in calls if c['lat'] is not None and c['lon'] is not None]
    return {
        'calls': plotted,
        'drivers': drivers,
        'facilities': facility_ids,
        # surfaced so the UI can be honest rather than silently dropping rows
        'calls_total': len(calls),
        'calls_without_location': len(calls) - len(plotted),
        'drivers_without_location': len(calls) - len(drivers),
        # assignments skipped because the driver stopped reporting GPS
        'drivers_not_tracking': stale_drivers,
        # assignments skipped because the driver logged out of their truck
        'drivers_logged_out': logged_out_drivers,
    }


# ── GET /api/contractor/route ────────────────────────────────────────────────

# Public OSRM demo server: no key, no signup, no bill. It is a community box
# with no SLA, so every failure here is soft — the map simply draws no line
# rather than showing an error. Swapping in a paid router (Google Directions,
# Mapbox) means changing _osrm_leg() and nothing else.
OSRM_URL = 'https://router.project-osrm.org/route/v1/driving'
OSRM_TIMEOUT = 8

# The drop-off leg runs between two fixed addresses, so it is worth caching for
# the day. The driver leg is not cached: the truck is moving, which is the whole
# point of drawing it.
_ROUTE_TTL = 3600


def _osrm_leg(a: tuple, b: tuple) -> dict | None:
    """Street path between two (lat, lon) points, or None if unroutable.

    OSRM takes lon,lat and returns lon,lat; Leaflet wants lat,lon. The flip is
    the single easiest thing to get wrong here, so it happens in exactly one
    place.
    """
    if not a or not b or a[0] is None or b[0] is None:
        return None
    try:
        import requests
        r = requests.get(f"{OSRM_URL}/{a[1]},{a[0]};{b[1]},{b[0]}",
                         params={'overview': 'full', 'geometries': 'geojson'},
                         timeout=OSRM_TIMEOUT)
        d = r.json()
        if d.get('code') != 'Ok' or not d.get('routes'):
            log.info('osrm: no route (%s)', d.get('code'))
            return None
        rt = d['routes'][0]
        return {
            'coords': [[c[1], c[0]] for c in rt['geometry']['coordinates']],
            'miles': round(rt['distance'] / 1609.344, 1),
            'minutes': round(rt['duration'] / 60),
        }
    except Exception as exc:
        log.info('osrm: leg failed: %s', exc)
        return None


@router.get("/api/contractor/route")
def contractor_route(request: Request, sa_id: str = Query(..., description='ServiceAppointment Id')):
    """Street route for one call: driver → breakdown, and for a tow, breakdown → drop-off.

    Scoped to the caller's own facilities exactly like every other endpoint here
    — the Id alone must never be enough to route somebody else's call.
    """
    _require_flag()
    facility_ids = _require_contractor_facilities(request)
    f_clause = _facility_in_clause(facility_ids)
    sa_id = sanitize_soql(sa_id)

    rows = sf_query_all(f"""
        SELECT {_SA_FIELDS}
        FROM ServiceAppointment
        WHERE Id = '{sa_id}'
          AND ERS_Work_Order__r.Facility_ID__c IN ({f_clause})
    """)
    if not rows:
        raise HTTPException(status_code=404, detail="Call not found")

    call = _shape(rows[0])
    _attach_drivers([call])

    # The pickup leg starts wherever the truck is now. With no GPS there is no
    # honest starting point, so that leg is simply omitted.
    driver = (call.get('driver_lat'), call.get('driver_lon'))
    breakdown = (call.get('lat'), call.get('lon'))

    # A tow's other half lives on the same work order. Look it up only for tows,
    # and only when this call is the pick-up — routing onward from a drop-off
    # would draw a line to itself.
    dropoff = (None, None)
    wo = call.get('wo_number')
    if wo and call.get('work_type') == 'Tow Pick-Up':
        sibs = sf_query_all(f"""
            SELECT {_SA_FIELDS}
            FROM ServiceAppointment
            WHERE ERS_Work_Order__r.WorkOrderNumber = '{sanitize_soql(wo)}'
              AND WorkType.Name = 'Tow Drop-Off'
              AND ERS_Work_Order__r.Facility_ID__c IN ({f_clause})
        """)
        if sibs:
            d = _shape(sibs[0])
            dropoff = (d.get('lat'), d.get('lon'))

    to_breakdown = _osrm_leg(driver, breakdown)

    to_dropoff = None
    if dropoff[0] is not None:
        key = f"route_{round(breakdown[0], 4)}_{round(breakdown[1], 4)}_{round(dropoff[0], 4)}_{round(dropoff[1], 4)}"
        to_dropoff = cache.cached_query(key, lambda: _osrm_leg(breakdown, dropoff), ttl=_ROUTE_TTL)

    return {
        'sa_id': sa_id,
        'sa_number': call.get('sa_number'),
        'work_type': call.get('work_type'),
        'to_breakdown': to_breakdown,
        'to_dropoff': to_dropoff,
        # so the UI can say WHY a line is missing instead of silently drawing nothing
        'has_driver_gps': driver[0] is not None,
        'has_dropoff': dropoff[0] is not None,
    }
