"""Dispatch Assist — ONE query for nearby drivers.

Uses a single SOQL with nested subqueries to get:
  - All active drivers in the SA's territory (with GPS)
  - Each driver's skills (subquery)
  - Each driver's active assignments (subquery)

SA/customer info is passed from the frontend (already in watchlist data).
"""

import logging
import threading
import time

from fastapi import APIRouter, HTTPException

from sf_client import sf_query_all, sanitize_soql
from utils import haversine, TRAVEL_SPEED_MPH

router = APIRouter()
log = logging.getLogger('watchlist.assist')

# Cache dispatch-assist results for 30s per SA
_assist_cache: dict = {}  # sa_id -> (timestamp, result)
_assist_lock = threading.Lock()
_ASSIST_CACHE_TTL = 30

# Travel tier thresholds (minutes)
_TRAVEL_TIERS = [
    (10, 'tier1'), (20, 'tier2'), (30, 'tier3'),
    (40, 'tier4'), (50, 'tier5'), (60, 'tier6'),
]
MAX_TRAVEL_MIN = 60


def _travel_tier(travel_min: float) -> str:
    for threshold, tier in _TRAVEL_TIERS:
        if travel_min <= threshold:
            return tier
    return 'excluded'


@router.get("/api/watchlist/dispatch-assist")
def api_dispatch_assist(sa_id: str, territory: str = None, lat: float = None,
                        lon: float = None, work_type_id: str = None):
    """Get nearby available resources for a specific SA.

    Uses ONE SOQL query with nested subqueries for skills + assignments.
    SA info is passed via query params from frontend (already in watchlist).
    Results cached 30s per SA.
    """
    if not sa_id or len(sa_id) < 15:
        raise HTTPException(400, "Invalid sa_id")

    # Check 30s result cache (lock guards the check-then-write)
    with _assist_lock:
        cached = _assist_cache.get(sa_id)
        if cached:
            ts, result = cached
            if time.time() - ts < _ASSIST_CACHE_TTL:
                return result

    if not territory:
        raise HTTPException(400, "territory hint required")
    territory = sanitize_soql(territory)

    t0 = time.time()

    # ── ONE QUERY: drivers + skills + assignments ──
    rows = sf_query_all(f"""
        SELECT Id, Name, LastKnownLatitude, LastKnownLongitude,
               LastKnownLocationDate, ERS_Driver_Type__c, ERS_Tech_ID__c,
               RelatedRecord.Phone, IsActive,
               (SELECT Skill.MasterLabel
                FROM ServiceResourceSkills),
               (SELECT ServiceAppointmentId,
                       ServiceAppointment.StatusCategory,
                       ServiceAppointment.WorkType.Name,
                       ServiceAppointment.Status
                FROM ServiceAppointments
                WHERE ServiceAppointment.StatusCategory
                      IN ('Scheduled','Dispatched','InProgress')
                  AND ServiceAppointment.SchedStartTime >= TODAY)
        FROM ServiceResource
        WHERE Id IN (
            SELECT ServiceResourceId
            FROM ServiceTerritoryMember
            WHERE ServiceTerritoryId = '{territory}'
              AND ServiceResource.IsActive = true
              AND EffectiveStartDate <= TODAY
              AND (EffectiveEndDate = null OR EffectiveEndDate >= TODAY)
        )
          AND IsActive = true
    """)

    elapsed = (time.time() - t0) * 1000
    log.info(f"Dispatch assist for {sa_id}: {elapsed:.0f}ms (1 query, {len(rows)} drivers)")

    sa_lat = lat
    sa_lon = lon

    # Build driver list from single query results
    drivers = []
    for sr in rows:
        rid = sr.get('Id')
        if not rid:
            continue

        d_lat = sr.get('LastKnownLatitude')
        d_lon = sr.get('LastKnownLongitude')
        phone = (sr.get('RelatedRecord') or {}).get('Phone')
        name = sr.get('Name', '?')

        # Distance / travel time
        distance = None
        travel_min = None
        if sa_lat and sa_lon and d_lat and d_lon:
            distance = haversine(d_lat, d_lon, sa_lat, sa_lon)
            travel_min = round((distance / TRAVEL_SPEED_MPH) * 60, 1) if distance else None

        if travel_min is not None and travel_min > MAX_TRAVEL_MIN:
            continue

        # Skills from nested subquery
        skill_records = (sr.get('ServiceResourceSkills') or {}).get('records', [])
        d_skills = set()
        for s in skill_records:
            label = (s.get('Skill') or {}).get('MasterLabel', '').lower()
            if label:
                d_skills.add(label)

        # Active assignments from nested subquery
        ar_records = (sr.get('ServiceAppointments') or {}).get('records', [])
        busy_info = None
        priority = {'InProgress': 3, 'Dispatched': 2, 'Scheduled': 1}
        for ar in ar_records:
            sa_info = ar.get('ServiceAppointment') or {}
            cat = sa_info.get('StatusCategory', '')
            if not busy_info or priority.get(cat, 0) > priority.get(
                    busy_info.get('status_category', ''), 0):
                busy_info = {
                    'status_category': cat,
                    'status': sa_info.get('Status', ''),
                    'work_type': (sa_info.get('WorkType') or {}).get('Name', ''),
                }

        is_available = busy_info is None
        tier = _travel_tier(travel_min) if travel_min is not None else 'unknown'

        drivers.append({
            'resource_id': rid,
            'name': name,
            'phone': phone,
            'driver_type': sr.get('ERS_Driver_Type__c', ''),
            'latitude': d_lat,
            'longitude': d_lon,
            'distance_miles': round(distance, 1) if distance else None,
            'travel_min': travel_min,
            'travel_tier': tier,
            'has_required_skills': True,  # enriched by frontend if needed
            'skills': sorted(d_skills),
            'is_available': is_available,
            'current_status': 'available' if is_available else busy_info.get('status_category', 'busy'),
            'current_work_type': busy_info.get('work_type', '') if busy_info else '',
            'gps_date': sr.get('LastKnownLocationDate'),
            'tech_id': sr.get('ERS_Tech_ID__c'),
        })

    # Sort: available first, then by distance
    drivers.sort(key=lambda d: (
        not d['is_available'],
        d['distance_miles'] or 9999,
    ))

    result = {
        'channel': 'on-platform',
        'drivers': drivers,
        'total_in_territory': len(rows),
        'total_eligible': len(drivers),
    }

    # Cache result and evict stale entries
    with _assist_lock:
        _assist_cache[sa_id] = (time.time(), result)
        now = time.time()
        stale = [k for k, (ts, _) in _assist_cache.items() if now - ts > _ASSIST_CACHE_TTL * 2]
        for k in stale:
            _assist_cache.pop(k, None)

    return result
