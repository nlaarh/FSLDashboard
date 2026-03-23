"""Command Center endpoint -- live territory overview."""

from fastapi import APIRouter, Query
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from sf_client import sf_query_all, sf_parallel, get_towbook_on_location
from dispatch_utils import parse_assign_events
from utils import (
    _ET, parse_dt as _parse_dt, to_eastern as _to_eastern,
    is_fleet_territory,
)
from dispatch import _driver_tier
import cache

router = APIRouter()


# ── Command Center -- Live Territory Overview ─────────────────────────────────

@router.get("/api/command-center")
def command_center(hours: int = Query(24, ge=1, le=168)):
    """Live operational dashboard across all territories."""
    now_utc = datetime.now(timezone.utc)
    cutoff_utc = (now_utc - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%SZ')

    def _fetch():
        from datetime import timezone as _tz

        # Parallel: SAs + active drivers with GPS per territory
        def _get_cc_sas():
            return sf_query_all(f"""
                SELECT Id, AppointmentNumber, Status, CreatedDate,
                       ActualStartTime, SchedStartTime,
                       ERS_Dispatch_Method__c, ERS_PTA__c,
                       ERS_Parent_Territory__c, ERS_Parent_Territory__r.Name,
                       Latitude, Longitude, PostalCode, Street, City,
                       ServiceTerritoryId, ServiceTerritory.Name,
                       ServiceTerritory.Latitude, ServiceTerritory.Longitude,
                       WorkType.Name
                FROM ServiceAppointment
                WHERE CreatedDate >= {cutoff_utc}
                  AND ServiceTerritoryId != null
                  AND RecordType.Name = 'ERS Service Appointment'
                  AND Status IN ('Dispatched','Completed','Canceled',
                                 'Cancel Call - Service Not En Route',
                                 'Cancel Call - Service En Route',
                                 'Unable to Complete','Assigned','No-Show')
                ORDER BY CreatedDate ASC
            """)

        def _get_cc_trucks():
            """On-shift drivers from Asset (vehicle login = on shift). Only real drivers."""
            return sf_query_all("""
                SELECT ERS_Driver__c, Name, ERS_Truck_Capabilities__c
                FROM Asset
                WHERE RecordType.Name = 'ERS Truck'
                  AND ERS_Driver__c != null
                  AND ERS_Driver__r.IsActive = true
            """)

        def _get_cc_drivers():
            """STM for territory->driver mapping + GPS positions."""
            return sf_query_all("""
                SELECT ServiceTerritoryId, ServiceResourceId,
                       ServiceResource.LastKnownLatitude,
                       ServiceResource.LastKnownLocationDate,
                       ServiceResource.ERS_Driver_Type__c
                FROM ServiceTerritoryMember
                WHERE TerritoryType IN ('P','S')
                  AND ServiceResource.IsActive = true
                  AND ServiceResource.ResourceType = 'T'
            """)

        # All GPS-capable drivers: Fleet + On-Platform Contractors (both use FSL app)
        def _get_all_fleet():
            return sf_query_all("""
                SELECT Id, Name, LastKnownLatitude, LastKnownLocationDate,
                       ERS_Driver_Type__c
                FROM ServiceResource
                WHERE IsActive = true AND ResourceType = 'T'
                  AND ERS_Driver_Type__c IN ('Fleet Driver', 'On-Platform Contractor Driver')
                  AND (NOT Name LIKE 'Test %')
                  AND (NOT Name LIKE '000-%')
                  AND (NOT Name LIKE '0 %')
                  AND (NOT Name LIKE '100A %')
                  AND (NOT Name LIKE '%SPOT%')
                  AND Name != 'Travel User'
            """)

        # Today's SAs across ALL statuses for status breakdown + driver ATA leaderboard
        # Use midnight ET (not UTC) so "today" matches the business day
        today_et = now_utc.astimezone(_ET).replace(hour=0, minute=0, second=0, microsecond=0)
        today_start = today_et.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        def _get_today_sas():
            return sf_query_all(f"""
                SELECT Id, Status, ERS_Dispatch_Method__c,
                       CreatedDate, ActualStartTime,
                       ERS_Cancellation_Reason__c, ERS_Facility_Decline_Reason__c,
                       WorkType.Name
                FROM ServiceAppointment
                WHERE CreatedDate >= {today_start}
                  AND ServiceTerritoryId != null
                  AND RecordType.Name = 'ERS Service Appointment'
            """)

        # Fleet completed SAs today with driver info for leaderboard
        def _get_fleet_leaderboard():
            return sf_query_all(f"""
                SELECT Id, CreatedDate, ActualStartTime,
                       ERS_Dispatch_Method__c,
                       ServiceTerritory.Name
                FROM ServiceAppointment
                WHERE CreatedDate >= {today_start}
                  AND Status = 'Completed'
                  AND ActualStartTime != null
                  AND ServiceTerritoryId != null
                  AND WorkType.Name != 'Tow Drop-Off'
                  AND ERS_Dispatch_Method__c = 'Field Services'
            """)

        def _get_fleet_drivers_today():
            return sf_query_all(f"""
                SELECT ServiceAppointmentId, ServiceResource.Name
                FROM AssignedResource
                WHERE ServiceAppointment.CreatedDate >= {today_start}
                  AND ServiceAppointment.Status = 'Completed'
                  AND ServiceAppointment.ERS_Dispatch_Method__c = 'Field Services'
            """)

        # Reassignment history: driver assignment changes for today's SAs
        def _get_reassign_history():
            """Driver changes = real bounces (SA reassigned to different driver)."""
            return sf_query_all(f"""
                SELECT ServiceAppointmentId,
                       ServiceAppointment.AppointmentNumber,
                       ServiceAppointment.ServiceTerritory.Name,
                       ServiceAppointment.ServiceTerritoryId,
                       ServiceAppointment.WorkType.Name,
                       ServiceAppointment.Status,
                       ServiceAppointment.ERS_Dispatch_Method__c,
                       CreatedDate, OldValue, NewValue
                FROM ServiceAppointmentHistory
                WHERE ServiceAppointment.CreatedDate >= {today_start}
                  AND Field = 'ERS_Assigned_Resource__c'
                  AND ServiceAppointment.RecordType.Name = 'ERS Service Appointment'
                  AND ServiceAppointment.WorkType.Name != 'Tow Drop-Off'
                ORDER BY ServiceAppointmentId, CreatedDate ASC
            """)

        # Currently busy fleet drivers (on active SAs)
        def _get_busy_drivers():
            return sf_query_all("""
                SELECT ServiceResourceId
                FROM AssignedResource
                WHERE ServiceAppointment.Status IN ('Dispatched','Assigned','In Progress',
                                                     'En Route','On Location')
                  AND ServiceAppointment.ServiceTerritoryId != null
                  AND ServiceAppointment.RecordType.Name = 'ERS Service Appointment'
            """)

        cc_data = sf_parallel(sas=_get_cc_sas, trucks=_get_cc_trucks,
                              drivers=_get_cc_drivers,
                              all_fleet=_get_all_fleet, today_sas=_get_today_sas,
                              fleet_lb=_get_fleet_leaderboard, fleet_ar=_get_fleet_drivers_today,
                              reassign=_get_reassign_history,
                              busy=_get_busy_drivers)
        sas = cc_data['sas']
        cc_trucks = cc_data['trucks']
        driver_members = cc_data['drivers']
        all_fleet_drivers = cc_data['all_fleet']
        today_sas_all = cc_data['today_sas']
        fleet_lb_sas = cc_data['fleet_lb']
        fleet_ar = cc_data['fleet_ar']
        reassign_history = cc_data['reassign']
        busy_ar = cc_data['busy']

        # Build on-shift driver set + tier from Asset (vehicle login = on shift)
        logged_in_ids = set()
        driver_tier_map = {}  # driver_id -> 'tow'|'battery'|'light'
        for asset in cc_trucks:
            dr_id = asset.get('ERS_Driver__c')
            if dr_id:
                logged_in_ids.add(dr_id)
                caps = asset.get('ERS_Truck_Capabilities__c') or ''
                driver_tier_map[dr_id] = _driver_tier(caps)

        # Busy drivers (currently on active SAs) — NOT available for new calls
        busy_driver_ids_set = {ar.get('ServiceResourceId') for ar in busy_ar if ar.get('ServiceResourceId')}

        # Build driver availability per territory (on-shift, NOT busy, by tier)
        now = datetime.now(_tz.utc)
        drivers_by_territory = defaultdict(int)
        drivers_by_territory_tier = defaultdict(lambda: defaultdict(int))  # tid -> tier -> count
        seen_drivers = set()
        for dm in driver_members:
            tid = dm.get('ServiceTerritoryId')
            dr_id = dm.get('ServiceResourceId')
            if not tid or not dr_id:
                continue
            if dr_id not in logged_in_ids:
                continue  # Not logged into a vehicle = not on shift
            if dr_id in busy_driver_ids_set:
                continue  # Currently servicing another SA
            sr = dm.get('ServiceResource') or dm
            name = sr.get('Name', '')
            if name.lower().startswith('towbook'):
                continue
            key = (tid, dr_id)
            if key not in seen_drivers:
                seen_drivers.add(key)
                drivers_by_territory[tid] += 1
                tier = driver_tier_map.get(dr_id, 'light')
                drivers_by_territory_tier[tid][tier] += 1

        # Group by territory
        by_territory = defaultdict(list)
        for sa in sas:
            tid = sa.get('ServiceTerritoryId')
            if tid:
                by_territory[tid].append(sa)

        territories = []
        for tid, sa_list_raw in by_territory.items():
            st = (sa_list_raw[0].get('ServiceTerritory') or {})
            t_lat = st.get('Latitude')
            t_lon = st.get('Longitude')
            t_name = st.get('Name') or '?'
            if not t_lat or not t_lon:
                continue

            # Exclude Tow Drop-Off from counts (paired SAs, not real calls)
            sa_list = [s for s in sa_list_raw
                       if 'drop' not in ((s.get('WorkType') or {}).get('Name', '') or '').lower()]
            total_t = len(sa_list)
            open_list = [s for s in sa_list if s.get('Status') in ('Dispatched', 'Assigned')]
            completed_list = [s for s in sa_list if s.get('Status') == 'Completed']
            canceled_list = [s for s in sa_list
                             if s.get('Status') in ('Canceled', 'Cancel Call - Service Not En Route',
                                                    'Cancel Call - Service En Route',
                                                    'Unable to Complete', 'No-Show')]

            response_times = []
            # Towbook SAs: get real On Location from SA history (ActualStartTime is midnight bulk-update)
            towbook_ids_terr = [s['Id'] for s in completed_list
                                if (s.get('ERS_Dispatch_Method__c') or '').lower() == 'towbook']
            towbook_on_loc_terr = get_towbook_on_location(towbook_ids_terr) if towbook_ids_terr else {}
            for s in completed_list:
                wt_name = (s.get('WorkType') or {}).get('Name', '') or ''
                if 'drop' in wt_name.lower():
                    continue
                c = _parse_dt(s.get('CreatedDate'))
                dispatch_method = (s.get('ERS_Dispatch_Method__c') or '').lower()
                if 'towbook' in dispatch_method:
                    on_loc_str = towbook_on_loc_terr.get(s['Id'])
                    a = _parse_dt(on_loc_str) if on_loc_str else None
                else:
                    a = _parse_dt(s.get('ActualStartTime'))
                if c and a:
                    diff = (a - c).total_seconds() / 60
                    if 0 < diff < 480:
                        response_times.append(diff)

            sla_pct = round(100 * sum(1 for r in response_times if r <= 45)
                            / max(len(response_times), 1)) if response_times else None
            avg_response = round(sum(response_times) / len(response_times)) if response_times else None
            completion_rate = round(100 * len(completed_list) / max(total_t, 1))

            open_waits = []
            for s in open_list:
                cdt = _parse_dt(s.get('CreatedDate'))
                if cdt:
                    if cdt.tzinfo is None:
                        cdt = cdt.replace(tzinfo=timezone.utc)
                    wt = (now_utc - cdt).total_seconds() / 60
                    if 0 < wt < 1440:
                        open_waits.append(round(wt))
            avg_wait = round(sum(open_waits) / len(open_waits)) if open_waits else 0
            max_wait = max(open_waits) if open_waits else 0

            if total_t < 3:
                health_status = 'good'
            elif avg_wait > 90 or (sla_pct is not None and sla_pct < 25):
                health_status = 'critical'
            elif avg_wait > 45 or (sla_pct is not None and sla_pct < 45) or completion_rate < 55:
                health_status = 'behind'
            else:
                health_status = 'good'

            sa_points = []
            for s in sa_list_raw:
                lat, lon = s.get('Latitude'), s.get('Longitude')
                if lat and lon:
                    et = _to_eastern(s.get('CreatedDate'))
                    sa_points.append({
                        'lat': float(lat), 'lon': float(lon),
                        'status': s.get('Status'),
                        'work_type': (s.get('WorkType') or {}).get('Name', '?'),
                        'time': et.strftime('%I:%M %p') if et else '?',
                    })

            avail_drivers = drivers_by_territory.get(tid, 0)
            open_count = len(open_list)

            # Fleet = territory 100*/800*. Everything else = contractor.
            is_contractor = not is_fleet_territory(t_name)

            capacity_status = 'normal'
            if is_contractor:
                # Contractors have multiple drivers not tracked in SF GPS
                # Flag based on open call count + wait time instead of driver ratio
                if open_count >= 5 or max_wait > 60:
                    capacity_status = 'over'
                elif open_count >= 2 or max_wait > 30:
                    capacity_status = 'busy'
            elif avail_drivers > 0 and open_count > 0:
                ratio = open_count / avail_drivers
                if ratio >= 2:
                    capacity_status = 'over'
                elif ratio >= 1:
                    capacity_status = 'busy'
            elif avail_drivers == 0 and open_count > 0:
                capacity_status = 'over'

            tier_breakdown = dict(drivers_by_territory_tier.get(tid, {}))

            territories.append({
                'id': tid, 'name': t_name,
                'lat': t_lat, 'lon': t_lon,
                'total': total_t, 'open': open_count,
                'completed': len(completed_list), 'canceled': len(canceled_list),
                'completion_rate': completion_rate,
                'sla_pct': sla_pct, 'avg_response': avg_response,
                'avg_wait': avg_wait, 'max_wait': max_wait,
                'status': health_status, 'sa_points': sa_points,
                'avail_drivers': avail_drivers,
                'avail_tow': tier_breakdown.get('tow', 0),
                'avail_battery': tier_breakdown.get('battery', 0),
                'avail_light': tier_breakdown.get('light', 0),
                'is_contractor': is_contractor,
                'capacity': capacity_status,
            })

        status_order = {'critical': 0, 'behind': 1, 'good': 2}
        territories.sort(key=lambda t: (status_order.get(t['status'], 3), -t['total']))

        # Open customers
        open_customers = []
        for tid, sa_list in by_territory.items():
            st = (sa_list[0].get('ServiceTerritory') or {})
            t_name_c = st.get('Name') or '?'
            for s in sa_list:
                if s.get('Status') not in ('Dispatched', 'Assigned'):
                    continue

                cdt = _parse_dt(s.get('CreatedDate'))
                sched = _parse_dt(s.get('SchedStartTime'))
                wait_min = 0
                is_asap = True

                if cdt:
                    if cdt.tzinfo is None:
                        cdt = cdt.replace(tzinfo=timezone.utc)
                    wait_min = round((now_utc - cdt).total_seconds() / 60)
                    if sched:
                        if sched.tzinfo is None:
                            sched = sched.replace(tzinfo=timezone.utc)
                        gap_min = (sched - cdt).total_seconds() / 60
                        if gap_min > 30:
                            is_asap = False

                if not is_asap:
                    continue

                open_customers.append({
                    'number': s.get('AppointmentNumber', '?'),
                    'customer': '',
                    'phone': '',
                    'zip': s.get('PostalCode') or '',
                    'address': f"{s.get('Street') or ''} {s.get('City') or ''}".strip(),
                    'wait_min': wait_min,
                    'work_type': (s.get('WorkType') or {}).get('Name', '?'),
                    'territory': t_name_c,
                    'lat': s.get('Latitude'),
                    'lon': s.get('Longitude'),
                })
        open_customers.sort(key=lambda x: x['wait_min'], reverse=True)

        # ── Fleet Driver Tile ──
        # Total = all active fleet drivers in SF (cleaned of test/SPOT/office accounts)
        fleet_total = len(all_fleet_drivers)

        # GPS status for ALL fleet drivers
        fleet_fresh = 0   # GPS < 1h -- on shift with GPS
        fleet_recent = 0  # GPS 1-4h -- recently active
        fleet_stale = 0   # GPS > 4h -- has GPS hardware but not reporting
        fleet_no_gps = 0  # never reported GPS
        for d in all_fleet_drivers:
            lat = d.get('LastKnownLatitude')
            lkd = d.get('LastKnownLocationDate')
            if not lat or not lkd:
                fleet_no_gps += 1
                continue
            age = now - _parse_dt(lkd)
            if age < timedelta(hours=1):
                fleet_fresh += 1
            elif age < timedelta(hours=4):
                fleet_recent += 1
            else:
                fleet_stale += 1
        fleet_on_gps = fleet_fresh + fleet_recent  # drivers trackable right now
        fleet_gps_pct = round(100 * fleet_on_gps / max(fleet_total, 1)) if fleet_total else 0

        # ── Today's SA Status Breakdown (all statuses) ──
        status_counts = {'Dispatched': 0, 'Accepted': 0, 'Assigned': 0,
                         'En Route': 0, 'On Location': 0, 'In Progress': 0,
                         'Completed': 0, 'Canceled': 0, 'No-Show': 0,
                         'Unable to Complete': 0}
        fleet_completed = 0
        towbook_completed = 0
        total_completed = 0
        cancel_reasons = defaultdict(int)
        decline_reasons = defaultdict(int)
        hourly_volume = defaultdict(int)
        total_today = 0
        for sa in today_sas_all:
            wt_name = ((sa.get('WorkType') or {}).get('Name', '') or '').lower()
            if 'drop' in wt_name:
                continue  # Exclude Tow Drop-Off from all today metrics
            total_today += 1
            st = sa.get('Status', '')
            dm = sa.get('ERS_Dispatch_Method__c') or ''
            # Normalize cancel statuses
            if st.startswith('Cancel Call'):
                status_counts['Canceled'] = status_counts.get('Canceled', 0) + 1
            elif st in status_counts:
                status_counts[st] += 1
            elif st == 'Spotted':
                status_counts['Dispatched'] += 1  # Spotted ~ re-dispatched
            # Fleet vs contractor completed
            if st == 'Completed':
                total_completed += 1
                if dm and 'towbook' in dm.lower():
                    towbook_completed += 1
                else:
                    fleet_completed += 1
            # ── Metric 1: Cancellation reasons ──
            cancel_reason = sa.get('ERS_Cancellation_Reason__c')
            if cancel_reason:
                cancel_reasons[cancel_reason] += 1
            # ── Metric 2: Decline reasons ──
            decline_reason = sa.get('ERS_Facility_Decline_Reason__c')
            if decline_reason:
                decline_reasons[decline_reason] += 1
            # ── Metric 4: Hourly volume ──
            created = _parse_dt(sa.get('CreatedDate'))
            if created:
                hour_et = created.astimezone(_ET).hour
                hourly_volume[hour_et] += 1
        fleet_completed_pct = round(100 * fleet_completed / max(total_completed, 1)) if total_completed else 0
        contractor_completed_pct = 100 - fleet_completed_pct if total_completed else 0

        # ── Metric 1: Top cancellation reasons (sorted by count) ──
        cancel_breakdown = sorted(
            [{'reason': r, 'count': c} for r, c in cancel_reasons.items()],
            key=lambda x: -x['count']
        )[:8]
        total_cancels = sum(c['count'] for c in cancel_breakdown)
        for cb in cancel_breakdown:
            cb['pct'] = round(100 * cb['count'] / max(total_cancels, 1), 1)

        # ── Metric 2: Top decline/rejection reasons (sorted by count) ──
        decline_breakdown = sorted(
            [{'reason': r, 'count': c} for r, c in decline_reasons.items()],
            key=lambda x: -x['count']
        )[:8]
        total_declines = sum(d['count'] for d in decline_breakdown)
        for db in decline_breakdown:
            db['pct'] = round(100 * db['count'] / max(total_declines, 1), 1)

        # ── Metric 3: Fleet Utilization by tier ──
        busy_driver_ids = {ar.get('ServiceResourceId') for ar in busy_ar if ar.get('ServiceResourceId')}
        tier_counts = {'tow': {'on_shift': 0, 'busy': 0},
                       'light': {'on_shift': 0, 'busy': 0},
                       'battery': {'on_shift': 0, 'busy': 0}}
        for asset in cc_trucks:
            dr_id = asset.get('ERS_Driver__c')
            if not dr_id:
                continue
            caps = asset.get('ERS_Truck_Capabilities__c') or ''
            tier = _driver_tier(caps)
            if tier in tier_counts:
                tier_counts[tier]['on_shift'] += 1
                if dr_id in busy_driver_ids:
                    tier_counts[tier]['busy'] += 1
        total_on_shift = sum(t['on_shift'] for t in tier_counts.values())
        total_busy = sum(t['busy'] for t in tier_counts.values())
        utilization_pct = round(100 * total_busy / max(total_on_shift, 1)) if total_on_shift else 0

        # ── Metric 4: Hourly volume (0-23h ET) ──
        hourly_data = [{'hour': h, 'count': hourly_volume.get(h, 0)} for h in range(24)]

        # (Metric 5 removed -- garage delay cost is covered by Reassignment Cost)

        # ── Fleet Driver Leaderboard (Top 3 / Bottom 3 by ATA today) ──
        # Map SA Id -> driver name from AssignedResource
        sa_to_driver = {}
        for ar in fleet_ar:
            sa_id = ar.get('ServiceAppointmentId')
            sr = ar.get('ServiceResource') or {}
            if sa_id and sr.get('Name'):
                sa_to_driver[sa_id] = sr['Name']

        # Compute ATA per driver
        from collections import defaultdict as _dd
        driver_atas = _dd(list)
        for sa in fleet_lb_sas:
            sa_id = sa.get('Id')
            driver_name = sa_to_driver.get(sa_id)
            if not driver_name:
                continue
            c = _parse_dt(sa.get('CreatedDate'))
            a = _parse_dt(sa.get('ActualStartTime'))
            if c and a:
                ata = (a - c).total_seconds() / 60
                if 0 < ata < 480:
                    driver_atas[driver_name].append(ata)

        # Filter to real drivers only — exclude placeholders, offices, test accounts
        _skip_prefixes = ('000-', '0 ', '100a ', 'test ', 'towbook', 'travel user')
        driver_stats = []
        for name, atas in driver_atas.items():
            if len(atas) == 0:
                continue
            if any(name.lower().startswith(p) for p in _skip_prefixes):
                continue
            avg_ata = round(sum(atas) / len(atas))
            driver_stats.append({'name': name, 'calls': len(atas), 'avg_ata': avg_ata})

        driver_stats.sort(key=lambda x: x['avg_ata'])
        top_3_fleet = driver_stats[:3] if len(driver_stats) >= 3 else driver_stats
        bottom_3_fleet = driver_stats[-3:][::-1] if len(driver_stats) >= 3 else []

        # ── Reassignment Cost (driver-level bounces) ──
        # Group driver assignment changes by SA using shared utility
        # (filters SF ID rows, detects human dispatchers, marks reassignments)
        _assign_events = parse_assign_events(reassign_history)
        sa_driver_changes = _dd(list)
        for sa_id, evs in _assign_events.items():
            h_sa = next(
                (h.get('ServiceAppointment') or {} for h in reassign_history
                 if h.get('ServiceAppointmentId') == sa_id),
                {}
            )
            for ev in evs:
                sa_driver_changes[sa_id].append({
                    'time': ev['ts'],
                    'driver': ev['driver'],
                    'sa': h_sa,
                })

        total_bounces = 0
        total_minutes_lost = 0
        affected_sas = set()

        for sa_id, assignments in sa_driver_changes.items():
            if len(assignments) < 2:
                continue  # No bounce — single assignment
            assignments.sort(key=lambda e: e['time'] if e['time'] else now)
            for i in range(1, len(assignments)):
                prev_time = assignments[i-1]['time']
                curr_time = assignments[i]['time']
                if not prev_time or not curr_time:
                    continue
                gap_min = (curr_time - prev_time).total_seconds() / 60
                if gap_min < 10 or gap_min >= 480:
                    continue  # <10m = quick system retry, >=480m = stale/overnight
                total_bounces += 1
                total_minutes_lost += gap_min
                affected_sas.add(sa_id)

        hours_lost = round(total_minutes_lost / 60, 1)

        return {
            'territories': territories,
            'open_customers': open_customers[:30],
            'summary': {
                'total_territories': len(territories),
                'total_sas': sum(t['total'] for t in territories),
                'total_open': sum(t['open'] for t in territories),
                'total_completed': sum(t['completed'] for t in territories),
                'good': sum(1 for t in territories if t['status'] == 'good'),
                'behind': sum(1 for t in territories if t['status'] == 'behind'),
                'critical': sum(1 for t in territories if t['status'] == 'critical'),
                'over_capacity': sum(1 for t in territories if t.get('capacity') == 'over'),
                'busy': sum(1 for t in territories if t.get('capacity') == 'busy'),
            },
            'fleet_gps': {
                'total_roster': fleet_total,
                'on_shift': len(logged_in_ids),
                'total': fleet_total,
                'active': fleet_on_gps,
                'fresh': fleet_fresh,
                'recent': fleet_recent,
                'stale': fleet_stale,
                'no_gps': fleet_no_gps,
                'pct': fleet_gps_pct,
            },
            'today_status': {**status_counts, 'total': sum(status_counts.values())},
            'today_split': {
                'total_completed': total_completed,
                'fleet_completed': fleet_completed,
                'contractor_completed': towbook_completed,
                'fleet_pct': fleet_completed_pct,
                'contractor_pct': contractor_completed_pct,
            },
            'fleet_leaderboard': {
                'top': top_3_fleet,
                'bottom': bottom_3_fleet,
            },
            'reassignment': {
                'total_bounces': total_bounces,
                'affected_calls': len(affected_sas),
                'hours_lost': hours_lost,
            },
            'cancel_breakdown': {
                'total': total_cancels,
                'reasons': cancel_breakdown,
            },
            'decline_breakdown': {
                'total': total_declines,
                'reasons': decline_breakdown,
            },
            'fleet_utilization': {
                'total_on_shift': total_on_shift,
                'total_busy': total_busy,
                'utilization_pct': utilization_pct,
                'by_tier': tier_counts,
            },
            'hourly_volume': hourly_data,
            'hours': hours,
        }

    return cache.cached_query(f'command_center_{hours}', _fetch, ttl=120)
