"""Dispatch optimization module — queue board, driver recommender, cross-skill cascade, forecast."""

from datetime import datetime, date, timedelta, timezone
from collections import defaultdict

from utils import (
    _ET, parse_dt as _parse_dt, haversine,
    TRAVEL_SPEED_MPH, TOW_SKILLS, LIGHT_SKILLS,
    BATTERY_SKILLS, SKILL_HIERARCHY,
)
from sf_client import sf_query_all, sf_parallel, sanitize_soql
import cache

# ── Constants (dispatch-specific) ────────────────────────────────────────────
URGENCY_THRESHOLDS = [
    (20, 'green'), (35, 'yellow'), (45, 'orange'),
]


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
                  AND ERS_Driver__r.IsActive = true
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
                  AND ServiceResource.IsActive = true
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
                'territory_type': d_type,
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
            'total_evaluated': len(data['gps']),
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
                  AND ERS_Driver__r.IsActive = true
            """),
            gps=lambda: sf_query_all(f"""
                SELECT ServiceResourceId,
                       ServiceResource.Name,
                       ServiceResource.LastKnownLatitude,
                       ServiceResource.LastKnownLongitude
                FROM ServiceTerritoryMember
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND TerritoryType IN ('P','S')
                  AND ServiceResource.IsActive = true
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
