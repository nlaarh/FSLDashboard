"""PTA Advisor endpoints — projected PTA for all garages."""

import os
import json as _json
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Request

from utils import _ET, parse_dt as _parse_dt
import cache

router = APIRouter()


# Cycle times in minutes (verified from 8,500+ SAs, Mar 2026)
_CYCLE_TIMES = {'tow': 115, 'winch': 40, 'battery': 38, 'light': 33}
_ONSITE_TIMES = {'tow': 60, 'winch': 15, 'battery': 20, 'light': 13}
# Dispatch + travel buffer per type (dispatch processing + avg travel-to from verified data)
_DISPATCH_TRAVEL = {'tow': 30, 'winch': 25, 'battery': 25, 'light': 25}
_DEFAULT_PTA = {'tow': 60, 'winch': 50, 'battery': 45, 'light': 45}  # fallback if no setting exists

# PTA type mapping: ERS_Type__c → our call tier
_PTA_TYPE_MAP = {
    'D': 'default',
    'F': 'tow',       # Full Service = tow/flatbed
    'Battery': 'battery',
    'BA': 'battery',
    'Lockout': 'light',
    'Winch': 'winch',
}

# Settings file for configurable refresh interval
_SETTINGS_FILE = os.path.expanduser('~/.fslapp/settings.json')

def _load_settings():
    try:
        with open(_SETTINGS_FILE) as f:
            return _json.load(f)
    except Exception:
        return {}

def _save_settings(settings: dict):
    os.makedirs(os.path.dirname(_SETTINGS_FILE), exist_ok=True)
    with open(_SETTINGS_FILE, 'w') as f:
        _json.dump(settings, f, indent=2)

def _pta_refresh_interval():
    return _load_settings().get('pta_refresh_interval', 900)


# ── Admin PIN (used by PTA advisor refresh + admin panel) ────────────────────
_ADMIN_PIN = os.getenv('ADMIN_PIN', '121838')

def _check_pin(request: Request):
    pin = request.headers.get('X-Admin-Pin', '')
    if pin != _ADMIN_PIN:
        raise HTTPException(status_code=403, detail="Invalid PIN")


# ── Skill hierarchy helpers (same as main.py) ────────────────────────────────

_TOW_CAPS = {'tow', 'flat bed', 'wheel lift'}
_BATTERY_CAPS = {'battery', 'battery service', 'jumpstart'}

def _driver_tier(truck_capabilities: str) -> str:
    """Classify driver tier from truck capabilities string (semicolon-separated)."""
    caps = {c.strip().lower() for c in (truck_capabilities or '').split(';') if c.strip()}
    if caps & _TOW_CAPS:
        return 'tow'
    if caps & _BATTERY_CAPS:
        light_caps = {'tire', 'lockout', 'locksmith', 'fuel - gasoline', 'fuel - diesel',
                      'extrication- driveway', 'extrication- highway/roadway', 'winch'}
        if caps & light_caps:
            return 'light'
        return 'battery'
    return 'light'

def _call_tier(work_type: str) -> str:
    """Classify call tier from work type name. 4 types: tow, winch, battery, light."""
    wt = (work_type or '').lower()
    if 'tow' in wt:
        return 'tow'
    if 'winch' in wt or 'extrication' in wt:
        return 'winch'
    if wt in ('battery', 'jumpstart'):
        return 'battery'
    return 'light'

def _can_serve(driver_tier: str, call_tier: str) -> bool:
    """Check if a driver tier can serve a call tier (skill hierarchy)."""
    hierarchy = {
        'tow': {'tow', 'winch', 'light', 'battery'},
        'light': {'winch', 'light', 'battery'},
        'battery': {'battery'},
    }
    return call_tier in hierarchy.get(driver_tier, set())

def _count_by_tier(driver_list):
    counts = defaultdict(int)
    for d in driver_list:
        counts[d['tier']] += 1
    return dict(counts)


@router.get("/api/pta-advisor")
def pta_advisor():
    """Projected PTA for all active garages. Pre-cached, auto-refreshes."""
    ttl = _pta_refresh_interval()

    def _fetch():
        now_utc = datetime.now(timezone.utc)
        now_et = now_utc.astimezone(_ET)
        today_start = now_et.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        cutoff = today_start.strftime('%Y-%m-%dT%H:%M:%SZ')

        from sf_client import sf_parallel, sf_query_all as _sqa

        data = sf_parallel(
            # Today's SAs with territory and work type
            sas=lambda: _sqa(f"""
                SELECT Id, Status, CreatedDate, ActualStartTime,
                       ERS_PTA__c, ERS_Dispatch_Method__c,
                       Off_Platform_Driver__r.Name, Off_Platform_Truck_Id__c,
                       ServiceTerritoryId, ServiceTerritory.Name,
                       WorkType.Name
                FROM ServiceAppointment
                WHERE CreatedDate >= {cutoff}
                  AND ServiceTerritoryId != null
                  AND Status IN ('Dispatched','Completed','Assigned',
                                 'Cancel Call - Service Not En Route',
                                 'Cancel Call - Service En Route',
                                 'Unable to Complete','Canceled','No-Show')
            """),
            # Assigned resources for active SAs (driver → SA mapping)
            assigned=lambda: _sqa(f"""
                SELECT ServiceResourceId, ServiceResource.Name, ServiceAppointmentId
                FROM AssignedResource
                WHERE ServiceAppointment.CreatedDate >= {cutoff}
                  AND ServiceAppointment.Status IN ('Dispatched','Assigned','In Progress')
            """),
            # Logged-in drivers (Asset = truck with driver)
            logged_in=lambda: _sqa("""
                SELECT ERS_Driver__c, Name, ERS_Truck_Capabilities__c
                FROM Asset
                WHERE RecordType.Name = 'ERS Truck'
                  AND ERS_Driver__c != null
                  AND ERS_Driver__r.IsActive = true
            """),
            # Territory membership (driver → territory)
            members=lambda: _sqa("""
                SELECT ServiceResourceId, ServiceTerritoryId
                FROM ServiceTerritoryMember
                WHERE ServiceTerritory.IsActive = true
                  AND EffectiveStartDate <= TODAY
                  AND (EffectiveEndDate = null OR EffectiveEndDate >= TODAY)
                  AND ServiceResource.IsActive = true
                  AND ServiceResource.ERS_Driver_Type__c IN ('Fleet Driver', 'On-Platform Contractor Driver')
            """),
            # Current PTA settings per territory+type
            pta_settings=lambda: _sqa("""
                SELECT ERS_Service_Territory__c, ERS_Type__c, ERS_Minutes__c
                FROM ERS_Service_Appointment_PTA__c
            """),
        )

        # ── Build lookup maps ──

        # Driver capabilities from truck assignment
        driver_caps = {}
        for asset in data['logged_in']:
            dr_id = asset.get('ERS_Driver__c')
            if dr_id:
                driver_caps[dr_id] = asset.get('ERS_Truck_Capabilities__c', '')
        logged_in_ids = set(driver_caps.keys())

        # Territory → set of logged-in driver IDs
        terr_drivers = defaultdict(set)
        for m in data['members']:
            dr_id = m.get('ServiceResourceId')
            tid = m.get('ServiceTerritoryId')
            if dr_id and tid and dr_id in logged_in_ids:
                terr_drivers[tid].add(dr_id)

        # SA → driver, driver → SA IDs, driver names
        sa_driver = {}
        driver_sa_ids = defaultdict(set)
        driver_names = {}
        for ar in data['assigned']:
            dr_id = ar.get('ServiceResourceId')
            sa_id = ar.get('ServiceAppointmentId')
            if dr_id and sa_id:
                sa_driver[sa_id] = dr_id
                driver_sa_ids[dr_id].add(sa_id)
                if dr_id not in driver_names:
                    driver_names[dr_id] = (ar.get('ServiceResource') or {}).get('Name', '?')
        busy_driver_ids = set(driver_sa_ids.keys())

        # Current PTA settings: territory_id → {call_tier: minutes, 'default': minutes}
        pta_map = defaultdict(dict)
        for p in data['pta_settings']:
            tid = p.get('ERS_Service_Territory__c')
            ptype = p.get('ERS_Type__c', '')
            mins = p.get('ERS_Minutes__c')
            if tid and mins is not None:
                mapped = _PTA_TYPE_MAP.get(ptype, 'default')
                pta_map[tid][mapped] = round(mins)

        # SA by ID for quick lookup
        sa_by_id = {}
        by_territory = defaultdict(list)
        for sa in data['sas']:
            tid = sa.get('ServiceTerritoryId')
            if tid:
                by_territory[tid].append(sa)
                sa_by_id[sa['Id']] = sa

        # ── Process each territory ──
        import heapq
        garages = []

        for tid, sa_list in by_territory.items():
            t_name = (sa_list[0].get('ServiceTerritory') or {}).get('Name', '?')

            # Today's stats — separate assigned (have driver) vs unassigned (true queue)
            open_sas = []       # unassigned open calls (true queue)
            assigned_open = []  # open calls already assigned to a driver
            completed_count = 0
            tb_drivers_seen = set()  # unique Towbook driver names from ALL today's SAs
            for sa in sa_list:
                st = sa.get('Status')
                wt = (sa.get('WorkType') or {}).get('Name', '')
                # Track all Towbook drivers seen today (active + completed)
                opd_name = (sa.get('Off_Platform_Driver__r') or {}).get('Name')
                if opd_name:
                    tb_drivers_seen.add(opd_name)
                if st == 'Completed':
                    completed_count += 1
                elif st in ('Dispatched', 'Assigned'):
                    if 'drop-off' in wt.lower():
                        continue
                    ct = _call_tier(wt)
                    cdt = _parse_dt(sa.get('CreatedDate'))
                    wait_min = 0
                    if cdt:
                        if cdt.tzinfo is None:
                            cdt = cdt.replace(tzinfo=timezone.utc)
                        wait_min = round((now_utc - cdt).total_seconds() / 60)
                    sa_info = {
                        'id': sa['Id'], 'tier': ct,
                        'wait_min': wait_min,
                        'pta_min': round(float(sa['ERS_PTA__c'])) if sa.get('ERS_PTA__c') and 0 < float(sa['ERS_PTA__c']) < 999 else None,
                    }
                    if sa['Id'] in sa_driver:
                        assigned_open.append(sa_info)  # already on a driver's plate
                    else:
                        open_sas.append(sa_info)  # truly unassigned
            all_open = assigned_open + open_sas
            all_open.sort(key=lambda x: x['wait_min'], reverse=True)
            open_sas.sort(key=lambda x: x['wait_min'], reverse=True)

            # Territory's drivers (logged-in only — Fleet drivers)
            all_driver_ids = terr_drivers.get(tid, set())
            has_pta_setting = tid in pta_map
            if not all_driver_ids and not all_open and not has_pta_setting:
                continue  # Skip territories with no drivers, no open calls, and no PTA settings

            idle_list = []
            busy_list = []
            for dr_id in all_driver_ids:
                tier = _driver_tier(driver_caps.get(dr_id, ''))
                if dr_id in busy_driver_ids:
                    # Total sequential remaining: count assigned pick-up SAs
                    # Driver works jobs sequentially. Total work = num_jobs × cycle_time.
                    # Subtract elapsed since oldest job started.
                    driver_sas = []
                    for sa_id in driver_sa_ids[dr_id]:
                        sa = sa_by_id.get(sa_id)
                        if not sa:
                            continue
                        wt = (sa.get('WorkType') or {}).get('Name', '')
                        if 'drop-off' in wt.lower():
                            continue  # drop-off is part of pick-up cycle
                        driver_sas.append(sa)

                    if driver_sas:
                        # Sort by CreatedDate to find oldest (current job)
                        driver_sas.sort(key=lambda s: s.get('CreatedDate', ''))
                        oldest = driver_sas[0]

                        # Sum ACTUAL per-job cycle times (tow=115, battery=38, light=33)
                        total_work = 0
                        for ds in driver_sas:
                            jct = _call_tier((ds.get('WorkType') or {}).get('Name', ''))
                            total_work += _CYCLE_TIMES.get(jct, 40)

                        # Subtract elapsed since oldest job
                        ast = _parse_dt(oldest.get('ActualStartTime'))
                        cdt = _parse_dt(oldest.get('CreatedDate'))
                        dm = oldest.get('ERS_Dispatch_Method__c', '')
                        if ast and dm == 'Field Services':
                            if ast.tzinfo is None:
                                ast = ast.replace(tzinfo=timezone.utc)
                            elapsed = (now_utc - ast).total_seconds() / 60
                        elif cdt:
                            if cdt.tzinfo is None:
                                cdt = cdt.replace(tzinfo=timezone.utc)
                            elapsed = (now_utc - cdt).total_seconds() / 60
                        else:
                            elapsed = 0
                        remaining = max(0, total_work - elapsed)
                    else:
                        remaining = 0
                    # Build job list for display
                    job_details = []
                    for s in driver_sas:
                        wt_n = (s.get('WorkType') or {}).get('Name', '?')
                        scdt = _parse_dt(s.get('CreatedDate'))
                        swait = 0
                        if scdt:
                            if scdt.tzinfo is None:
                                scdt = scdt.replace(tzinfo=timezone.utc)
                            swait = round((now_utc - scdt).total_seconds() / 60)
                        job_details.append({
                            'work_type': wt_n,
                            'wait_min': swait,
                            'pta_min': round(float(s['ERS_PTA__c'])) if s.get('ERS_PTA__c') else None,
                            'has_arrived': s.get('ActualStartTime') is not None,
                        })
                    busy_list.append({
                        'name': driver_names.get(dr_id, '?'),
                        'tier': tier,
                        'remaining_min': round(remaining),
                        'jobs': len(driver_sas),
                        'job_details': job_details,
                    })
                else:
                    idle_list.append({'tier': tier})

            # ── Towbook (off-platform) drivers from active SAs ──
            tb_drivers = defaultdict(list)  # driver_name → [sa, ...]
            for sa in sa_list:
                st = sa.get('Status')
                if st not in ('Dispatched', 'Assigned'):
                    continue
                wt = (sa.get('WorkType') or {}).get('Name', '')
                if 'drop-off' in wt.lower():
                    continue
                opd = (sa.get('Off_Platform_Driver__r') or {}).get('Name')
                if opd:
                    tb_drivers[opd].append(sa)

            for tb_name, tb_sas in tb_drivers.items():
                tb_sas.sort(key=lambda s: s.get('CreatedDate', ''))
                total_work = 0
                for ds in tb_sas:
                    jct = _call_tier((ds.get('WorkType') or {}).get('Name', ''))
                    total_work += _CYCLE_TIMES.get(jct, 40)
                oldest = tb_sas[0]
                cdt = _parse_dt(oldest.get('CreatedDate'))
                elapsed = 0
                if cdt:
                    if cdt.tzinfo is None:
                        cdt = cdt.replace(tzinfo=timezone.utc)
                    elapsed = (now_utc - cdt).total_seconds() / 60
                remaining = max(0, total_work - elapsed)
                job_details = []
                for s in tb_sas:
                    wt_n = (s.get('WorkType') or {}).get('Name', '?')
                    scdt = _parse_dt(s.get('CreatedDate'))
                    swait = 0
                    if scdt:
                        if scdt.tzinfo is None:
                            scdt = scdt.replace(tzinfo=timezone.utc)
                        swait = round((now_utc - scdt).total_seconds() / 60)
                    job_details.append({
                        'work_type': wt_n,
                        'wait_min': swait,
                        'pta_min': round(float(s['ERS_PTA__c'])) if s.get('ERS_PTA__c') else None,
                        'has_arrived': s.get('ActualStartTime') is not None,
                    })
                # Infer tier from truck ID pattern or default to 'tow' for Towbook
                busy_list.append({
                    'name': tb_name,
                    'tier': 'tow',  # Towbook drivers are typically tow-capable
                    'remaining_min': round(remaining),
                    'jobs': len(tb_sas),
                    'job_details': job_details,
                    'towbook': True,
                })

            # ── Project PTA for each call type ──
            # Algorithm: simulate FIFO dispatch with skill hierarchy
            has_fleet_drivers = len(all_driver_ids) > 0
            projected = {}
            current_settings = pta_map.get(tid, {})

            for call_type in ('tow', 'winch', 'battery', 'light'):
                # Drivers that can serve this call type
                capable_idle = [d for d in idle_list if _can_serve(d['tier'], call_type)]
                capable_busy = [d for d in busy_list if _can_serve(d['tier'], call_type)]

                # Current PTA setting for this type (exact → default fallback)
                current_min = current_settings.get(call_type) or current_settings.get('default')
                travel = _DISPATCH_TRAVEL.get(call_type, 25)

                if capable_idle:
                    # Idle driver available → use type-specific PTA if set,
                    # otherwise scale the default by call complexity
                    type_specific = current_settings.get(call_type)
                    if type_specific:
                        projected_min = type_specific
                    elif current_min:
                        # Default setting exists but no per-type override
                        # Scale: default is typically calibrated for tow (most common)
                        # Battery/light are faster service → shorter PTA
                        type_scale = {'tow': 1.0, 'winch': 0.75, 'battery': 0.65, 'light': 0.7}
                        projected_min = round(current_min * type_scale.get(call_type, 1.0))
                    else:
                        projected_min = _DEFAULT_PTA.get(call_type, 45)
                elif capable_busy:
                    if not has_fleet_drivers:
                        # Towbook garage: use ERS_PTA__c from live SAs matching
                        # THIS call type — different types have different PTAs.
                        # Fall back to all types, then setting, then default.
                        type_ptas = [oc['pta_min'] for oc in all_open
                                     if oc.get('pta_min') and oc.get('tier') == call_type]
                        if type_ptas:
                            projected_min = round(sum(type_ptas) / len(type_ptas))
                        else:
                            # No live SAs of this type → use PTA setting or default
                            if current_min:
                                type_scale = {'tow': 1.0, 'winch': 0.75, 'battery': 0.65, 'light': 0.7}
                                projected_min = round(current_min * type_scale.get(call_type, 1.0))
                            else:
                                projected_min = _DEFAULT_PTA.get(call_type, 45)
                    else:
                        # Fleet garage: simulate — busy drivers become free,
                        # serve queued calls, then our new call
                        heap = [d['remaining_min'] for d in capable_busy]
                        heapq.heapify(heap)

                        for oc in open_sas:
                            if any(_can_serve(d['tier'], oc['tier']) for d in capable_busy):
                                t = heapq.heappop(heap)
                                cycle = _CYCLE_TIMES.get(oc['tier'], 40)
                                heapq.heappush(heap, t + cycle)

                        next_free = heapq.heappop(heap) if heap else 0
                        projected_min = round(next_free + travel)
                else:
                    # No capable drivers — Towbook: use type-matched PTA or setting
                    if not has_fleet_drivers:
                        type_ptas = [oc['pta_min'] for oc in all_open
                                     if oc.get('pta_min') and oc.get('tier') == call_type]
                        if type_ptas:
                            projected_min = round(sum(type_ptas) / len(type_ptas))
                        elif current_min:
                            type_scale = {'tow': 1.0, 'winch': 0.75, 'battery': 0.65, 'light': 0.7}
                            projected_min = round(current_min * type_scale.get(call_type, 1.0))
                        else:
                            projected_min = _DEFAULT_PTA.get(call_type, 45)
                    else:
                        projected_min = None  # No coverage for this type

                # Recommendation
                if projected_min is None:
                    rec = 'no_coverage'
                elif current_min is None:
                    rec = 'no_setting'
                elif projected_min > current_min * 1.2:
                    rec = 'increase'
                elif projected_min < current_min * 0.6:
                    rec = 'decrease'
                else:
                    rec = 'ok'

                projected[call_type] = {
                    'projected_min': projected_min,
                    'current_setting_min': current_min,
                    'recommendation': rec,
                }

            # Queue stats (all_open = assigned + unassigned, for display)
            queue_by_type = defaultdict(int)
            for oc in all_open:
                queue_by_type[oc['tier']] += 1

            longest_wait = all_open[0]['wait_min'] if all_open else 0
            avg_wait = round(sum(oc['wait_min'] for oc in all_open) / max(len(all_open), 1)) if all_open else 0

            # Average projected PTA across all service types
            proj_vals = [p['projected_min'] for p in projected.values() if p.get('projected_min') is not None]
            avg_projected = round(sum(proj_vals) / len(proj_vals)) if proj_vals else None

            garages.append({
                'id': tid,
                'name': t_name,
                'has_fleet_drivers': has_fleet_drivers,
                'queue_depth': len(all_open),
                'queue_by_type': dict(queue_by_type),
                'drivers': {
                    'total': len(all_driver_ids) if has_fleet_drivers else len(tb_drivers_seen),
                    'idle': len(idle_list),
                    'busy': len(busy_list),
                    'idle_by_tier': _count_by_tier(idle_list),
                    'busy_by_tier': _count_by_tier(busy_list),
                    'capable_idle': {ct: len([d for d in idle_list if _can_serve(d['tier'], ct)]) for ct in ('tow','winch','battery','light')},
                    'capable_busy': {ct: len([d for d in busy_list if _can_serve(d['tier'], ct)]) for ct in ('tow','winch','battery','light')},
                    'is_towbook': not has_fleet_drivers,
                    'busy_details': busy_list,
                    'tb_seen_today': len(tb_drivers_seen),
                    'tb_active': len(tb_drivers),
                },
                'completed_today': completed_count,
                'projected_pta': projected,
                'avg_projected_pta': avg_projected,
                'longest_wait': longest_wait,
                'avg_wait': avg_wait,
            })

        # Sort: most urgent first (highest projected tow PTA, then queue depth)
        def _urgency(g):
            tow_proj = (g['projected_pta'].get('tow') or {}).get('projected_min') or 0
            return (-tow_proj, -g['queue_depth'], g['name'])
        garages.sort(key=_urgency)

        return {
            'garages': garages,
            'computed_at': now_utc.isoformat(),
            'refresh_interval': ttl,
            'totals': {
                'garages_active': len(garages),
                'total_queue': sum(g['queue_depth'] for g in garages),
                'total_drivers': sum(g['drivers']['total'] for g in garages),
                'total_idle': sum(g['drivers']['idle'] for g in garages),
            },
        }

    return cache.cached_query('pta_advisor', _fetch, ttl=ttl)


@router.post("/api/pta-advisor/refresh")
def pta_advisor_refresh(request: Request):
    """Force refresh PTA advisor cache. PIN-protected."""
    _check_pin(request)
    cache.invalidate('pta_advisor')
    return pta_advisor()


## NOTE: /api/admin/settings GET and PUT are in routers/admin.py
