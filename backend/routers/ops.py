"""Ops endpoints -- daily operations space."""

import math as _math
from fastapi import APIRouter, HTTPException, Query
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from sf_client import sf_query_all, sf_parallel, sanitize_soql
from utils import (
    _ET, parse_dt as _parse_dt, to_eastern as _to_eastern,
    is_fleet_territory,
)
from ops import get_ops_territories, get_ops_territory_detail, get_ops_garages
import cache

router = APIRouter()


# ── Daily Operations ──────────────────────────────────────────────────────────

@router.get("/api/ops/territories")
def ops_territories():
    """Today's operational view -- all territories with correct PTA/ATA."""
    return get_ops_territories()


@router.get("/api/ops/territory/{territory_id}")
def ops_territory_detail(territory_id: str):
    """Today's SA list for a single territory with PTA/ATA per call."""
    territory_id = sanitize_soql(territory_id)
    return get_ops_territory_detail(territory_id)


@router.get("/api/ops/garages")
def ops_garages():
    """All garage territories with location, phone, and priority matrix info."""
    return get_ops_garages()


# ── Haversine helper ─────────────────────────────────────────────────────────

def _haversine_mi(lat1, lon1, lat2, lon2):
    R = 3958.8  # Earth radius in miles
    dlat = _math.radians(lat2 - lat1)
    dlon = _math.radians(lon2 - lon1)
    a = _math.sin(dlat/2)**2 + _math.cos(_math.radians(lat1)) * _math.cos(_math.radians(lat2)) * _math.sin(dlon/2)**2
    return round(R * 2 * _math.atan2(_math.sqrt(a), _math.sqrt(1-a)), 1)


# ── Skill hierarchy for driver-call matching ─────────────────────────────────
# 4 call types: Tow, Winch, Battery, Light (everything else)
# Driver tiers: Tow can do all 4. Light can do winch+light+battery. Battery only battery.
_TOW_CAPS = {'tow', 'flat bed', 'wheel lift'}
_BATTERY_CAPS = {'battery', 'battery service', 'jumpstart'}

def _driver_tier(truck_capabilities: str) -> str:
    """Classify driver tier from truck capabilities string (semicolon-separated)."""
    caps = {c.strip().lower() for c in (truck_capabilities or '').split(';') if c.strip()}
    if caps & _TOW_CAPS:
        return 'tow'
    if caps & _BATTERY_CAPS:
        # Has battery but NOT light-service items like Tire/Lockout -> battery-only
        light_caps = {'tire', 'lockout', 'locksmith', 'fuel - gasoline', 'fuel - diesel',
                      'extrication- driveway', 'extrication- highway/roadway', 'winch'}
        if caps & light_caps:
            return 'light'
        return 'battery'
    # Has light-service caps (tire, lockout, etc.) but no tow and no battery
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


# ── Ops Brief -- Fleet Status + Coverage + Suggestions ────────────────────────

@router.get("/api/ops/brief")
def ops_brief():
    """Proactive ops brief: fleet status, coverage gaps, demand, suggestions."""
    from ops import _get_priority_matrix

    def _fetch():
        now_utc = datetime.now(timezone.utc)
        now_et = now_utc.astimezone(_ET)
        today_start = now_et.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        cutoff = today_start.strftime('%Y-%m-%dT%H:%M:%SZ')

        # 1) Parallel fetch: drivers, active SAs, priority matrix, hourly baseline
        from sf_client import sf_parallel, sf_query_all as _sqa

        def _get_drivers():
            return _sqa("""
                SELECT Id, Name, LastKnownLatitude, LastKnownLongitude,
                       LastKnownLocationDate, ERS_Driver_Type__c, ERS_Tech_ID__c,
                       RelatedRecord.Phone
                FROM ServiceResource
                WHERE IsActive = true AND ResourceType = 'T'
                  AND LastKnownLatitude != null
                  AND ERS_Driver_Type__c IN ('Fleet Driver', 'On-Platform Contractor Driver')
            """)

        def _get_active_sas():
            return _sqa(f"""
                SELECT Id, AppointmentNumber, Status, CreatedDate, ActualStartTime,
                       ERS_PTA__c, ERS_Dispatch_Method__c, ERS_Parent_Territory__c,
                       ERS_Parent_Territory__r.Name,
                       ServiceTerritoryId, ServiceTerritory.Name,
                       WorkType.Name, Latitude, Longitude, Street, City, PostalCode
                FROM ServiceAppointment
                WHERE CreatedDate >= {cutoff}
                  AND ServiceTerritoryId != null
                  AND Status IN ('Dispatched','Completed','Canceled',
                                 'Cancel Call - Service Not En Route',
                                 'Cancel Call - Service En Route',
                                 'Unable to Complete','Assigned','No-Show')
                ORDER BY CreatedDate ASC
            """)

        def _get_assigned_resources():
            return _sqa(f"""
                SELECT ServiceResourceId, ServiceAppointmentId,
                       ServiceResource.Name
                FROM AssignedResource
                WHERE ServiceAppointment.CreatedDate >= {cutoff}
                  AND ServiceAppointment.Status IN ('Dispatched','Assigned','In Progress')
            """)

        def _get_logged_in_drivers():
            """Drivers currently logged into a vehicle (Asset.ERS_Driver__c)."""
            return _sqa("""
                SELECT ERS_Driver__c, Name, ERS_Truck_Capabilities__c, ERS_LegacyTruckID__c
                FROM Asset
                WHERE RecordType.Name = 'ERS Truck'
                  AND ERS_Driver__c != null
                  AND ERS_Driver__r.IsActive = true
            """)

        def _get_hourly_baseline():
            """Historical hourly volume for same DOW (last 8 weeks)."""
            dow = now_utc.weekday()  # 0=Mon ... 6=Sun
            # SF DAY_IN_WEEK: 1=Sun, 2=Mon, ... 7=Sat
            sf_dow = dow + 2 if dow < 6 else 1
            eight_weeks_ago = (now_utc - timedelta(weeks=8)).strftime('%Y-%m-%dT00:00:00Z')
            return _sqa(f"""
                SELECT HOUR_IN_DAY(CreatedDate) hr, COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE CreatedDate >= {eight_weeks_ago}
                  AND DAY_IN_WEEK(CreatedDate) = {sf_dow}
                  AND ServiceTerritoryId != null
                  AND Status != 'Canceled'
                GROUP BY HOUR_IN_DAY(CreatedDate)
                ORDER BY HOUR_IN_DAY(CreatedDate)
            """)

        data = sf_parallel(
            drivers=_get_drivers,
            sas=_get_active_sas,
            assigned=_get_assigned_resources,
            baseline=_get_hourly_baseline,
            logged_in=_get_logged_in_drivers,
        )

        # Filter: only drivers logged into a vehicle (Asset.ERS_Driver__c)
        logged_in_ids = set()
        truck_info = {}  # driver_id -> truck info
        for asset in data['logged_in']:
            dr_id = asset.get('ERS_Driver__c')
            if dr_id:
                logged_in_ids.add(dr_id)
                truck_info[dr_id] = {
                    'truck_name': asset.get('Name', ''),
                    'truck_capabilities': asset.get('ERS_Truck_Capabilities__c', ''),
                    'truck_legacy_id': asset.get('ERS_LegacyTruckID__c', ''),
                }
        all_drivers_raw = []
        for d in data['drivers']:
            if d.get('Name', '').lower().startswith('towbook'):
                continue
            if d['Id'] not in logged_in_ids:
                continue
            all_drivers_raw.append(d)
        all_sas = data['sas']
        assigned_raw = data['assigned']
        baseline_raw = data['baseline']
        matrix = _get_priority_matrix()

        # 2) Build assigned driver set (drivers with active/dispatched SAs)
        busy_driver_ids = set()
        busy_driver_sa = {}  # driver_id -> SA info
        for ar in assigned_raw:
            dr_id = ar.get('ServiceResourceId')
            sa_id = ar.get('ServiceAppointmentId')
            if dr_id:
                busy_driver_ids.add(dr_id)
                busy_driver_sa[dr_id] = sa_id

        # 3) Classify drivers
        idle_drivers = []
        busy_drivers = []
        for d in all_drivers_raw:
            gps_date = _to_eastern(d.get('LastKnownLocationDate'))
            truck = truck_info.get(d['Id'], {})
            caps = truck.get('truck_capabilities', '')
            driver_info = {
                'id': d['Id'],
                'name': d.get('Name', '?'),
                'lat': float(d['LastKnownLatitude']),
                'lon': float(d['LastKnownLongitude']),
                'gps_time': gps_date.strftime('%I:%M %p') if gps_date else '?',
                'driver_type': d.get('ERS_Driver_Type__c', ''),
                'tier': _driver_tier(caps),
                'phone': (d.get('RelatedRecord') or {}).get('Phone'),
                'truck': truck.get('truck_name', ''),
                'truck_capabilities': caps,
            }
            if d['Id'] in busy_driver_ids:
                busy_drivers.append(driver_info)
            else:
                idle_drivers.append(driver_info)

        fleet_status = {
            'total': len(all_drivers_raw),
            'busy': len(busy_drivers),
            'idle': len(idle_drivers),
            'idle_drivers': idle_drivers,
            'busy_drivers': busy_drivers,
        }

        # 4) Open calls (waiting for service) -- exclude Tow Drop-Off (paired SAs, not actionable)
        open_sas = []
        for sa in all_sas:
            if sa.get('Status') not in ('Dispatched', 'Assigned'):
                continue
            wt = (sa.get('WorkType') or {}).get('Name', '')
            if 'drop-off' in wt.lower():
                continue
            cdt = _parse_dt(sa.get('CreatedDate'))
            wait_min = 0
            if cdt:
                if cdt.tzinfo is None:
                    cdt = cdt.replace(tzinfo=timezone.utc)
                wait_min = round((now_utc - cdt).total_seconds() / 60)
            if wait_min > 1440:
                continue  # Stale SA -- skip
            lat, lon = sa.get('Latitude'), sa.get('Longitude')
            pta = sa.get('ERS_PTA__c')
            wt_name = (sa.get('WorkType') or {}).get('Name', '?')
            open_sas.append({
                'id': sa.get('Id'),
                'number': sa.get('AppointmentNumber', '?'),
                'wait_min': wait_min,
                'pta_min': round(float(pta)) if pta and 0 < float(pta) < 999 else None,
                'work_type': wt_name,
                'call_tier': _call_tier(wt_name),
                'lat': float(lat) if lat else None,
                'lon': float(lon) if lon else None,
                'territory': (sa.get('ServiceTerritory') or {}).get('Name', '?'),
                'territory_id': sa.get('ServiceTerritoryId'),
                'zone': (sa.get('ERS_Parent_Territory__r') or {}).get('Name', '?'),
                'zone_id': sa.get('ERS_Parent_Territory__c'),
                'address': f"{sa.get('Street') or ''} {sa.get('City') or ''}".strip(),
                'zip': sa.get('PostalCode') or '',
            })
        open_sas.sort(key=lambda x: x['wait_min'], reverse=True)

        # 5) At-risk calls (approaching SLA)
        at_risk = []
        for oc in open_sas:
            sla_target = oc['pta_min'] or 45
            time_left = sla_target - oc['wait_min']
            if time_left < 15 and oc['lat'] and oc['lon']:
                # Find nearest idle driver WITH matching skills
                ct = oc.get('call_tier', 'light')
                nearest = None
                nearest_dist = 999
                for drv in idle_drivers:
                    if not _can_serve(drv.get('tier', 'light'), ct):
                        continue
                    d = _haversine_mi(oc['lat'], oc['lon'], drv['lat'], drv['lon'])
                    if d < nearest_dist:
                        nearest_dist = d
                        nearest = drv
                at_risk.append({
                    **oc,
                    'time_left_min': max(time_left, 0),
                    'sla_target': sla_target,
                    'nearest_idle_driver': nearest['name'] if nearest else None,
                    'nearest_idle_dist_mi': nearest_dist if nearest and nearest_dist < 999 else None,
                    'nearest_idle_tier': nearest.get('tier') if nearest else None,
                })

        # 6) Zone-level coverage analysis using priority matrix
        # Group open calls by zone
        calls_by_zone = defaultdict(list)
        for oc in open_sas:
            if oc['zone_id']:
                calls_by_zone[oc['zone_id']].append(oc)

        # Also count completed today by zone
        completed_by_zone = defaultdict(int)
        for sa in all_sas:
            if sa.get('Status') == 'Completed':
                zone_id = sa.get('ERS_Parent_Territory__c')
                if zone_id:
                    completed_by_zone[zone_id] += 1

        # Build zone summaries
        zones = []
        zone_names = {}
        zone_cities = defaultdict(lambda: defaultdict(int))
        for sa in all_sas:
            zid = sa.get('ERS_Parent_Territory__c')
            zname = (sa.get('ERS_Parent_Territory__r') or {}).get('Name')
            if zid and zname:
                zone_names[zid] = zname
                city = (sa.get('City') or '').strip()
                if city:
                    zone_cities[zid][city] += 1

        # Build display name: "CM011 -- Buffalo" (code + most common city)
        zone_display = {}
        for zid, code in zone_names.items():
            cities = zone_cities.get(zid, {})
            if cities:
                top_city = max(cities, key=cities.get)
                zone_display[zid] = f"{code} \u2014 {top_city}"
            else:
                zone_display[zid] = code

        for zone_id, zone_name in zone_names.items():
            open_calls = calls_by_zone.get(zone_id, [])
            completed = completed_by_zone.get(zone_id, 0)

            # Find primary garage for this zone from matrix
            primary_garage = None
            for (pid, sid), rank in matrix['rank_lookup'].items():
                if pid == zone_id and rank == 1:
                    # Get garage name from by_garage entries
                    for entry in matrix['by_garage'].get(sid, []):
                        if entry['parent_id'] == zone_id:
                            primary_garage = sid
                            break
                    break

            # Find nearest driver to zone centroid -- must match skill of longest-waiting call
            nearest_driver = None
            nearest_dist = 999
            zone_lat = None
            zone_lon = None
            if open_calls:
                lats = [c['lat'] for c in open_calls if c['lat']]
                lons = [c['lon'] for c in open_calls if c['lon']]
                # Use the tier of the longest-waiting call for matching
                longest_call_tier = open_calls[0].get('call_tier', 'light') if open_calls else 'light'
                if lats and lons:
                    zone_lat = sum(lats) / len(lats)
                    zone_lon = sum(lons) / len(lons)
                    for drv in idle_drivers:
                        if not _can_serve(drv.get('tier', 'light'), longest_call_tier):
                            continue
                        d = _haversine_mi(zone_lat, zone_lon, drv['lat'], drv['lon'])
                        if d < nearest_dist:
                            nearest_dist = d
                            nearest_driver = drv

            # Zone health
            max_wait = max((c['wait_min'] for c in open_calls), default=0)
            status = 'clear'
            if len(open_calls) >= 3 and max_wait > 45:
                status = 'critical'
            elif len(open_calls) >= 2 and max_wait > 30:
                status = 'strained'
            elif len(open_calls) > 0:
                status = 'active'

            zones.append({
                'zone_id': zone_id,
                'zone_name': zone_display.get(zone_id, zone_name),
                'open_calls': len(open_calls),
                'completed_today': completed,
                'total_today': len(open_calls) + completed,
                'max_wait_min': max_wait,
                'status': status,
                'nearest_idle_driver': nearest_driver['name'] if nearest_driver else None,
                'nearest_idle_dist_mi': nearest_dist if nearest_driver and nearest_dist < 999 else None,
                'coverage': 'covered' if nearest_driver and nearest_dist < 15 else ('thin' if nearest_driver and nearest_dist < 30 else 'gap'),
            })
        zones.sort(key=lambda z: (-z['open_calls'], -z['max_wait_min']))

        # 7) Volume baseline comparison
        # Current hour volume
        current_hour = _to_eastern(now_utc.isoformat()).hour if _to_eastern(now_utc.isoformat()) else now_utc.hour
        current_hour_calls = sum(1 for sa in all_sas
                                 if _to_eastern(sa.get('CreatedDate'))
                                 and _to_eastern(sa.get('CreatedDate')).hour == current_hour)

        # Parse baseline -- HOUR_IN_DAY returns UTC, convert to Eastern
        hourly_baseline = {}
        for row in baseline_raw:
            utc_hr = row.get('hr')
            cnt = row.get('cnt', 0)
            if utc_hr is not None:
                # Convert UTC hour to Eastern (DST-aware)
                ref_utc = now_utc.replace(hour=int(utc_hr), minute=0, second=0, microsecond=0)
                eastern_hr = ref_utc.astimezone(_ET).hour
                hourly_baseline[eastern_hr] = hourly_baseline.get(eastern_hr, 0) + round(cnt / 8)  # avg over 8 weeks

        normal_for_hour = hourly_baseline.get(current_hour, 0)
        pct_vs_normal = round(100 * (current_hour_calls - normal_for_hour) / max(normal_for_hour, 1)) if normal_for_hour > 0 else 0

        demand = {
            'current_hour': current_hour,
            'current_hour_calls': current_hour_calls,
            'normal_for_hour': normal_for_hour,
            'pct_vs_normal': pct_vs_normal,
            'trend': 'surge' if pct_vs_normal > 30 else ('above' if pct_vs_normal > 10 else ('normal' if pct_vs_normal > -15 else 'quiet')),
            'hourly_baseline': hourly_baseline,
            'today_total': len(all_sas),
        }

        # 8) Actionable suggestions
        suggestions = []

        # Reposition idle drivers toward uncovered zones (skill-matched)
        for z in zones:
            if z['open_calls'] > 0 and z['coverage'] == 'gap':
                # Find closest idle driver with matching skills
                best_drv = None
                best_dist = 999
                zone_calls = calls_by_zone.get(z['zone_id'], [])
                if zone_calls:
                    zc = zone_calls[0]
                    zc_tier = zc.get('call_tier', 'light')
                    if zc['lat'] and zc['lon']:
                        for drv in idle_drivers:
                            if not _can_serve(drv.get('tier', 'light'), zc_tier):
                                continue
                            d = _haversine_mi(zc['lat'], zc['lon'], drv['lat'], drv['lon'])
                            if d < best_dist:
                                best_dist = d
                                best_drv = drv
                if best_drv:
                    suggestions.append({
                        'type': 'reposition',
                        'priority': 'high',
                        'driver': best_drv['name'],
                        'driver_type': best_drv['driver_type'],
                        'to_zone': z['zone_name'],
                        'distance_mi': best_dist,
                        'reason': f"{z['open_calls']} call(s) waiting, no driver within 30 mi",
                    })

        # Escalate calls at risk of missing SLA
        for ar in at_risk:
            suggestions.append({
                'type': 'escalate',
                'priority': 'critical' if ar['time_left_min'] <= 5 else 'high',
                'call_number': ar['number'],
                'wait_min': ar['wait_min'],
                'sla_target': ar['sla_target'],
                'time_left_min': ar['time_left_min'],
                'work_type': ar['work_type'],
                'nearest_driver': ar.get('nearest_idle_driver'),
                'nearest_dist_mi': ar.get('nearest_idle_dist_mi'),
                'reason': f"SA {ar['number']} at {ar['wait_min']} min -- " + ('PAST SLA' if ar['time_left_min'] <= 0 else f"{ar['time_left_min']} min to SLA"),
            })

        # Surge warning
        if demand['trend'] == 'surge':
            suggestions.append({
                'type': 'surge',
                'priority': 'medium',
                'reason': f"Volume {pct_vs_normal}% above normal for {current_hour}:00. Consider activating backup drivers.",
            })

        # Coverage thin warnings
        thin_zones = [z for z in zones if z['coverage'] == 'thin' and z['open_calls'] > 0]
        if thin_zones:
            for tz in thin_zones[:3]:
                suggestions.append({
                    'type': 'coverage',
                    'priority': 'medium',
                    'zone': tz['zone_name'],
                    'nearest_driver': tz['nearest_idle_driver'],
                    'distance_mi': tz['nearest_idle_dist_mi'],
                    'reason': f"{tz['zone_name']}: nearest idle driver is {tz['nearest_idle_dist_mi']} mi away",
                })

        # Sort suggestions by priority
        pri_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        suggestions.sort(key=lambda s: pri_order.get(s['priority'], 9))

        return {
            'fleet': fleet_status,
            'open_calls': open_sas[:30],
            'at_risk': at_risk,
            'zones': zones,
            'demand': demand,
            'suggestions': suggestions[:15],
            'generated_at': now_utc.isoformat(),
        }

    return cache.cached_query('ops_brief', _fetch, ttl=60)
