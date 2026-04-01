"""Garage endpoints — analytics space."""

from fastapi import APIRouter, HTTPException, Query
from datetime import datetime, date, timedelta, timezone
from collections import defaultdict

from sf_client import sf_query_all, sf_parallel, sanitize_soql, get_towbook_on_location
from utils import (
    _ET, parse_dt as _parse_dt, to_eastern as _to_eastern,
    is_fleet_territory,
)
from scheduler import generate_schedule
from simulator import simulate_day
from scorer import compute_score
from dispatch import get_response_decomposition
import cache

router = APIRouter()


# ── Skill hierarchy for driver-call matching ─────────────────────────────────
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


# ── Garages ──────────────────────────────────────────────────────────────────

@router.get("/api/garages")
def list_garages():
    """List roadside garages -- territories with recent SA volume."""
    def _fetch():
        from ops import _get_priority_matrix
        d28 = (date.today() - timedelta(days=28)).isoformat()
        data = sf_parallel(
            counts=lambda: sf_query_all(f"""
                SELECT ServiceTerritoryId, ServiceTerritory.Name, COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE CreatedDate >= {d28}T00:00:00Z
                  AND ServiceTerritoryId != null
                  AND Status IN ('Dispatched','Completed','Assigned')
                  AND WorkType.Name != 'Tow Drop-Off'
                GROUP BY ServiceTerritoryId, ServiceTerritory.Name
                ORDER BY COUNT(Id) DESC
            """),
            territories=lambda: sf_query_all(
                "SELECT Id, Name, City, State, Latitude, Longitude, IsActive "
                "FROM ServiceTerritory WHERE IsActive = true"),
        )
        terr_map = {r['Id']: r for r in data['territories']}
        matrix = _get_priority_matrix()
        garages = []
        for r in data['counts']:
            tid = r.get('ServiceTerritoryId')
            t = terr_map.get(tid, {})
            # Count primary (rank 1) vs secondary (rank 2+) zones from priority matrix
            zone_entries = matrix['by_garage'].get(tid, [])
            primary_zones = 0
            secondary_zones = 0
            for entry in zone_entries:
                rank = matrix['rank_lookup'].get((entry['parent_id'], tid))
                if rank == 1:
                    primary_zones += 1
                elif rank and rank >= 2:
                    secondary_zones += 1
            garages.append({
                'id': tid,
                'name': (r.get('ServiceTerritory') or {}).get('Name') or t.get('Name', '?'),
                'sa_count_28d': r.get('cnt', 0),
                'city': t.get('City'),
                'state': t.get('State'),
                'lat': t.get('Latitude'),
                'lon': t.get('Longitude'),
                'active': t.get('IsActive', True),
                'primary_zones': primary_zones,
                'secondary_zones': secondary_zones,
            })
        return garages

    return cache.cached_query('garages_list', _fetch, ttl=600)


# ── Schedule ─────────────────────────────────────────────────────────────────

@router.get("/api/garages/{territory_id}/schedule")
def get_schedule(territory_id: str,
                 weeks: int = Query(4, ge=1, le=12),
                 start_date: str = Query(None),
                 end_date: str = Query(None)):
    territory_id = sanitize_soql(territory_id)
    if start_date:
        start_date = sanitize_soql(start_date)
    if end_date:
        end_date = sanitize_soql(end_date)
    cache_key = f"schedule_{territory_id}_{start_date or 'none'}_{end_date or 'none'}_{weeks}"
    result = cache.cached_query(
        cache_key,
        lambda: generate_schedule(territory_id, weeks, start_date=start_date, end_date=end_date),
        ttl=3600,
    )
    if 'error' in result and not result.get('schedule'):
        raise HTTPException(status_code=404, detail=result['error'])
    return result


# ── Scorecard -- Goal-Based Performance ───────────────────────────────────

@router.get("/api/garages/{territory_id}/scorecard")
def get_scorecard(territory_id: str, weeks: int = Query(4, ge=1, le=12)):
    """Performance scorecard: SLA compliance, fleet capacity, and gap analysis."""
    territory_id = sanitize_soql(territory_id)
    days = weeks * 7
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    since = f"{cutoff}T00:00:00Z"

    def _fetch():
        # Get territory name for fleet/contractor classification
        _t_rows = sf_query_all(f"SELECT Name FROM ServiceTerritory WHERE Id = '{territory_id}' LIMIT 1")
        territory_name = _t_rows[0].get('Name', '') if _t_rows else ''
        _is_fleet = is_fleet_territory(territory_name)

        # Get member IDs for territory membership + garage type detection
        members_raw = sf_query_all(f"""
            SELECT ServiceResourceId, ServiceResource.Name,
                   ServiceResource.ERS_Driver_Type__c, TerritoryType
            FROM ServiceTerritoryMember
            WHERE ServiceTerritoryId = '{territory_id}'
              AND ServiceResource.IsActive = true
              AND ServiceResource.ResourceType = 'T'
        """)
        # Fleet = territory 100*/800*. Contractor = everything else.
        towbook_members = [m for m in members_raw
                           if ((m.get('ServiceResource') or {}).get('Name') or '').lower().startswith('towbook')]
        fleet_members = [m for m in members_raw if m not in towbook_members]
        is_towbook_garage = not _is_fleet and len(towbook_members) > 0 and len(fleet_members) == 0

        if is_towbook_garage:
            members = members_raw
        else:
            # Fleet/On-Platform garage: exclude generic Towbook placeholders
            members = fleet_members
        driver_ids = set(m['ServiceResourceId'] for m in members)

        # 7 parallel queries: volume, response times, Asset trucks, SA trucks, PTA aggregate, DOW, + member STM IDs for fleet
        data = sf_parallel(
            vol=lambda: sf_query_all(f"""
                SELECT WorkType.Name, Status, COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                  AND Status IN ('Dispatched','Completed','Canceled','Assigned')
                  AND WorkType.Name != 'Tow Drop-Off'
                GROUP BY WorkType.Name, Status
            """),
            rt=lambda: sf_query_all(f"""
                SELECT Id, CreatedDate, ActualStartTime, ERS_PTA__c, ERS_Dispatch_Method__c
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                  AND Status = 'Completed'
                  AND ActualStartTime != null
                  AND WorkType.Name != 'Tow Drop-Off'
                ORDER BY CreatedDate DESC
                LIMIT 500
            """),
            asset_trucks=lambda: sf_query_all("""
                SELECT ERS_Driver__c, Name, ERS_Truck_Capabilities__c
                FROM Asset
                WHERE RecordType.Name = 'ERS Truck'
                  AND ERS_Driver__c != null
            """),
            trucks=lambda: sf_query_all(f"""
                SELECT Off_Platform_Truck_Id__c, WorkType.Name, COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                  AND Off_Platform_Truck_Id__c != null
                GROUP BY Off_Platform_Truck_Id__c, WorkType.Name
            """),
            pta_agg=lambda: sf_query_all(f"""
                SELECT COUNT(Id) total,
                       AVG(ERS_PTA__c) avg_pta
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                  AND ERS_PTA__c != null AND ERS_PTA__c > 0 AND ERS_PTA__c < 999
                  AND Status IN ('Dispatched','Completed','Canceled','Assigned')
                  AND WorkType.Name != 'Tow Drop-Off'
            """),
            dow=lambda: sf_query_all(f"""
                SELECT DAY_IN_WEEK(CreatedDate) dow, COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                  AND Status IN ('Dispatched','Completed','Canceled','Assigned')
                  AND WorkType.Name != 'Tow Drop-Off'
                GROUP BY DAY_IN_WEEK(CreatedDate)
            """),
        )
        # Volume breakdown
        type_counts = defaultdict(int)
        total = 0
        completed_count = 0
        for r in data['vol']:
            wt = r.get('Name') or 'Unknown'  # Aggregate flattens WorkType.Name -> Name
            status = r.get('Status')
            cnt = r.get('cnt', 0)
            type_counts[wt] += cnt
            total += cnt
            if status == 'Completed':
                completed_count += cnt

        if total == 0:
            raise HTTPException(status_code=404, detail="No SAs found")

        tow_sa_count = sum(v for k, v in type_counts.items() if 'tow' in k.lower())
        batt_sa_count = sum(v for k, v in type_counts.items() if k.lower() in ('battery', 'jumpstart'))
        light_sa_count = sum(v for k, v in type_counts.items()
                             if k.lower() in ('tire', 'lockout', 'locksmith', 'winch out', 'fuel / miscellaneous', 'pvs'))

        # Fleet classification from Asset truck capabilities (on-shift drivers only)
        asset_caps = {}
        on_shift_ids = set()
        for asset in data['asset_trucks']:
            dr_id = asset.get('ERS_Driver__c')
            if dr_id:
                on_shift_ids.add(dr_id)
                asset_caps[dr_id] = asset.get('ERS_Truck_Capabilities__c', '')

        # Only count drivers in this territory who are on shift
        territory_on_shift = driver_ids & on_shift_ids
        tow_drivers = set()
        battery_drivers = set()
        light_drivers = set()
        for did in territory_on_shift:
            caps = asset_caps.get(did, '')
            tier = _driver_tier(caps) if caps else 'light'
            if tier == 'tow':
                tow_drivers.add(did)
            elif tier == 'battery':
                battery_drivers.add(did)
            else:
                light_drivers.add(did)
        battery_light_drivers = battery_drivers | light_drivers
        classified = tow_drivers | battery_light_drivers
        unclassified = territory_on_shift - classified

        # Trucks
        tow_wt_names = set(k for k in type_counts if 'tow' in k.lower())
        tow_trucks = set()
        other_trucks = set()
        for tr in data['trucks']:
            tid_truck = tr.get('Off_Platform_Truck_Id__c', '')
            wt_n = tr.get('Name', '')  # Aggregate flattens WorkType.Name -> Name
            if wt_n.lower() in [n.lower() for n in tow_wt_names]:
                tow_trucks.add(tid_truck)
            else:
                other_trucks.add(tid_truck)
        pure_other_trucks = other_trucks - tow_trucks

        # Response times + PTA from individual completed SAs
        pta_values = []
        pta_under_45 = 0
        pta_under_90 = 0
        pta_sentinel_count = 0  # PTA = 999 (no ETA given)
        response_times = []

        # Fetch real arrival times for Towbook SAs (On Location from history)
        towbook_rt_ids = [
            s['Id'] for s in data['rt']
            if (s.get('ERS_Dispatch_Method__c') or '') == 'Towbook' and s.get('Id')
        ]
        towbook_on_loc = get_towbook_on_location(towbook_rt_ids)

        for s in data['rt']:
            created = _parse_dt(s.get('CreatedDate'))
            started = _parse_dt(s.get('ActualStartTime'))
            pta = s.get('ERS_PTA__c')
            dispatch_method = s.get('ERS_Dispatch_Method__c') or ''

            if pta is not None:
                pv = float(pta)
                if pv >= 999:
                    pta_sentinel_count += 1  # count "No ETA" separately
                elif pv <= 0:
                    pass  # skip invalid PTA values
                else:
                    pta_values.append(pv)
                    if pv <= 45:
                        pta_under_45 += 1
                    if pv <= 90:
                        pta_under_90 += 1

            # Towbook: use real On Location timestamp from SA history
            # Fleet: use ActualStartTime directly
            if dispatch_method == 'Towbook':
                on_loc_str = towbook_on_loc.get(s.get('Id'))
                on_loc = _parse_dt(on_loc_str) if on_loc_str else None
                if created and on_loc:
                    diff = (on_loc - created).total_seconds() / 60
                    if 0 < diff < 480:
                        response_times.append(diff)
            else:
                if created and started:
                    diff = (started - created).total_seconds() / 60
                    if 0 < diff < 480:
                        response_times.append(diff)

        # PTA aggregate for total PTA stats (all SAs, not just completed)
        pta_agg = data['pta_agg'][0] if data['pta_agg'] else {}
        total_with_pta = pta_agg.get('total', len(pta_values))
        avg_pta = pta_agg.get('avg_pta')
        median_pta = round(avg_pta) if avg_pta else None  # Use avg as proxy

        median_response = round(sorted(response_times)[len(response_times)//2]) if response_times else None
        avg_response = round(sum(response_times)/len(response_times)) if response_times else None
        resp_under_45 = sum(1 for r in response_times if r <= 45)

        # PTA buckets from completed SAs
        pta_buckets = []
        total_pta_all = len(pta_values) + pta_sentinel_count
        ranges = [('Under 45 min', 0, 45), ('45-90 min', 45, 90), ('90-120 min', 90, 120),
                  ('2-3 hours', 120, 180), ('3+ hours', 180, 999)]
        for label, lo, hi in ranges:
            ct = sum(1 for v in pta_values if lo < v <= hi) if lo > 0 else sum(1 for v in pta_values if v <= hi)
            if lo == 180:
                ct = sum(1 for v in pta_values if 180 < v < 999)
            pta_buckets.append({'label': label, 'count': ct,
                                'pct': round(100*ct/max(total_pta_all, 1), 1)})
        if pta_sentinel_count > 0:
            pta_buckets.append({'label': 'No ETA (999)', 'count': pta_sentinel_count,
                                'pct': round(100*pta_sentinel_count/max(total_pta_all, 1), 1)})

        no_pta = total - int(total_with_pta or 0)
        if no_pta > 0:
            pta_buckets.append({'label': 'No PTA set', 'count': no_pta,
                                'pct': round(100*no_pta/max(total,1), 1)})

        # DOW volume from parallel aggregate
        dow_data = data['dow']
        # SOQL DOW: 1=Sun..7=Sat -> Python strftime %a
        _DOW_MAP = {1: 'Sun', 2: 'Mon', 3: 'Tue', 4: 'Wed', 5: 'Thu', 6: 'Fri', 7: 'Sat'}
        dow_volume = {_DOW_MAP.get(int(r.get('dow', 0)), '?'): r.get('cnt', 0) for r in dow_data}
        n_weeks = max(weeks, 1)
        dow_avg = {d: round(v / n_weeks) for d, v in dow_volume.items()}

        # Build fleet section based on garage type
        if is_towbook_garage:
            fleet_section = {
                'garage_type': 'towbook',
                'total_contractors': len(tow_trucks | pure_other_trucks),
                'tow_trucks': len(tow_trucks),
                'other_trucks': len(pure_other_trucks),
                'total_trucks': len(tow_trucks | pure_other_trucks),
                # Keep legacy fields at 0 for backwards compat
                'total_members': 0,
                'tow_drivers': 0,
                'battery_light_drivers': 0,
                'unclassified': 0,
            }
        else:
            fleet_section = {
                'garage_type': 'fleet',
                'total_members': len(territory_on_shift),  # on-shift drivers (from Asset login)
                'roster_total': len(driver_ids),  # full STM roster for reference
                'tow_drivers': len(tow_drivers),
                'battery_light_drivers': len(battery_light_drivers),
                'unclassified': len(unclassified),
                'tow_trucks': len(tow_trucks),
                'other_trucks': len(pure_other_trucks),
                'total_trucks': len(tow_trucks | pure_other_trucks),
            }

        return {
            'garage_type': 'fleet' if _is_fleet else ('towbook' if is_towbook_garage else 'contractor'),
            'sla': {
                'target_minutes': 45,
                'pta_compliance_45min': round(100*pta_under_45/max(len(pta_values),1), 1),
                'pta_compliance_90min': round(100*pta_under_90/max(len(pta_values),1), 1),
                'median_pta_promised': median_pta,
                'actual_median_response': median_response,
                'actual_avg_response': avg_response,
                'actual_under_45min': resp_under_45,
                'actual_under_45min_pct': round(100*resp_under_45/max(len(response_times), 1), 1),
                'response_sample_size': len(response_times),
                'response_metric': 'ATA (actual)',
                'gap_vs_target': (median_response - 45) if median_response else None,
                'pta_buckets': pta_buckets,
            },
            'fleet': fleet_section,
            'volume': {
                'total': total,
                'completed': completed_count,
                'daily_average': round(total / max(days, 1), 1),
                'weekly_average': round(total / n_weeks),
                'tow_sas': tow_sa_count,
                'battery_sas': batt_sa_count,
                'light_sas': light_sa_count,
                'by_type': dict(type_counts),
                'by_dow': dow_avg,
            },
            'goals': [
                {
                    'name': '45-Min Response SLA',
                    'target': '45 min',
                    'actual': f'{median_response} min' if median_response else 'N/A',
                    'met': (median_response or 999) <= 45,
                    'gap': f'+{round(median_response - 45)} min' if median_response and median_response > 45 else 'On target',
                },
                {
                    'name': 'PTA Promise <= 45 min',
                    'target': '100%',
                    'actual': f'{round(100*pta_under_45/max(len(pta_values),1), 1)}%',
                    'met': pta_under_45 == len(pta_values),
                    'gap': f'Only {round(100*pta_under_45/max(len(pta_values),1), 1)}% promised <=45 min',
                },
                {
                    'name': 'Completion Rate',
                    'target': '95%',
                    'actual': f'{round(100*completed_count/max(total,1), 1)}%',
                    'met': completed_count/max(total,1) >= 0.95,
                    'gap': f'{round(100*completed_count/max(total,1), 1)}%',
                },
            ],
        }

    return cache.cached_query(f'scorecard_{territory_id}_{weeks}', _fetch, ttl=3600)


# ── Appointments (Day View) ─────────────────────────────────────────────────

@router.get("/api/garages/{territory_id}/appointments")
def get_appointments(territory_id: str, date_str: str = Query(..., alias='date')):
    """Get all SAs for a territory on a specific date."""
    territory_id = sanitize_soql(territory_id)
    date_str = sanitize_soql(date_str)
    def _fetch():
        next_day = (date.fromisoformat(date_str) + timedelta(days=1)).isoformat()
        sas = sf_query_all(f"""
            SELECT Id, AppointmentNumber, Status, CreatedDate,
                   SchedStartTime, ActualStartTime, ActualEndTime,
                   Street, City, State, PostalCode, Latitude, Longitude,
                   WorkType.Name,
                   (SELECT ServiceResource.Name FROM ServiceResources)
            FROM ServiceAppointment
            WHERE ServiceTerritoryId = '{territory_id}'
              AND CreatedDate >= {date_str}T00:00:00Z
              AND CreatedDate < {next_day}T00:00:00Z
              AND Status IN ('Dispatched','Completed','Canceled','Assigned')
            ORDER BY CreatedDate ASC
        """)

        appointments = []
        for sa in sas:
            ars = sa.get('ServiceResources')
            driver_name = 'Unassigned'
            if ars and ars.get('records'):
                sr = ars['records'][0].get('ServiceResource') or {}
                driver_name = sr.get('Name', 'Unassigned')
            if driver_name.lower().startswith('towbook'):
                driver_name = f"Towbook ({driver_name})"

            et = _to_eastern(sa.get('CreatedDate'))
            appointments.append({
                'id': sa['Id'],
                'number': sa.get('AppointmentNumber', '?'),
                'status': sa.get('Status'),
                'work_type': (sa.get('WorkType') or {}).get('Name', '?'),
                'created_time': et.strftime('%I:%M %p') if et else '?',
                'address': f"{sa.get('Street') or ''} {sa.get('City') or ''}".strip(),
                'lat': sa.get('Latitude'),
                'lon': sa.get('Longitude'),
                'driver': driver_name,
            })
        return appointments
    return cache.cached_query(f'appointments_{territory_id}_{date_str}', _fetch, ttl=120)


# ── Simulation ───────────────────────────────────────────────────────────────

@router.get("/api/garages/{territory_id}/simulate")
def run_simulation(territory_id: str, date_str: str = Query(..., alias='date')):
    territory_id = sanitize_soql(territory_id)
    date_str = sanitize_soql(date_str)
    def _fetch():
        results = simulate_day(territory_id, date_str)
        if not results:
            return None

        total = len(results)
        known = [r for r in results if r.get('closest_picked') is not None]
        unknown = [r for r in results if r.get('closest_picked') is None]
        closest_picked = sum(1 for r in known if r.get('closest_picked'))
        total_extra = sum(r.get('extra_miles', 0) or 0 for r in known if not r.get('closest_picked'))
        has_closest = [r for r in results if r.get('closest_distance') is not None]

        return {
            'results': results,
            'summary': {
                'total_sas': total,
                'closest_picked': closest_picked,
                'closest_pct': round(100 * closest_picked / max(len(known), 1), 1) if known else None,
                'known_assignments': len(known),
                'unknown_assignments': len(unknown),
                'wrong_decisions': len(known) - closest_picked if known else None,
                'total_extra_miles': round(total_extra, 1) if known else None,
                'avg_extra_miles': round(total_extra / max(len(known) - closest_picked, 1), 1) if known else None,
                'avg_closest_distance': round(sum(r['closest_distance'] for r in has_closest) / max(len(has_closest), 1), 1) if has_closest else None,
                'dispatched_via': 'Towbook' if len(unknown) > len(known) else 'Salesforce FSL',
            },
        }

    result = cache.cached_query(f'simulate_{territory_id}_{date_str}', _fetch, ttl=120)
    if result is None:
        raise HTTPException(status_code=404, detail="No simulatable SAs found")
    return result


# ── Performance Score ────────────────────────────────────────────────────────

@router.get("/api/garages/{territory_id}/score")
def get_score(territory_id: str, weeks: int = Query(4, ge=1, le=12)):
    territory_id = sanitize_soql(territory_id)
    result = compute_score(territory_id, weeks)
    if result.get('error'):
        raise HTTPException(status_code=404, detail=result['error'])
    return result


# ── Performance Dashboard ─────────────────────────────────────────────────────

@router.get("/api/garages/{territory_id}/performance")
def get_performance(
    territory_id: str,
    period_start: str = Query(...),
    period_end: str = Query(...),
):
    territory_id = sanitize_soql(territory_id)
    period_start = sanitize_soql(period_start)
    period_end = sanitize_soql(period_end)
    cache_key = f"perf_{territory_id}_{period_start}_{period_end}"
    return cache.cached_query_persistent(cache_key, lambda: _compute_performance(territory_id, period_start, period_end), ttl=3600)


def _compute_performance(territory_id: str, period_start: str, period_end: str) -> dict:
    """All from Salesforce -- parallel queries."""
    is_single_day = period_start == period_end
    next_day = (date.fromisoformat(period_end) + timedelta(days=1)).isoformat()
    since = f"{period_start}T00:00:00Z"
    until = f"{next_day}T00:00:00Z"

    # Parallel: individual SAs + WO IDs for surveys + trend aggregate
    data = sf_parallel(
        sas=lambda: sf_query_all(f"""
            SELECT Id, Status, CreatedDate, ActualStartTime, ActualEndTime,
                   SchedStartTime, ERS_Auto_Assign__c, ERS_PTA__c,
                   ERS_Facility_Decline_Reason__c, ERS_Cancellation_Reason__c,
                   ERS_Dispatch_Method__c, ERS_Spotting_Number__c, WorkType.Name
            FROM ServiceAppointment
            WHERE ServiceTerritoryId = '{territory_id}'
              AND CreatedDate >= {since}
              AND CreatedDate < {until}
              AND Status IN ('Dispatched','Completed','Canceled','Assigned',
                             'Cancel Call - Service Not En Route',
                             'Cancel Call - Service En Route',
                             'Unable to Complete','No-Show')
            ORDER BY CreatedDate ASC
        """),
        trend=lambda: sf_query_all(f"""
            SELECT DAY_IN_MONTH(CreatedDate) d,
                   HOUR_IN_DAY(CreatedDate) hr,
                   Status, COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE ServiceTerritoryId = '{territory_id}'
              AND CreatedDate >= {since}
              AND CreatedDate < {until}
            GROUP BY DAY_IN_MONTH(CreatedDate), HOUR_IN_DAY(CreatedDate), Status
        """) if is_single_day else sf_query_all(f"""
            SELECT DAY_IN_MONTH(CreatedDate) d,
                   CALENDAR_MONTH(CreatedDate) m,
                   Status, COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE ServiceTerritoryId = '{territory_id}'
              AND CreatedDate >= {since}
              AND CreatedDate < {until}
            GROUP BY DAY_IN_MONTH(CreatedDate), CALENDAR_MONTH(CreatedDate), Status
        """),
        # SA history: territory assignment sequence (which garage was assigned 1st, 2nd, etc.)
        # Note: NewValue can't be filtered on History objects -- filter in Python
        sa_history=lambda: sf_query_all(f"""
            SELECT ServiceAppointmentId, OldValue, NewValue, CreatedDate
            FROM ServiceAppointmentHistory
            WHERE Field = 'ServiceTerritory'
              AND ServiceAppointment.ServiceTerritoryId = '{territory_id}'
              AND ServiceAppointment.CreatedDate >= {since}
              AND ServiceAppointment.CreatedDate < {until}
            ORDER BY ServiceAppointmentId, CreatedDate ASC
        """),
    )

    all_sas = data['sas']
    if not all_sas:
        raise HTTPException(status_code=404, detail="No SAs found for this period")

    # Exclude Tow Drop-Off from all counts (paired SAs, not real calls)
    sas = [s for s in all_sas
           if 'drop' not in ((s.get('WorkType') or {}).get('Name', '') or '').lower()]
    total = len(sas)
    completed = [s for s in sas if s.get('Status') == 'Completed']

    # Fetch real arrival times for Towbook SAs (On Location from SA history)
    towbook_completed_ids = [
        s['Id'] for s in completed
        if (s.get('ERS_Dispatch_Method__c') or '') == 'Towbook' and s.get('Id')
    ]
    towbook_on_location = get_towbook_on_location(towbook_completed_ids)

    # Dispatch method breakdown
    fs_count = sum(1 for s in sas if (s.get('ERS_Dispatch_Method__c') or '') == 'Field Services')
    tb_count = sum(1 for s in sas if (s.get('ERS_Dispatch_Method__c') or '') == 'Towbook')
    dispatch_mix = {
        'field_services': fs_count,
        'towbook': tb_count,
        'other': total - fs_count - tb_count,
        'primary_method': 'Field Services' if fs_count >= tb_count else 'Towbook',
        'fs_pct': round(100 * fs_count / max(total, 1), 1),
        'tb_pct': round(100 * tb_count / max(total, 1), 1),
    }

    # Acceptance
    primary = [s for s in sas if s.get('ERS_Auto_Assign__c') is True]
    not_primary = [s for s in sas if s.get('ERS_Auto_Assign__c') is not True]

    def _accepted(lst):
        return [s for s in lst if not s.get('ERS_Facility_Decline_Reason__c')]

    primary_accepted = _accepted(primary)
    not_primary_accepted = _accepted(not_primary)

    acceptance = {
        'primary_total': len(primary),
        'primary_accepted': len(primary_accepted),
        'primary_pct': round(100 * len(primary_accepted) / max(len(primary), 1), 1),
        'not_primary_total': len(not_primary),
        'not_primary_accepted': len(not_primary_accepted),
        'not_primary_pct': round(100 * len(not_primary_accepted) / max(len(not_primary), 1), 1),
        'total_declined': sum(1 for s in sas if s.get('ERS_Facility_Decline_Reason__c')),
        'note': 'auto-assigned = primary dispatch; manual = secondary/backup',
    }

    # Completion
    completion = {
        'total': total,
        'completed': len(completed),
        'pct': round(100 * len(completed) / max(total, 1), 1),
    }

    # 1st Call vs 2nd+ Call -- from SA history (territory assignment sequence)
    sa_history = data.get('sa_history', [])

    # Build assignment order per SA: list of territory IDs in chronological order
    sa_territory_order = defaultdict(list)  # sa_id -> [territory_id_1, territory_id_2, ...]
    for h in sa_history:
        sa_id = h.get('ServiceAppointmentId')
        new_val = h.get('NewValue', '') or ''
        if sa_id and new_val.startswith('0Hh'):
            # Only add if different from last (avoid duplicates from same assignment)
            order = sa_territory_order[sa_id]
            if not order or order[-1] != new_val:
                order.append(new_val)

    first_call_sas = []
    second_call_sas = []
    for s in sas:
        sa_id = s['Id']
        order = sa_territory_order.get(sa_id, [])
        if not order:
            # No history found -- treat as 1st call (initial assignment, no reassignment)
            first_call_sas.append(s)
        elif order[0] == territory_id:
            first_call_sas.append(s)
        else:
            second_call_sas.append(s)

    first_call_accepted = [s for s in first_call_sas if not s.get('ERS_Facility_Decline_Reason__c')]
    second_call_accepted = [s for s in second_call_sas if not s.get('ERS_Facility_Decline_Reason__c')]

    # Completion of accepted -- of SAs they didn't decline, how many completed?
    accepted_sas = [s for s in sas if not s.get('ERS_Facility_Decline_Reason__c')]
    accepted_completed = [s for s in accepted_sas if s.get('Status') == 'Completed']

    first_call = {
        'first_call_total': len(first_call_sas),
        'first_call_accepted': len(first_call_accepted),
        'first_call_pct': round(100 * len(first_call_accepted) / max(len(first_call_sas), 1), 1) if first_call_sas else None,
        'second_call_total': len(second_call_sas),
        'second_call_accepted': len(second_call_accepted),
        'second_call_pct': round(100 * len(second_call_accepted) / max(len(second_call_sas), 1), 1) if second_call_sas else None,
        'first_call_source': 'sa_history',
        'accepted_total': len(accepted_sas),
        'accepted_completed': len(accepted_completed),
        'accepted_completion_pct': round(100 * len(accepted_completed) / max(len(accepted_sas), 1), 1) if accepted_sas else None,
    }

    # Response times (exclude Tow Drop-Off)
    # Towbook: use real On Location timestamp from SA history
    # Fleet: use ActualStartTime directly
    response_times = []
    for s in completed:
        wt_name = (s.get('WorkType') or {}).get('Name', '') or ''
        if 'drop' in wt_name.lower():
            continue
        dispatch_method = (s.get('ERS_Dispatch_Method__c') or '')
        created = _parse_dt(s.get('CreatedDate'))
        if dispatch_method == 'Towbook':
            on_loc_str = towbook_on_location.get(s.get('Id'))
            on_loc = _parse_dt(on_loc_str) if on_loc_str else None
            if created and on_loc:
                diff = (on_loc - created).total_seconds() / 60
                if 0 < diff < 480:
                    response_times.append(diff)
        else:
            started = _parse_dt(s.get('ActualStartTime'))
            if created and started:
                diff = (started - created).total_seconds() / 60
                if 0 < diff < 480:
                    response_times.append(diff)

    def _bucket(lo, hi):
        return sum(1 for t in response_times if lo <= t < hi)

    rt_n = max(len(response_times), 1)
    rt = {
        'total': len(response_times),
        'under_45': _bucket(0, 45),
        'b45_90': _bucket(45, 90),
        'b90_120': _bucket(90, 120),
        'over_120': _bucket(120, 9999),
        'median': round(sorted(response_times)[len(response_times) // 2]) if response_times else None,
        'avg': round(sum(response_times) / len(response_times)) if response_times else None,
    }
    for k in ('under_45', 'b45_90', 'b90_120', 'over_120'):
        rt[f'{k}_pct'] = round(100 * rt[k] / rt_n, 1)

    # PTA-ATA accuracy (PTA promised vs actual arrival)
    # Towbook: use real On Location from SA history; Fleet: use ActualStartTime
    pts_deltas = []
    for s in completed:
        dispatch_method = (s.get('ERS_Dispatch_Method__c') or '')
        pta = s.get('ERS_PTA__c')
        created = _parse_dt(s.get('CreatedDate'))
        if dispatch_method == 'Towbook':
            on_loc_str = towbook_on_location.get(s.get('Id'))
            actual_arrival = _parse_dt(on_loc_str) if on_loc_str else None
        else:
            actual_arrival = _parse_dt(s.get('ActualStartTime'))
        if pta is not None and created and actual_arrival:
            pv = float(pta)
            if pv >= 999 or pv <= 0:
                continue
            expected = created + timedelta(minutes=pv)
            delta = (actual_arrival - expected).total_seconds() / 60
            pts_deltas.append(delta)

    pts_ata = None
    if pts_deltas:
        n = len(pts_deltas)
        on_time = sum(1 for d in pts_deltas if d <= 0)
        pts_ata = {
            'total': n,
            'on_time': on_time,
            'on_time_pct': round(100 * on_time / n, 1),
            'late': n - on_time,
            'late_pct': round(100 * (n - on_time) / n, 1),
            'avg_delta': round(sum(pts_deltas) / n, 1),
            'median_delta': round(sorted(pts_deltas)[n // 2], 1),
            'buckets': [
                {'label': 'Early / On time', 'count': sum(1 for d in pts_deltas if d <= 0)},
                {'label': '1-10 min late', 'count': sum(1 for d in pts_deltas if 0 < d <= 10)},
                {'label': '10-20 min late', 'count': sum(1 for d in pts_deltas if 10 < d <= 20)},
                {'label': '20-30 min late', 'count': sum(1 for d in pts_deltas if 20 < d <= 30)},
                {'label': '30+ min late', 'count': sum(1 for d in pts_deltas if d > 30)},
            ],
        }
        for b in pts_ata['buckets']:
            b['pct'] = round(100 * b['count'] / n, 1)

    # Trend from aggregate data
    bucket_totals = defaultdict(int)
    bucket_completed = defaultdict(int)
    for r in data['trend']:
        d = int(r.get('d', 0))
        status = r.get('Status')
        cnt = r.get('cnt', 0)
        if is_single_day:
            hr = int(r.get('hr', 0))
            # Shift UTC hour to Eastern (DST-aware)
            utc_dt = datetime(int(period_start[:4]), int(period_start[5:7]), int(period_start[8:10]),
                              hr, tzinfo=timezone.utc)
            eastern_dt = utc_dt.astimezone(_ET)
            eastern_hr = eastern_dt.hour
            key = f"{eastern_hr:02d}:00"
        else:
            m = int(r.get('m', 1))
            year = int(period_start[:4])
            key = f"{year}-{m:02d}-{d:02d}"
        bucket_totals[key] += cnt
        if status == 'Completed':
            bucket_completed[key] += cnt

    trend = sorted([{
        'label': k,
        'date': k,
        'total': bucket_totals[k],
        'completed': bucket_completed.get(k, 0),
    } for k in bucket_totals], key=lambda x: x['date'])

    return {
        'total': total,
        'total_sas': total,
        'completed': len(completed),
        'acceptance': acceptance,
        'completion': completion,
        'first_call': first_call,
        'response_time': rt,
        'pts_ata': pts_ata,
        'dispatch_mix': dispatch_mix,
        'trend': trend,
        'period': {
            'start': period_start,
            'end': period_end,
            'single_day': is_single_day,
        },
        'definitions': {
            'first_call_acceptance': '1st Call: SELECT ServiceAppointmentHistory.NewValue FROM ServiceAppointmentHistory WHERE Field = \'ServiceTerritory\' ORDER BY CreatedDate ASC -- first NewValue (ID starting with 0Hh) with OldValue=null = original garage. If original = this garage -> 1st Call (Primary). Otherwise -> 2nd+ Call (Secondary, received after cascade). Accepted = ERS_Facility_Decline_Reason__c IS NULL.',
            'completion_of_accepted': 'Filter: ServiceAppointment.ERS_Facility_Decline_Reason__c IS NULL (accepted only). Then: COUNT(ServiceAppointment.Status = \'Completed\') / COUNT(accepted) x 100. Isolates ops effectiveness from acceptance behavior.',
        },
    }


# ── Decomposition ────────────────────────────────────────────────────────────

@router.get("/api/garages/{territory_id}/decomposition")
def api_response_decomposition(
    territory_id: str,
    period_start: str = Query(...),
    period_end: str = Query(...),
):
    """Response time decomposition + decline analysis + driver leaderboard."""
    territory_id = sanitize_soql(territory_id)
    period_start = sanitize_soql(period_start)
    period_end = sanitize_soql(period_end)
    return get_response_decomposition(territory_id, period_start, period_end)
