"""Garage performance dashboard — response decomposition, acceptance, completion."""

from fastapi import APIRouter, HTTPException, Query
from datetime import datetime, date, timedelta, timezone
from collections import defaultdict

from sf_client import sf_query_all, sf_parallel, sanitize_soql, get_towbook_on_location
from utils import (
    _ET, parse_dt as _parse_dt, to_eastern as _to_eastern,
    is_fleet_territory,
)
from dispatch_decomposition import get_response_decomposition
import cache

router = APIRouter()


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
    return cache.cached_query_persistent(cache_key, lambda: _compute_performance(territory_id, period_start, period_end), max_stale_hours=26)


def _compute_performance(territory_id: str, period_start: str, period_end: str) -> dict:
    """All from Salesforce -- parallel queries."""
    is_single_day = period_start == period_end
    next_day = (date.fromisoformat(period_end) + timedelta(days=1)).isoformat()
    since = f"{period_start}T00:00:00Z"
    until = f"{next_day}T00:00:00Z"

    # Parallel: individual SAs + WO IDs for surveys + trend aggregate
    data = sf_parallel(
        sas=lambda: sf_query_all(f"""
            SELECT Id, Status, CreatedDate, ActualStartTime,
                   ERS_Auto_Assign__c, ERS_PTA__c,
                   ERS_Facility_Decline_Reason__c,
                   ERS_Dispatch_Method__c, WorkType.Name
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
            SELECT ServiceAppointmentId, NewValue, CreatedDate
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
