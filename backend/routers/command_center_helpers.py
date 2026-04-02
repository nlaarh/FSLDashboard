"""Command Center helper functions — split from command_center.py.

Contains: territory aggregation, today's metrics computation,
fleet leaderboard, reassignment cost calculation.
These are utility functions imported by command_center.py (not a router).
"""

from datetime import datetime, timedelta, timezone
from collections import defaultdict

from utils import (
    _ET, parse_dt as _parse_dt, to_eastern as _to_eastern,
    is_fleet_territory,
)
from sf_client import get_towbook_on_location
from dispatch import _driver_tier


def build_driver_availability(cc_trucks, driver_members, busy_ar, now):
    """Build driver availability per territory (on-shift, NOT busy, by tier).

    Returns (drivers_by_territory, drivers_by_territory_tier, driver_tier_map, logged_in_ids).
    """
    logged_in_ids = set()
    driver_tier_map = {}  # driver_id -> 'tow'|'battery'|'light'
    for asset in cc_trucks:
        dr_id = asset.get('ERS_Driver__c')
        if dr_id:
            logged_in_ids.add(dr_id)
            caps = asset.get('ERS_Truck_Capabilities__c') or ''
            driver_tier_map[dr_id] = _driver_tier(caps)

    busy_driver_ids_set = {ar.get('ServiceResourceId') for ar in busy_ar if ar.get('ServiceResourceId')}

    drivers_by_territory = defaultdict(int)
    drivers_by_territory_tier = defaultdict(lambda: defaultdict(int))
    seen_drivers = set()
    for dm in driver_members:
        tid = dm.get('ServiceTerritoryId')
        dr_id = dm.get('ServiceResourceId')
        if not tid or not dr_id:
            continue
        if dr_id not in logged_in_ids:
            continue
        if dr_id in busy_driver_ids_set:
            continue
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

    return drivers_by_territory, drivers_by_territory_tier, driver_tier_map, logged_in_ids, busy_driver_ids_set


def build_territory_data(by_territory, now_utc, drivers_by_territory, drivers_by_territory_tier):
    """Build territory summary list from grouped SAs.

    Returns list of territory dicts ready for the response.
    """
    territories = []
    for tid, sa_list_raw in by_territory.items():
        st = (sa_list_raw[0].get('ServiceTerritory') or {})
        t_lat = st.get('Latitude')
        t_lon = st.get('Longitude')
        t_name = st.get('Name') or '?'
        if not t_lat or not t_lon:
            continue

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
        is_contractor = not is_fleet_territory(t_name)

        capacity_status = 'normal'
        if is_contractor:
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
    return territories


def build_today_metrics(today_sas_all, fleet_lb_sas, fleet_ar, cc_trucks, busy_ar, now_utc):
    """Build today's SA status breakdown, leaderboard, and utilization metrics.

    Returns dict with keys: status_counts, today_split, fleet_leaderboard,
    fleet_utilization, cancel_breakdown, decline_breakdown, hourly_volume.
    """
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
            continue
        total_today += 1
        st = sa.get('Status', '')
        dm = sa.get('ERS_Dispatch_Method__c') or ''
        if st.startswith('Cancel Call'):
            status_counts['Canceled'] = status_counts.get('Canceled', 0) + 1
        elif st in status_counts:
            status_counts[st] += 1
        elif st == 'Spotted':
            status_counts['Dispatched'] += 1
        if st == 'Completed':
            total_completed += 1
            if dm and 'towbook' in dm.lower():
                towbook_completed += 1
            else:
                fleet_completed += 1
        cancel_reason = sa.get('ERS_Cancellation_Reason__c')
        if cancel_reason:
            cancel_reasons[cancel_reason] += 1
        decline_reason = sa.get('ERS_Facility_Decline_Reason__c')
        if decline_reason:
            decline_reasons[decline_reason] += 1
        created = _parse_dt(sa.get('CreatedDate'))
        if created:
            hour_et = created.astimezone(_ET).hour
            hourly_volume[hour_et] += 1

    fleet_completed_pct = round(100 * fleet_completed / max(total_completed, 1)) if total_completed else 0
    contractor_completed_pct = 100 - fleet_completed_pct if total_completed else 0

    # Cancel breakdown
    cancel_breakdown = sorted(
        [{'reason': r, 'count': c} for r, c in cancel_reasons.items()],
        key=lambda x: -x['count']
    )[:8]
    total_cancels = sum(c['count'] for c in cancel_breakdown)
    for cb in cancel_breakdown:
        cb['pct'] = round(100 * cb['count'] / max(total_cancels, 1), 1)

    # Decline breakdown
    decline_breakdown = sorted(
        [{'reason': r, 'count': c} for r, c in decline_reasons.items()],
        key=lambda x: -x['count']
    )[:8]
    total_declines = sum(d['count'] for d in decline_breakdown)
    for db in decline_breakdown:
        db['pct'] = round(100 * db['count'] / max(total_declines, 1), 1)

    # Fleet utilization by tier
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

    # Hourly volume
    hourly_data = [{'hour': h, 'count': hourly_volume.get(h, 0)} for h in range(24)]

    # Fleet driver leaderboard
    sa_to_driver = {}
    for ar in fleet_ar:
        sa_id = ar.get('ServiceAppointmentId')
        sr = ar.get('ServiceResource') or {}
        if sa_id and sr.get('Name'):
            sa_to_driver[sa_id] = sr['Name']

    driver_atas = defaultdict(list)
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

    return {
        'status_counts': status_counts,
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
        'fleet_utilization': {
            'total_on_shift': total_on_shift,
            'total_busy': total_busy,
            'utilization_pct': utilization_pct,
            'by_tier': tier_counts,
        },
        'cancel_breakdown': {
            'total': total_cancels,
            'reasons': cancel_breakdown,
        },
        'decline_breakdown': {
            'total': total_declines,
            'reasons': decline_breakdown,
        },
        'hourly_volume': hourly_data,
    }


def build_reassignment_cost(reassign_history, today_sas_all, now):
    """Compute reassignment cost (driver-level bounces).

    Returns dict with total_bounces, affected_calls, hours_lost, by_channel.
    """
    from dispatch_utils import parse_assign_events

    _assign_events = parse_assign_events(reassign_history)
    sa_driver_changes = defaultdict(list)
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

    sa_dispatch = {}
    for s in today_sas_all:
        sa_dispatch[s.get('Id', '')] = s.get('ERS_Dispatch_Method__c') or ''

    total_bounces = 0
    total_minutes_lost = 0
    affected_sas = set()
    channel_stats = {
        'fleet': {'bounces': 0, 'minutes': 0, 'calls': set()},
        'contractor': {'bounces': 0, 'minutes': 0, 'calls': set()},
        'towbook': {'bounces': 0, 'minutes': 0, 'calls': set()},
    }

    for sa_id, assignments in sa_driver_changes.items():
        if len(assignments) < 2:
            continue
        dm = sa_dispatch.get(sa_id, '')
        if dm == 'Field Services':
            terr_name = ''
            if assignments and assignments[0].get('sa'):
                terr_name = (assignments[0]['sa'].get('ServiceTerritory') or {}).get('Name', '')
            channel = 'fleet' if is_fleet_territory(terr_name) else 'contractor'
        elif dm == 'Towbook':
            channel = 'towbook'
        else:
            channel = 'towbook'

        assignments.sort(key=lambda e: e['time'] if e['time'] else now)
        for i in range(1, len(assignments)):
            prev_time = assignments[i-1]['time']
            curr_time = assignments[i]['time']
            if not prev_time or not curr_time:
                continue
            gap_min = (curr_time - prev_time).total_seconds() / 60
            if gap_min < 10 or gap_min >= 480:
                continue
            total_bounces += 1
            total_minutes_lost += gap_min
            affected_sas.add(sa_id)
            channel_stats[channel]['bounces'] += 1
            channel_stats[channel]['minutes'] += gap_min
            channel_stats[channel]['calls'].add(sa_id)

    hours_lost = round(total_minutes_lost / 60, 1)

    return {
        'total_bounces': total_bounces,
        'affected_calls': len(affected_sas),
        'hours_lost': hours_lost,
        'by_channel': {
            ch: {
                'bounces': s['bounces'],
                'hours_lost': round(s['minutes'] / 60, 1),
                'calls': len(s['calls']),
            } for ch, s in channel_stats.items()
        },
    }
