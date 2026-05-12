"""Dispatch Assist — nearby drivers and garages for a flagged SA.

Normal mode (territory assigned):
  ONE SOQL with nested subqueries → drivers in SA's territory.

000 mode (facility starts with '000' — all cascade options exhausted):
  TWO parallel queries:
    1. Priority Matrix for the SA's original grid zone → ranked Towbook garages
    2. All active FSL drivers org-wide → filter by haversine distance
  Returns both lists so dispatcher sees garages to call + drivers to dispatch.
"""

import logging
import threading
import time

from fastapi import APIRouter, HTTPException

from sf_client import sf_query_all, sf_parallel, sanitize_soql
from utils import haversine, TRAVEL_SPEED_MPH, is_fleet_territory

router = APIRouter()
log = logging.getLogger('watchlist.assist')

# Cache dispatch-assist results per SA
# 120s: dispatchers re-open the panel within 2 min regularly; stale by 2 min is fine
_assist_cache: dict = {}  # sa_id -> (timestamp, result)
_assist_lock = threading.Lock()
_ASSIST_CACHE_TTL = 120

# Travel tier thresholds (minutes)
_TRAVEL_TIERS = [
    (10, 'tier1'), (20, 'tier2'), (30, 'tier3'),
    (40, 'tier4'), (50, 'tier5'), (60, 'tier6'),
]
MAX_TRAVEL_MIN = 60
MAX_RESULTS = 20

# Work type → required skill fragments (lowercase substring match against driver skill labels).
# A driver matches if ANY of their skills contains ANY of the listed fragments.
# Empty set = no specific skill requirement (show all drivers).
_WORK_TYPE_SKILLS: dict[str, set[str]] = {
    'tow':        {'tow', 'wheel lift', 'flat bed'},
    'tire':       {'tire'},
    'battery':    {'battery', 'jumpstart'},
    'lockout':    {'lockout', 'locksmith'},
    'locksmith':  {'locksmith'},
    'winch':      {'extrication', 'winch'},
    'fuel':       {'fuel'},
    'ev':         {'ev'},
}


def _required_skill_fragments(work_type: str) -> set[str]:
    """Return the set of skill label fragments required for this work type."""
    if not work_type:
        return set()
    wt = work_type.lower()
    frags: set[str] = set()
    for keyword, skill_frags in _WORK_TYPE_SKILLS.items():
        if keyword in wt:
            frags |= skill_frags
    return frags


def _skills_match(driver_skills: set[str], required_frags: set[str]) -> bool:
    """True if the driver has at least one skill matching any required fragment."""
    if not required_frags:
        return True
    return any(frag in skill for skill in driver_skills for frag in required_frags)


def _travel_tier(travel_min: float) -> str:
    for threshold, tier in _TRAVEL_TIERS:
        if travel_min <= threshold:
            return tier
    return 'excluded'


def _build_busy_map(ar_rows: list) -> dict:
    """Build {resource_id: busy_info} from flat AssignedResource rows.

    Flat AssignedResource query is 5-10x faster than a nested ServiceAppointments
    subquery because SF evaluates it as a single indexed scan, not per-row.
    """
    busy_map: dict = {}
    priority = {'InProgress': 3, 'Dispatched': 2, 'Scheduled': 1}
    for ar in ar_rows:
        rid = ar.get('ServiceResourceId')
        if not rid:
            continue
        sa_info = ar.get('ServiceAppointment') or {}
        cat = sa_info.get('StatusCategory', '')
        new_info = {
            'status_category': cat,
            'status': sa_info.get('Status', ''),
            'work_type': (sa_info.get('WorkType') or {}).get('Name', ''),
        }
        existing = busy_map.get(rid)
        if not existing or priority.get(cat, 0) > priority.get(existing.get('status_category', ''), 0):
            busy_map[rid] = new_info
    return busy_map


def _process_drivers(rows: list, sa_lat, sa_lon, busy_map: dict = None,
                     work_type: str = None) -> list:
    """Convert raw ServiceResource rows into ranked driver dicts.

    Filters:
      - Hard cap: travel > 60 min → excluded
      - No skills at all → excluded (placeholder/system accounts, not real dispatchable drivers)
      - Busy + no required skills → excluded (can't do the job and won't be free soon enough)

    Sort: skilled first → available first → closest first.
    """
    required_frags = _required_skill_fragments(work_type)
    drivers = []
    for sr in rows:
        rid = sr.get('Id')
        if not rid:
            continue

        d_lat = sr.get('LastKnownLatitude')
        d_lon = sr.get('LastKnownLongitude')
        phone = (sr.get('RelatedRecord') or {}).get('Phone')

        distance = None
        travel_min = None
        if sa_lat and sa_lon and d_lat and d_lon:
            distance = haversine(d_lat, d_lon, sa_lat, sa_lon)
            travel_min = round((distance / TRAVEL_SPEED_MPH) * 60, 1) if distance else None

        if travel_min is not None and travel_min > MAX_TRAVEL_MIN:
            continue

        skill_records = (sr.get('ServiceResourceSkills') or {}).get('records', [])
        d_skills = set()
        for s in skill_records:
            label = (s.get('Skill') or {}).get('MasterLabel', '').lower()
            if label:
                d_skills.add(label)

        has_skills = _skills_match(d_skills, required_frags)

        if not d_skills:
            continue  # skip drivers with no skills configured

        if busy_map is not None:
            busy_info = busy_map.get(rid)
        else:
            # Fallback: parse nested subquery (legacy / single-query path)
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

        # Drop busy drivers who lack required skills — they can't help even when free
        if not is_available and not has_skills and required_frags:
            continue

        tier = _travel_tier(travel_min) if travel_min is not None else 'unknown'

        drivers.append({
            'resource_id': rid,
            'name': sr.get('Name', '?'),
            'phone': phone,
            'driver_type': sr.get('ERS_Driver_Type__c', ''),
            'latitude': d_lat,
            'longitude': d_lon,
            'distance_miles': round(distance, 1) if distance else None,
            'travel_min': travel_min,
            'travel_tier': tier,
            'has_required_skills': has_skills,
            'skills': sorted(d_skills),
            'is_available': is_available,
            'current_status': 'available' if is_available else busy_info.get('status_category', 'busy'),
            'current_work_type': busy_info.get('work_type', '') if busy_info else '',
            'gps_date': sr.get('LastKnownLocationDate'),
            'tech_id': sr.get('ERS_Tech_ID__c'),
        })

    # Skilled → available → closest
    drivers.sort(key=lambda d: (not d['has_required_skills'], not d['is_available'], d['travel_min'] or 9999))
    return drivers


_TERRITORY_MEMBER_SUBQUERY = """
    SELECT ServiceResourceId FROM ServiceTerritoryMember
    WHERE ServiceTerritoryId = '{t}'
      AND ServiceResource.IsActive = true
      AND EffectiveStartDate <= TODAY
      AND (EffectiveEndDate = null OR EffectiveEndDate >= TODAY)
"""


def _fetch_territory_drivers(territory: str, sa_lat, sa_lon, work_type: str = None) -> dict:
    """Normal mode: two parallel queries instead of one slow nested query.

    Q1 — ServiceResource + skills (no appointment subquery → much smaller payload)
    Q2 — Flat AssignedResource for active SAs in territory (single indexed scan)
    Both filter by the same ServiceTerritoryMember subquery so they run simultaneously.
    """
    mem_sub = _TERRITORY_MEMBER_SUBQUERY.format(t=territory)

    def _q_drivers():
        return sf_query_all(f"""
            SELECT Id, Name, LastKnownLatitude, LastKnownLongitude,
                   LastKnownLocationDate, ERS_Driver_Type__c, ERS_Tech_ID__c,
                   RelatedRecord.Phone, IsActive,
                   (SELECT Skill.MasterLabel FROM ServiceResourceSkills)
            FROM ServiceResource
            WHERE Id IN ({mem_sub})
              AND IsActive = true
        """)

    def _q_busy():
        # Flat AssignedResource scan — StatusCategory index is sufficient,
        # SchedStartTime filter adds a second scan and is redundant here
        return sf_query_all(f"""
            SELECT ServiceResourceId,
                   ServiceAppointment.StatusCategory,
                   ServiceAppointment.WorkType.Name,
                   ServiceAppointment.Status
            FROM AssignedResource
            WHERE ServiceResourceId IN ({mem_sub})
              AND ServiceAppointment.StatusCategory IN ('Scheduled','Dispatched','InProgress')
        """)

    def _q_logged_in():
        return sf_query_all("""
            SELECT ERS_Driver__c
            FROM Asset
            WHERE RecordType.Name = 'ERS Truck'
              AND ERS_Driver__c != null
        """)

    def _q_absent():
        return sf_query_all("""
            SELECT ResourceId
            FROM ResourceAbsence
            WHERE Start <= TODAY AND End >= TODAY
        """)

    data = sf_parallel(drivers=_q_drivers, busy=_q_busy, logged_in=_q_logged_in, absent=_q_absent)
    busy_map = _build_busy_map(data['busy'])
    logged_in_ids = {a.get('ERS_Driver__c') for a in data['logged_in'] if a.get('ERS_Driver__c')}
    absent_ids = {a.get('ResourceId') for a in data['absent'] if a.get('ResourceId')}
    rows = [r for r in data['drivers'] if r.get('Id') in logged_in_ids and r.get('Id') not in absent_ids]
    drivers = _process_drivers(rows, sa_lat, sa_lon, busy_map=busy_map, work_type=work_type)
    return {
        'mode': 'normal',
        'channel': 'on-platform',
        'drivers': drivers[:MAX_RESULTS],
        'garages': [],
        'total_in_territory': len(rows),
        'total_eligible': len(drivers),
    }


def _fetch_000_resources(sa_lat, sa_lon, parent_territory_id: str, work_type: str = None) -> dict:
    """000 mode: all cascade options exhausted.

    Runs two queries in parallel:
      1. Priority Matrix for the SA's original grid zone → ranked Towbook garages
      2. All active FSL on-platform drivers org-wide → filter by distance
    """
    safe_ptid = sanitize_soql(parent_territory_id)

    def _q_garages():
        return sf_query_all(f"""
            SELECT ERS_Spotted_Territory__r.Id,
                   ERS_Spotted_Territory__r.Name,
                   ERS_Spotted_Territory__r.Latitude,
                   ERS_Spotted_Territory__r.Longitude,
                   ERS_Spotted_Territory__r.ERS_Facility_Account__r.Phone,
                   ERS_Priority__c
            FROM ERS_Territory_Priority_Matrix__c
            WHERE ERS_Parent_Service_Territory__c = '{safe_ptid}'
              AND ERS_Priority__c < 10
              AND ERS_Spotted_Territory__r.IsActive = true
            ORDER BY ERS_Priority__c
        """)

    def _q_fsl_drivers():
        # GPS freshness filter cuts the dataset to drivers who actually worked
        # in the last 2 days — excludes long-offline/inactive records
        return sf_query_all("""
            SELECT Id, Name, LastKnownLatitude, LastKnownLongitude,
                   LastKnownLocationDate, ERS_Driver_Type__c, ERS_Tech_ID__c,
                   RelatedRecord.Phone,
                   (SELECT Skill.MasterLabel FROM ServiceResourceSkills)
            FROM ServiceResource
            WHERE IsActive = true
              AND ERS_Driver_Type__c IN ('Fleet Driver', 'On-Platform Contractor Driver')
              AND LastKnownLatitude != null
              AND LastKnownLocationDate >= LAST_N_DAYS:2
        """)

    def _q_fsl_busy():
        # Scoped to FSL on-platform drivers + recent SAs only.
        # Without ERS_Driver_Type__c filter this scanned the entire org (~42s).
        # CreatedDate >= LAST_N_DAYS:2 matches the GPS freshness window in _q_fsl_drivers.
        return sf_query_all("""
            SELECT ServiceResourceId,
                   ServiceAppointment.StatusCategory,
                   ServiceAppointment.WorkType.Name,
                   ServiceAppointment.Status
            FROM AssignedResource
            WHERE ServiceAppointment.StatusCategory IN ('Scheduled','Dispatched','InProgress')
              AND ServiceResource.ERS_Driver_Type__c IN ('Fleet Driver', 'On-Platform Contractor Driver')
              AND ServiceResource.IsActive = true
              AND ServiceAppointment.CreatedDate >= LAST_N_DAYS:2
        """)

    def _q_logged_in():
        return sf_query_all("""
            SELECT ERS_Driver__c
            FROM Asset
            WHERE RecordType.Name = 'ERS Truck'
              AND ERS_Driver__c != null
        """)

    def _q_absent():
        return sf_query_all("""
            SELECT ResourceId
            FROM ResourceAbsence
            WHERE Start <= TODAY AND End >= TODAY
        """)

    data = sf_parallel(garages=_q_garages, fsl_drivers=_q_fsl_drivers, fsl_busy=_q_fsl_busy,
                       logged_in=_q_logged_in, absent=_q_absent)
    pm_rows = data['garages']
    logged_in_ids = {a.get('ERS_Driver__c') for a in data['logged_in'] if a.get('ERS_Driver__c')}
    absent_ids = {a.get('ResourceId') for a in data['absent'] if a.get('ResourceId')}
    sr_rows = [r for r in data['fsl_drivers'] if r.get('Id') in logged_in_ids and r.get('Id') not in absent_ids]

    # Build garage list from Priority Matrix
    garages = []
    seen_ids = set()
    for pm in pm_rows:
        st = pm.get('ERS_Spotted_Territory__r') or {}
        st_id = st.get('Id')
        st_name = st.get('Name', '')

        if not st_id or st_id in seen_ids:
            continue
        # Skip Fleet territories (covered by driver section) and special routing entries
        if is_fleet_territory(st_name) or st_name.startswith('LS') or st_name.startswith('000'):
            continue
        seen_ids.add(st_id)

        g_lat = st.get('Latitude')
        g_lon = st.get('Longitude')
        phone_raw = (st.get('ERS_Facility_Account__r') or {}).get('Phone') or ''
        # Normalise phone: strip non-digits for tel: links
        phone_digits = ''.join(c for c in phone_raw if c.isdigit())

        distance = haversine(g_lat, g_lon, sa_lat, sa_lon) if (g_lat and g_lon and sa_lat and sa_lon) else None
        travel_min = round((distance / TRAVEL_SPEED_MPH) * 60, 1) if distance else None

        garages.append({
            'territory_id': st_id,
            'name': st_name,
            'priority': int(pm.get('ERS_Priority__c', 10)),
            'phone': phone_digits,
            'phone_display': phone_raw,
            'latitude': g_lat,
            'longitude': g_lon,
            'distance_miles': round(distance, 1) if distance else None,
            'travel_min': travel_min,
        })

    garages.sort(key=lambda g: (g['priority'], g['distance_miles'] or 9999))

    busy_map = _build_busy_map(data['fsl_busy'])
    drivers = _process_drivers(sr_rows, sa_lat, sa_lon, busy_map=busy_map, work_type=work_type)

    return {
        'mode': 'geo_search',
        'channel': 'on-platform',
        'drivers': drivers[:MAX_RESULTS],
        'garages': garages[:MAX_RESULTS],
        'total_in_territory': len(sr_rows),
        'total_eligible': len(drivers),
    }


@router.get("/api/watchlist/dispatch-assist")
def api_dispatch_assist(sa_id: str, territory: str = None, lat: float = None,
                        lon: float = None, work_type: str = None,
                        parent_territory_id: str = None):
    """Get nearby resources for a flagged SA.

    Normal mode: drivers in the SA's territory (one SOQL).
    000 mode (parent_territory_id provided): ranked Towbook garages from Priority
    Matrix + all FSL drivers within 60-min range (two parallel SOQLs).
    Results cached 30s per SA.
    """
    if not sa_id or len(sa_id) < 15:
        raise HTTPException(400, "Invalid sa_id")

    with _assist_lock:
        cached = _assist_cache.get(sa_id)
        if cached:
            ts, result = cached
            if time.time() - ts < _ASSIST_CACHE_TTL:
                return result

    sa_lat = lat
    sa_lon = lon
    t0 = time.time()

    if parent_territory_id:
        # 000 mode: all cascade options exhausted — geo search
        result = _fetch_000_resources(sa_lat, sa_lon, parent_territory_id, work_type=work_type)
    else:
        if not territory:
            raise HTTPException(400, "territory hint required")
        result = _fetch_territory_drivers(sanitize_soql(territory), sa_lat, sa_lon, work_type=work_type)

    elapsed = (time.time() - t0) * 1000
    log.info(
        f"Dispatch assist {sa_id} mode={result['mode']}: {elapsed:.0f}ms "
        f"({len(result['drivers'])} drivers, {len(result['garages'])} garages)"
    )

    with _assist_lock:
        _assist_cache[sa_id] = (time.time(), result)
        now = time.time()
        stale = [k for k, (ts, _) in _assist_cache.items() if now - ts > _ASSIST_CACHE_TTL * 2]
        for k in stale:
            _assist_cache.pop(k, None)

    return result
