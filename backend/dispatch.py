"""Dispatch optimization module — queue board, driver recommender, cross-skill cascade, forecast."""

import math, os, sys
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo
from collections import defaultdict

_ET = ZoneInfo('America/New_York')

from sf_client import sf_query_all, sf_parallel, sanitize_soql, get_towbook_on_location
import cache

# ── Constants ────────────────────────────────────────────────────────────────

TRAVEL_SPEED_MPH = 25
CYCLE_TIMES = {'tow': 115, 'battery': 38, 'light': 33}
BLOCK_MIN = 120  # 2-hour shift blocks

TOW_SKILLS = {'tow', 'flat bed', 'wheel lift'}
LIGHT_SKILLS = {'tire', 'lockout', 'locksmith', 'winch out', 'fuel / miscellaneous', 'pvs'}
BATTERY_SKILLS = {'battery', 'jumpstart'}

# Skill hierarchy: tow drivers can do light+battery, light can do battery
SKILL_HIERARCHY = {
    'tow': ['tow', 'light', 'battery'],
    'light': ['light', 'battery'],
    'battery': ['battery'],
}

DOW_WEATHER_MULTIPLIERS = {
    'Clear': 1.0, 'Mild': 1.05, 'Moderate': 1.10, 'Severe': 1.25, 'Extreme': 1.40,
}

URGENCY_THRESHOLDS = [
    (20, 'green'), (35, 'yellow'), (45, 'orange'),
]


def _parse_dt(dt_str):
    if not dt_str:
        return None
    if isinstance(dt_str, datetime):
        return dt_str
    try:
        s = dt_str.replace('+0000', '+00:00').replace('Z', '+00:00')
        return datetime.fromisoformat(s)
    except Exception:
        return None


def haversine(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    R = 3959
    la1, la2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lat2 - lat1)
    dn = math.radians(lon2 - lon1)
    a = math.sin(dl / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dn / 2) ** 2
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 2)


def _classify_driver(skills_set):
    lower = {s.lower() for s in skills_set}
    if lower & TOW_SKILLS:
        return 'tow'
    if lower & LIGHT_SKILLS:
        return 'light'
    if lower & BATTERY_SKILLS:
        return 'battery'
    return 'unknown'


def _classify_worktype(wt_name):
    wt = (wt_name or '').lower()
    if 'tow' in wt:
        return 'tow'
    if wt in ('battery', 'jumpstart'):
        return 'battery'
    if wt in ('tire', 'lockout', 'locksmith', 'winch out', 'fuel / miscellaneous', 'pvs'):
        return 'light'
    return 'light'


def _driver_tier(truck_capabilities: str) -> str:
    """Classify driver tier from Asset.ERS_Truck_Capabilities__c (semicolon-separated)."""
    caps = {c.strip().lower() for c in (truck_capabilities or '').split(';') if c.strip()}
    if caps & TOW_SKILLS:
        return 'tow'
    if caps & BATTERY_SKILLS:
        # Has battery but also has light-service items → light driver
        light_caps = {'tire', 'lockout', 'locksmith', 'fuel - gasoline', 'fuel - diesel',
                      'extrication- driveway', 'extrication- highway/roadway', 'winch'}
        if caps & light_caps:
            return 'light'
        return 'battery'
    return 'light'


def _can_cover(driver_tier, call_tier):
    return call_tier in SKILL_HIERARCHY.get(driver_tier, [])


def _urgency(wait_min, pta=None):
    if pta and wait_min > float(pta):
        return 'red'
    for threshold, level in URGENCY_THRESHOLDS:
        if wait_min < threshold:
            return level
    return 'red'


# ── Feature 1: Live Queue Board ─────────────────────────────────────────────

def get_live_queue():
    """All open SAs across all territories with aging and urgency."""

    def _fetch():
        now = datetime.now(timezone.utc)
        today_et = now.astimezone(_ET).replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff = today_et.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

        sas = sf_query_all(f"""
            SELECT Id, AppointmentNumber, Status, CreatedDate,
                   SchedStartTime, ERS_PTA__c, ERS_PTA_Due__c,
                   ERS_Dispatch_Method__c, ERS_Auto_Assign__c,
                   ERS_Facility_Decline_Reason__c,
                   ServiceTerritoryId, ServiceTerritory.Name,
                   WorkType.Name, Street, City,
                   Latitude, Longitude
            FROM ServiceAppointment
            WHERE Status IN ('Dispatched', 'Assigned')
              AND CreatedDate >= {cutoff}
              AND ServiceTerritoryId != null
            ORDER BY CreatedDate ASC
        """)

        queue = []
        by_urgency = defaultdict(int)
        by_territory = defaultdict(lambda: {'count': 0, 'max_wait': 0, 'name': ''})
        total_wait = 0

        for sa in sas:
            created = _parse_dt(sa.get('CreatedDate'))
            wait_min = round((now - created).total_seconds() / 60) if created else 0
            pta = sa.get('ERS_PTA__c')
            pta_val = float(pta) if pta else None
            pta_breached = pta_val is not None and 0 < pta_val < 999 and wait_min > pta_val

            wt = (sa.get('WorkType') or {}).get('Name', '') or ''
            if 'drop' in wt.lower():
                continue

            urg = _urgency(wait_min, pta)
            tid = sa.get('ServiceTerritoryId', '')
            tname = (sa.get('ServiceTerritory') or {}).get('Name', '')

            # Escalation suggestions
            suggestion = None
            decline = sa.get('ERS_Facility_Decline_Reason__c')
            dispatch = sa.get('ERS_Dispatch_Method__c', '')
            if wait_min > 45 and dispatch == 'Towbook':
                suggestion = 'Consider reassigning to Field Services fleet'
            elif wait_min > 35 and not decline:
                suggestion = 'Contact garage for ETA update'
            elif decline:
                suggestion = f'Previously declined ({decline}) — reassign immediately'
            elif wait_min > 30:
                suggestion = 'Approaching SLA breach — consider cross-skill assignment'

            item = {
                'sa_id': sa.get('Id', ''),
                'number': sa.get('AppointmentNumber', ''),
                'work_type': wt,
                'call_tier': _classify_worktype(wt),
                'status': sa.get('Status', ''),
                'territory_id': tid,
                'territory_name': tname,
                'wait_min': wait_min,
                'pta_promise': round(pta_val) if pta_val else None,
                'pta_breached': pta_breached,
                'urgency': urg,
                'lat': sa.get('Latitude'),
                'lon': sa.get('Longitude'),
                'address': f"{sa.get('Street', '')} {sa.get('City', '')}".strip(),
                'dispatch_method': dispatch,
                'declined': decline is not None,
                'decline_reason': decline,
                'escalation_suggestion': suggestion,
                'created': created.strftime('%I:%M %p') if created else '?',
                'auto_assign': sa.get('ERS_Auto_Assign__c', False),
            }
            queue.append(item)
            by_urgency[urg] += 1
            total_wait += wait_min

            t = by_territory[tid]
            t['count'] += 1
            t['name'] = tname
            if wait_min > t['max_wait']:
                t['max_wait'] = wait_min

        n = len(queue)
        return {
            'queue': queue,
            'summary': {
                'total_open': n,
                'breached_count': sum(1 for q in queue if q['pta_breached']),
                'avg_wait': round(total_wait / max(n, 1)),
                'max_wait': max((q['wait_min'] for q in queue), default=0),
                'by_urgency': dict(by_urgency),
                'by_territory': sorted([
                    {'id': tid, 'name': v['name'], 'count': v['count'], 'max_wait': v['max_wait']}
                    for tid, v in by_territory.items()
                ], key=lambda x: -x['max_wait']),
            },
        }

    return cache.cached_query('queue_live', _fetch, ttl=30)


# ── Feature 2: Next Best Driver Recommender ──────────────────────────────────

def recommend_drivers(sa_id: str):
    """For a given SA, recommend top 3 drivers ranked by composite score."""
    sa_id = sanitize_soql(sa_id)

    def _fetch():
        # Get SA details
        sa_rows = sf_query_all(f"""
            SELECT Id, AppointmentNumber, Status, CreatedDate,
                   ERS_PTA__c, ServiceTerritoryId, ServiceTerritory.Name,
                   WorkType.Name, Latitude, Longitude, Street, City
            FROM ServiceAppointment
            WHERE Id = '{sa_id}'
        """)
        if not sa_rows:
            return {'error': 'SA not found'}
        sa = sa_rows[0]
        tid = sa.get('ServiceTerritoryId')
        if not tid:
            return {'error': 'SA has no territory'}

        sa_lat = sa.get('Latitude')
        sa_lon = sa.get('Longitude')
        wt_name = (sa.get('WorkType') or {}).get('Name', '')
        call_tier = _classify_worktype(wt_name)

        # Parallel queries: Asset for on-shift, STM for GPS, AssignedResource for busy
        data = sf_parallel(
            trucks=lambda: sf_query_all("""
                SELECT ERS_Driver__c, Name, ERS_Truck_Capabilities__c
                FROM Asset
                WHERE RecordType.Name = 'ERS Truck'
                  AND ERS_Driver__c != null
            """),
            gps=lambda: sf_query_all(f"""
                SELECT ServiceResourceId,
                       ServiceResource.Name,
                       ServiceResource.ERS_Driver_Type__c,
                       ServiceResource.LastKnownLatitude,
                       ServiceResource.LastKnownLongitude,
                       ServiceResource.LastKnownLocationDate
                FROM ServiceTerritoryMember
                WHERE ServiceTerritoryId = '{tid}'
                  AND TerritoryType IN ('P','S')
            """),
            active_sas=lambda: sf_query_all(f"""
                SELECT ServiceResourceId, COUNT(Id) cnt
                FROM AssignedResource
                WHERE ServiceAppointment.Status IN ('Dispatched', 'Assigned', 'In Progress')
                  AND ServiceAppointment.ServiceTerritoryId = '{tid}'
                GROUP BY ServiceResourceId
            """),
        )

        # Build on-shift set + truck capabilities from Asset
        logged_in_ids = set()
        driver_caps = {}
        for asset in data['trucks']:
            dr_id = asset.get('ERS_Driver__c')
            if dr_id:
                logged_in_ids.add(dr_id)
                driver_caps[dr_id] = asset.get('ERS_Truck_Capabilities__c', '')

        # Build GPS lookup from STM (only for on-shift drivers)
        gps_lookup = {}
        for m in data['gps']:
            d_id = m.get('ServiceResourceId')
            if d_id and d_id in logged_in_ids:
                res = m.get('ServiceResource') or {}
                gps_lookup[d_id] = {
                    'name': res.get('Name', ''),
                    'type': res.get('ERS_Driver_Type__c', ''),
                    'lat': res.get('LastKnownLatitude'),
                    'lon': res.get('LastKnownLongitude'),
                }

        # Build active workload map
        workload = {}
        for r in data['active_sas']:
            workload[r.get('ServiceResourceId', '')] = r.get('cnt', 0)

        # Evaluate each on-shift driver in this territory
        candidates = []
        for d_id, gps in gps_lookup.items():
            name = gps['name']
            if name.lower().startswith('towbook'):
                continue

            d_lat = gps['lat']
            d_lon = gps['lon']
            caps = driver_caps.get(d_id, '')
            d_tier = _driver_tier(caps) if caps else 'light'
            d_type = gps['type']
            d_load = workload.get(d_id, 0)

            # Distance and ETA
            dist = haversine(d_lat, d_lon, sa_lat, sa_lon) if d_lat and d_lon and sa_lat and sa_lon else None
            eta = round(dist / TRAVEL_SPEED_MPH * 60) if dist else None

            # Skill match
            can_do = _can_cover(d_tier, call_tier)
            if d_tier == call_tier:
                skill_match = 'full'
            elif can_do:
                skill_match = 'cross-skill'
            else:
                skill_match = 'none'

            if not can_do or not d_lat or not d_lon:
                continue

            # Scores (0-100)
            eta_score = max(0, 100 - max(0, (eta or 60) - 10) * 3)
            skill_score = 100 if skill_match == 'full' else 75
            load_score = max(10, 100 - d_load * 30)
            # No shift data from SOQL easily — use workload as proxy
            shift_score = 100 if d_load == 0 else 70 if d_load == 1 else 40

            composite = round(
                eta_score * 0.40 +
                skill_score * 0.25 +
                load_score * 0.20 +
                shift_score * 0.15, 1
            )

            candidates.append({
                'driver_id': d_id,
                'driver_name': name,
                'driver_type': d_type or d_tier,
                'driver_tier': d_tier,
                'eta_min': eta,
                'distance_mi': dist,
                'skill_match': skill_match,
                'active_jobs': d_load,
                'composite_score': composite,
                'scores': {
                    'eta': round(eta_score),
                    'skill': round(skill_score),
                    'workload': round(load_score),
                    'shift': round(shift_score),
                },
                'lat': d_lat,
                'lon': d_lon,
                'territory_type': m.get('TerritoryType', ''),
            })

        # Sort by composite score descending
        candidates.sort(key=lambda c: -c['composite_score'])

        return {
            'sa': {
                'id': sa.get('Id'),
                'number': sa.get('AppointmentNumber'),
                'work_type': wt_name,
                'call_tier': call_tier,
                'lat': sa_lat,
                'lon': sa_lon,
                'address': f"{sa.get('Street', '')} {sa.get('City', '')}".strip(),
                'pta_promise': sa.get('ERS_PTA__c'),
            },
            'recommendations': candidates[:5],
            'total_eligible': len(candidates),
            'total_evaluated': len(data['members']),
        }

    return cache.cached_query(f'recommend_{sa_id}', _fetch, ttl=60)


# ── Feature 3: Cross-Skill Cascade Status ────────────────────────────────────

def get_cascade_status(territory_id: str):
    """Show cross-skill dispatch opportunities for a territory."""
    territory_id = sanitize_soql(territory_id)

    def _fetch():
        now = datetime.now(timezone.utc)
        today_et = now.astimezone(_ET).replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff = today_et.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

        data = sf_parallel(
            open_sas=lambda: sf_query_all(f"""
                SELECT Id, AppointmentNumber, WorkType.Name,
                       Latitude, Longitude, CreatedDate, ERS_PTA__c
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND Status IN ('Dispatched', 'Assigned')
                  AND CreatedDate >= {cutoff}
                ORDER BY CreatedDate ASC
            """),
            trucks=lambda: sf_query_all("""
                SELECT ERS_Driver__c, Name, ERS_Truck_Capabilities__c
                FROM Asset
                WHERE RecordType.Name = 'ERS Truck'
                  AND ERS_Driver__c != null
            """),
            gps=lambda: sf_query_all(f"""
                SELECT ServiceResourceId,
                       ServiceResource.Name,
                       ServiceResource.LastKnownLatitude,
                       ServiceResource.LastKnownLongitude
                FROM ServiceTerritoryMember
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND TerritoryType IN ('P','S')
            """),
            assigned=lambda: sf_query_all(f"""
                SELECT ServiceResourceId, COUNT(Id) cnt
                FROM AssignedResource
                WHERE ServiceAppointment.Status IN ('Dispatched', 'Assigned', 'In Progress')
                  AND ServiceAppointment.ServiceTerritoryId = '{territory_id}'
                GROUP BY ServiceResourceId
            """),
        )

        # Build on-shift set + truck capabilities from Asset
        logged_in_ids = set()
        driver_caps = {}
        for asset in data['trucks']:
            dr_id = asset.get('ERS_Driver__c')
            if dr_id:
                logged_in_ids.add(dr_id)
                driver_caps[dr_id] = asset.get('ERS_Truck_Capabilities__c', '')

        # GPS lookup from STM (only on-shift drivers in this territory)
        gps_lookup = {}
        for m in data['gps']:
            d_id = m.get('ServiceResourceId')
            if d_id and d_id in logged_in_ids:
                res = m.get('ServiceResource') or {}
                gps_lookup[d_id] = {
                    'name': res.get('Name', ''),
                    'lat': res.get('LastKnownLatitude'),
                    'lon': res.get('LastKnownLongitude'),
                }

        busy_drivers = set()
        for r in data['assigned']:
            if r.get('cnt', 0) > 0:
                busy_drivers.add(r.get('ServiceResourceId', ''))

        # Classify on-shift drivers by tier using truck capabilities
        drivers_by_tier = defaultdict(list)
        for d_id, gps in gps_lookup.items():
            name = gps['name']
            if name.lower().startswith('towbook'):
                continue
            caps = driver_caps.get(d_id, '')
            d_tier = _driver_tier(caps) if caps else 'light'
            d_busy = d_id in busy_drivers
            drivers_by_tier[d_tier].append({
                'id': d_id,
                'name': name,
                'tier': d_tier,
                'busy': d_busy,
                'lat': gps['lat'],
                'lon': gps['lon'],
            })

        # Skill utilization
        utilization = {}
        for tier in ('tow', 'light', 'battery'):
            drivers = drivers_by_tier.get(tier, [])
            total = len(drivers)
            busy = sum(1 for d in drivers if d['busy'])
            utilization[tier] = {
                'total': total,
                'busy': busy,
                'idle': total - busy,
                'utilization_pct': round(100 * busy / max(total, 1)),
            }

        # Find cascade opportunities
        opportunities = []
        for sa in data['open_sas']:
            wt = (sa.get('WorkType') or {}).get('Name', '') or ''
            if 'drop' in wt.lower():
                continue
            call_tier = _classify_worktype(wt)

            # Check if primary tier has idle drivers
            primary_idle = [d for d in drivers_by_tier.get(call_tier, []) if not d['busy'] and d['lat']]
            if primary_idle:
                continue  # Primary drivers available, no cascade needed

            # Find cross-skill candidates
            sa_lat = sa.get('Latitude')
            sa_lon = sa.get('Longitude')
            cascade_candidates = []

            for tier in ('tow', 'light', 'battery'):
                if tier == call_tier:
                    continue
                if not _can_cover(tier, call_tier):
                    continue
                idle = [d for d in drivers_by_tier.get(tier, []) if not d['busy'] and d['lat']]
                for d in idle:
                    dist = haversine(d['lat'], d['lon'], sa_lat, sa_lon) if sa_lat and sa_lon else None
                    eta = round(dist / TRAVEL_SPEED_MPH * 60) if dist else None
                    cascade_candidates.append({
                        'driver_id': d['id'],
                        'driver_name': d['name'],
                        'driver_tier': tier,
                        'cascade_type': f"{tier.title()} → {call_tier.title()}",
                        'distance_mi': dist,
                        'eta_min': eta,
                    })

            cascade_candidates.sort(key=lambda c: c.get('eta_min') or 999)

            if cascade_candidates:
                best = cascade_candidates[0]
                created = _parse_dt(sa.get('CreatedDate'))
                wait = round((now - created).total_seconds() / 60) if created else 0
                opportunities.append({
                    'sa_id': sa.get('Id'),
                    'sa_number': sa.get('AppointmentNumber'),
                    'work_type': wt,
                    'call_tier': call_tier,
                    'wait_min': wait,
                    'primary_drivers_idle': 0,
                    'cascade_candidates': cascade_candidates[:3],
                    'recommendation': f"Assign to {best['driver_name']} ({best['cascade_type']}, {best['distance_mi']} mi, ~{best['eta_min']} min)",
                })

        cross_skill_available = []
        for from_tier in ('tow', 'light'):
            for to_tier in SKILL_HIERARCHY[from_tier]:
                if to_tier == from_tier:
                    continue
                idle_count = utilization[from_tier]['idle']
                if idle_count > 0 and utilization[to_tier]['idle'] == 0:
                    cross_skill_available.append({
                        'from': from_tier, 'to': to_tier, 'idle_count': idle_count,
                    })

        return {
            'territory_id': territory_id,
            'utilization': utilization,
            'cross_skill_available': cross_skill_available,
            'cascade_opportunities': opportunities,
            'summary': {
                'total_open': len([s for s in data['open_sas'] if 'drop' not in ((s.get('WorkType') or {}).get('Name', '') or '').lower()]),
                'cascade_eligible': len(opportunities),
                'potential_time_saved_min': sum(
                    max(0, o['wait_min'] - (o['cascade_candidates'][0]['eta_min'] or 0))
                    for o in opportunities if o['cascade_candidates']
                ),
            },
        }

    return cache.cached_query(f'cascade_{territory_id}', _fetch, ttl=60)


# ── Feature 4: Enhanced Scorecard (decomposition + decline analysis) ─────────

def get_response_decomposition(territory_id: str, period_start: str, period_end: str):
    """Break response time into dispatch, travel, on-site segments."""
    territory_id = sanitize_soql(territory_id)
    period_start = sanitize_soql(period_start)
    period_end = sanitize_soql(period_end)

    def _fetch():
        next_day = (date.fromisoformat(period_end) + timedelta(days=1)).isoformat()
        since = f"{period_start}T00:00:00Z"
        until = f"{next_day}T00:00:00Z"

        data = sf_parallel(
            sas=lambda: sf_query_all(f"""
                SELECT Id, Status, CreatedDate, SchedStartTime,
                       ActualStartTime, ActualEndTime,
                       ERS_PTA__c, ERS_Dispatch_Method__c,
                       Off_Platform_Truck_Id__c,
                       Off_Platform_Driver__c, Off_Platform_Driver__r.Name,
                       WorkType.Name
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                  AND CreatedDate < {until}
                  AND Status = 'Completed'
                  AND ActualStartTime != null
                  AND ActualEndTime != null
                ORDER BY CreatedDate ASC
            """),
            declines=lambda: sf_query_all(f"""
                SELECT ERS_Facility_Decline_Reason__c reason, COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                  AND CreatedDate < {until}
                  AND ERS_Facility_Decline_Reason__c != null
                GROUP BY ERS_Facility_Decline_Reason__c
                ORDER BY COUNT(Id) DESC
            """),
            cancels=lambda: sf_query_all(f"""
                SELECT ERS_Cancellation_Reason__c reason, COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                  AND CreatedDate < {until}
                  AND ERS_Cancellation_Reason__c != null
                GROUP BY ERS_Cancellation_Reason__c
                ORDER BY COUNT(Id) DESC
            """),
            drivers=lambda: sf_query_all(f"""
                SELECT ServiceResource.Name, ServiceResource.Id,
                       COUNT(Id) total_calls
                FROM AssignedResource
                WHERE ServiceAppointment.ServiceTerritoryId = '{territory_id}'
                  AND ServiceAppointment.CreatedDate >= {since}
                  AND ServiceAppointment.CreatedDate < {until}
                  AND ServiceAppointment.Status = 'Completed'
                GROUP BY ServiceResource.Name, ServiceResource.Id
                ORDER BY COUNT(Id) DESC
                LIMIT 25
            """),
            driver_sas=lambda: sf_query_all(f"""
                SELECT ServiceResource.Name, ServiceResource.Id,
                       ServiceAppointment.CreatedDate, ServiceAppointment.ActualStartTime,
                       ServiceAppointment.ActualEndTime, ServiceAppointment.ERS_PTA__c,
                       ServiceAppointment.WorkType.Name,
                       ServiceAppointment.ERS_Facility_Decline_Reason__c,
                       ServiceAppointment.ERS_Dispatch_Method__c
                FROM AssignedResource
                WHERE ServiceAppointment.ServiceTerritoryId = '{territory_id}'
                  AND ServiceAppointment.CreatedDate >= {since}
                  AND ServiceAppointment.CreatedDate < {until}
                  AND ServiceAppointment.Status = 'Completed'
                  AND ServiceAppointment.ActualStartTime != null
                ORDER BY ServiceResource.Name
                LIMIT 2000
            """),
            # Towbook garage: decline SAs with Off_Platform_Truck_Id for per-contractor decline tracking
            decline_sas=lambda: sf_query_all(f"""
                SELECT Off_Platform_Driver__c, ERS_Facility_Decline_Reason__c
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                  AND CreatedDate < {until}
                  AND ERS_Facility_Decline_Reason__c != null
                LIMIT 2000
            """),
        )

        # Response time decomposition
        decomp_by_wt = defaultdict(lambda: {'dispatch': [], 'travel': [], 'onsite': [], 'total': [], 'count': 0})
        all_dispatch = []
        all_travel = []
        all_onsite = []
        all_total = []

        # Towbook ActualStartTime is NOT real arrival — the integration writes a
        # future estimated time. Real arrival = ServiceAppointmentHistory 'On Location'.
        def _is_towbook(sa):
            return (sa.get('ERS_Dispatch_Method__c') or '') == 'Towbook'

        _tb_count = sum(1 for sa in data['sas'] if _is_towbook(sa))
        is_towbook_garage = _tb_count > len(data['sas']) * 0.5

        # Fetch real On Location timestamps for Towbook SAs
        _towbook_completed_ids = [
            sa['Id'] for sa in data['sas']
            if _is_towbook(sa) and sa.get('Id')
        ]
        _on_loc_map = get_towbook_on_location(_towbook_completed_ids) if _towbook_completed_ids else {}

        for sa in data['sas']:
            wt = (sa.get('WorkType') or {}).get('Name', '') or ''
            if 'drop' in wt.lower():
                continue

            created = _parse_dt(sa.get('CreatedDate'))
            sched = _parse_dt(sa.get('SchedStartTime'))
            started = _parse_dt(sa.get('ActualStartTime'))
            ended = _parse_dt(sa.get('ActualEndTime'))

            if not created:
                continue

            if _is_towbook(sa):
                # Towbook: use real On Location timestamp from ServiceAppointmentHistory
                on_loc_str = _on_loc_map.get(sa.get('Id'))
                on_loc = _parse_dt(on_loc_str) if on_loc_str else None
                if not on_loc or not created:
                    continue
                response = (on_loc - created).total_seconds() / 60
                if response <= 0 or response > 480:
                    continue
                # Can't decompose dispatch/travel for Towbook — use total response
                dispatch_val = response
                travel_val = 0
                # On-site: use On Location → End if both exist
                if on_loc and ended:
                    onsite = (ended - on_loc).total_seconds() / 60
                    if onsite < 0 or onsite > 240:
                        onsite = 0
                else:
                    onsite = 0
                total_min = response + onsite
            else:
                # Fleet: use real ATA timestamps
                if not started or not ended:
                    continue

                total_min = (ended - created).total_seconds() / 60
                if total_min <= 0 or total_min > 480:
                    continue

                onsite = (ended - started).total_seconds() / 60
                if onsite < 0 or onsite > 240:
                    continue

                response = (started - created).total_seconds() / 60
                if response < 0:
                    continue

                if sched and created < sched < started:
                    dispatch_val = (sched - created).total_seconds() / 60
                    travel_val = (started - sched).total_seconds() / 60
                else:
                    dispatch_val = response
                    travel_val = 0

            wt_key = wt if wt else 'Other'
            d = decomp_by_wt[wt_key]
            d['dispatch'].append(dispatch_val)
            d['travel'].append(travel_val)
            d['onsite'].append(onsite)
            d['total'].append(total_min)
            d['count'] += 1

            all_dispatch.append(dispatch_val)
            all_travel.append(travel_val)
            all_onsite.append(onsite)
            all_total.append(total_min)

        def _avg(lst):
            return round(sum(lst) / max(len(lst), 1)) if lst else None

        def _median(lst):
            if not lst:
                return None
            s = sorted(lst)
            return round(s[len(s) // 2])

        decomposition = {
            'avg_dispatch_min': _avg(all_dispatch),
            'avg_travel_min': _avg(all_travel),
            'avg_onsite_min': _avg(all_onsite),
            'avg_total_min': _avg(all_total),
            'median_dispatch_min': _median(all_dispatch),
            'median_travel_min': _median(all_travel),
            'median_onsite_min': _median(all_onsite),
            'median_total_min': _median(all_total),
            'sample_size': len(all_total),
            'method_note': 'ATA from On Location history (Towbook garages)' if is_towbook_garage else 'ATA-based (real arrival times)',
            'response_metric': 'ATA (actual)',
            'by_work_type': {},
        }
        for wt_key, d in decomp_by_wt.items():
            decomposition['by_work_type'][wt_key] = {
                'dispatch': _avg(d['dispatch']),
                'travel': _avg(d['travel']),
                'onsite': _avg(d['onsite']),
                'total': _avg(d['total']),
                'count': d['count'],
            }

        # Decline analysis
        total_sas_for_decline = len(data['sas'])
        decline_rows = data['declines']
        total_declines = sum(r.get('cnt', 0) for r in decline_rows)
        decline_analysis = {
            'total_declines': total_declines,
            'decline_rate': round(100 * total_declines / max(total_sas_for_decline + total_declines, 1), 1),
            'by_reason': [
                {'reason': r.get('reason', 'Unknown'), 'count': r.get('cnt', 0),
                 'pct': round(100 * r.get('cnt', 0) / max(total_declines, 1), 1)}
                for r in decline_rows
            ],
            'top_reason': decline_rows[0].get('reason') if decline_rows else None,
        }

        # Cancellation analysis
        cancel_rows = data['cancels']
        total_cancels = sum(r.get('cnt', 0) for r in cancel_rows)
        cancel_analysis = {
            'total_cancellations': total_cancels,
            'by_reason': [
                {'reason': r.get('reason', 'Unknown'), 'count': r.get('cnt', 0),
                 'pct': round(100 * r.get('cnt', 0) / max(total_cancels, 1), 1)}
                for r in cancel_rows
            ],
        }

        # Detect Towbook garage: check if majority of completed SAs are Towbook-dispatched
        tb_sa_count = sum(1 for sa in data['sas'] if (sa.get('ERS_Dispatch_Method__c') or '') == 'Towbook')
        is_towbook_garage = tb_sa_count > len(data['sas']) * 0.5

        missing_truck_id_count = 0

        if is_towbook_garage:
            # Towbook garage: build leaderboard from driver (Off_Platform_Driver__c)
            contractor_stats = {}
            # Build per-driver decline counts
            driver_decline_counts = defaultdict(int)
            for d in data['decline_sas']:
                did = d.get('Off_Platform_Driver__c') or ''
                if did:
                    driver_decline_counts[did] += 1

            for sa in data['sas']:
                wt = (sa.get('WorkType') or {}).get('Name', '') or ''
                if 'drop' in wt.lower():
                    continue

                driver_id = sa.get('Off_Platform_Driver__c') or ''
                if not driver_id:
                    missing_truck_id_count += 1
                    continue

                driver_name = (sa.get('Off_Platform_Driver__r') or {}).get('Name', '') or 'Unknown Driver'

                if driver_id not in contractor_stats:
                    contractor_stats[driver_id] = {
                        'name': driver_name, 'id': driver_id,
                        'total_calls': 0, 'response_times': [],
                        'onsite_times': [], 'declines': driver_decline_counts.get(driver_id, 0),
                    }

                cs = contractor_stats[driver_id]
                if driver_name != 'Unknown Driver' and cs['name'] == 'Unknown Driver':
                    cs['name'] = driver_name
                cs['total_calls'] += 1

                # Use real On Location timestamp for Towbook response time
                created_lb = _parse_dt(sa.get('CreatedDate'))
                on_loc_str = _on_loc_map.get(sa.get('Id'))
                on_loc = _parse_dt(on_loc_str) if on_loc_str else None
                if created_lb and on_loc:
                    rt = (on_loc - created_lb).total_seconds() / 60
                    if 0 < rt < 480:
                        cs['response_times'].append(rt)

                # On-site duration: On Location → End
                ended_lb = _parse_dt(sa.get('ActualEndTime'))
                if on_loc and ended_lb:
                    ot = (ended_lb - on_loc).total_seconds() / 60
                    if 0 < ot < 240:
                        cs['onsite_times'].append(ot)

            leaderboard = []
            for cs in contractor_stats.values():
                rts = cs['response_times']
                ots = cs['onsite_times']
                leaderboard.append({
                    'name': cs['name'],
                    'id': cs['id'],
                    'total_calls': cs['total_calls'],
                    'avg_response_min': round(sum(rts) / len(rts)) if rts else None,
                    'median_response_min': round(sorted(rts)[len(rts) // 2]) if rts else None,
                    'avg_onsite_min': round(sum(ots) / len(ots)) if ots else None,
                    'declines': cs['declines'],
                    'decline_rate': round(100 * cs['declines'] / max(cs['total_calls'] + cs['declines'], 1), 1),
                    'response_metric': 'ATA (actual)',
                })
            leaderboard.sort(key=lambda d: d['total_calls'], reverse=True)
        else:
            # Fleet/On-Platform garage: build leaderboard from AssignedResource
            driver_stats = {}
            for r in data['driver_sas']:
                sa_data = r
                sa_ref = sa_data.get('ServiceAppointment') or sa_data

                # Exclude Tow Drop-Off SAs (paired SAs, not real member calls)
                wt_name = ((sa_ref.get('WorkType') or {}).get('Name', '') or '')
                if 'drop' in wt_name.lower():
                    continue

                # Skip Towbook SAs — ActualStartTime is unreliable (midnight bulk-update)
                dispatch_method = (sa_ref.get('ERS_Dispatch_Method__c') or '')
                if dispatch_method == 'Towbook':
                    continue

                drv = (r.get('ServiceResource') or {}).get('Name', '?')
                drv_id = (r.get('ServiceResource') or {}).get('Id', '')

                if drv_id not in driver_stats:
                    driver_stats[drv_id] = {
                        'name': drv, 'id': drv_id,
                        'total_calls': 0, 'response_times': [],
                        'onsite_times': [], 'declines': 0,
                    }

                ds = driver_stats[drv_id]
                ds['total_calls'] += 1

                created = _parse_dt(sa_ref.get('CreatedDate'))
                started = _parse_dt(sa_ref.get('ActualStartTime'))
                ended = _parse_dt(sa_ref.get('ActualEndTime'))

                if created and started:
                    rt = (started - created).total_seconds() / 60
                    if 0 < rt < 480:
                        ds['response_times'].append(rt)
                if started and ended:
                    ot = (ended - started).total_seconds() / 60
                    if 0 < ot < 240:
                        ds['onsite_times'].append(ot)
                if sa_ref.get('ERS_Facility_Decline_Reason__c'):
                    ds['declines'] += 1

            leaderboard = []
            for ds in driver_stats.values():
                rts = ds['response_times']
                ots = ds['onsite_times']
                leaderboard.append({
                    'name': ds['name'],
                    'id': ds['id'],
                    'total_calls': ds['total_calls'],
                    'avg_response_min': round(sum(rts) / len(rts)) if rts else None,
                    'median_response_min': round(sorted(rts)[len(rts) // 2]) if rts else None,
                    'avg_onsite_min': round(sum(ots) / len(ots)) if ots else None,
                    'declines': ds['declines'],
                    'decline_rate': round(100 * ds['declines'] / max(ds['total_calls'], 1), 1),
                })
            leaderboard.sort(key=lambda d: d.get('avg_response_min') or 999)

        return {
            'garage_type': 'towbook' if is_towbook_garage else 'fleet',
            'response_decomposition': decomposition,
            'decline_analysis': decline_analysis,
            'cancel_analysis': cancel_analysis,
            'driver_leaderboard': leaderboard,
            'missing_truck_id_count': missing_truck_id_count,
        }

    return cache.cached_query(f'decomp_{territory_id}_{period_start}_{period_end}', _fetch, ttl=3600)


# ── Feature 5: Demand Forecast ───────────────────────────────────────────────

def get_forecast(territory_id: str, weeks_history: int = 8):
    """16-day demand forecast using DOW patterns + weather."""
    territory_id = sanitize_soql(territory_id)

    def _fetch():
        days_back = weeks_history * 7
        cutoff = (date.today() - timedelta(days=days_back)).isoformat()
        since = f"{cutoff}T00:00:00Z"

        # Historical volume by DOW
        hist = sf_query_all(f"""
            SELECT DAY_IN_WEEK(CreatedDate) dow, COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE ServiceTerritoryId = '{territory_id}'
              AND CreatedDate >= {since}
              AND Status IN ('Dispatched','Completed','Canceled','Assigned')
              AND WorkType.Name != 'Tow Drop-Off'
            GROUP BY DAY_IN_WEEK(CreatedDate)
        """)

        # SOQL DOW: 1=Sun..7=Sat
        _DOW_MAP = {1: 'Sun', 2: 'Mon', 3: 'Tue', 4: 'Wed', 5: 'Thu', 6: 'Fri', 7: 'Sat'}
        _DOW_NUM = {'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3, 'Fri': 4, 'Sat': 5, 'Sun': 6}
        dow_totals = {}
        for r in hist:
            day_name = _DOW_MAP.get(int(r.get('dow', 0)), '?')
            dow_totals[day_name] = r.get('cnt', 0)

        dow_avg = {d: round(v / max(weeks_history, 1)) for d, v in dow_totals.items()}

        # Get weather forecast
        weather_forecast = []
        try:
            weather_api_path = os.path.join(os.path.dirname(__file__), '..', '..', '..')
            sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
            from weather import WeatherAnalyzer
            wx = WeatherAnalyzer()
            fc = wx.get_forecast(forecast_days=16)
            if fc is not None and len(fc) > 0:
                for _, row in fc.iterrows():
                    weather_forecast.append({
                        'date': row['date'].strftime('%Y-%m-%d') if hasattr(row['date'], 'strftime') else str(row['date'])[:10],
                        'temp_max_f': round(row.get('temp_max_f', 0)),
                        'temp_min_f': round(row.get('temp_min_f', 0)),
                        'snow_in': round(row.get('snow_in', 0), 1),
                        'precip_in': round(row.get('precip_in', 0), 1),
                        'wind_max_mph': round(row.get('wind_max_mph', 0)),
                        'severity': row.get('severity', 'Clear'),
                        'weather_desc': row.get('weather_desc', ''),
                        'weather_code': int(row.get('weather_code', 0)),
                    })
        except Exception:
            # Fallback: generate 16 days without weather
            for i in range(16):
                d = date.today() + timedelta(days=i)
                weather_forecast.append({
                    'date': d.isoformat(),
                    'temp_max_f': None, 'temp_min_f': None,
                    'snow_in': 0, 'precip_in': 0, 'wind_max_mph': 0,
                    'severity': 'Clear', 'weather_desc': 'No forecast data',
                    'weather_code': 0,
                })

        # Build 16-day forecast
        forecast_days = []
        for wx_day in weather_forecast:
            d = date.fromisoformat(wx_day['date'])
            dow_name = d.strftime('%a')
            base_vol = dow_avg.get(dow_name, 0)
            multiplier = DOW_WEATHER_MULTIPLIERS.get(wx_day['severity'], 1.0)
            adjusted = round(base_vol * multiplier)

            # Driver needs per 2-hour block
            call_tier_split = {'tow': 0.48, 'battery': 0.30, 'light': 0.22}
            peak_block_calls = round(adjusted * 0.15)  # ~15% of daily volume in peak 2h block
            peak_tow = math.ceil(peak_block_calls * call_tier_split['tow'] * CYCLE_TIMES['tow'] / BLOCK_MIN)
            peak_bl = math.ceil(peak_block_calls * (call_tier_split['battery'] + call_tier_split['light']) * CYCLE_TIMES['battery'] / BLOCK_MIN)

            forecast_days.append({
                'date': wx_day['date'],
                'day_of_week': dow_name,
                'weather': wx_day,
                'base_volume': base_vol,
                'weather_multiplier': multiplier,
                'adjusted_volume': adjusted,
                'driver_needs': {
                    'peak_tow': peak_tow,
                    'peak_batt_light': peak_bl,
                    'peak_total': peak_tow + peak_bl,
                    'peak_block': '12-2pm',
                },
                'confidence': 'high' if base_vol > 10 else 'medium' if base_vol > 0 else 'low',
            })

        return {
            'forecast': forecast_days,
            'model': {
                'weeks_analyzed': weeks_history,
                'dow_averages': dow_avg,
                'weather_multipliers': DOW_WEATHER_MULTIPLIERS,
            },
        }

    return cache.cached_query(f'forecast_{territory_id}_{weeks_history}', _fetch, ttl=3600)
