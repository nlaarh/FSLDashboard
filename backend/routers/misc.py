"""Miscellaneous standalone endpoints: health, sync, GPS health, SA lookup,
scheduler insights, features, territory forecast."""

import os
import json as _json
import math as _math
from datetime import datetime, date, timedelta, timezone
from collections import defaultdict, Counter
from fastapi import APIRouter, HTTPException, Query

from utils import (
    _ET, parse_dt as _parse_dt, to_eastern as _to_eastern,
    haversine,
)
from sf_client import sf_query_all, sf_parallel, get_stats as sf_stats, sanitize_soql
import cache

router = APIRouter()


# ── Health ───────────────────────────────────────────────────────────────────

@router.get("/api/health")
def health():
    return {"status": "ok", "db_seeded": True, "sync_in_progress": False,
            "cache": cache.stats(), "salesforce": sf_stats()}


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

    return cache.cached_query('gps_health', _fetch, ttl=3600)


# ── SA Lookup — Zoom-to with Driver Positions ────────────────────────────────

@router.get("/api/sa/{sa_number}")
def lookup_sa(sa_number: str):
    """Lookup an SA by AppointmentNumber and return driver positions."""
    sa_number = sanitize_soql(sa_number)
    def _fetch():
        return _lookup_sa_impl(sa_number)
    result = cache.cached_query(f'sa_lookup_{sa_number}', _fetch, ttl=30)
    if result is None:
        raise HTTPException(status_code=404, detail=f"SA {sa_number} not found")
    return result


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

    # Live driver GPS — only drivers logged into a vehicle
    if tid:
        from sf_client import sf_parallel as _sf_par, sf_query_all as _sqa_local

        def _get_members():
            return _sqa_local(f"""
                SELECT ServiceResourceId, ServiceResource.Name,
                       ServiceResource.LastKnownLatitude,
                       ServiceResource.LastKnownLongitude,
                       ServiceResource.LastKnownLocationDate,
                       TerritoryType
                FROM ServiceTerritoryMember
                WHERE ServiceTerritoryId = '{tid}'
            """)

        def _get_vehicles():
            return _sqa_local("""
                SELECT ERS_Driver__c, Name, ERS_Truck_Capabilities__c
                FROM Asset
                WHERE RecordType.Name = 'ERS Truck'
                  AND ERS_Driver__c != null
            """)

        fetched = _sf_par(members=_get_members, vehicles=_get_vehicles)
        members = fetched['members']
        members = [m for m in members
                    if not ((m.get('ServiceResource') or {}).get('Name') or '').lower().startswith('towbook')]

        # Build vehicle login set
        vehicle_login_ids = set()
        vehicle_info = {}
        for asset in fetched['vehicles']:
            dr_id = asset.get('ERS_Driver__c')
            if dr_id:
                vehicle_login_ids.add(dr_id)
                vehicle_info[dr_id] = {
                    'truck': asset.get('Name', ''),
                    'capabilities': asset.get('ERS_Truck_Capabilities__c', ''),
                }

        sa_lat = sa.get('Latitude')
        sa_lon = sa.get('Longitude')
        if sa_lat: sa_lat = float(sa_lat)
        if sa_lon: sa_lon = float(sa_lon)

        for m in members:
            sr = m.get('ServiceResource') or {}
            sr_id = m.get('ServiceResourceId')
            # Only include drivers logged into a vehicle
            if sr_id not in vehicle_login_ids:
                continue
            d_lat = sr.get('LastKnownLatitude')
            d_lon = sr.get('LastKnownLongitude')
            if d_lat: d_lat = float(d_lat)
            if d_lon: d_lon = float(d_lon)
            dist = haversine(d_lat, d_lon, sa_lat, sa_lon) if d_lat and d_lon and sa_lat and sa_lon else None

            gps_date = _to_eastern(sr.get('LastKnownLocationDate'))
            truck = vehicle_info.get(sr_id, {})
            result['drivers'].append({
                'id': sr_id,
                'name': sr.get('Name', '?'),
                'phone': '',
                'lat': d_lat,
                'lon': d_lon,
                'gps_time': gps_date.strftime('%I:%M %p') if gps_date else '?',
                'distance': dist,
                'territory_type': m.get('TerritoryType', '?'),
                'truck': truck.get('truck', ''),
                'truck_capabilities': truck.get('capabilities', ''),
                'next_job': None,
            })

        result['drivers'].sort(key=lambda d: d.get('distance') or 9999)

    return result


# ── Scheduler Insights — Auto vs Manual + Dispatch Quality ───────────────────

_SYSTEM_DISPATCHERS = {
    'it system user', 'mulesoft integration', 'replicant integration user',
    'automated process', 'system', 'fsl optimizer',
}

def _is_system_dispatcher(name: str) -> bool:
    """True if the dispatcher is a system/automation user, not a human."""
    n = (name or '').strip().lower()
    return n in _SYSTEM_DISPATCHERS or 'integration' in n or 'system' in n or 'automated' in n


def _haversine_mi(lat1, lon1, lat2, lon2):
    R = 3958.8  # Earth radius in miles
    dlat = _math.radians(lat2 - lat1)
    dlon = _math.radians(lon2 - lon1)
    a = _math.sin(dlat/2)**2 + _math.cos(_math.radians(lat1)) * _math.cos(_math.radians(lat2)) * _math.sin(dlon/2)**2
    return round(R * 2 * _math.atan2(_math.sqrt(a), _math.sqrt(1-a)), 1)


@router.get("/api/scheduler-insights")
def scheduler_insights():
    """Scheduler decision quality based on SA history — who actually dispatched. Today from midnight ET; falls back to last 24h if today is empty."""
    now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(_ET)
    today_cutoff = now_et.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    fallback_cutoff = (now_utc - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ')
    cutoff_utc = today_cutoff  # will switch to fallback if today is empty

    def _fetch():
        from sf_client import sf_parallel
        nonlocal cutoff_utc

        # 1) Parallel fetch: today's fleet + Towbook SAs, assigned resources, all drivers w/ GPS, territory members, Asset login
        def _get_sas():
            return sf_query_all(f"""
                SELECT Id, AppointmentNumber, Status, CreatedDate,
                       ActualStartTime, SchedStartTime,
                       ERS_Dispatch_Method__c, Latitude, Longitude,
                       ERS_Dispatched_Geolocation__Latitude__s,
                       ERS_Dispatched_Geolocation__Longitude__s,
                       ServiceTerritoryId, ServiceTerritory.Name,
                       WorkType.Name
                FROM ServiceAppointment
                WHERE CreatedDate >= {cutoff_utc}
                  AND ServiceTerritoryId != null
                  AND ERS_Dispatch_Method__c IN ('Field Services', 'Towbook')
                  AND Status IN ('Dispatched','Completed','Assigned')
                ORDER BY CreatedDate ASC
            """)

        def _get_assigned():
            return sf_query_all(f"""
                SELECT ServiceAppointmentId, ServiceResourceId,
                       ServiceResource.Name,
                       ServiceResource.LastKnownLatitude,
                       ServiceResource.LastKnownLongitude,
                       ServiceResource.ERS_Driver_Type__c
                FROM AssignedResource
                WHERE ServiceAppointment.CreatedDate >= {cutoff_utc}
                  AND ServiceAppointment.ERS_Dispatch_Method__c IN ('Field Services', 'Towbook')
            """)

        def _get_drivers():
            return sf_query_all("""
                SELECT Id, Name, LastKnownLatitude, LastKnownLongitude
                FROM ServiceResource
                WHERE IsActive = true AND ResourceType = 'T'
                  AND LastKnownLatitude != null
                  AND ERS_Driver_Type__c IN ('Fleet Driver', 'On-Platform Contractor Driver')
                  AND (NOT Name LIKE 'Towbook%')
                  AND (NOT Name LIKE 'Test %')
                  AND (NOT Name LIKE '000-%')
                  AND (NOT Name LIKE '0 %')
                  AND (NOT Name LIKE '100A %')
                  AND Name != 'Travel User'
            """)

        def _get_members():
            return sf_query_all("""
                SELECT ServiceResourceId, ServiceTerritoryId, TerritoryType
                FROM ServiceTerritoryMember
                WHERE TerritoryType IN ('P','S')
                  AND ServiceResource.IsActive = true
                  AND ServiceResource.ResourceType = 'T'
                  AND ServiceResource.ERS_Driver_Type__c IN ('Fleet Driver', 'On-Platform Contractor Driver')
            """)

        def _get_trucks():
            """On-shift drivers from Asset for filtering comparison pool."""
            return sf_query_all("""
                SELECT ERS_Driver__c
                FROM Asset
                WHERE RecordType.Name = 'ERS Truck'
                  AND ERS_Driver__c != null
            """)

        data = sf_parallel(
            sas=_get_sas,
            assigned=_get_assigned,
            drivers=_get_drivers,
            members=_get_members,
            trucks=_get_trucks,
        )

        sas_raw = data['sas']
        assigned_raw = data['assigned']
        all_drivers = data['drivers']
        members_raw = data['members']
        # On-shift driver IDs from Asset
        on_shift_ids = {t.get('ERS_Driver__c') for t in data['trucks'] if t.get('ERS_Driver__c')}

        # Exclude Tow Drop-Off
        sas = [s for s in sas_raw if 'drop' not in ((s.get('WorkType') or {}).get('Name', '') or '').lower()]

        # Fallback: if today has no data at all, use last 24h
        is_fallback = False
        if not sas and cutoff_utc == today_cutoff:
            cutoff_utc = fallback_cutoff
            is_fallback = True
            fb_data = sf_parallel(sas=_get_sas, assigned=_get_assigned)
            sas_raw = fb_data['sas']
            assigned_raw = fb_data['assigned']
            sas = [s for s in sas_raw if 'drop' not in ((s.get('WorkType') or {}).get('Name', '') or '').lower()]

        empty = {'total': 0, 'auto_count': 0, 'manual_count': 0, 'auto_pct': 0,
                 'auto_avg_response': None, 'manual_avg_response': None,
                 'auto_avg_speed': None, 'manual_avg_speed': None,
                 'auto_sla': None, 'manual_sla': None,
                 'closest_pct': None, 'closest_evaluated': 0,
                 'dispatchers': [], 'is_fallback': False}
        if not sas:
            return empty

        sa_by_id = {s['Id']: s for s in sas}
        sa_ids = list(sa_by_id.keys())

        # Build lookup: SA → assigned driver ID
        sa_to_driver = {}
        for ar in assigned_raw:
            sa_id = ar.get('ServiceAppointmentId')
            dr_id = ar.get('ServiceResourceId')
            if sa_id and dr_id:
                sa_to_driver[sa_id] = dr_id

        # Build lookup: driver ID → GPS.  Fleet drivers report GPS via FSL mobile app
        # (LastKnownLatitude/Longitude).  If they have coords, they're active.
        # The _get_drivers query already filters: IsActive, ResourceType=T,
        # Fleet Driver / Transit Auto Detail types, excludes Towbook/Test/placeholder names.
        fleet_driver_gps = {}
        for d in all_drivers:
            lat, lon = d.get('LastKnownLatitude'), d.get('LastKnownLongitude')
            if lat and lon:
                fleet_driver_gps[d['Id']] = (float(lat), float(lon))

        # Build lookup: territory → fleet driver IDs with GPS
        territory_drivers = defaultdict(set)
        for m in members_raw:
            tid = m.get('ServiceTerritoryId')
            dr_id = m.get('ServiceResourceId')
            if tid and dr_id and dr_id in fleet_driver_gps:
                territory_drivers[tid].add(dr_id)

        # 2) Batch query ServiceAppointmentHistory for status changes
        #    Human intervention = a Membership User (dispatcher) made ANY status
        #    change on the SA. Dispatchers use the full workflow (Assigned → Spotted
        #    → Dispatched) so checking only 'Dispatched' undercounts.
        #    Verified: ~40% of all SAs have human touches (Jan-Mar 2026).
        dispatched_by = {}          # sa_id -> {'name': str, 'profile': str} (who set 'Dispatched')
        human_touched = set()       # sa_ids where a Membership User made ANY status change
        batch_size = 150
        for i in range(0, len(sa_ids), batch_size):
            batch = sa_ids[i:i + batch_size]
            id_str = "','".join(batch)
            rows = sf_query_all(f"""
                SELECT ServiceAppointmentId, CreatedBy.Name,
                       CreatedBy.Profile.Name, NewValue
                FROM ServiceAppointmentHistory
                WHERE ServiceAppointmentId IN ('{id_str}')
                  AND Field = 'Status'
            """)
            for r in rows:
                sa_id = r.get('ServiceAppointmentId')
                cb = r.get('CreatedBy') or {}
                name = cb.get('Name', '?')
                profile = (cb.get('Profile') or {}).get('Name', '')
                nv = r.get('NewValue', '')
                if nv == 'Dispatched':
                    dispatched_by[sa_id] = {'name': name, 'profile': profile}
                # Any status change by a dispatcher = human intervention
                if profile == 'Membership User':
                    human_touched.add(sa_id)

        # 3) Classify each SA — human intervention applies to ALL channels
        #    (fleet, Towbook, contractor). If a dispatcher touched it, it's manual.
        auto_sas, manual_sas, towbook_sas, towbook_human_sas = [], [], [], []
        for s in sas:
            dispatch_method = s.get('ERS_Dispatch_Method__c') or ''
            human = s['Id'] in human_touched
            if dispatch_method == 'Towbook':
                if human:
                    towbook_human_sas.append(s)
                else:
                    towbook_sas.append(s)
            elif human:
                manual_sas.append(s)
            else:
                auto_sas.append(s)

        auto_count = len(auto_sas)
        manual_count = len(manual_sas)
        towbook_count = len(towbook_sas) + len(towbook_human_sas)
        towbook_auto_count = len(towbook_sas)
        towbook_human_count = len(towbook_human_sas)
        fleet_total = auto_count + manual_count
        total = fleet_total + towbook_count
        auto_pct = round(100 * auto_count / max(fleet_total, 1))
        # No-human-intervention = SAs where no Membership User made any status change
        no_human_count = auto_count + towbook_auto_count
        human_count = manual_count + towbook_human_count
        no_human_pct = round(100 * no_human_count / max(total, 1))

        # 4) Avg response time: auto vs manual (completed only)
        def _response_times(sa_list):
            times = []
            for s in sa_list:
                if s.get('Status') != 'Completed':
                    continue
                c = _parse_dt(s.get('CreatedDate'))
                a = _parse_dt(s.get('ActualStartTime'))
                if c and a:
                    diff = (a - c).total_seconds() / 60
                    if 0 < diff < 480:
                        times.append(diff)
            return times

        auto_times = _response_times(auto_sas)
        manual_times = _response_times(manual_sas)

        auto_avg_response = round(sum(auto_times) / len(auto_times)) if auto_times else None
        manual_avg_response = round(sum(manual_times) / len(manual_times)) if manual_times else None

        # 5) Avg dispatch speed (CreatedDate → SchedStartTime)
        def _dispatch_speeds(sa_list):
            speeds = []
            for s in sa_list:
                c = _parse_dt(s.get('CreatedDate'))
                sc = _parse_dt(s.get('SchedStartTime'))
                if c and sc:
                    speed = (sc - c).total_seconds() / 60
                    if 0 < speed < 120:
                        speeds.append(speed)
            return speeds

        auto_speeds = _dispatch_speeds(auto_sas)
        manual_speeds = _dispatch_speeds(manual_sas)

        auto_avg_speed = round(sum(auto_speeds) / len(auto_speeds)) if auto_speeds else None
        manual_avg_speed = round(sum(manual_speeds) / len(manual_speeds)) if manual_speeds else None

        # 6) SLA hit rate
        auto_sla = round(100 * sum(1 for t in auto_times if t <= 45) / max(len(auto_times), 1)) if auto_times else None
        manual_sla = round(100 * sum(1 for t in manual_times if t <= 45) / max(len(manual_times), 1)) if manual_times else None

        # 7) "Closest driver" metric — split by system vs dispatcher
        def _closest_driver_analysis(sa_list):
            """Check if the assigned driver was the closest fleet driver (by GPS)."""
            hits, evaluated = 0, 0
            total_extra_miles = 0.0
            for s in sa_list:
                sa_lat, sa_lon = s.get('Latitude'), s.get('Longitude')
                if not sa_lat or not sa_lon:
                    continue
                sa_lat, sa_lon = float(sa_lat), float(sa_lon)
                assigned_dr = sa_to_driver.get(s['Id'])
                if not assigned_dr or assigned_dr not in fleet_driver_gps:
                    continue
                tid = s.get('ServiceTerritoryId')
                terr_drivers_set = territory_drivers.get(tid, set())
                candidates = [(dr_id, fleet_driver_gps[dr_id]) for dr_id in terr_drivers_set if dr_id in fleet_driver_gps]
                if len(candidates) < 2:
                    continue

                # Use dispatch-time GPS for the assigned driver (where they were when dispatched)
                disp_lat = s.get('ERS_Dispatched_Geolocation__Latitude__s')
                disp_lon = s.get('ERS_Dispatched_Geolocation__Longitude__s')

                distances = []
                for dr_id, (dlat, dlon) in candidates:
                    if dr_id == assigned_dr and disp_lat and disp_lon:
                        dist = _haversine_mi(sa_lat, sa_lon, float(disp_lat), float(disp_lon))
                    else:
                        dist = _haversine_mi(sa_lat, sa_lon, dlat, dlon)
                    distances.append((dr_id, dist))
                distances.sort(key=lambda x: x[1])
                evaluated += 1
                closest_dist = distances[0][1]
                assigned_dist = next((d for dr, d in distances if dr == assigned_dr), closest_dist)
                if assigned_dr == distances[0][0]:
                    hits += 1
                else:
                    total_extra_miles += (assigned_dist - closest_dist)
            pct = round(100 * hits / max(evaluated, 1)) if evaluated > 0 else None
            extra = round(total_extra_miles, 1) if evaluated > 0 else None
            wrong = (evaluated - hits) if evaluated > 0 else None
            return pct, evaluated, extra, wrong

        auto_closest_pct, auto_closest_eval, auto_extra_miles, auto_wrong = _closest_driver_analysis(auto_sas)
        manual_closest_pct, manual_closest_eval, manual_extra_miles, manual_wrong = _closest_driver_analysis(manual_sas)
        # Towbook contractors don't use FSL GPS / ServiceResource — no valid closest-driver data
        towbook_closest_pct, towbook_closest_eval, towbook_extra_miles, towbook_wrong = None, 0, None, None
        # Total extra miles across fleet channels only
        _extras = [x for x in [auto_extra_miles, manual_extra_miles] if x is not None]
        total_extra_miles_today = round(sum(_extras), 1) if _extras else None

        # 8) Top dispatchers — only Membership User profile (real FSL Dispatcher Console users)
        dispatcher_counts = Counter()
        for s in sas:
            info = dispatched_by.get(s['Id'])
            if info and info['profile'] == 'Membership User':
                dispatcher_counts[info['name']] += 1
        top_dispatchers = [{'name': n, 'count': c} for n, c in dispatcher_counts.most_common(5)]

        return {
            'total': total,
            'fleet_total': fleet_total,
            'auto_count': auto_count,
            'manual_count': manual_count,
            'towbook_count': towbook_count,
            'auto_pct': auto_pct,
            'no_human_count': no_human_count,
            'no_human_pct': no_human_pct,
            'human_count': human_count,
            'towbook_auto_count': towbook_auto_count,
            'towbook_human_count': towbook_human_count,
            'auto_avg_response': auto_avg_response,
            'manual_avg_response': manual_avg_response,
            'auto_avg_speed': auto_avg_speed,
            'manual_avg_speed': manual_avg_speed,
            'auto_sla': auto_sla,
            'manual_sla': manual_sla,
            'auto_closest_pct': auto_closest_pct,
            'auto_closest_eval': auto_closest_eval,
            'auto_extra_miles': auto_extra_miles,
            'auto_wrong': auto_wrong,
            'manual_closest_pct': manual_closest_pct,
            'manual_closest_eval': manual_closest_eval,
            'manual_extra_miles': manual_extra_miles,
            'manual_wrong': manual_wrong,
            'towbook_closest_pct': towbook_closest_pct,
            'towbook_closest_eval': towbook_closest_eval,
            'towbook_extra_miles': towbook_extra_miles,
            'towbook_wrong': towbook_wrong,
            'total_extra_miles': total_extra_miles_today,
            'dispatchers': top_dispatchers,
            'is_fallback': is_fallback,
        }

    return cache.cached_query('scheduler_insights_today', _fetch, ttl=3600)


# ── Feature Flags ────────────────────────────────────────────────────────────

_DEFAULT_FEATURES = {
    'pta_advisor': True,
    'onroute': True,
    'matrix': True,
    'chat': True,
}

_SETTINGS_FILE = os.path.expanduser('~/.fslapp/settings.json')

def _load_settings():
    try:
        with open(_SETTINGS_FILE) as f:
            return _json.load(f)
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
