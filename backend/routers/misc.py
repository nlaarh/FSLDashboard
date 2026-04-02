"""Miscellaneous standalone endpoints: health, sync, GPS health, SA lookup,
scheduler insights, features, territory forecast."""

import os
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Query

from utils import (
    _ET, parse_dt as _parse_dt, to_eastern as _to_eastern,
    haversine,
)
from sf_client import sf_query_all, sf_parallel, get_stats as sf_stats, sanitize_soql
from dispatch_utils import fetch_gps_history, gps_at_time, parse_assign_events
import cache

router = APIRouter()


# ── Health ───────────────────────────────────────────────────────────────────

@router.get("/api/health")
def health():
    return {"status": "ok", "db_seeded": True, "sync_in_progress": False,
            "cache": cache.stats(), "salesforce": sf_stats()}


@router.post("/api/warmup")
def warmup():
    """Force-warm all cache keys synchronously. Called by deploy script after deployment.

    Ensures the first real user never waits for cold SF queries.
    Returns once all hot keys are populated.
    """
    import refresher
    schedule = refresher._get_schedule()
    warmed = 0
    for interval, key, fn, persist in schedule:
        try:
            fn()  # calls the endpoint → cached_query → cold-starts if needed
            warmed += 1
        except Exception:
            pass
    return {"status": "warmed", "keys": warmed, "total": len(schedule)}


# ── Compat endpoints (frontend expects these) ───────────────────────────────

@router.get("/api/db/status")
def db_status():
    return {"seeded": True, "db_size_mb": 0, "tables": [], "mode": "live_sf"}


@router.post("/api/sync")
def run_sync():
    cache.invalidate()
    return {"status": "cache_cleared", "message": "In-memory cache cleared. All data live from SF."}


# ── GPS Health ────────────────────────────────────────────────────────────────

@router.get("/api/gps-health")
def gps_health():
    """GPS health for field drivers only (ERS_Driver_Type__c is set)."""
    from datetime import timezone as _tz
    def _fetch():
        drivers = sf_query_all("""
            SELECT Id, Name, ERS_Driver_Type__c,
                   LastKnownLatitude, LastKnownLongitude, LastKnownLocationDate
            FROM ServiceResource
            WHERE IsActive = true AND ResourceType = 'T'
              AND ERS_Driver_Type__c IN ('Fleet Driver', 'On-Platform Contractor Driver')
        """)
        now = datetime.now(_tz.utc)
        buckets = {'fleet': {}, 'on_platform': {}, 'off_platform': {}}
        type_map = {
            'Fleet Driver': 'fleet',
            'On-Platform Contractor Driver': 'on_platform',
            'Off-Platform Contractor Driver': 'off_platform',
        }
        for key in buckets:
            buckets[key] = {'total': 0, 'fresh': 0, 'recent': 0, 'stale': 0, 'no_gps': 0}

        for d in drivers:
            dtype = type_map.get(d.get('ERS_Driver_Type__c'))
            if not dtype:
                continue
            b = buckets[dtype]
            b['total'] += 1
            lat = d.get('LastKnownLatitude')
            lkd = d.get('LastKnownLocationDate')
            if not lat:
                b['no_gps'] += 1
                continue
            if lkd:
                age = now - _parse_dt(lkd)
                if age < timedelta(hours=4):
                    b['fresh'] += 1
                elif age < timedelta(hours=24):
                    b['recent'] += 1
                else:
                    b['stale'] += 1
            else:
                b['stale'] += 1

        total = sum(b['total'] for b in buckets.values())
        fresh = sum(b['fresh'] for b in buckets.values())
        recent = sum(b['recent'] for b in buckets.values())
        stale = sum(b['stale'] for b in buckets.values())
        no_gps = sum(b['no_gps'] for b in buckets.values())
        usable = fresh + recent
        usable_pct = round(100 * usable / max(total, 1)) if total else 0

        return {
            'total': total,
            'fresh': fresh,
            'recent': recent,
            'stale': stale,
            'no_gps': no_gps,
            'usable': usable,
            'usable_pct': usable_pct,
            'by_type': buckets,
        }

    return cache.cached_query('gps_health', _fetch, ttl=300)  # 5 min — drivers log in/out frequently


# ── SA Lookup — Zoom-to with Driver Positions ────────────────────────────────

@router.get("/api/sa/{sa_number}")
def lookup_sa(sa_number: str):
    """Lookup an SA by AppointmentNumber and return driver positions."""
    sa_number = sanitize_soql(sa_number)
    # Accept both "717120" and "SA-717120"
    if not sa_number.upper().startswith('SA-'):
        sa_number = f'SA-{sa_number}'
    def _fetch():
        return _lookup_sa_impl(sa_number)
    result = cache.cached_query(f'sa_lookup_{sa_number}', _fetch, ttl=30)
    if result is None:
        raise HTTPException(status_code=404, detail=f"SA {sa_number} not found")
    return result


_SKILL_MAP = {
    'tow':         ['tow', 'flat bed', 'flatbed'],
    'battery':     ['battery'],
    'tire':        ['tire'],
    'lockout':     ['lockout'],
    'fuel':        ['fuel', 'light'],
    'winch':       ['winch', 'light'],
    'extrication': ['extrication'],
}


def _fetch_sa_core(sa: dict) -> dict | None:
    """Fetch territory, member, skill, and GPS data for an SA.

    Shared by _lookup_sa_impl (map popup) and the SA Report endpoint.
    Returns a data bag with raw SF rows and derived helpers, or None if the
    territory has no fleet members (e.g. Towbook-only territory).

    Args:
        sa: Raw ServiceAppointment row with at minimum:
            Id, ServiceTerritoryId, WorkType.Name, CreatedDate,
            Latitude, Longitude, ERS_Dispatched_Geolocation__*_s
    """
    from sf_client import sf_parallel as _sf_par, sf_query_all as _sqa_local
    from collections import defaultdict as _dd

    tid = sa.get('ServiceTerritoryId')
    if not tid:
        return None

    sa_id = sa['Id']
    wt_name = (sa.get('WorkType') or {}).get('Name', '').lower()
    sa_lat = float(sa['Latitude']) if sa.get('Latitude') else None
    sa_lon = float(sa['Longitude']) if sa.get('Longitude') else None
    disp_lat = sa.get('ERS_Dispatched_Geolocation__Latitude__s')
    disp_lon = sa.get('ERS_Dispatched_Geolocation__Longitude__s')

    # ── Parallel fetch: AR, SAHistory, territory members ────────────────────
    def _get_ar():
        return _sqa_local(f"""
            SELECT ServiceResourceId, ServiceResource.Name, CreatedDate
            FROM AssignedResource
            WHERE ServiceAppointmentId = '{sa_id}'
            ORDER BY CreatedDate DESC LIMIT 1
        """)

    def _get_sa_hist():
        return _sqa_local(f"""
            SELECT ServiceAppointmentId, NewValue, CreatedDate,
                   CreatedBy.Name, CreatedBy.Profile.Name
            FROM ServiceAppointmentHistory
            WHERE ServiceAppointmentId = '{sa_id}'
              AND Field = 'ERS_Assigned_Resource__c'
            ORDER BY CreatedDate ASC
        """)

    def _get_members():
        return _sqa_local(f"""
            SELECT ServiceResourceId, ServiceResource.Name,
                   ServiceResource.IsActive, TerritoryType
            FROM ServiceTerritoryMember
            WHERE ServiceTerritoryId = '{tid}'
              AND TerritoryType IN ('P', 'S')
              AND ServiceResource.IsActive = true
              AND ServiceResource.ResourceType = 'T'
        """)

    first = _sf_par(ar=_get_ar, sa_hist=_get_sa_hist, members=_get_members)

    ar_row = first['ar'][0] if first['ar'] else None
    assigned_sr_id = ar_row.get('ServiceResourceId') if ar_row else None

    # True dispatch time = first SAHistory row (not AR.CreatedDate, which reflects
    # the FINAL assignment after any reassignments)
    assign_events_map = parse_assign_events(first['sa_hist'])
    sa_events = assign_events_map.get(sa_id, [])
    dispatch_dt = (sa_events[0]['ts'] if sa_events else None) or _parse_dt(sa.get('CreatedDate'))

    # Filter out Towbook placeholder members
    members = [m for m in first['members']
               if not ((m.get('ServiceResource') or {}).get('Name') or '').lower().startswith('towbook')]

    # Cascade fallback: if the SA's current territory has no fleet members (e.g. it was
    # cascaded from a Fleet territory to a Towbook garage), look back in SAHistory
    # for the original fleet territory. Field name is 'ServiceTerritory' (not 'ServiceTerritoryId').
    if not members:
        tid_hist = _sqa_local(f"""
            SELECT OldValue, NewValue
            FROM ServiceAppointmentHistory
            WHERE ServiceAppointmentId = '{sa_id}'
              AND Field = 'ServiceTerritory'
            ORDER BY CreatedDate ASC
        """)
        # First row with OldValue=null has NewValue=original territory ID
        original_tid = None
        for h in tid_hist:
            if h.get('OldValue') is None:
                nv = h.get('NewValue') or ''
                if len(nv) >= 15 and nv.startswith('0H'):
                    original_tid = nv
                    break
        if original_tid and original_tid != tid:
            orig_members_raw = _sqa_local(f"""
                SELECT ServiceResourceId, ServiceResource.Name,
                       ServiceResource.IsActive, TerritoryType
                FROM ServiceTerritoryMember
                WHERE ServiceTerritoryId = '{original_tid}'
                  AND TerritoryType IN ('P', 'S')
                  AND ServiceResource.IsActive = true
                  AND ServiceResource.ResourceType = 'T'
            """)
            members = [m for m in orig_members_raw
                       if not ((m.get('ServiceResource') or {}).get('Name') or '').lower().startswith('towbook')]

    if not members:
        return None

    all_sr_ids = list({m.get('ServiceResourceId') for m in members if m.get('ServiceResourceId')})
    if assigned_sr_id and assigned_sr_id not in all_sr_ids:
        all_sr_ids.append(assigned_sr_id)

    # ── Skill filtering ──────────────────────────────────────────────────────
    required_skills = []
    for kw, skills in _SKILL_MAP.items():
        if kw in wt_name:
            required_skills.extend(skills)

    ids_quoted = ', '.join(f"'{i}'" for i in all_sr_ids)

    def _get_skills():
        if not required_skills:
            return []
        cond = ' OR '.join(f"Skill.MasterLabel LIKE '%{s.title()}%'" for s in required_skills)
        return _sqa_local(f"""
            SELECT ServiceResourceId, Skill.MasterLabel
            FROM ServiceResourceSkill
            WHERE ServiceResourceId IN ({ids_quoted})
              AND ({cond})
              AND (EffectiveStartDate = null OR EffectiveStartDate <= TODAY)
              AND (EffectiveEndDate = null OR EffectiveEndDate >= TODAY)
        """)

    skill_rows = _get_skills()

    # Build both a filtered set (for map display) and a full dict (for build_assign_steps)
    driver_skills = _dd(set)
    for r in skill_rows:
        sr_id = r.get('ServiceResourceId')
        lbl = (r.get('Skill') or {}).get('MasterLabel', '')
        if sr_id and lbl:
            driver_skills[sr_id].add(lbl)

    if required_skills:
        skilled_ids = {sr_id for sr_id in driver_skills}
        if assigned_sr_id:
            skilled_ids.add(assigned_sr_id)
    else:
        skilled_ids = set(all_sr_ids)

    # ── GPS history around dispatch time ────────────────────────────────────
    # 15-min lookback: only show drivers actively on Track at the moment of dispatch.
    # A driver with GPS older than 15 min has likely logged off their vehicle.
    # The 5-min forward buffer handles slight clock skew between Track and SF.
    if dispatch_dt:
        hist_start = (dispatch_dt - timedelta(minutes=15)).strftime('%Y-%m-%dT%H:%M:%SZ')
        hist_end   = (dispatch_dt + timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%SZ')
        lat_hist, lon_hist = fetch_gps_history(list(skilled_ids), hist_start, hist_end)
    else:
        lat_hist, lon_hist = _dd(list), _dd(list)

    # Name map (members + assigned driver if external)
    name_map = {m.get('ServiceResourceId'): (m.get('ServiceResource') or {}).get('Name', '?')
                for m in members}
    if ar_row and assigned_sr_id:
        name_map[assigned_sr_id] = (ar_row.get('ServiceResource') or {}).get('Name',
                                    name_map.get(assigned_sr_id, '?'))

    return {
        'sa':             sa,
        'ar_row':         ar_row,
        'assigned_sr_id': assigned_sr_id,
        'sa_events':      sa_events,
        'dispatch_dt':    dispatch_dt,
        'members':        members,
        'all_sr_ids':     all_sr_ids,
        'skilled_ids':    skilled_ids,
        'driver_skills':  dict(driver_skills),
        'name_map':       name_map,
        'lat_hist':       lat_hist,
        'lon_hist':       lon_hist,
        'required_skills': required_skills,
        'disp_lat':       disp_lat,
        'disp_lon':       disp_lon,
        'sa_lat':         sa_lat,
        'sa_lon':         sa_lon,
    }


def _lookup_sa_impl(sa_number: str):
    sa_list = sf_query_all(f"""
        SELECT Id, AppointmentNumber, Status, CreatedDate,
               ActualStartTime, ActualEndTime,
               Latitude, Longitude, Street, City, State, PostalCode,
               WorkType.Name, ServiceTerritoryId, ServiceTerritory.Name,
               Off_Platform_Truck_Id__c, ERS_PTA__c,
               ERS_Dispatched_Geolocation__Latitude__s,
               ERS_Dispatched_Geolocation__Longitude__s
        FROM ServiceAppointment
        WHERE AppointmentNumber = '{sa_number}'
        LIMIT 1
    """)
    if not sa_list:
        return None

    sa = sa_list[0]
    tid = sa.get('ServiceTerritoryId')
    et = _to_eastern(sa.get('CreatedDate'))
    start_et = _to_eastern(sa.get('ActualStartTime'))
    end_et = _to_eastern(sa.get('ActualEndTime'))

    cd = _parse_dt(sa.get('CreatedDate'))
    ast = _parse_dt(sa.get('ActualStartTime'))
    response_min = None
    if cd and ast:
        diff = (ast - cd).total_seconds() / 60
        if 0 < diff < 1440:
            response_min = round(diff)

    result = {
        'sa': {
            'id': sa['Id'],
            'number': sa.get('AppointmentNumber'),
            'status': sa.get('Status'),
            'work_type': (sa.get('WorkType') or {}).get('Name', '?'),
            'customer': '',
            'phone': '',
            'address': f"{sa.get('Street') or ''} {sa.get('City') or ''} {sa.get('State') or ''}".strip(),
            'zip': sa.get('PostalCode') or '',
            'lat': sa.get('Latitude'),
            'lon': sa.get('Longitude'),
            'territory': (sa.get('ServiceTerritory') or {}).get('Name', '?'),
            'territory_id': tid,
            'truck_id': sa.get('Off_Platform_Truck_Id__c') or '',
            'pta': sa.get('ERS_PTA__c'),
            'created': et.strftime('%I:%M %p') if et else '?',
            'started': start_et.strftime('%I:%M %p') if start_et else None,
            'completed': end_et.strftime('%I:%M %p') if end_et else None,
            'response_min': response_min,
            'dispatched_lat': sa.get('ERS_Dispatched_Geolocation__Latitude__s'),
            'dispatched_lon': sa.get('ERS_Dispatched_Geolocation__Longitude__s'),
        },
        'drivers': [],
    }

    core = _fetch_sa_core(sa)
    if not core:
        return result

    assigned_sr_id = core['assigned_sr_id']
    disp_lat, disp_lon = core['disp_lat'], core['disp_lon']
    sa_lat, sa_lon = core['sa_lat'], core['sa_lon']
    dispatch_dt = core['dispatch_dt']

    for sr_id in core['skilled_ids']:
        is_assigned = (sr_id == assigned_sr_id)

        if is_assigned and disp_lat and disp_lon:
            d_lat, d_lon = float(disp_lat), float(disp_lon)
            gps_label = 'at dispatch'
        else:
            d_lat, d_lon = gps_at_time(sr_id, dispatch_dt, core['lat_hist'], core['lon_hist'])
            if d_lat is None or d_lon is None:
                continue
            gps_label = dispatch_dt.strftime('%I:%M %p') if dispatch_dt else '?'

        dist = haversine(d_lat, d_lon, sa_lat, sa_lon) if d_lat and d_lon and sa_lat and sa_lon else None

        result['drivers'].append({
            'id': sr_id,
            'name': core['name_map'].get(sr_id, '?'),
            'phone': '',
            'lat': d_lat,
            'lon': d_lon,
            'gps_time': gps_label,
            'distance': round(dist, 1) if dist else None,
            'territory_type': next((m.get('TerritoryType', '') for m in core['members']
                                    if m.get('ServiceResourceId') == sr_id), ''),
            'truck': '',
            'truck_capabilities': '',
            'next_job': None,
            'is_assigned': is_assigned,
        })

    result['drivers'].sort(key=lambda d: (0 if d['is_assigned'] else 1, d.get('distance') or 9999))
    return result


# ── Feature Flags ────────────────────────────────────────────────────────────

_DEFAULT_FEATURES = {
    'pta_advisor': True,
    'onroute': True,
    'matrix': True,
    'chat': True,
}

def _load_settings():
    try:
        import database
        return database.get_all_settings()
    except Exception:
        return {}


@router.get("/api/features")
def get_features():
    """Return feature flags + configurable URLs. Public (no auth) — UI needs this."""
    settings = _load_settings()
    return {
        **_DEFAULT_FEATURES,
        **settings.get('features', {}),
        'help_video_url': settings.get('help_video_url', 'https://youtu.be/WovtITtz7Z0'),
    }
