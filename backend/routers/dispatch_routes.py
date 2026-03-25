"""Dispatch optimization and insights drill-down endpoints."""

from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Query

from utils import parse_dt as _parse_dt, is_fleet_territory, haversine as _haversine
from sf_client import sf_query_all, sf_parallel, sanitize_soql
from dispatch_utils import fetch_gps_history, gps_at_time, parse_assign_events, classify_dispatch
from dispatch import (
    get_live_queue, recommend_drivers, get_cascade_status,
    get_forecast, _classify_worktype, _driver_tier, _can_cover,
)
import cache

router = APIRouter()

_ET = ZoneInfo('America/New_York')


def _today_start_utc():
    """Return today midnight ET as UTC ISO string for SOQL filters."""
    now = datetime.now(_ET)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(ZoneInfo('UTC')).strftime('%Y-%m-%dT%H:%M:%SZ')


def _fmt_et(iso_str):
    """Format an ISO datetime string to 'H:MM AM/PM' in Eastern."""
    dt = _parse_dt(iso_str)
    if not dt:
        return ''
    return dt.astimezone(_ET).strftime('%-I:%M %p')


def _sa_row(sa, ata=None, minutes_lost=None):
    """Build a standard SA detail dict from a ServiceAppointment record."""
    return {
        'sa_id': sa.get('Id', ''),
        'number': sa.get('AppointmentNumber', ''),
        'customer': (sa.get('Account') or {}).get('Name', ''),
        'work_type': (sa.get('WorkType') or {}).get('Name', ''),
        'territory': (sa.get('ServiceTerritory') or {}).get('Name', ''),
        'status': sa.get('Status', ''),
        'created_time': _fmt_et(sa.get('CreatedDate')),
        'cancel_reason': sa.get('ERS_Cancellation_Reason__c') or '',
        'reject_reason': sa.get('ERS_Facility_Decline_Reason__c') or '',
        'dispatch_method': sa.get('ERS_Dispatch_Method__c') or '',
        'ata_min': ata,
        'minutes_lost': minutes_lost,
    }


# ── Dispatch Optimization ────────────────────────────────────────────────────

@router.get("/api/dispatch/queue")
def api_dispatch_queue():
    """Live queue board — all open SAs with aging and urgency."""
    return get_live_queue()

@router.get("/api/dispatch/recommend/{sa_id}")
def api_dispatch_recommend(sa_id: str):
    """Top driver recommendations for a specific SA."""
    sa_id = sanitize_soql(sa_id)
    result = recommend_drivers(sa_id)
    if 'error' in result:
        raise HTTPException(status_code=404, detail=result['error'])
    return result

@router.get("/api/dispatch/cascade/{territory_id}")
def api_dispatch_cascade(territory_id: str):
    """Cross-skill cascade opportunities for a territory."""
    territory_id = sanitize_soql(territory_id)
    return get_cascade_status(territory_id)

# ── Dispatch Insights Drill-Down (lazy, on-demand) ─────────────────────────

@router.get("/api/insights/reassignment-detail")
def api_reassignment_detail():
    """Drill-down: all SAs reassigned today — full driver+territory chain with timings.

    Shows the complete story for each SA: every territory/garage it was sent to,
    every driver offered, how long each held it, and what happened (Rejected/Declined/Accepted).
    """
    today_start = _today_start_utc()

    def _fetch():
        import re
        _SF_ID = re.compile(r'^[a-zA-Z0-9]{15}$|^[a-zA-Z0-9]{18}$')

        # Query driver changes + territory changes + status changes in one go
        rows = sf_query_all(f"""
            SELECT ServiceAppointmentId,
                   ServiceAppointment.AppointmentNumber,
                   ServiceAppointment.Account.Name,
                   ServiceAppointment.WorkType.Name,
                   ServiceAppointment.ServiceTerritory.Name,
                   ServiceAppointment.ServiceTerritoryId,
                   ServiceAppointment.Status,
                   ServiceAppointment.CreatedDate,
                   ServiceAppointment.ERS_Cancellation_Reason__c,
                   ServiceAppointment.ERS_Facility_Decline_Reason__c,
                   ServiceAppointment.ERS_Dispatch_Method__c,
                   Field, CreatedDate, OldValue, NewValue
            FROM ServiceAppointmentHistory
            WHERE ServiceAppointment.CreatedDate >= {today_start}
              AND Field IN ('ERS_Assigned_Resource__c', 'ServiceTerritory', 'Status')
              AND ServiceAppointment.WorkType.Name != 'Tow Drop-Off'
            ORDER BY ServiceAppointmentId, CreatedDate ASC
        """)

        # Group all events by SA, skipping SF ID duplicate rows
        sa_events = defaultdict(list)
        sa_info = {}
        for r in rows:
            sa_id = r.get('ServiceAppointmentId')
            if not sa_id:
                continue
            field = r.get('Field', '')
            new_val = (r.get('NewValue') or '').strip()
            old_val = (r.get('OldValue') or '').strip()

            # Each field change writes 2 rows: display name + SF ID. Skip the ID rows.
            if field in ('ERS_Assigned_Resource__c', 'ServiceTerritory'):
                if new_val and _SF_ID.match(new_val):
                    continue
                if not new_val and old_val and _SF_ID.match(old_val):
                    continue

            ts = _parse_dt(r.get('CreatedDate'))
            if ts is None:
                continue

            sa_events[sa_id].append({'field': field, 'new': new_val, 'old': old_val, 'ts': ts})
            if sa_id not in sa_info:
                sa_info[sa_id] = r.get('ServiceAppointment') or {}

        _now_utc = datetime.now(_ET).astimezone()
        bounced_sas = []

        for sa_id, events in sa_events.items():
            events.sort(key=lambda e: e['ts'])

            # Walk events to build complete assignment timeline.
            # Each "step" is one driver/garage being offered the SA.
            current_territory = None
            open_assign = None   # {territory, driver, ts_start}
            last_status = None
            chain = []           # completed steps

            def _close_assign(ts_end, outcome):
                nonlocal open_assign
                if not open_assign:
                    return
                dur = (ts_end - open_assign['ts_start']).total_seconds() / 60
                chain.append({
                    'territory':   open_assign['territory'],
                    'driver':      open_assign['driver'],
                    'assigned_at': _fmt_et(open_assign['ts_start'].isoformat()),
                    'outcome_at':  _fmt_et(ts_end.isoformat()),
                    'duration_min': round(dur) if 0 <= dur < 480 else None,
                    'outcome':     outcome,
                    '_ts_start':   open_assign['ts_start'],
                    '_ts_end':     ts_end,
                })
                open_assign = None

            for evt in events:
                field   = evt['field']
                new_val = evt['new']
                ts      = evt['ts']

                if field == 'ServiceTerritory' and new_val:
                    current_territory = new_val

                elif field == 'Status':
                    last_status = new_val
                    # Final acceptance closes the open assignment
                    if new_val in ('Accepted', 'Dispatched') and open_assign:
                        _close_assign(ts, 'Accepted')

                elif field == 'ERS_Assigned_Resource__c':
                    if new_val:
                        # New driver/resource being assigned — close any open step first
                        if open_assign:
                            outcome = last_status if last_status in ('Rejected', 'Declined') else 'Released'
                            _close_assign(ts, outcome)
                        open_assign = {'territory': current_territory, 'driver': new_val, 'ts_start': ts}
                        last_status = None
                    else:
                        # Driver cleared — close the current step
                        outcome = last_status if last_status in ('Rejected', 'Declined') else 'Released'
                        _close_assign(ts, outcome)
                        last_status = None

            # Still-open assignment (in progress right now)
            if open_assign:
                dur = (_now_utc - open_assign['ts_start']).total_seconds() / 60
                chain.append({
                    'territory':   open_assign['territory'],
                    'driver':      open_assign['driver'],
                    'assigned_at': _fmt_et(open_assign['ts_start'].isoformat()),
                    'duration_min': round(dur) if 0 <= dur < 480 else None,
                    'outcome':     'In Progress',
                    '_ts_start':   open_assign['ts_start'],
                    '_ts_end':     None,
                })

            # Only show SAs that were actually reassigned (≥ 2 attempts)
            if len(chain) < 2:
                continue

            # Calculate gap between each step ending and the next starting
            for i in range(len(chain) - 1):
                ts_end  = chain[i]['_ts_end']
                ts_next = chain[i + 1]['_ts_start']
                if ts_end and ts_next:
                    gap = (ts_next - ts_end).total_seconds() / 60
                    chain[i]['gap_to_next_min'] = round(gap) if 0 <= gap < 480 else 0
                else:
                    chain[i]['gap_to_next_min'] = None
            chain[-1]['gap_to_next_min'] = None

            # Total time = from first assignment to final acceptance (or now)
            ts_first = chain[0]['_ts_start']
            ts_last  = chain[-1]['_ts_end'] or _now_utc
            total_min = (ts_last - ts_first).total_seconds() / 60
            total_min = round(total_min) if 0 < total_min < 480 else None

            # Clean internal fields
            for c in chain:
                del c['_ts_start']
                del c['_ts_end']

            sa = sa_info.get(sa_id, {})
            sa['Id'] = sa_id  # sub-object doesn't include Id — set it explicitly
            row = _sa_row(sa, minutes_lost=total_min)
            row['bounce_chain'] = chain
            row['bounce_count'] = len(chain) - 1   # attempts before final
            row['_created_iso'] = sa.get('CreatedDate') or ''
            bounced_sas.append(row)

        # Sort most recent first
        bounced_sas.sort(key=lambda x: x.get('_created_iso') or '', reverse=True)
        bounced_sas = bounced_sas[:200]

        # Enrich: dispatch method from SA
        if bounced_sas:
            bounced_ids = [b['sa_id'] for b in bounced_sas if b.get('sa_id')]
            driver_info = {}
            for i in range(0, len(bounced_ids), 150):
                batch = bounced_ids[i:i + 150]
                id_str = "','".join(batch)
                extras = sf_query_all(f"""
                    SELECT Id, Off_Platform_Driver__r.Name, ERS_Dispatch_Method__c
                    FROM ServiceAppointment
                    WHERE Id IN ('{id_str}')
                """)
                for e in extras:
                    drv = (e.get('Off_Platform_Driver__r') or {}).get('Name')
                    driver_info[e['Id']] = {
                        'off_platform_driver': drv or '',
                        'dispatch_method': e.get('ERS_Dispatch_Method__c') or '',
                    }
            for b in bounced_sas:
                info = driver_info.get(b.get('sa_id'), {})
                b['off_platform_driver'] = info.get('off_platform_driver', '')
                b['dispatch_method'] = info.get('dispatch_method', '')

        return {'bounces': bounced_sas}

    return cache.cached_query('drilldown_reassignment', _fetch, ttl=120)


@router.get("/api/insights/human-intervention")
def api_human_intervention():
    """Drill-down: SAs where a human dispatcher intervened today, and auto SAs."""
    today_start = _today_start_utc()

    def _fetch():
        # Get all ERS SAs for today (exclude Tow Drop-Off — member response = Pick-Up only)
        sas = sf_query_all(f"""
            SELECT Id, AppointmentNumber, Account.Name, WorkType.Name,
                   ServiceTerritory.Name, Status, CreatedDate, ActualStartTime,
                   ERS_Cancellation_Reason__c, ERS_Facility_Decline_Reason__c,
                   ERS_Dispatch_Method__c, ERS_PTA__c
            FROM ServiceAppointment
            WHERE CreatedDate >= {today_start}
              AND WorkType.Name IN ('Tow Pick-Up','Battery','Tire','Lockout','Winch Out','Fuel','Locksmith','EV')
        """)
        if not sas:
            return {'human': [], 'auto': [], 'human_count': 0, 'auto_count': 0}

        sa_map = {s['Id']: s for s in sas}
        sa_ids = list(sa_map.keys())

        # Manual dispatch = SA was reassigned (ERS_Assigned_Resource__c changed >1 time)
        # AND a human (Membership User) was involved in any of those changes.
        # Each assignment creates 2 history rows (display name + SF ID), so count > 2
        # means the resource changed at least once after initial assignment.
        hist_count: dict[str, int] = {}    # sa_id -> total SAHistory rows for field
        human_sas: dict[str, str] = {}     # sa_id -> dispatcher name (first human found)
        batch_size = 150
        for i in range(0, len(sa_ids), batch_size):
            batch = sa_ids[i:i + batch_size]
            id_str = "','".join(batch)
            rows = sf_query_all(f"""
                SELECT ServiceAppointmentId, CreatedBy.Name, CreatedBy.Profile.Name
                FROM ServiceAppointmentHistory
                WHERE ServiceAppointmentId IN ('{id_str}')
                  AND Field = 'ERS_Assigned_Resource__c'
            """)
            for r in rows:
                sa_id = r.get('ServiceAppointmentId')
                if not sa_id:
                    continue
                hist_count[sa_id] = hist_count.get(sa_id, 0) + 1
                cb = r.get('CreatedBy') or {}
                profile = (cb.get('Profile') or {}).get('Name', '')
                if profile == 'Membership User' and sa_id not in human_sas:
                    human_sas[sa_id] = cb.get('Name', '?')

        # Only manual if reassigned (count > 2) AND human was involved
        human_sas = {sa_id: name for sa_id, name in human_sas.items()
                     if hist_count.get(sa_id, 0) > 2}

        human_list, auto_list = [], []
        for sa in sas:
            sa_id = sa['Id']
            created = sa.get('CreatedDate')
            actual = sa.get('ActualStartTime')
            ata = None
            if created and actual:
                t1, t2 = _parse_dt(created), _parse_dt(actual)
                if t1 and t2:
                    ata = round((t2 - t1).total_seconds() / 60)
            pta_raw = sa.get('ERS_PTA__c')
            pta = round(float(pta_raw)) if pta_raw and 0 < float(pta_raw) < 999 else None
            pta_delta = round(ata - pta) if ata and pta else None

            row = _sa_row(sa, ata=ata)
            row['pta_min'] = pta
            row['pta_delta'] = pta_delta  # positive = late, negative = early
            if sa_id in human_sas:
                row['dispatcher'] = human_sas[sa_id]
                human_list.append(row)
            else:
                auto_list.append(row)

        return {
            'human': human_list[:200],
            'auto': auto_list[:200],
            'human_count': len(human_list),
            'auto_count': len(auto_list),
        }

    return cache.cached_query('drilldown_human_intervention', _fetch, ttl=120)


@router.get("/api/insights/dispatcher-detail/{name}")
def api_dispatcher_detail(name: str):
    """Drill-down: SAs handled by a specific dispatcher today."""
    name = sanitize_soql(name)
    today_start = _today_start_utc()

    def _fetch():
        # NewValue can't be filtered in SOQL — fetch all status changes
        # by this user and filter for 'Dispatched' in Python (matches command center logic)
        history = sf_query_all(f"""
            SELECT ServiceAppointmentId,
                   ServiceAppointment.AppointmentNumber,
                   ServiceAppointment.Account.Name,
                   ServiceAppointment.WorkType.Name,
                   ServiceAppointment.ServiceTerritory.Name,
                   ServiceAppointment.Status,
                   ServiceAppointment.CreatedDate,
                   ServiceAppointment.ActualStartTime,
                   ServiceAppointment.ERS_Cancellation_Reason__c,
                   ServiceAppointment.ERS_Facility_Decline_Reason__c,
                   ServiceAppointment.ERS_Dispatch_Method__c,
                   CreatedDate, NewValue
            FROM ServiceAppointmentHistory
            WHERE ServiceAppointment.CreatedDate >= {today_start}
              AND Field = 'Status'
              AND CreatedBy.Name = '{name}'
            ORDER BY CreatedDate DESC
        """)

        seen = set()
        sas = []
        for r in history:
            if r.get('NewValue') != 'Dispatched':
                continue
            sa_id = r.get('ServiceAppointmentId')
            if sa_id in seen:
                continue
            seen.add(sa_id)
            sa = r.get('ServiceAppointment') or {}
            created = sa.get('CreatedDate')
            actual = sa.get('ActualStartTime')
            ata = None
            if created and actual:
                t1, t2 = _parse_dt(created), _parse_dt(actual)
                if t1 and t2:
                    ata = round((t2 - t1).total_seconds() / 60)
            row = _sa_row(sa, ata=ata)
            row['dispatched_at'] = _fmt_et(r.get('CreatedDate'))
            sas.append(row)

        return {'dispatcher': name, 'calls': sas[:30]}

    return cache.cached_query(f'drilldown_dispatcher_{name}', _fetch, ttl=120)


@router.get("/api/insights/driver-detail/{name}")
def api_driver_detail(name: str):
    """Drill-down: SAs completed by a specific fleet driver today."""
    name = sanitize_soql(name)
    today_start = _today_start_utc()

    def _fetch():
        rows = sf_query_all(f"""
            SELECT ServiceAppointment.Id,
                   ServiceAppointment.AppointmentNumber,
                   ServiceAppointment.Account.Name,
                   ServiceAppointment.WorkType.Name,
                   ServiceAppointment.ServiceTerritory.Name,
                   ServiceAppointment.Status,
                   ServiceAppointment.CreatedDate,
                   ServiceAppointment.ActualStartTime,
                   ServiceAppointment.ERS_Cancellation_Reason__c,
                   ServiceAppointment.ERS_Facility_Decline_Reason__c,
                   ServiceAppointment.ERS_Dispatch_Method__c
            FROM AssignedResource
            WHERE ServiceAppointment.CreatedDate >= {today_start}
              AND ServiceAppointment.ERS_Dispatch_Method__c = 'Field Services'
              AND ServiceAppointment.Status = 'Completed'
              AND ServiceAppointment.ActualStartTime != null
              AND ServiceAppointment.WorkType.Name != 'Tow Drop-Off'
              AND ServiceResource.Name = '{name}'
            ORDER BY ServiceAppointment.CreatedDate DESC
        """)

        sas = []
        for r in rows:
            sa = r.get('ServiceAppointment') or {}
            created = sa.get('CreatedDate')
            actual = sa.get('ActualStartTime')
            ata = None
            if created and actual:
                t1, t2 = _parse_dt(created), _parse_dt(actual)
                if t1 and t2:
                    ata = round((t2 - t1).total_seconds() / 60)
            sas.append(_sa_row(sa, ata=ata))

        return {'driver': name, 'calls': sas[:30]}

    return cache.cached_query(f'drilldown_driver_{name}', _fetch, ttl=120)


@router.get("/api/insights/cancel-detail/{reason}")
def api_cancel_detail(reason: str):
    """Drill-down: SAs cancelled with a specific reason today."""
    reason = sanitize_soql(reason)
    today_start = _today_start_utc()

    def _fetch():
        rows = sf_query_all(f"""
            SELECT Id, AppointmentNumber, Account.Name, WorkType.Name,
                   ServiceTerritory.Name, Status, CreatedDate,
                   ERS_Cancellation_Reason__c, ERS_Facility_Decline_Reason__c,
                   ERS_Dispatch_Method__c, ActualStartTime
            FROM ServiceAppointment
            WHERE CreatedDate >= {today_start}
              AND ERS_Cancellation_Reason__c = '{reason}'
              AND WorkType.Name != 'Tow Drop-Off'
            ORDER BY CreatedDate DESC
            LIMIT 50
        """)
        sas = []
        for sa in rows:
            wt = (sa.get('WorkType') or {}).get('Name', '')
            if 'drop' in wt.lower():
                continue
            created = sa.get('CreatedDate')
            actual = sa.get('ActualStartTime')
            ata = None
            if created and actual:
                t1, t2 = _parse_dt(created), _parse_dt(actual)
                if t1 and t2:
                    ata = round((t2 - t1).total_seconds() / 60)
            sas.append(_sa_row(sa, ata=ata))
        return {'reason': reason, 'calls': sas}

    return cache.cached_query(f'drilldown_cancel_{reason}', _fetch, ttl=120)


@router.get("/api/insights/decline-detail/{reason}")
def api_decline_detail(reason: str):
    """Drill-down: SAs declined/rejected with a specific reason today."""
    reason = sanitize_soql(reason)
    today_start = _today_start_utc()

    def _fetch():
        rows = sf_query_all(f"""
            SELECT Id, AppointmentNumber, Account.Name, WorkType.Name,
                   ServiceTerritory.Name, Status, CreatedDate,
                   ERS_Cancellation_Reason__c, ERS_Facility_Decline_Reason__c,
                   ERS_Dispatch_Method__c, ActualStartTime
            FROM ServiceAppointment
            WHERE CreatedDate >= {today_start}
              AND ERS_Facility_Decline_Reason__c = '{reason}'
              AND WorkType.Name != 'Tow Drop-Off'
            ORDER BY CreatedDate DESC
            LIMIT 50
        """)
        sas = []
        for sa in rows:
            wt = (sa.get('WorkType') or {}).get('Name', '')
            if 'drop' in wt.lower():
                continue
            created = sa.get('CreatedDate')
            actual = sa.get('ActualStartTime')
            ata = None
            if created and actual:
                t1, t2 = _parse_dt(created), _parse_dt(actual)
                if t1 and t2:
                    ata = round((t2 - t1).total_seconds() / 60)
            sas.append(_sa_row(sa, ata=ata))
        return {'reason': reason, 'calls': sas}

    return cache.cached_query(f'drilldown_decline_{reason}', _fetch, ttl=120)


@router.get("/api/insights/status-detail/{status}")
def api_status_detail(status: str):
    """Drill-down: SAs in a specific status today."""
    status = sanitize_soql(status)
    today_start = _today_start_utc()

    def _fetch():
        rows = sf_query_all(f"""
            SELECT Id, AppointmentNumber, Account.Name, WorkType.Name,
                   ServiceTerritory.Name, Status, CreatedDate,
                   ERS_Cancellation_Reason__c, ERS_Facility_Decline_Reason__c,
                   ERS_Dispatch_Method__c, ActualStartTime
            FROM ServiceAppointment
            WHERE CreatedDate >= {today_start}
              AND Status = '{status}'
              AND WorkType.Name != 'Tow Drop-Off'
            ORDER BY CreatedDate DESC
            LIMIT 50
        """)
        sas = []
        for sa in rows:
            wt = (sa.get('WorkType') or {}).get('Name', '')
            if 'drop' in wt.lower():
                continue
            created = sa.get('CreatedDate')
            actual = sa.get('ActualStartTime')
            ata = None
            if created and actual:
                t1, t2 = _parse_dt(created), _parse_dt(actual)
                if t1 and t2:
                    ata = round((t2 - t1).total_seconds() / 60)
            sas.append(_sa_row(sa, ata=ata))
        return {'status': status, 'calls': sas}

    return cache.cached_query(f'drilldown_status_{status}', _fetch, ttl=120)


@router.get("/api/insights/capacity-detail/{territory_name}")
def api_capacity_detail(territory_name: str):
    """Drill-down: open calls for a specific territory today."""
    territory_name = sanitize_soql(territory_name)
    today_start = _today_start_utc()

    def _fetch():
        rows = sf_query_all(f"""
            SELECT Id, AppointmentNumber, Account.Name, WorkType.Name,
                   ServiceTerritory.Name, Status, CreatedDate,
                   ERS_Cancellation_Reason__c, ERS_Facility_Decline_Reason__c,
                   ERS_Dispatch_Method__c, ActualStartTime
            FROM ServiceAppointment
            WHERE CreatedDate >= {today_start}
              AND ServiceTerritory.Name = '{territory_name}'
              AND Status IN ('Dispatched', 'Assigned', 'Accepted', 'En Route', 'On Location')
              AND WorkType.Name != 'Tow Drop-Off'
            ORDER BY CreatedDate ASC
            LIMIT 50
        """)
        sas = []
        for sa in rows:
            wt = (sa.get('WorkType') or {}).get('Name', '')
            if 'drop' in wt.lower():
                continue
            # Show how long the call has been waiting
            created = sa.get('CreatedDate')
            wait = None
            if created:
                t1 = _parse_dt(created)
                if t1:
                    wait = round((datetime.now(ZoneInfo('UTC')) - t1).total_seconds() / 60)
            row = _sa_row(sa)
            row['wait_min'] = wait
            sas.append(row)
        return {'territory': territory_name, 'calls': sas}

    return cache.cached_query(f'drilldown_capacity_{territory_name}', _fetch, ttl=60)


@router.get("/api/insights/gps-detail/{bucket}")
def api_gps_detail(bucket: str):
    """Drill-down: on-shift fleet drivers by GPS freshness."""
    from datetime import timedelta
    valid_buckets = {'fresh', 'recent', 'stale', 'no_gps', 'all'}
    if bucket not in valid_buckets:
        raise HTTPException(400, f"Invalid bucket. Use: {', '.join(sorted(valid_buckets))}")

    def _fetch():
        # On-shift = logged into a truck (Asset with ERS_Driver__c set)
        on_shift = sf_query_all("""
            SELECT ERS_Driver__c, ERS_Driver__r.Name, ERS_Driver__r.ERS_Tech_ID__c,
                   ERS_Driver__r.LastKnownLatitude, ERS_Driver__r.LastKnownLongitude,
                   ERS_Driver__r.LastKnownLocationDate,
                   ERS_Driver__r.ERS_Driver_Type__c,
                   Name, ERS_Truck_Capabilities__c
            FROM Asset
            WHERE RecordType.Name = 'ERS Truck'
              AND ERS_Driver__c != null
              AND ERS_Driver__r.IsActive = true
        """)
        now = datetime.now(ZoneInfo('UTC'))
        result = []
        seen = set()
        for a in on_shift:
            driver_id = a.get('ERS_Driver__c')
            if not driver_id or driver_id in seen:
                continue
            seen.add(driver_id)
            dr = a.get('ERS_Driver__r') or {}
            lat = dr.get('LastKnownLatitude')
            lkd_str = dr.get('LastKnownLocationDate')
            lkd = _parse_dt(lkd_str) if lkd_str else None

            if not lat or not lkd:
                gps_bucket = 'no_gps'
                age_min = None
                last_update = ''
            else:
                age = now - lkd
                age_min = round(age.total_seconds() / 60)
                if age < timedelta(hours=1):
                    gps_bucket = 'fresh'
                elif age < timedelta(hours=4):
                    gps_bucket = 'recent'
                else:
                    gps_bucket = 'stale'
                last_update = _fmt_et(lkd_str)

            if bucket != 'all' and gps_bucket != bucket:
                continue

            result.append({
                'name': dr.get('Name', ''),
                'tech_id': dr.get('ERS_Tech_ID__c') or '',
                'truck': a.get('Name', ''),
                'truck_type': a.get('ERS_Truck_Capabilities__c') or '',
                'gps_bucket': gps_bucket,
                'age_min': age_min,
                'last_update': last_update,
                'lat': lat,
                'lon': dr.get('LastKnownLongitude'),
            })

        # Sort: fresh first (by name), then recent (by name), then stale (oldest first), then no_gps
        bucket_order = {'fresh': 0, 'recent': 1, 'stale': 2, 'no_gps': 3}
        result.sort(key=lambda x: (bucket_order.get(x['gps_bucket'], 9), x['name']))
        return {'bucket': bucket, 'total': len(result), 'drivers': result}

    return cache.cached_query(f'drilldown_gps_{bucket}', _fetch, ttl=120)


@router.get("/api/insights/closest-driver-detail")
def api_closest_driver_detail():
    """Drill-down: for each fleet SA today, show all candidate drivers with
    distances and highlight which one was actually picked.

    Reuses the same data/logic as scheduler-insights _closest_driver_analysis
    but returns per-SA detail instead of aggregates.
    """
    from sf_client import sf_parallel

    cutoff_utc = _today_start_utc()

    def _fetch():
        from collections import defaultdict

        def _get_sas():
            return sf_query_all(f"""
                SELECT Id, AppointmentNumber, Status, CreatedDate,
                       ERS_Dispatch_Method__c, Latitude, Longitude,
                       ERS_Dispatched_Geolocation__Latitude__s,
                       ERS_Dispatched_Geolocation__Longitude__s,
                       ServiceTerritoryId, ServiceTerritory.Name,
                       WorkType.Name
                FROM ServiceAppointment
                WHERE CreatedDate >= {cutoff_utc}
                  AND ServiceTerritoryId != null
                  AND ERS_Dispatch_Method__c = 'Field Services'
                  AND Status IN ('Dispatched','Completed','Assigned')
                ORDER BY CreatedDate DESC
            """)

        def _get_assigned():
            return sf_query_all(f"""
                SELECT ServiceAppointmentId, ServiceResourceId,
                       ServiceResource.Name,
                       ServiceResource.LastKnownLatitude,
                       ServiceResource.LastKnownLongitude,
                       ServiceResource.ERS_Driver_Type__c,
                       CreatedBy.Name, CreatedBy.Profile.Name
                FROM AssignedResource
                WHERE ServiceAppointment.CreatedDate >= {cutoff_utc}
                  AND ServiceAppointment.ERS_Dispatch_Method__c = 'Field Services'
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

        def _get_logged_in():
            """Asset-based login: drivers currently assigned to a truck = on shift."""
            return sf_query_all("""
                SELECT ERS_Driver__c, ERS_Truck_Capabilities__c
                FROM Asset
                WHERE RecordType.Name = 'ERS Truck'
                  AND ERS_Driver__c != null
            """)

        def _get_active_assignments():
            """All assigned resources for today's SAs — used to determine driver busy status."""
            return sf_query_all(f"""
                SELECT ServiceResourceId, ServiceAppointmentId,
                       ServiceAppointment.CreatedDate,
                       ServiceAppointment.Status
                FROM AssignedResource
                WHERE ServiceAppointment.CreatedDate >= {cutoff_utc}
                  AND ServiceAppointment.Status IN ('Dispatched','Assigned','In Progress','En Route','On Location')
            """)

        def _get_members():
            return sf_query_all("""
                SELECT ServiceResourceId, ServiceTerritoryId
                FROM ServiceTerritoryMember
                WHERE TerritoryType IN ('P','S')
                  AND ServiceResource.IsActive = true
                  AND ServiceResource.ResourceType = 'T'
            """)

        def _get_sa_hist():
            """SAHistory rows for manual dispatch detection: manual = count > 2 AND human involved."""
            return sf_query_all(f"""
                SELECT ServiceAppointmentId, CreatedBy.Name, CreatedBy.Profile.Name
                FROM ServiceAppointmentHistory
                WHERE ServiceAppointment.CreatedDate >= {cutoff_utc}
                  AND ServiceAppointment.ERS_Dispatch_Method__c = 'Field Services'
                  AND Field = 'ERS_Assigned_Resource__c'
            """)

        data = sf_parallel(
            sas=_get_sas, assigned=_get_assigned,
            drivers=_get_drivers, members=_get_members,
            logged_in=_get_logged_in,
            active_assignments=_get_active_assignments,
            sa_hist=_get_sa_hist,
        )

        sas_raw = data['sas']
        assigned_raw = data['assigned']
        all_drivers = data['drivers']
        members_raw = data['members']
        logged_in_ids = set()
        driver_capabilities = {}  # driver_id -> set of capability strings
        for a in data['logged_in']:
            dr_id = a.get('ERS_Driver__c')
            if dr_id:
                logged_in_ids.add(dr_id)
                caps = (a.get('ERS_Truck_Capabilities__c') or '').lower()
                driver_capabilities[dr_id] = {c.strip() for c in caps.split(';') if c.strip()}
        # Exclude Tow Drop-Off
        sas = [s for s in sas_raw if 'drop' not in ((s.get('WorkType') or {}).get('Name', '') or '').lower()]

        if not sas:
            return {'calls': [], 'summary': {'evaluated': 0, 'closest_picked': 0, 'total_extra_miles': 0}}

        # SA → assigned driver (from current AR record)
        sa_to_driver = {}
        sa_to_driver_name = {}
        for ar in assigned_raw:
            sa_id = ar.get('ServiceAppointmentId')
            dr_id = ar.get('ServiceResourceId')
            if sa_id and dr_id:
                sa_to_driver[sa_id] = dr_id
                sa_to_driver_name[sa_id] = (ar.get('ServiceResource') or {}).get('Name', '?')

        # Manual dispatch detection via shared utility (same logic as simulator.py)
        _assign_events = parse_assign_events(data['sa_hist'])
        _dispatch_class = classify_dispatch(_assign_events)

        sa_to_dispatcher = {
            sa_id: {
                'name': _dispatch_class.get(sa_id, {}).get('dispatcher_name', 'System'),
                'is_auto': not _dispatch_class.get(sa_id, {}).get('is_manual', False),
            }
            for sa_id in sa_to_driver
        }

        # Driver name lookup
        driver_names = {}
        for d in all_drivers:
            driver_names[d['Id']] = d.get('Name', '?')

        # Historical GPS for all on-shift fleet drivers across today
        # Using ServiceResourceHistory so all driver comparisons are point-in-time
        # (not stale current position from LastKnownLatitude)
        fleet_ids = [d['Id'] for d in all_drivers if d['Id'] in logged_in_ids]
        now_utc = datetime.now(ZoneInfo('UTC'))
        hist_end = (now_utc.strftime('%Y-%m-%dT%H:%M:%SZ'))
        lat_hist, lon_hist = fetch_gps_history(fleet_ids, cutoff_utc, hist_end)

        # Territory → on-shift fleet driver IDs (GPS availability checked per-SA)
        territory_drivers = defaultdict(set)
        for m in members_raw:
            tid = m.get('ServiceTerritoryId')
            dr_id = m.get('ServiceResourceId')
            if tid and dr_id and dr_id in logged_in_ids:
                territory_drivers[tid].add(dr_id)

        # Build driver → list of active SA ids (to check busy status at dispatch time)
        # A driver is "busy" for a given SA if they had another active SA at that time
        driver_active_sas = defaultdict(list)  # driver_id → [(sa_id, created_dt)]
        for ar in data['active_assignments']:
            dr_id = ar.get('ServiceResourceId')
            sa_id = ar.get('ServiceAppointmentId')
            sa_obj = ar.get('ServiceAppointment') or {}
            created = _parse_dt(sa_obj.get('CreatedDate'))
            if dr_id and sa_id and created:
                driver_active_sas[dr_id].append((sa_id, created))

        def _driver_busy_for_sa(dr_id, sa_id, sa_created_dt):
            """Check if driver had another active SA before this SA was created."""
            for other_sa_id, other_created in driver_active_sas.get(dr_id, []):
                if other_sa_id != sa_id and other_created < sa_created_dt:
                    return True
            return False

        # Build per-SA detail
        results = []
        total_evaluated = 0
        total_closest_picked = 0
        total_extra = 0.0

        for s in sas:
            sa_lat, sa_lon = s.get('Latitude'), s.get('Longitude')
            if not sa_lat or not sa_lon:
                continue
            sa_lat, sa_lon = float(sa_lat), float(sa_lon)

            assigned_dr = sa_to_driver.get(s['Id'])
            if not assigned_dr:
                continue

            tid = s.get('ServiceTerritoryId')
            wt_name = (s.get('WorkType') or {}).get('Name', '')
            call_tier = _classify_worktype(wt_name)
            sa_created_dt = _parse_dt(s.get('CreatedDate'))

            # Dispatch-time geolocation for the assigned driver (most accurate snapshot)
            disp_lat = s.get('ERS_Dispatched_Geolocation__Latitude__s')
            disp_lon = s.get('ERS_Dispatched_Geolocation__Longitude__s')

            # Build driver list using point-in-time GPS for every driver
            # Drivers with no GPS history at SA creation time are excluded (not on Track)
            drivers_list = []
            for dr_id in territory_drivers.get(tid, set()):
                caps = driver_capabilities.get(dr_id, set())
                dr_tier = _driver_tier(';'.join(caps)) if caps else 'light'
                if not _can_cover(dr_tier, call_tier) and dr_id != assigned_dr:
                    continue

                # Use ERS_Dispatched_Geolocation for the assigned driver when available;
                # use point-in-time GPS history for all others (and as fallback)
                if dr_id == assigned_dr and disp_lat and disp_lon:
                    dlat, dlon = float(disp_lat), float(disp_lon)
                else:
                    dlat, dlon = gps_at_time(dr_id, sa_created_dt, lat_hist, lon_hist)

                if dlat is None or dlon is None:
                    continue  # driver not on Track at SA creation time — exclude

                dist = _haversine(sa_lat, sa_lon, dlat, dlon)
                busy = _driver_busy_for_sa(dr_id, s['Id'], sa_created_dt) if sa_created_dt else False
                drivers_list.append({
                    'name': driver_names.get(dr_id, '?'),
                    'distance_mi': dist,
                    'picked': dr_id == assigned_dr,
                    'busy': busy,
                    'lat': dlat,
                    'lon': dlon,
                })

            # Drop SAs where assigned driver had no GPS (can't evaluate fairness)
            if not any(d['picked'] for d in drivers_list):
                continue

            drivers_list.sort(key=lambda x: x['distance_mi'])

            # Separate available (idle) vs all for metrics
            available_drivers = [d for d in drivers_list if not d['busy']]
            total_on_shift = len(drivers_list)
            total_available = len(available_drivers)

            # Use only AVAILABLE drivers for closest-driver calculation
            if available_drivers:
                closest_dist = available_drivers[0]['distance_mi']
                closest_name = available_drivers[0]['name']
            else:
                # All busy — fall back to all drivers
                closest_dist = drivers_list[0]['distance_mi']
                closest_name = drivers_list[0]['name']

            total_evaluated += 1

            picked_driver = next((d for d in drivers_list if d['picked']), None)
            picked_dist = picked_driver['distance_mi'] if picked_driver else closest_dist
            is_closest = (closest_name == (picked_driver or {}).get('name'))
            extra_mi = round(picked_dist - closest_dist, 1) if not is_closest and picked_dist > closest_dist else 0

            if is_closest:
                total_closest_picked += 1
            else:
                total_extra += extra_mi

            disp_info = sa_to_dispatcher.get(s['Id'], {})

            results.append({
                'number': s.get('AppointmentNumber', ''),
                'work_type': wt_name,
                'status': s.get('Status', ''),
                'territory': (s.get('ServiceTerritory') or {}).get('Name', ''),
                'created_time': _fmt_et(s.get('CreatedDate')),
                '_created_iso': s.get('CreatedDate', ''),
                'assigned_driver': sa_to_driver_name.get(s['Id'], '?'),
                'assigned_distance': picked_dist,
                'closest_driver': closest_name,
                'closest_distance': closest_dist,
                'extra_miles': extra_mi,
                'is_closest': is_closest,
                'dispatcher': disp_info.get('name', '?'),
                'is_auto': disp_info.get('is_auto', True),
                'on_shift': total_on_shift,
                'available': total_available,
                'candidates': drivers_list,
            })

        # Sort: most recent SA first
        results.sort(key=lambda x: x.get('_created_iso', ''), reverse=True)

        return {
            'calls': results[:200],
            'summary': {
                'evaluated': total_evaluated,
                'closest_picked': total_closest_picked,
                'total_extra_miles': round(total_extra, 1),
            },
        }

    return cache.cached_query('drilldown_closest_driver', _fetch, ttl=300)


# ── 30-Day Rolling Trends ──────────────────────────────────────────────────

@router.get("/api/insights/trends")
def api_trends():
    """30-day rolling trend data for the Dispatch Insights Trends tab.

    Returns daily KPI series (volume, completion, auto%, SLA%, ATA by channel,
    reassignments, satisfaction) plus top/bottom garages by performance.
    Shows last 30 COMPLETE days (up to yesterday, excludes today's partial data).
    Pre-computed nightly at 12:05 AM ET, persisted to disk.
    """
    import re
    from sf_client import sf_parallel

    _sf_id_pat = re.compile(r'^[a-zA-Z0-9]{15}$|^[a-zA-Z0-9]{18}$')

    def _fetch():
        # ── Parallel SOQL queries ────────────────────────────────────
        # Use LAST_N_DAYS:31 + CreatedDate < TODAY to get 30 complete days
        # (excludes today's incomplete data)

        def _get_sas():
            return sf_query_all("""
                SELECT Id, CreatedDate, Status, ActualStartTime, ERS_PTA__c,
                       ERS_Dispatch_Method__c, ServiceTerritoryId,
                       ServiceTerritory.Name, WorkType.Name,
                       CreatedBy.Profile.Name
                FROM ServiceAppointment
                WHERE CreatedDate = LAST_N_DAYS:31
                  AND CreatedDate < TODAY
                  AND ServiceTerritoryId != null
                  AND RecordType.Name = 'ERS Service Appointment'
            """)

        def _get_status_history():
            return sf_query_all("""
                SELECT ServiceAppointmentId, CreatedDate, NewValue
                FROM ServiceAppointmentHistory
                WHERE CreatedDate = LAST_N_DAYS:31
                  AND CreatedDate < TODAY
                  AND Field = 'Status'
                  AND ServiceAppointment.RecordType.Name = 'ERS Service Appointment'
            """)

        def _get_reassignment_history():
            return sf_query_all("""
                SELECT ServiceAppointmentId, CreatedDate, NewValue
                FROM ServiceAppointmentHistory
                WHERE CreatedDate = LAST_N_DAYS:31
                  AND CreatedDate < TODAY
                  AND Field = 'ERS_Assigned_Resource__c'
                  AND ServiceAppointment.RecordType.Name = 'ERS Service Appointment'
            """)

        def _get_satisfaction():
            return sf_query_all("""
                SELECT DAY_ONLY(CreatedDate) d,
                       ERS_Overall_Satisfaction__c sat,
                       COUNT(Id) cnt
                FROM Survey_Result__c
                WHERE CreatedDate = LAST_N_DAYS:31
                  AND CreatedDate < TODAY
                  AND ERS_Overall_Satisfaction__c != null
                GROUP BY DAY_ONLY(CreatedDate), ERS_Overall_Satisfaction__c
            """)

        def _get_reassign_with_creator():
            """SAHistory rows for manual dispatch detection.
            Manual = count > 2 (reassigned at least once) AND a human (Membership User) was involved.
            Each assignment creates 2 rows (display name + SF ID), so count > 2 = reassigned.
            """
            return sf_query_all("""
                SELECT ServiceAppointmentId, CreatedBy.Name, CreatedBy.Profile.Name
                FROM ServiceAppointmentHistory
                WHERE CreatedDate = LAST_N_DAYS:31
                  AND CreatedDate < TODAY
                  AND Field = 'ERS_Assigned_Resource__c'
                  AND ServiceAppointment.RecordType.Name = 'ERS Service Appointment'
            """)

        # Run sequentially to avoid starving SF API for user requests
        # (this runs in a background thread for nightly refresh)
        import time as _time
        data = {}
        for name, fn in [('sas', _get_sas), ('status_hist', _get_status_history),
                          ('reassign_hist', _get_reassignment_history),
                          ('satisfaction', _get_satisfaction), ('assign_hist', _get_reassign_with_creator)]:
            data[name] = fn()
            _time.sleep(0.5)

        all_sas = data['sas']
        status_hist = data['status_hist']
        reassign_hist = data['reassign_hist']
        satisfaction_rows = data['satisfaction']
        assign_hist_rows = data['assign_hist']

        import logging
        _log = logging.getLogger('trends')
        _log.info(f"Trends fetch: sas={len(all_sas)}, status_hist={len(status_hist)}, reassign={len(reassign_hist)}, satisfaction={len(satisfaction_rows)}, assign_hist={len(assign_hist_rows)}")

        # ── Pre-process history data ─────────────────────────────────

        # 1. Manual dispatch: SA was reassigned (SAHistory count > 2) AND a human was involved.
        #    Each assignment creates 2 SAHistory rows (display name + SF ID).
        #    count > 2 means at least one reassignment happened.
        #    Single assignment (by anyone) = auto.
        _hist_count: dict = {}
        _hist_human: set = set()
        for r in assign_hist_rows:
            sa_id = r.get('ServiceAppointmentId')
            if not sa_id:
                continue
            _hist_count[sa_id] = _hist_count.get(sa_id, 0) + 1
            profile = ((r.get('CreatedBy') or {}).get('Profile') or {}).get('Name', '')
            if profile == 'Membership User':
                _hist_human.add(sa_id)
        human_touched_ids = {sa_id for sa_id, cnt in _hist_count.items()
                             if cnt > 2 and sa_id in _hist_human}

        # 2. Towbook on-location times: {sa_id: earliest 'On Location' datetime}
        towbook_on_location = {}
        for r in status_hist:
            sa_id = r.get('ServiceAppointmentId')
            if not sa_id:
                continue
            if r.get('NewValue') == 'On Location':
                ts = _parse_dt(r.get('CreatedDate'))
                if ts:
                    if sa_id not in towbook_on_location or ts < towbook_on_location[sa_id]:
                        towbook_on_location[sa_id] = ts

        # 3. Reassignments per day — only count 2nd+ assignments (actual reassignments)
        #    First assignment is normal dispatch; only subsequent ones are reassignments.
        reassign_by_day = defaultdict(int)
        _sa_assign_seq = defaultdict(int)  # count name-only rows per SA
        for r in reassign_hist:
            new_val = (r.get('NewValue') or '').strip()
            if not new_val or _sf_id_pat.match(new_val):
                continue  # Skip SF ID duplicate rows
            sa_id = r.get('ServiceAppointmentId')
            _sa_assign_seq[sa_id] += 1
            if _sa_assign_seq[sa_id] > 1:  # 2nd+ = actual reassignment
                date_str = (r.get('CreatedDate') or '')[:10]
                if date_str:
                    reassign_by_day[date_str] += 1

        # 4. Satisfaction by day: {date_str: {'total_satisfied': int, 'total_surveys': int}}
        sat_by_day = defaultdict(lambda: {'totally_satisfied': 0, 'total': 0})
        for r in satisfaction_rows:
            date_str = r.get('d', '')
            sat_val = (r.get('sat') or '').strip()
            cnt = r.get('cnt', 0) or 0
            if date_str and sat_val:
                sat_by_day[date_str]['total'] += cnt
                if sat_val.lower() == 'totally satisfied':
                    sat_by_day[date_str]['totally_satisfied'] += cnt

        # ── Build daily buckets from SAs ─────────────────────────────

        daily = defaultdict(lambda: {
            'volume': 0, 'completed': 0,
            'fleet_ata_sum': 0.0, 'fleet_ata_count': 0,
            'towbook_ata_sum': 0.0, 'towbook_ata_count': 0,
            'sla_hits': 0, 'sla_eligible': 0,
            'auto_count': 0, 'total_for_auto': 0,
            'sa_ids': [],
        })

        # SA lookup for Towbook ATA calculation
        sa_lookup = {}
        for sa in all_sas:
            sa_lookup[sa.get('Id')] = sa

        for sa in all_sas:
            wt = (sa.get('WorkType') or {}).get('Name', '') or ''
            if 'drop' in wt.lower():
                continue  # Exclude Tow Drop-Off

            date_str = (sa.get('CreatedDate') or '')[:10]
            if not date_str:
                continue

            d = daily[date_str]
            d['volume'] += 1
            d['sa_ids'].append(sa.get('Id'))

            if sa.get('Status') == 'Completed':
                d['completed'] += 1

            dispatch_method = sa.get('ERS_Dispatch_Method__c') or ''

            # Auto dispatch: all SAs count. Manual = human reassigned after initial assignment.
            # Who created the SA doesn't matter.
            d['total_for_auto'] += 1
            if sa.get('Id') not in human_touched_ids:
                d['auto_count'] += 1

            # Fleet ATA + SLA (only completed Fleet SAs with ActualStartTime)
            if sa.get('Status') == 'Completed' and dispatch_method == 'Field Services':
                created = _parse_dt(sa.get('CreatedDate'))
                actual = _parse_dt(sa.get('ActualStartTime'))
                if created and actual:
                    diff_min = (actual - created).total_seconds() / 60
                    if 0 < diff_min < 480:
                        d['fleet_ata_sum'] += diff_min
                        d['fleet_ata_count'] += 1
                        d['sla_eligible'] += 1
                        if diff_min <= 45:
                            d['sla_hits'] += 1

            # Towbook ATA (use SAHistory 'On Location', NOT ActualStartTime)
            if sa.get('Status') == 'Completed' and dispatch_method == 'Towbook':
                sa_id = sa.get('Id')
                on_loc = towbook_on_location.get(sa_id)
                if on_loc:
                    created = _parse_dt(sa.get('CreatedDate'))
                    if created:
                        diff_min = (on_loc - created).total_seconds() / 60
                        if 0 < diff_min < 480:
                            d['towbook_ata_sum'] += diff_min
                            d['towbook_ata_count'] += 1

        # ── Assemble daily output ────────────────────────────────────

        days_output = []
        for date_str in sorted(daily.keys()):
            d = daily[date_str]
            vol = d['volume']
            comp = d['completed']

            fleet_ata = round(d['fleet_ata_sum'] / d['fleet_ata_count']) if d['fleet_ata_count'] else None
            towbook_ata = round(d['towbook_ata_sum'] / d['towbook_ata_count']) if d['towbook_ata_count'] else None
            sla_pct = round(100 * d['sla_hits'] / d['sla_eligible']) if d['sla_eligible'] else None
            auto_pct = round(100 * d['auto_count'] / d['total_for_auto']) if d['total_for_auto'] else None

            sat_info = sat_by_day.get(date_str, {})
            sat_pct = (
                round(100 * sat_info['totally_satisfied'] / sat_info['total'])
                if sat_info.get('total') else None
            )

            days_output.append({
                'date': date_str,
                'volume': vol,
                'completed': comp,
                'completion_pct': round(100 * comp / vol) if vol else 0,
                'auto_pct': auto_pct,
                'sla_pct': sla_pct,
                'fleet_ata': fleet_ata,
                'towbook_ata': towbook_ata,
                'reassignments': reassign_by_day.get(date_str, 0),
                'closest_pct': None,  # TODO: too expensive for 30-day span; shown on today-only card
                'satisfaction_pct': sat_pct,
            })

        # ── Top / Bottom garages (30-day aggregate) ──────────────────

        garage = defaultdict(lambda: {
            'volume': 0, 'completed': 0,
            'ata_sum': 0.0, 'ata_count': 0,
        })

        for sa in all_sas:
            wt = (sa.get('WorkType') or {}).get('Name', '') or ''
            if 'drop' in wt.lower():
                continue
            tname = (sa.get('ServiceTerritory') or {}).get('Name', '')
            if not tname:
                continue
            # Skip non-garage territories: offices, grid zones, fleet aggregates, spot
            tl = tname.lower()
            if any(x in tl for x in ('office', 'spot', 'fleet', 'region')):
                continue
            # Grid zones = 2-letter + 3-digit pattern (e.g., WR006, CM001)
            if len(tname) <= 6 and tname[:2].isalpha() and tname[2:].isdigit():
                continue
            g = garage[tname]
            g['volume'] += 1
            if sa.get('Status') == 'Completed':
                g['completed'] += 1

            dispatch_method = sa.get('ERS_Dispatch_Method__c') or ''
            if sa.get('Status') == 'Completed':
                # Fleet: use ActualStartTime
                if dispatch_method == 'Field Services':
                    created = _parse_dt(sa.get('CreatedDate'))
                    actual = _parse_dt(sa.get('ActualStartTime'))
                    if created and actual:
                        diff = (actual - created).total_seconds() / 60
                        if 0 < diff < 480:
                            g['ata_sum'] += diff
                            g['ata_count'] += 1
                # Towbook: use SAHistory 'On Location'
                elif dispatch_method == 'Towbook':
                    sa_id = sa.get('Id')
                    on_loc = towbook_on_location.get(sa_id)
                    if on_loc:
                        created = _parse_dt(sa.get('CreatedDate'))
                        if created:
                            diff = (on_loc - created).total_seconds() / 60
                            if 0 < diff < 480:
                                g['ata_sum'] += diff
                                g['ata_count'] += 1

        # Minimum 20 calls to qualify (avoid noise from low-volume garages)
        qualified = []
        for name, g in garage.items():
            if g['volume'] < 20:
                continue
            avg_ata = round(g['ata_sum'] / g['ata_count']) if g['ata_count'] else 999
            comp_pct = round(100 * g['completed'] / g['volume']) if g['volume'] else 0
            qualified.append({
                'name': name,
                'ata': avg_ata,
                'completion_pct': comp_pct,
                'volume': g['volume'],
            })

        # Top 3 = lowest ATA among garages with >85% completion
        top_pool = [g for g in qualified if g['completion_pct'] > 85 and g['ata'] < 999]
        top_pool.sort(key=lambda x: x['ata'])
        top_garages = top_pool[:3]

        # Bottom 3 = highest ATA with actual ATA data (exclude 999 = no data)
        bottom_pool = [g for g in qualified if g['ata'] < 999]
        bottom_pool.sort(key=lambda x: (-x['ata'], x['completion_pct']))
        bottom_garages = bottom_pool[:3]

        return {
            'days': days_output,
            'top_garages': top_garages,
            'bottom_garages': bottom_garages,
        }

    # Serve from cache ONLY — never block a request with heavy SF queries.
    # The nightly thread (12:05 AM ET) or manual trigger populates the cache.
    cached = cache.get('insights_trends_30d')
    if cached:
        return cached
    # Try disk cache (survives restarts)
    disk = cache.disk_get('insights_trends_30d', ttl=86400)
    if disk:
        cache.put('insights_trends_30d', disk, 86400)
        return disk
    # No cache at all — trigger background generation, return empty immediately
    import threading, logging as _lg
    def _bg():
        _log = _lg.getLogger('trends')
        for attempt in range(3):
            try:
                result = _fetch()
                cache.put('insights_trends_30d', result, 86400)
                cache.disk_put('insights_trends_30d', result, 86400)
                _log.info("Trends 30d background generation complete.")
                return
            except Exception as e:
                _log.warning(f"Trends 30d fetch failed (attempt {attempt+1}/3): {e}")
                if attempt < 2:
                    import time as _t; _t.sleep(300)  # retry in 5 min
        _log.error("Trends 30d fetch failed after 3 attempts — cache not updated.")
    threading.Thread(target=_bg, daemon=True).start()
    return {'days': [], 'top_garages': [], 'bottom_garages': [], 'loading': True}


def _fetch_trends_range(start_utc: str, end_utc: str) -> list[dict]:
    """Fetch trend daily rows for a specific UTC datetime range [start_utc, end_utc).
    Skips garage ranking (too expensive for small ranges — caller keeps existing rankings).
    start_utc / end_utc format: '2026-03-17T00:00:00Z'
    """
    import re as _re

    def _get_sas():
        return sf_query_all(f"""
            SELECT Id, CreatedDate, Status, ActualStartTime, ERS_PTA__c,
                   ERS_Dispatch_Method__c, WorkType.Name,
                   CreatedBy.Profile.Name
            FROM ServiceAppointment
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND ServiceTerritoryId != null
        """)

    def _get_hist():
        return sf_query_all(f"""
            SELECT ServiceAppointmentId, CreatedDate, NewValue
            FROM ServiceAppointmentHistory
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND Field = 'Status'
              AND ServiceAppointment.RecordType.Name = 'ERS Service Appointment'
        """)

    def _get_reassign():
        return sf_query_all(f"""
            SELECT ServiceAppointmentId, CreatedDate, NewValue
            FROM ServiceAppointmentHistory
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND Field = 'ERS_Assigned_Resource__c'
              AND ServiceAppointment.RecordType.Name = 'ERS Service Appointment'
        """)

    def _get_sat():
        return sf_query_all(f"""
            SELECT DAY_ONLY(CreatedDate) d, ERS_Overall_Satisfaction__c sat, COUNT(Id) cnt
            FROM Survey_Result__c
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND ERS_Overall_Satisfaction__c != null
            GROUP BY DAY_ONLY(CreatedDate), ERS_Overall_Satisfaction__c
        """)

    def _get_assign_hist():
        """SAHistory rows for manual dispatch detection.
        Manual = count > 2 (reassigned at least once) AND a human (Membership User) was involved.
        Each assignment creates 2 rows (display name + SF ID), so count > 2 = reassigned.
        """
        return sf_query_all(f"""
            SELECT ServiceAppointmentId, CreatedBy.Name, CreatedBy.Profile.Name
            FROM ServiceAppointmentHistory
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND Field = 'ERS_Assigned_Resource__c'
              AND ServiceAppointment.RecordType.Name = 'ERS Service Appointment'
              AND ServiceAppointment.ServiceTerritoryId != null
        """)

    # Run sequentially (not sf_parallel) to avoid starving the SF API rate limiter
    # when this runs in a background thread alongside user requests
    import time as _time
    data = {}
    for name, fn in [('sas', _get_sas), ('hist', _get_hist), ('reassign', _get_reassign),
                      ('sat', _get_sat), ('assign_hist', _get_assign_hist)]:
        data[name] = fn()
        _time.sleep(0.5)  # brief pause between queries to yield API bandwidth

    # Manual dispatch: SA was reassigned (SAHistory count > 2) AND a human was involved.
    # Each assignment creates 2 SAHistory rows (display name + SF ID).
    # count > 2 means at least one reassignment happened.
    _hist_count: dict = {}
    _hist_human: set = set()
    for r in data['assign_hist']:
        sa_id = r.get('ServiceAppointmentId')
        if not sa_id:
            continue
        _hist_count[sa_id] = _hist_count.get(sa_id, 0) + 1
        profile = ((r.get('CreatedBy') or {}).get('Profile') or {}).get('Name', '')
        if profile == 'Membership User':
            _hist_human.add(sa_id)
    human_touched = {sa_id for sa_id, cnt in _hist_count.items()
                     if cnt > 2 and sa_id in _hist_human}

    # Towbook on-location times
    on_location: dict = {}
    for r in data['hist']:
        sa_id = r.get('ServiceAppointmentId')
        if not sa_id:
            continue
        if r.get('NewValue') == 'On Location':
            ts = _parse_dt(r.get('CreatedDate'))
            if ts and (sa_id not in on_location or ts < on_location[sa_id]):
                on_location[sa_id] = ts

    # Reassignments per day — only 2nd+ assignments (actual reassignments, not first dispatch)
    _sf_id_pat = _re.compile(r'^[a-zA-Z0-9]{15}$|^[a-zA-Z0-9]{18}$')
    reassign_by_day: dict = defaultdict(int)
    _sa_assign_seq: dict = defaultdict(int)
    for r in data['reassign']:
        new_val = (r.get('NewValue') or '').strip()
        if not new_val or _sf_id_pat.match(new_val):
            continue
        sa_id = r.get('ServiceAppointmentId')
        _sa_assign_seq[sa_id] += 1
        if _sa_assign_seq[sa_id] > 1:
            date_str = (r.get('CreatedDate') or '')[:10]
            if date_str:
                reassign_by_day[date_str] += 1

    # Satisfaction by day
    sat_by_day: dict = defaultdict(lambda: {'totally_satisfied': 0, 'total': 0})
    for r in data['sat']:
        date_str = r.get('d', '')
        sat_val = (r.get('sat') or '').strip()
        cnt = r.get('cnt', 0) or 0
        if date_str and sat_val:
            sat_by_day[date_str]['total'] += cnt
            if sat_val.lower() == 'totally satisfied':
                sat_by_day[date_str]['totally_satisfied'] += cnt

    # Build daily buckets
    daily: dict = defaultdict(lambda: {
        'volume': 0, 'completed': 0,
        'fleet_ata_sum': 0.0, 'fleet_ata_count': 0,
        'towbook_ata_sum': 0.0, 'towbook_ata_count': 0,
        'sla_hits': 0, 'sla_eligible': 0,
        'auto_count': 0, 'total_for_auto': 0,
    })

    for sa in data['sas']:
        wt = (sa.get('WorkType') or {}).get('Name', '') or ''
        if 'drop' in wt.lower():
            continue
        date_str = (sa.get('CreatedDate') or '')[:10]
        if not date_str:
            continue
        d = daily[date_str]
        d['volume'] += 1
        if sa.get('Status') == 'Completed':
            d['completed'] += 1
        # Auto dispatch: all SAs count. Manual = human reassigned after initial assignment.
        d['total_for_auto'] += 1
        if sa.get('Id') not in human_touched:
            d['auto_count'] += 1
        dm = sa.get('ERS_Dispatch_Method__c') or ''
        if sa.get('Status') == 'Completed':
            if dm == 'Field Services':
                created = _parse_dt(sa.get('CreatedDate'))
                actual = _parse_dt(sa.get('ActualStartTime'))
                if created and actual:
                    diff = (actual - created).total_seconds() / 60
                    if 0 < diff < 480:
                        d['fleet_ata_sum'] += diff
                        d['fleet_ata_count'] += 1
                        d['sla_eligible'] += 1
                        if diff <= 45:
                            d['sla_hits'] += 1
            elif dm == 'Towbook':
                on_loc = on_location.get(sa.get('Id'))
                if on_loc:
                    created = _parse_dt(sa.get('CreatedDate'))
                    if created:
                        diff = (on_loc - created).total_seconds() / 60
                        if 0 < diff < 480:
                            d['towbook_ata_sum'] += diff
                            d['towbook_ata_count'] += 1

    # Assemble output rows
    rows = []
    for date_str in sorted(daily.keys()):
        d = daily[date_str]
        vol = d['volume']
        comp = d['completed']
        sat_info = sat_by_day.get(date_str, {})
        rows.append({
            'date': date_str,
            'volume': vol,
            'completed': comp,
            'completion_pct': round(100 * comp / vol) if vol else 0,
            'auto_pct': round(100 * d['auto_count'] / d['total_for_auto']) if d['total_for_auto'] else None,
            'sla_pct': round(100 * d['sla_hits'] / d['sla_eligible']) if d['sla_eligible'] else None,
            'fleet_ata': round(d['fleet_ata_sum'] / d['fleet_ata_count']) if d['fleet_ata_count'] else None,
            'towbook_ata': round(d['towbook_ata_sum'] / d['towbook_ata_count']) if d['towbook_ata_count'] else None,
            'reassignments': reassign_by_day.get(date_str, 0),
            'closest_pct': None,
            'satisfaction_pct': round(100 * sat_info['totally_satisfied'] / sat_info['total']) if sat_info.get('total') else None,
        })
    return rows


@router.get("/api/insights/trends/refresh")
def api_trends_force_refresh():
    """Force-refresh 30-day trends. Smart: fetches only missing days (≤7) or triggers full refresh."""
    import threading, logging as _lg
    from datetime import date as _date, timedelta as _td, timezone as _tz

    log = _lg.getLogger('trends_refresh')
    today_utc = _date.today()  # UTC date
    yesterday_utc = today_utc - _td(days=1)

    # Expected last 30 complete days (UTC dates, as stored in cache)
    expected = {(yesterday_utc - _td(days=i)).isoformat() for i in range(30)}

    current = cache.disk_get_stale('insights_trends_30d')
    cached_dates = {d['date'] for d in (current or {}).get('days', [])} if current else set()
    missing = sorted(expected - cached_dates)

    if not missing:
        return {'status': 'up_to_date', 'missing_days': 0, 'cached_through': yesterday_utc.isoformat()}

    log.info(f"Trends force-refresh: {len(missing)} missing days ({missing[0]} … {missing[-1]})")

    if len(missing) <= 7 and current:
        # Incremental path: only fetch the missing date range
        start_utc = f"{missing[0]}T00:00:00Z"
        end_utc = f"{((_date.fromisoformat(missing[-1])) + _td(days=1)).isoformat()}T00:00:00Z"
        try:
            new_rows = _fetch_trends_range(start_utc, end_utc)
            # Merge: keep existing days not in new_rows, add new_rows
            new_dates = {r['date'] for r in new_rows}
            merged_days = [d for d in current['days'] if d['date'] not in new_dates] + new_rows
            merged_days.sort(key=lambda x: x['date'])
            # Keep last 30 days only
            merged_days = merged_days[-30:]
            merged = {**current, 'days': merged_days}
            cache.put('insights_trends_30d', merged, 86400)
            cache.disk_put('insights_trends_30d', merged, 86400)
            log.info(f"Incremental trends merge complete: added {len(new_rows)} days.")
            return {'status': 'updated', 'missing_days': len(missing), 'new_days': len(new_rows), 'data': merged}
        except Exception as e:
            log.warning(f"Incremental fetch failed, falling back to full refresh: {e}")
            # Fall through to full refresh

    # Full refresh path
    cache.disk_invalidate('insights_trends_30d')
    cache.invalidate('insights_trends_30d')

    def _bg():
        _log = _lg.getLogger('trends_refresh')
        for attempt in range(3):
            try:
                result = api_trends()  # re-uses existing _fetch via bg thread logic
                if result and not result.get('loading'):
                    _log.info("Full refresh bg complete.")
                    return
                # _fetch is still running in its own daemon thread; give it time
                import time as _t
                for _ in range(90):
                    _t.sleep(10)
                    done = cache.get('insights_trends_30d')
                    if done and not done.get('loading'):
                        _log.info("Full refresh complete (polled).")
                        return
                raise TimeoutError("Full refresh timed out after 15min")
            except Exception as e:
                _log.warning(f"Full refresh attempt {attempt+1}/3 failed: {e}")
                if attempt < 2:
                    import time as _t2; _t2.sleep(60)

    # Trigger the first api_trends call to start the bg thread
    api_trends()
    threading.Thread(target=_bg, daemon=True).start()
    return {'status': 'full_refresh_triggered', 'missing_days': len(missing), 'loading': True}


def _generate_month_trends(month: str):
    """Heavy lifting for monthly trends — runs in background thread."""
    import re, calendar, logging
    from datetime import date as _date, timedelta as _td

    _log = logging.getLogger('trends_month')
    year, mon = int(month[:4]), int(month[5:7])

    first_day = _date(year, mon, 1)
    last_day_num = calendar.monthrange(year, mon)[1]
    end_day = _date(year, mon, last_day_num) + _td(days=1)

    today = _date.today()
    is_current = (year == today.year and mon == today.month)
    if is_current:
        end_day = today  # exclude today

    cache_key = f'insights_trends_month_{month}'
    ttl = 14400 if is_current else 31536000  # 4h current, 1 year past (data never changes)

    start_utc = f"{first_day.isoformat()}T00:00:00Z"
    end_utc = f"{end_day.isoformat()}T00:00:00Z"

    days_output = _fetch_trends_range(start_utc, end_utc)

    # Garage rankings — parallel SF queries
    def _get_garage_sas():
        return sf_query_all(f"""
            SELECT Id, CreatedDate, Status, ActualStartTime,
                   ERS_Dispatch_Method__c, ServiceTerritoryId,
                   ServiceTerritory.Name, WorkType.Name
            FROM ServiceAppointment
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND ServiceTerritoryId != null
              AND RecordType.Name = 'ERS Service Appointment'
        """)

    def _get_garage_hist():
        return sf_query_all(f"""
            SELECT ServiceAppointmentId, CreatedDate, NewValue
            FROM ServiceAppointmentHistory
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND Field = 'Status'
              AND ServiceAppointment.RecordType.Name = 'ERS Service Appointment'
        """)

    garage_data = sf_parallel(sas=_get_garage_sas, hist=_get_garage_hist)
    all_sas = garage_data['sas']

    towbook_on_location = {}
    for r in garage_data['hist']:
        sa_id = r.get('ServiceAppointmentId')
        if sa_id and r.get('NewValue') == 'On Location':
            ts = _parse_dt(r.get('CreatedDate'))
            if ts and (sa_id not in towbook_on_location or ts < towbook_on_location[sa_id]):
                towbook_on_location[sa_id] = ts

    garage = defaultdict(lambda: {'volume': 0, 'completed': 0, 'ata_sum': 0.0, 'ata_count': 0})
    for sa in all_sas:
        wt = (sa.get('WorkType') or {}).get('Name', '') or ''
        if 'drop' in wt.lower():
            continue
        tname = (sa.get('ServiceTerritory') or {}).get('Name', '')
        if not tname:
            continue
        tl = tname.lower()
        if any(x in tl for x in ('office', 'spot', 'fleet', 'region')):
            continue
        if len(tname) <= 6 and tname[:2].isalpha() and tname[2:].isdigit():
            continue
        g = garage[tname]
        g['volume'] += 1
        if sa.get('Status') == 'Completed':
            g['completed'] += 1
        dm = sa.get('ERS_Dispatch_Method__c') or ''
        if sa.get('Status') == 'Completed':
            if dm == 'Field Services':
                created = _parse_dt(sa.get('CreatedDate'))
                actual = _parse_dt(sa.get('ActualStartTime'))
                if created and actual:
                    diff = (actual - created).total_seconds() / 60
                    if 0 < diff < 480:
                        g['ata_sum'] += diff; g['ata_count'] += 1
            elif dm == 'Towbook':
                on_loc = towbook_on_location.get(sa.get('Id'))
                if on_loc:
                    created = _parse_dt(sa.get('CreatedDate'))
                    if created:
                        diff = (on_loc - created).total_seconds() / 60
                        if 0 < diff < 480:
                            g['ata_sum'] += diff; g['ata_count'] += 1

    qualified = []
    for name, g in garage.items():
        if g['volume'] < 20:
            continue
        avg_ata = round(g['ata_sum'] / g['ata_count']) if g['ata_count'] else 999
        comp_pct = round(100 * g['completed'] / g['volume']) if g['volume'] else 0
        qualified.append({'name': name, 'ata': avg_ata, 'completion_pct': comp_pct, 'volume': g['volume']})

    top_pool = sorted([g for g in qualified if g['completion_pct'] > 85 and g['ata'] < 999], key=lambda x: x['ata'])
    bottom_pool = sorted([g for g in qualified if g['ata'] < 999], key=lambda x: (-x['ata'], x['completion_pct']))

    result = {
        'month': month,
        'days': days_output,
        'top_garages': top_pool[:3],
        'bottom_garages': bottom_pool[:3],
    }

    cache.put(cache_key, result, ttl)
    cache.disk_put(cache_key, result, ttl)
    _log.info(f"Month trends for {month}: {len(days_output)} days, {len(all_sas)} SAs")
    return result


# Track which months are currently being generated (filesystem lock for cross-worker safety)

@router.get("/api/insights/trends/month")
def api_trends_month(month: str = Query(..., description="YYYY-MM format, e.g. 2026-02")):
    """Trend data for a specific calendar month.

    Non-blocking: serves from cache only. If no cache exists, triggers
    background generation and returns {loading: true} immediately.
    """
    import re, calendar, logging
    from datetime import date as _date

    if not re.match(r'^\d{4}-\d{2}$', month):
        raise HTTPException(400, "month must be YYYY-MM format (e.g. 2026-02)")
    try:
        year, mon = int(month[:4]), int(month[5:7])
        if mon < 1 or mon > 12:
            raise ValueError
    except ValueError:
        raise HTTPException(400, "Invalid month")

    today = _date.today()
    if _date(year, mon, 1) > today:
        raise HTTPException(400, "Cannot fetch future months")

    is_current = (year == today.year and mon == today.month)
    cache_key = f'insights_trends_month_{month}'
    ttl = 43200 if is_current else 604800  # 12h current, 7d past

    # 1. Memory cache
    cached = cache.get(cache_key)
    if cached:
        return cached
    # 2. Disk cache
    disk = cache.disk_get(cache_key, ttl=ttl)
    if disk:
        cache.put(cache_key, disk, ttl)
        return disk

    # 3. No cache — trigger background generation, return immediately
    import threading
    _log = logging.getLogger('trends_month')

    gen_lock = f'gen_month_{month}'
    if cache.fs_lock_acquire(gen_lock, max_age=1800):
        def _bg():
            try:
                _generate_month_trends(month)
            except Exception as e:
                _log.warning(f"Month trends generation failed for {month}: {e}")
            finally:
                cache.fs_lock_release(gen_lock)
        threading.Thread(target=_bg, daemon=True).start()
        _log.info(f"Month trends background generation started for {month}")

    return {'month': month, 'days': [], 'top_garages': [], 'bottom_garages': [], 'loading': True}


@router.get("/api/insights/trends/month/refresh")
def api_trends_month_refresh(month: str = Query(..., description="YYYY-MM format")):
    """Force-refresh a specific month's trends — clears cache and regenerates."""
    import re, threading, logging
    from datetime import date as _date

    if not re.match(r'^\d{4}-\d{2}$', month):
        raise HTTPException(400, "month must be YYYY-MM format")
    year, mon = int(month[:4]), int(month[5:7])
    today = _date.today()
    if _date(year, mon, 1) > today:
        raise HTTPException(400, "Cannot refresh future months")

    _log = logging.getLogger('trends_month')
    cache_key = f'insights_trends_month_{month}'

    # Clear memory + disk cache for this month
    cache.invalidate(cache_key)
    cache.disk_invalidate(cache_key)
    # Also clear the 30-day rolling trends since they overlap with current month
    cache.invalidate('insights_trends_30d')
    cache.disk_invalidate('insights_trends_30d')
    _log.info(f"Month {month} cache cleared, starting regeneration")

    # Trigger background regeneration
    gen_lock = f'gen_month_{month}'
    if cache.fs_lock_acquire(gen_lock, max_age=1800):
        def _bg():
            try:
                _generate_month_trends(month)
            except Exception as e:
                _log.warning(f"Month trends refresh failed for {month}: {e}")
            finally:
                cache.fs_lock_release(gen_lock)
        threading.Thread(target=_bg, daemon=True).start()

    return {'status': 'refreshing', 'month': month}


## NOTE: /api/garages/{territory_id}/decomposition is in routers/garages.py
## NOTE: /api/territory/{territory_id}/forecast is kept here (not in garages.py)

@router.get("/api/territory/{territory_id}/forecast")
def api_forecast(territory_id: str, weeks_history: int = Query(8, ge=2, le=16)):
    """16-day demand forecast using DOW patterns + weather."""
    territory_id = sanitize_soql(territory_id)
    return get_forecast(territory_id, weeks_history)


# ── Satisfaction Score Analysis ──────────────────────────────────────────────

def _satisfaction_insights(sat_pct, avg_ata, pta_miss_pct, rt_sat_pct, volume):
    """Rule-based insights for satisfaction data. Returns list of insight dicts."""
    insights = []
    if volume is not None and volume < 5:
        insights.append({'type': 'caution', 'text': 'Small sample size — interpret with caution', 'icon': '⚠'})
        return insights  # Don't generate other insights on tiny samples
    if sat_pct is not None and sat_pct < 60:
        insights.append({'type': 'critical', 'text': f'Critical: {sat_pct}% satisfaction — investigate individual comments', 'icon': '🔴'})
    if avg_ata is not None and sat_pct is not None and avg_ata > 45 and sat_pct < 80:
        insights.append({'type': 'warning', 'text': f'High ATA ({avg_ata}m) likely driving low satisfaction ({sat_pct}%)', 'icon': '🕐'})
    if pta_miss_pct is not None and pta_miss_pct > 30 and sat_pct is not None and sat_pct < 80:
        insights.append({'type': 'warning', 'text': f'Broken promises damaging satisfaction — {pta_miss_pct}% PTA violations', 'icon': '💔'})
    if rt_sat_pct is not None and sat_pct is not None and rt_sat_pct < sat_pct - 10:
        insights.append({'type': 'info', 'text': f'Wait time is the pain point — response time satisfaction ({rt_sat_pct}%) trails overall ({sat_pct}%)', 'icon': '⏱'})
    elif rt_sat_pct is not None and sat_pct is not None and rt_sat_pct >= sat_pct and sat_pct < 75:
        insights.append({'type': 'info', 'text': 'Response time OK but overall low — issue may be technician quality or communication', 'icon': '🔧'})
    if sat_pct is not None and sat_pct >= 90:
        insights.append({'type': 'success', 'text': f'Excellent performance — {sat_pct}% totally satisfied', 'icon': '🌟'})
    return insights


def _build_executive_insight(month, sat_pct, rt_pct, tech_pct, total_surveys,
                              avg_ata, pta_miss_pct, daily_trend, all_garages):
    """VP monthly briefing — 5-8 lines, bottom line up front.

    Not a data dump. A concise analysis: what happened, why, who's responsible, what to do.
    """
    import calendar
    from datetime import date as _date

    year, mon = int(month[:4]), int(month[5:7])
    month_name = calendar.month_name[mon]
    target = 82

    if sat_pct is None or total_surveys == 0:
        return {'headline': f'No satisfaction data for {month_name} {year}.', 'body': [], 'actions': []}

    # Classify garages
    bad_garages = sorted(
        [g for g in all_garages if g['totally_satisfied_pct'] is not None
         and g['totally_satisfied_pct'] < target and g['surveys'] >= 5],
        key=lambda g: g['totally_satisfied_pct']
    )
    good_count = sum(1 for g in all_garages
                     if g['totally_satisfied_pct'] is not None and g['totally_satisfied_pct'] >= target)
    total_garages = len([g for g in all_garages if g['surveys'] >= 2])

    # Diagnose: wait time vs driver quality
    if rt_pct is not None and tech_pct is not None:
        if rt_pct < target and tech_pct >= target:
            diagnosis = 'wait_time'
        elif tech_pct < target and rt_pct >= target:
            diagnosis = 'technician'
        elif rt_pct < target and tech_pct < target:
            diagnosis = 'both'
        else:
            diagnosis = 'on_target'
    else:
        diagnosis = None

    # Month-over-month
    prev_month_data = _get_previous_month_sat(month)
    prev_pct = prev_month_data.get('totally_satisfied_pct') if prev_month_data else None
    prev_name = prev_month_data.get('month_name', 'last month') if prev_month_data else None

    # Worst days
    bad_days = sorted(
        [d for d in daily_trend
         if d.get('totally_satisfied_pct') is not None and d['totally_satisfied_pct'] < target
         and d.get('surveys', 0) >= 10],
        key=lambda d: d['totally_satisfied_pct']
    )

    # ── Build the briefing (5-8 lines) ──
    body = []

    # Line 1: Headline with trend context
    if sat_pct >= target:
        trend_ctx = ''
        if prev_pct is not None:
            delta = sat_pct - prev_pct
            if delta > 0:
                trend_ctx = f', up {delta} from {prev_name}'
            elif delta < 0:
                trend_ctx = f', down {abs(delta)} from {prev_name}'
        risk = ''
        if diagnosis == 'wait_time':
            risk = ' Response time is the risk.'
        elif diagnosis == 'technician':
            risk = ' Driver quality is the risk.'
        body.append(f"On target at {sat_pct}%{trend_ctx}.{risk}")
    else:
        gap = target - sat_pct
        body.append(f"{gap} {'point' if gap == 1 else 'points'} below target at {sat_pct}%.")

    # Line 2: Root cause — one sentence
    if diagnosis == 'wait_time':
        body.append(f"Technician quality is strong ({tech_pct}%), but members are unhappy with wait times — Response Time satisfaction is only {rt_pct}%.")
    elif diagnosis == 'technician':
        body.append(f"Wait times are acceptable ({rt_pct}% RT satisfaction), but driver quality is the problem — Technician satisfaction is {tech_pct}%.")
    elif diagnosis == 'both':
        body.append(f"Both wait times ({rt_pct}% RT) and driver quality ({tech_pct}% Tech) are below target.")

    # Line 3: ATA + PTA — the operational evidence
    ata_pta_parts = []
    if avg_ata and avg_ata > 45:
        ata_pta_parts.append(f"average response was {avg_ata} minutes")
    if pta_miss_pct and pta_miss_pct > 15:
        ata_pta_parts.append(f"{pta_miss_pct}% of calls missed their promised arrival time")
    if ata_pta_parts:
        body.append(f"{' and '.join(ata_pta_parts).capitalize()} — these broken promises drive the most dissatisfied surveys.")

    # Line 4: Who's responsible — specific facilities
    if bad_garages:
        bottom = bad_garages[:3]
        garage_details = []
        for g in bottom:
            name = g['name'].split(' - ')[-1].strip() if ' - ' in g['name'] else g['name']
            garage_details.append(f"{name} ({g['totally_satisfied_pct']}%)")
        body.append(f"Three facilities account for most of the damage: {', '.join(garage_details)}. The remaining {good_count} garages are performing above target.")

    # Line 5: Worst days (brief)
    if bad_days:
        day_strs = []
        for d in bad_days[:3]:
            day_num = d['date'].split('-')[-1].lstrip('0')
            day_strs.append(f"{month_name} {day_num} ({d['totally_satisfied_pct']}%)")
        body.append(f"Worst days: {', '.join(day_strs)} — click any day above to see what went wrong.")

    # ── Actions (1-2 lines) ──
    actions = []
    if bad_garages:
        names = ', '.join(g['name'].split(' - ')[-1].strip() for g in bad_garages[:3])
        if diagnosis == 'wait_time':
            actions.append(f"Capacity review at {names} — are they taking more calls than they can handle?")
        elif diagnosis == 'technician':
            actions.append(f"Driver quality review at {names} — check customer comments for patterns.")
        else:
            actions.append(f"Review operations at {names}.")

    if pta_miss_pct and pta_miss_pct > 25:
        actions.append(f"PTA promises need recalibration — {pta_miss_pct}% miss rate means we're over-promising on arrival times.")

    if not actions:
        actions.append("On track. Monitor response times to maintain margin above 82%.")

    return {
        'headline': f"{month_name} {year}: {sat_pct}% — {'on target' if sat_pct >= target else f'{target - sat_pct} below target'}.",
        'body': body,
        'actions': actions,
        'diagnosis': diagnosis,
    }


def _build_zone_satisfaction(all_garages, matrix):
    """Map each zone to its primary garage's satisfaction score.

    Returns: {zone_territory_id: {garage_name, sat_pct, surveys, avg_ata, tier}}
    The frontend uses zone_territory_id to match against GeoJSON feature territory_id.
    """
    # Build garage satisfaction lookup: garage_name → data
    garage_by_name = {g['name']: g for g in all_garages}

    # Build garage ID → name from the priority matrix + garage list
    # We need to resolve spotted_territory_id → garage name
    # The garage list has (id, name) — fetch it from ops garages cache
    garage_id_to_name = {}
    try:
        from ops import get_ops_garages
        ops_garages = get_ops_garages()
        for g in ops_garages:
            garage_id_to_name[g['id']] = g['name']
    except Exception:
        pass

    # For each zone (parent_territory_id), find rank-1 garage
    zone_sat = {}
    rank_lookup = matrix.get('rank_lookup', {})
    by_parent = {}
    for (parent_id, spotted_id), rank in rank_lookup.items():
        if rank == 1:  # Primary garage
            by_parent[parent_id] = spotted_id

    for zone_id, garage_id in by_parent.items():
        garage_name = garage_id_to_name.get(garage_id, '')
        g = garage_by_name.get(garage_name)
        if g:
            zone_sat[zone_id] = {
                'garage_name': garage_name,
                'sat_pct': g.get('totally_satisfied_pct'),
                'surveys': g.get('surveys', 0),
                'avg_ata': g.get('avg_ata'),
                'tier': g.get('tier'),
            }
        else:
            zone_sat[zone_id] = {
                'garage_name': garage_name,
                'sat_pct': None,
                'surveys': 0,
                'avg_ata': None,
                'tier': None,
            }

    return zone_sat


def _get_previous_month_sat(current_month):
    """Get previous month's satisfaction % from disk cache (no extra SF query)."""
    import calendar
    year, mon = int(current_month[:4]), int(current_month[5:7])
    if mon == 1:
        prev_year, prev_mon = year - 1, 12
    else:
        prev_year, prev_mon = year, mon - 1
    prev_key = f'satisfaction_overview_{prev_year}-{prev_mon:02d}'
    prev_data = cache.disk_get_stale(prev_key)
    if prev_data and prev_data.get('summary', {}).get('totally_satisfied_pct') is not None:
        return {
            'totally_satisfied_pct': prev_data['summary']['totally_satisfied_pct'],
            'month_name': calendar.month_name[prev_mon],
        }
    return None


def _is_real_garage(name):
    """Filter out non-garage territories (offices, grid zones, fleet aggregates, spot)."""
    if not name:
        return False
    nl = name.lower()
    if any(x in nl for x in ('office', 'spot', 'fleet', 'region')):
        return False
    if len(name) <= 6 and name[:2].isalpha() and name[2:].isdigit():
        return False
    return True


# Satisfaction generation uses filesystem locks (cross-worker safe)


@router.get("/api/insights/satisfaction/overview")
def api_satisfaction_overview(month: str = Query(..., description="YYYY-MM format, e.g. 2026-03")):
    """Satisfaction overview: summary cards, daily trend, and garage ranking for a month.

    Non-blocking: serves from cache. If no cache, triggers background generation.
    """
    import re, calendar, logging, threading
    from datetime import date as _date

    if not re.match(r'^\d{4}-\d{2}$', month):
        raise HTTPException(400, "month must be YYYY-MM format (e.g. 2026-03)")
    year, mon = int(month[:4]), int(month[5:7])
    today = _date.today()
    if _date(year, mon, 1) > today:
        raise HTTPException(400, "Cannot fetch future months")

    is_current = (year == today.year and mon == today.month)
    cache_key = f'satisfaction_overview_{month}'
    ttl = 43200 if is_current else 31536000  # 12h current, 1yr past

    cached = cache.get(cache_key)
    if cached:
        return cached
    disk = cache.disk_get(cache_key, ttl=ttl)
    if disk:
        cache.put(cache_key, disk, ttl)
        return disk

    _log = logging.getLogger('satisfaction')
    gen_lock = f'gen_sat_overview_{month}'
    if cache.fs_lock_acquire(gen_lock, max_age=1800):
        def _bg():
            try:
                result = _generate_satisfaction_overview(month)
                cache.put(cache_key, result, ttl)
                cache.disk_put(cache_key, result, ttl)
                _log.info(f"Satisfaction overview for {month} generated.")
            except Exception as e:
                import traceback
                _log.warning(f"Satisfaction overview generation failed for {month}: {e}\n{traceback.format_exc()}")
            finally:
                cache.fs_lock_release(gen_lock)
        threading.Thread(target=_bg, daemon=True).start()
        _log.info(f"Satisfaction overview background generation started for {month}")

    return {'month': month, 'summary': {}, 'daily_trend': [], 'all_garages': [], 'loading': True}


@router.get("/api/insights/satisfaction/refresh")
def api_satisfaction_refresh(month: str = Query(..., description="YYYY-MM format")):
    """Force-refresh satisfaction overview for a month. Clears cache and regenerates."""
    import re, threading, logging
    from datetime import date as _date

    if not re.match(r'^\d{4}-\d{2}$', month):
        raise HTTPException(400, "month must be YYYY-MM format")

    _log = logging.getLogger('satisfaction')
    cache_key = f'satisfaction_overview_{month}'

    # Clear both L1 and L2 cache
    cache.invalidate(cache_key)
    cache.disk_invalidate(cache_key)

    # Trigger background regeneration
    gen_lock = f'gen_sat_overview_{month}'
    if cache.fs_lock_acquire(gen_lock, max_age=1800):
        year, mon = int(month[:4]), int(month[5:7])
        today = _date.today()
        is_current = (year == today.year and mon == today.month)
        ttl = 43200 if is_current else 31536000

        def _bg():
            try:
                result = _generate_satisfaction_overview(month)
                cache.put(cache_key, result, ttl)
                cache.disk_put(cache_key, result, ttl)
                _log.info(f"Satisfaction refresh complete for {month}")
            except Exception as e:
                _log.warning(f"Satisfaction refresh failed for {month}: {e}")
            finally:
                cache.fs_lock_release(gen_lock)
        threading.Thread(target=_bg, daemon=True).start()

    return {'status': 'refreshing', 'month': month}


def _generate_satisfaction_overview(month: str):
    """Heavy lifting for satisfaction overview — runs in background thread."""
    import calendar, time as _time
    from datetime import date as _date, timedelta as _td

    year, mon = int(month[:4]), int(month[5:7])
    first_day = _date(year, mon, 1)
    last_day_num = calendar.monthrange(year, mon)[1]
    end_day = _date(year, mon, last_day_num) + _td(days=1)

    today = _date.today()
    is_current = (year == today.year and mon == today.month)
    if is_current:
        end_day = today

    start_utc = f"{first_day.isoformat()}T00:00:00Z"
    end_utc = f"{end_day.isoformat()}T00:00:00Z"

    # ── Attribution: by CALL DATE (ERS_Work_Order__r.CreatedDate) not survey date ──
    # A survey submitted March 7 about a Feb 28 call is attributed to Feb 28.
    # This aligns satisfaction with same-day ATA/PTA for accurate correlation.

    # ── Batch 1: All 4 survey queries in parallel (same object, different GROUP BYs) ──
    batch1 = sf_parallel(
        daily_sat=lambda: sf_query_all(f"""
            SELECT DAY_ONLY(ERS_Work_Order__r.CreatedDate) d,
                   ERS_Overall_Satisfaction__c sat,
                   COUNT(Id) cnt
            FROM Survey_Result__c
            WHERE ERS_Work_Order__r.CreatedDate >= {start_utc} AND ERS_Work_Order__r.CreatedDate < {end_utc}
              AND ERS_Overall_Satisfaction__c != null
            GROUP BY DAY_ONLY(ERS_Work_Order__r.CreatedDate), ERS_Overall_Satisfaction__c
        """),
        garage_overall=lambda: sf_query_all(f"""
            SELECT ERS_Work_Order__r.ServiceTerritory.Name tname,
                   ERS_Overall_Satisfaction__c sat,
                   COUNT(Id) cnt
            FROM Survey_Result__c
            WHERE ERS_Work_Order__r.CreatedDate >= {start_utc} AND ERS_Work_Order__r.CreatedDate < {end_utc}
              AND ERS_Overall_Satisfaction__c != null
              AND ERS_Work_Order__r.ServiceTerritoryId != null
            GROUP BY ERS_Work_Order__r.ServiceTerritory.Name, ERS_Overall_Satisfaction__c
            ORDER BY ERS_Work_Order__r.ServiceTerritory.Name
        """),
        garage_rt=lambda: sf_query_all(f"""
            SELECT ERS_Work_Order__r.ServiceTerritory.Name tname,
                   ERS_Response_Time_Satisfaction__c sat,
                   COUNT(Id) cnt
            FROM Survey_Result__c
            WHERE ERS_Work_Order__r.CreatedDate >= {start_utc} AND ERS_Work_Order__r.CreatedDate < {end_utc}
              AND ERS_Response_Time_Satisfaction__c != null
              AND ERS_Work_Order__r.ServiceTerritoryId != null
            GROUP BY ERS_Work_Order__r.ServiceTerritory.Name, ERS_Response_Time_Satisfaction__c
            ORDER BY ERS_Work_Order__r.ServiceTerritory.Name
        """),
        garage_tech=lambda: sf_query_all(f"""
            SELECT ERS_Work_Order__r.ServiceTerritory.Name tname,
                   ERS_Technician_Satisfaction__c sat,
                   COUNT(Id) cnt
            FROM Survey_Result__c
            WHERE ERS_Work_Order__r.CreatedDate >= {start_utc} AND ERS_Work_Order__r.CreatedDate < {end_utc}
              AND ERS_Technician_Satisfaction__c != null
              AND ERS_Work_Order__r.ServiceTerritoryId != null
            GROUP BY ERS_Work_Order__r.ServiceTerritory.Name, ERS_Technician_Satisfaction__c
            ORDER BY ERS_Work_Order__r.ServiceTerritory.Name
        """),
    )
    daily_sat = batch1['daily_sat']
    garage_overall = batch1['garage_overall']
    garage_rt = batch1['garage_rt']
    garage_tech = batch1['garage_tech']

    # ── Batch 2: SA volume + completed SAs in parallel ──
    batch2 = sf_parallel(
        sa_volume=lambda: sf_query_all(f"""
            SELECT DAY_ONLY(CreatedDate) d, COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND ServiceTerritoryId != null
              AND RecordType.Name = 'ERS Service Appointment'
            GROUP BY DAY_ONLY(CreatedDate)
        """),
        completed=lambda: sf_query_all(f"""
            SELECT Id, CreatedDate, Status, ActualStartTime,
                   ERS_Dispatch_Method__c, ERS_PTA__c, WorkType.Name
            FROM ServiceAppointment
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND ServiceTerritoryId != null
              AND RecordType.Name = 'ERS Service Appointment'
              AND Status = 'Completed'
        """),
    )
    sa_vol_by_day = {}
    for r in batch2['sa_volume']:
        sa_vol_by_day[r.get('d', '')] = r.get('cnt', 0) or 0
    completed_sas = batch2['completed']

    # Query 7: Towbook on-location times for accurate ATA
    towbook_ids = [sa.get('Id') for sa in completed_sas
                   if (sa.get('ERS_Dispatch_Method__c') or '') == 'Towbook']
    towbook_on_location = {}
    for i in range(0, len(towbook_ids), 200):
        chunk = towbook_ids[i:i+200]
        id_list = "','".join(chunk)
        hist_rows = sf_query_all(f"""
            SELECT ServiceAppointmentId, CreatedDate, NewValue
            FROM ServiceAppointmentHistory
            WHERE ServiceAppointmentId IN ('{id_list}')
              AND Field = 'Status'
        """)
        for r in hist_rows:
            if r.get('NewValue') != 'On Location':
                continue
            sa_id = r.get('ServiceAppointmentId')
            ts = _parse_dt(r.get('CreatedDate'))
            if ts and (sa_id not in towbook_on_location or ts < towbook_on_location[sa_id]):
                towbook_on_location[sa_id] = ts
        if i + 200 < len(towbook_ids):
            _time.sleep(0.3)

    # ── Build daily ATA/PTA buckets ──
    day_ata = defaultdict(lambda: {'ata_sum': 0.0, 'ata_count': 0, 'pta_miss': 0, 'pta_eligible': 0})
    for sa in completed_sas:
        wt = (sa.get('WorkType') or {}).get('Name', '') or ''
        if 'drop' in wt.lower():
            continue
        date_str = (sa.get('CreatedDate') or '')[:10]
        if not date_str:
            continue
        dm = sa.get('ERS_Dispatch_Method__c') or ''
        bucket = day_ata[date_str]

        # ATA calculation (same logic as garage-level)
        if dm == 'Field Services':
            created = _parse_dt(sa.get('CreatedDate'))
            actual = _parse_dt(sa.get('ActualStartTime'))
            if created and actual:
                diff = (actual - created).total_seconds() / 60
                if 0 < diff < 480:
                    bucket['ata_sum'] += diff
                    bucket['ata_count'] += 1
        elif dm == 'Towbook':
            on_loc = towbook_on_location.get(sa.get('Id'))
            if on_loc:
                created = _parse_dt(sa.get('CreatedDate'))
                if created:
                    diff = (on_loc - created).total_seconds() / 60
                    if 0 < diff < 480:
                        bucket['ata_sum'] += diff
                        bucket['ata_count'] += 1

        # PTA miss: ERS_PTA__c is minutes promised, compare with actual ATA minutes
        pta_raw = sa.get('ERS_PTA__c')
        if pta_raw is not None:
            pta_min = float(pta_raw)
            if 0 < pta_min < 999:
                created = _parse_dt(sa.get('CreatedDate'))
                if dm == 'Towbook':
                    arrived = towbook_on_location.get(sa.get('Id'))
                else:
                    arrived = _parse_dt(sa.get('ActualStartTime'))
                if created and arrived:
                    ata_min = (arrived - created).total_seconds() / 60
                    if 0 < ata_min < 480:
                        bucket['pta_eligible'] += 1
                        if ata_min > pta_min:
                            bucket['pta_miss'] += 1

    # ── Assemble daily trend ──
    day_buckets = defaultdict(lambda: {'totally_satisfied': 0, 'satisfied': 0, 'total': 0})
    for r in daily_sat:
        d = r.get('d', '')
        sat_val = (r.get('sat') or '').strip().lower()
        cnt = r.get('cnt', 0) or 0
        if d and sat_val:
            day_buckets[d]['total'] += cnt
            if sat_val == 'totally satisfied':
                day_buckets[d]['totally_satisfied'] += cnt
            elif sat_val == 'satisfied':
                day_buckets[d]['satisfied'] += cnt

    # Days within last 7 days have incomplete survey data (surveys still arriving)
    incomplete_cutoff = (today - _td(days=7)).isoformat()

    all_trend_dates = sorted(set(list(day_buckets.keys()) + list(day_ata.keys())))
    daily_trend = []
    for d in all_trend_dates:
        b = day_buckets.get(d, {'totally_satisfied': 0, 'satisfied': 0, 'total': 0})
        a = day_ata.get(d, {'ata_sum': 0, 'ata_count': 0, 'pta_miss': 0, 'pta_eligible': 0})
        ts_pct = round(100 * b['totally_satisfied'] / b['total']) if b['total'] else None
        avg_ata = round(a['ata_sum'] / a['ata_count']) if a['ata_count'] else None
        pta_miss_pct = round(100 * a['pta_miss'] / a['pta_eligible']) if a['pta_eligible'] else None
        daily_trend.append({
            'date': d,
            'totally_satisfied_pct': ts_pct,
            'surveys': b['total'],
            'sa_volume': sa_vol_by_day.get(d, 0),
            'avg_ata': avg_ata,
            'pta_miss_pct': pta_miss_pct,
            'incomplete': d > incomplete_cutoff,  # surveys still arriving for recent days
        })

    # ── Assemble garage data ──
    def _agg_satisfaction(rows, field_name='sat'):
        """Aggregate satisfaction rows into {garage: {totally_satisfied, total, pct}}."""
        garages = defaultdict(lambda: {'totally_satisfied': 0, 'total': 0})
        for r in rows:
            tname = (r.get('tname') or
                     ((r.get('ERS_Work_Order__r') or {}).get('ServiceTerritory') or {}).get('Name', ''))
            if not _is_real_garage(tname):
                continue
            sat_val = (r.get(field_name) or '').strip().lower()
            cnt = r.get('cnt', 0) or 0
            if tname and sat_val:
                garages[tname]['total'] += cnt
                if sat_val == 'totally satisfied':
                    garages[tname]['totally_satisfied'] += cnt
        return garages

    overall = _agg_satisfaction(garage_overall)
    rt = _agg_satisfaction(garage_rt)
    tech = _agg_satisfaction(garage_tech)

    all_garages = []
    for name, o in overall.items():
        if o['total'] < 1:
            continue
        ts_pct = round(100 * o['totally_satisfied'] / o['total'])
        rt_info = rt.get(name, {'totally_satisfied': 0, 'total': 0})
        rt_pct = round(100 * rt_info['totally_satisfied'] / rt_info['total']) if rt_info['total'] else None
        tech_info = tech.get(name, {'totally_satisfied': 0, 'total': 0})
        tech_pct = round(100 * tech_info['totally_satisfied'] / tech_info['total']) if tech_info['total'] else None

        insights = _satisfaction_insights(ts_pct, None, None, rt_pct, o['total'])

        all_garages.append({
            'name': name,
            'totally_satisfied_pct': ts_pct,
            'response_time_pct': rt_pct,
            'technician_pct': tech_pct,
            'surveys': o['total'],
            'insights': insights,
        })

    all_garages.sort(key=lambda g: g['totally_satisfied_pct'], reverse=True)

    # Summary cards
    total_surveys = sum(b['total'] for b in day_buckets.values())
    total_ts = sum(b['totally_satisfied'] for b in day_buckets.values())

    # Overall response time & technician (flatten from garage-level)
    rt_total = sum(g['total'] for g in rt.values())
    rt_ts = sum(g['totally_satisfied'] for g in rt.values())
    tech_total = sum(g['total'] for g in tech.values())
    tech_ts = sum(g['totally_satisfied'] for g in tech.values())

    sat_pct = round(100 * total_ts / total_surveys) if total_surveys else None
    rt_pct = round(100 * rt_ts / rt_total) if rt_total else None
    tech_pct = round(100 * tech_ts / tech_total) if tech_total else None

    summary = {
        'totally_satisfied_pct': sat_pct,
        'response_time_pct': rt_pct,
        'technician_pct': tech_pct,
        'total_surveys': total_surveys,
    }

    # ── ATA / PTA aggregates for the executive insight ──
    total_ata_sum = sum(day_ata[d]['ata_sum'] for d in day_ata)
    total_ata_count = sum(day_ata[d]['ata_count'] for d in day_ata)
    total_pta_miss = sum(day_ata[d]['pta_miss'] for d in day_ata)
    total_pta_eligible = sum(day_ata[d]['pta_eligible'] for d in day_ata)
    avg_ata = round(total_ata_sum / total_ata_count) if total_ata_count else None
    pta_miss_pct = round(100 * total_pta_miss / total_pta_eligible) if total_pta_eligible else None

    # ── Executive Insight — auto-generated VP summary ──
    executive_insight = _build_executive_insight(
        month=month, sat_pct=sat_pct, rt_pct=rt_pct, tech_pct=tech_pct,
        total_surveys=total_surveys, avg_ata=avg_ata, pta_miss_pct=pta_miss_pct,
        daily_trend=daily_trend, all_garages=all_garages,
    )

    # ── Zone → garage satisfaction map (for geographic map visualization) ──
    from ops import _get_priority_matrix
    zone_sat = _build_zone_satisfaction(all_garages, _get_priority_matrix())

    return {
        'month': month,
        'summary': summary,
        'daily_trend': daily_trend,
        'all_garages': all_garages,
        'executive_insight': executive_insight,
        'zone_satisfaction': zone_sat,
    }


@router.get("/api/insights/satisfaction/garage/{name}")
def api_satisfaction_garage(name: str, month: str = Query(..., description="YYYY-MM")):
    """Garage-level satisfaction detail: daily satisfaction + ATA correlation + insights."""
    import re, calendar, logging, threading
    from datetime import date as _date, timedelta as _td

    name = sanitize_soql(name)
    if not re.match(r'^\d{4}-\d{2}$', month):
        raise HTTPException(400, "month must be YYYY-MM format")
    year, mon = int(month[:4]), int(month[5:7])
    today = _date.today()
    if _date(year, mon, 1) > today:
        raise HTTPException(400, "Cannot fetch future months")

    is_current = (year == today.year and mon == today.month)
    cache_key = f'satisfaction_garage_{name}_{month}'
    ttl = 7200 if is_current else 31536000  # 2h current, 1yr past

    cached = cache.get(cache_key)
    if cached:
        return cached
    disk = cache.disk_get(cache_key, ttl=ttl)
    if disk:
        cache.put(cache_key, disk, ttl)
        return disk

    _log = logging.getLogger('satisfaction')
    gen_lock = f'gen_sat_garage_{name}_{month}'
    if cache.fs_lock_acquire(gen_lock, max_age=1800):
        def _bg():
            try:
                result = _generate_satisfaction_garage(name, month)
                cache.put(cache_key, result, ttl)
                cache.disk_put(cache_key, result, ttl)
                _log.info(f"Satisfaction garage detail for {name} {month} generated.")
            except Exception as e:
                _log.warning(f"Satisfaction garage generation failed for {name} {month}: {e}")
            finally:
                cache.fs_lock_release(gen_lock)
        threading.Thread(target=_bg, daemon=True).start()

    return {'garage': name, 'month': month, 'summary': {}, 'daily': [], 'insights': [], 'loading': True}


def _generate_satisfaction_garage(name: str, month: str):
    """Generate garage-level satisfaction detail with ATA correlation."""
    import calendar, time as _time
    from datetime import date as _date, timedelta as _td

    year, mon = int(month[:4]), int(month[5:7])
    first_day = _date(year, mon, 1)
    last_day_num = calendar.monthrange(year, mon)[1]
    end_day = _date(year, mon, last_day_num) + _td(days=1)

    today = _date.today()
    is_current = (year == today.year and mon == today.month)
    if is_current:
        end_day = today

    start_utc = f"{first_day.isoformat()}T00:00:00Z"
    end_utc = f"{end_day.isoformat()}T00:00:00Z"

    safe_name = name  # already sanitized by sanitize_soql at router level

    # Query 1: Daily satisfaction for this garage
    sat_rows = sf_query_all(f"""
        SELECT DAY_ONLY(CreatedDate) d,
               ERS_Overall_Satisfaction__c sat,
               ERS_Response_Time_Satisfaction__c rt_sat,
               COUNT(Id) cnt
        FROM Survey_Result__c
        WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
          AND ERS_Overall_Satisfaction__c != null
          AND ERS_Work_Order__r.ServiceTerritory.Name = '{safe_name}'
        GROUP BY DAY_ONLY(CreatedDate), ERS_Overall_Satisfaction__c, ERS_Response_Time_Satisfaction__c
    """)
    _time.sleep(0.5)

    # Query 2: Completed SAs for ATA calculation (reuse existing pattern)
    sas = sf_query_all(f"""
        SELECT Id, CreatedDate, Status, ActualStartTime,
               ERS_Dispatch_Method__c, ERS_PTA__c, WorkType.Name
        FROM ServiceAppointment
        WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
          AND ServiceTerritory.Name = '{safe_name}'
          AND ServiceTerritoryId != null
          AND Status = 'Completed'
    """)
    _time.sleep(0.5)

    # Query 3: Towbook on-location times
    sa_ids = [sa.get('Id') for sa in sas if (sa.get('ERS_Dispatch_Method__c') or '') == 'Towbook']
    towbook_on_location = {}
    if sa_ids:
        # Batch in chunks of 200
        for i in range(0, len(sa_ids), 200):
            chunk = sa_ids[i:i+200]
            id_list = "','".join(chunk)
            hist_rows = sf_query_all(f"""
                SELECT ServiceAppointmentId, CreatedDate, NewValue
                FROM ServiceAppointmentHistory
                WHERE ServiceAppointmentId IN ('{id_list}')
                  AND Field = 'Status'
            """)
            for r in hist_rows:
                if r.get('NewValue') != 'On Location':
                    continue
                sa_id = r.get('ServiceAppointmentId')
                ts = _parse_dt(r.get('CreatedDate'))
                if ts and (sa_id not in towbook_on_location or ts < towbook_on_location[sa_id]):
                    towbook_on_location[sa_id] = ts
            if i + 200 < len(sa_ids):
                _time.sleep(0.3)

    # ── Build daily satisfaction buckets ──
    day_sat = defaultdict(lambda: {'totally_satisfied': 0, 'total': 0, 'rt_ts': 0, 'rt_total': 0})
    for r in sat_rows:
        d = r.get('d', '')
        sat_val = (r.get('sat') or '').strip().lower()
        rt_val = (r.get('rt_sat') or '').strip().lower()
        cnt = r.get('cnt', 0) or 0
        if d and sat_val:
            day_sat[d]['total'] += cnt
            if sat_val == 'totally satisfied':
                day_sat[d]['totally_satisfied'] += cnt
            if rt_val:
                day_sat[d]['rt_total'] += cnt
                if rt_val == 'totally satisfied':
                    day_sat[d]['rt_ts'] += cnt

    # ── Build daily ATA/PTA buckets ──
    day_ata = defaultdict(lambda: {'ata_sum': 0.0, 'ata_count': 0, 'pta_miss': 0, 'pta_eligible': 0})
    for sa in sas:
        wt = (sa.get('WorkType') or {}).get('Name', '') or ''
        if 'drop' in wt.lower():
            continue
        date_str = (sa.get('CreatedDate') or '')[:10]
        if not date_str:
            continue
        dm = sa.get('ERS_Dispatch_Method__c') or ''
        d = day_ata[date_str]

        # ATA calculation
        if dm == 'Field Services':
            created = _parse_dt(sa.get('CreatedDate'))
            actual = _parse_dt(sa.get('ActualStartTime'))
            if created and actual:
                diff = (actual - created).total_seconds() / 60
                if 0 < diff < 480:
                    d['ata_sum'] += diff
                    d['ata_count'] += 1
        elif dm == 'Towbook':
            on_loc = towbook_on_location.get(sa.get('Id'))
            if on_loc:
                created = _parse_dt(sa.get('CreatedDate'))
                if created:
                    diff = (on_loc - created).total_seconds() / 60
                    if 0 < diff < 480:
                        d['ata_sum'] += diff
                        d['ata_count'] += 1

        # PTA miss: ERS_PTA__c is minutes promised, compare with actual ATA minutes
        pta_raw = sa.get('ERS_PTA__c')
        if pta_raw is not None:
            pta_min = float(pta_raw)
            if 0 < pta_min < 999:
                created = _parse_dt(sa.get('CreatedDate'))
                if dm == 'Towbook':
                    arrived = towbook_on_location.get(sa.get('Id'))
                else:
                    arrived = _parse_dt(sa.get('ActualStartTime'))
                if created and arrived:
                    ata_min = (arrived - created).total_seconds() / 60
                    if 0 < ata_min < 480:
                        d['pta_eligible'] += 1
                        if ata_min > pta_min:
                            d['pta_miss'] += 1

    # ── Merge and generate output ──
    all_dates = sorted(set(list(day_sat.keys()) + list(day_ata.keys())))
    daily = []
    for d in all_dates:
        s = day_sat.get(d, {'totally_satisfied': 0, 'total': 0, 'rt_ts': 0, 'rt_total': 0})
        a = day_ata.get(d, {'ata_sum': 0, 'ata_count': 0, 'pta_miss': 0, 'pta_eligible': 0})

        sat_pct = round(100 * s['totally_satisfied'] / s['total']) if s['total'] else None
        rt_pct = round(100 * s['rt_ts'] / s['rt_total']) if s['rt_total'] else None
        avg_ata = round(a['ata_sum'] / a['ata_count']) if a['ata_count'] else None
        pta_miss_pct = round(100 * a['pta_miss'] / a['pta_eligible']) if a['pta_eligible'] else None

        insights = _satisfaction_insights(sat_pct, avg_ata, pta_miss_pct, rt_pct, s['total'])

        daily.append({
            'date': d,
            'totally_satisfied_pct': sat_pct,
            'response_time_pct': rt_pct,
            'surveys': s['total'],
            'avg_ata': avg_ata,
            'pta_miss_pct': pta_miss_pct,
            'insights': insights,
        })

    # Summary
    total_surveys = sum(day_sat[d]['total'] for d in day_sat)
    total_ts = sum(day_sat[d]['totally_satisfied'] for d in day_sat)
    total_rt = sum(day_sat[d]['rt_total'] for d in day_sat)
    total_rt_ts = sum(day_sat[d]['rt_ts'] for d in day_sat)
    total_ata_sum = sum(day_ata[d]['ata_sum'] for d in day_ata)
    total_ata_count = sum(day_ata[d]['ata_count'] for d in day_ata)

    summary = {
        'totally_satisfied_pct': round(100 * total_ts / total_surveys) if total_surveys else None,
        'response_time_pct': round(100 * total_rt_ts / total_rt) if total_rt else None,
        'avg_ata': round(total_ata_sum / total_ata_count) if total_ata_count else None,
        'total_surveys': total_surveys,
    }

    # Top-level insights for the garage
    garage_insights = _satisfaction_insights(
        summary['totally_satisfied_pct'],
        summary['avg_ata'],
        None,  # PTA miss aggregated would need full recalc
        summary['response_time_pct'],
        total_surveys,
    )

    return {
        'garage': name,
        'month': month,
        'summary': summary,
        'daily': daily,
        'insights': garage_insights,
    }


@router.get("/api/insights/satisfaction/detail/{name}/{date}")
def api_satisfaction_detail(name: str, date: str):
    """Individual survey cards for a garage on a specific date."""
    import re

    name = sanitize_soql(name)
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        raise HTTPException(400, "date must be YYYY-MM-DD format")

    cache_key = f'satisfaction_detail_{name}_{date}'
    cached = cache.get(cache_key)
    if cached:
        return cached
    disk = cache.disk_get(cache_key, ttl=3600)
    if disk:
        cache.put(cache_key, disk, 3600)
        return disk

    # Build date range for the day
    from datetime import date as _date, timedelta as _td
    d = _date.fromisoformat(date)
    start_utc = f"{d.isoformat()}T00:00:00Z"
    end_utc = f"{(d + _td(days=1)).isoformat()}T00:00:00Z"

    safe_name = name  # already sanitized by sanitize_soql at router level

    rows = sf_query_all(f"""
        SELECT Id, CreatedDate,
               ERS_Overall_Satisfaction__c,
               ERS_Response_Time_Satisfaction__c,
               ERS_Technician_Satisfaction__c,
               ERS_Work_Order_Number__c,
               ERS_Work_Order__r.WorkOrderNumber,
               Customer_Comments__c
        FROM Survey_Result__c
        WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
          AND ERS_Work_Order__r.ServiceTerritory.Name = '{safe_name}'
    """)

    surveys = []
    for r in rows:
        surveys.append({
            'id': r.get('Id', ''),
            'created': _fmt_et(r.get('CreatedDate')),
            'overall': r.get('ERS_Overall_Satisfaction__c') or '',
            'response_time': r.get('ERS_Response_Time_Satisfaction__c') or '',
            'technician': r.get('ERS_Technician_Satisfaction__c') or '',
            'wo_number': r.get('ERS_Work_Order_Number__c') or '',
            'comment': r.get('Customer_Comments__c') or '',
        })

    result = {'garage': name, 'date': date, 'surveys': surveys}
    cache.put(cache_key, result, 3600)
    cache.disk_put(cache_key, result, 3600)
    return result


@router.get("/api/insights/satisfaction/day/{date}")
def api_satisfaction_day(date: str):
    """Full day analysis: what drove the satisfaction score on this date.

    Pulls surveys by garage, SA performance (ATA, cancelled, completed),
    and individual problem surveys with comments. Synchronous — data is small
    (single day).
    """
    import re, time as _time
    from datetime import date as _date, timedelta as _td

    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        raise HTTPException(400, "date must be YYYY-MM-DD format")

    cache_key = f'satisfaction_day_{date}'
    cached = cache.get(cache_key)
    if cached:
        return cached
    disk = cache.disk_get(cache_key, ttl=7200)
    if disk:
        cache.put(cache_key, disk, 7200)
        return disk

    d = _date.fromisoformat(date)
    start_utc = f"{d.isoformat()}T00:00:00Z"
    end_utc = f"{(d + _td(days=1)).isoformat()}T00:00:00Z"

    # ── Query 1: All surveys for calls on this day (by call date, not survey date) ──
    surveys = sf_query_all(f"""
        SELECT Id, CreatedDate,
               ERS_Overall_Satisfaction__c,
               ERS_Response_Time_Satisfaction__c,
               ERS_Technician_Satisfaction__c,
               ERS_Work_Order_Number__c,
               ERS_Work_Order__r.Id,
               ERS_Work_Order__r.ServiceTerritory.Name,
               Customer_Comments__c
        FROM Survey_Result__c
        WHERE ERS_Work_Order__r.CreatedDate >= {start_utc} AND ERS_Work_Order__r.CreatedDate < {end_utc}
          AND ERS_Overall_Satisfaction__c != null
    """)
    _time.sleep(0.3)

    # ── Enrich surveys with SA details (Survey → WO → WOLI → SA) ──
    wo_ids = list(set(
        (sv.get('ERS_Work_Order__r') or {}).get('Id', '')
        for sv in surveys if (sv.get('ERS_Work_Order__r') or {}).get('Id')
    ))
    wo_to_sa = {}  # WO Id → SA details
    if wo_ids:
        # Step 1: WO IDs → WOLI IDs (batch 200)
        woli_to_wo = {}
        for i in range(0, len(wo_ids), 200):
            chunk = wo_ids[i:i+200]
            id_list = "','".join(chunk)
            wolis = sf_query_all(f"""
                SELECT Id, WorkOrderId
                FROM WorkOrderLineItem
                WHERE WorkOrderId IN ('{id_list}')
            """)
            for w in wolis:
                woli_to_wo[w['Id']] = w.get('WorkOrderId', '')
        _time.sleep(0.3)

        # Step 2: WOLI IDs → SAs
        woli_ids = list(woli_to_wo.keys())
        if woli_ids:
            for i in range(0, len(woli_ids), 200):
                chunk = woli_ids[i:i+200]
                id_list = "','".join(chunk)
                sa_rows = sf_query_all(f"""
                    SELECT Id, AppointmentNumber, CreatedDate, Status, ParentRecordId,
                           ERS_Assigned_Resource__r.Name,
                           ActualStartTime, ERS_Dispatch_Method__c
                    FROM ServiceAppointment
                    WHERE ParentRecordId IN ('{id_list}')
                      AND RecordType.Name = 'ERS Service Appointment'
                """)
                for sa in sa_rows:
                    woli_id = sa.get('ParentRecordId', '')
                    wo_id = woli_to_wo.get(woli_id, '')
                    if wo_id and wo_id not in wo_to_sa:
                        driver = (sa.get('ERS_Assigned_Resource__r') or {}).get('Name', '')
                        wo_to_sa[wo_id] = {
                            'sa_number': sa.get('AppointmentNumber', ''),
                            'call_date': (sa.get('CreatedDate') or '')[:10],
                            'status': sa.get('Status', ''),
                            'driver': driver,
                        }
            _time.sleep(0.3)

    # ── Query 2: All SAs created this day (performance picture) ──
    sas = sf_query_all(f"""
        SELECT Id, CreatedDate, Status, ActualStartTime,
               ERS_Dispatch_Method__c, ERS_PTA__c,
               ServiceTerritory.Name, WorkType.Name,
               ERS_Cancellation_Reason__c,
               AppointmentNumber
        FROM ServiceAppointment
        WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
          AND ServiceTerritoryId != null
          AND RecordType.Name = 'ERS Service Appointment'
    """)
    _time.sleep(0.3)

    # ── Query 3: Towbook on-location (for correct ATA) ──
    towbook_ids = [sa.get('Id') for sa in sas
                   if sa.get('Status') == 'Completed'
                   and (sa.get('ERS_Dispatch_Method__c') or '') == 'Towbook']
    towbook_on_loc = {}
    if towbook_ids:
        for i in range(0, len(towbook_ids), 200):
            chunk = towbook_ids[i:i+200]
            id_list = "','".join(chunk)
            hist = sf_query_all(f"""
                SELECT ServiceAppointmentId, CreatedDate, NewValue
                FROM ServiceAppointmentHistory
                WHERE ServiceAppointmentId IN ('{id_list}')
                  AND Field = 'Status'
            """)
            for r in hist:
                if r.get('NewValue') != 'On Location':
                    continue
                sa_id = r.get('ServiceAppointmentId')
                ts = _parse_dt(r.get('CreatedDate'))
                if ts and (sa_id not in towbook_on_loc or ts < towbook_on_loc[sa_id]):
                    towbook_on_loc[sa_id] = ts

    # ── Aggregate surveys by garage ──
    garage_surveys = defaultdict(lambda: {
        'totally_satisfied': 0, 'satisfied': 0, 'dissatisfied': 0,
        'totally_dissatisfied': 0, 'neither': 0, 'total': 0,
    })
    total_ts, total_s, total_d, total_td, total_n = 0, 0, 0, 0, 0
    problem_surveys = []  # dissatisfied/totally dissatisfied with details

    for sv in surveys:
        garage = ((sv.get('ERS_Work_Order__r') or {}).get('ServiceTerritory') or {}).get('Name', '') or 'Unknown'
        sat_val = (sv.get('ERS_Overall_Satisfaction__c') or '').strip().lower()
        g = garage_surveys[garage]
        g['total'] += 1

        if sat_val == 'totally satisfied':
            g['totally_satisfied'] += 1
            total_ts += 1
        elif sat_val == 'satisfied':
            g['satisfied'] += 1
            total_s += 1
        elif sat_val == 'dissatisfied':
            g['dissatisfied'] += 1
            total_d += 1
        elif sat_val == 'totally dissatisfied':
            g['totally_dissatisfied'] += 1
            total_td += 1
        else:
            g['neither'] += 1
            total_n += 1

        # Collect problem surveys (dissatisfied or worse, OR has negative comment)
        if sat_val in ('dissatisfied', 'totally dissatisfied', 'neither satisfied nor dissatisfied'):
            wo_id = (sv.get('ERS_Work_Order__r') or {}).get('Id', '')
            sa_info = wo_to_sa.get(wo_id, {})
            problem_surveys.append({
                'garage': garage,
                'overall': sv.get('ERS_Overall_Satisfaction__c') or '',
                'response_time': sv.get('ERS_Response_Time_Satisfaction__c') or '',
                'technician': sv.get('ERS_Technician_Satisfaction__c') or '',
                'wo_number': sv.get('ERS_Work_Order_Number__c') or '',
                'comment': sv.get('Customer_Comments__c') or '',
                'sa_number': sa_info.get('sa_number', ''),
                'call_date': sa_info.get('call_date', ''),
                'driver': sa_info.get('driver', ''),
            })

    # ── Aggregate SAs by garage ──
    garage_ops = defaultdict(lambda: {
        'total': 0, 'completed': 0, 'cancelled': 0,
        'ata_sum': 0.0, 'ata_count': 0,
        'sla_hits': 0, 'sla_eligible': 0,
        'ata_under_30': 0, 'ata_30_45': 0, 'ata_45_60': 0, 'ata_over_60': 0,
    })
    cancel_reasons = defaultdict(int)
    long_ata_sas = []  # SAs with ATA > 60min

    for sa in sas:
        wt = (sa.get('WorkType') or {}).get('Name', '') or ''
        if 'drop' in wt.lower():
            continue
        garage = (sa.get('ServiceTerritory') or {}).get('Name', '') or 'Unknown'
        g = garage_ops[garage]
        g['total'] += 1

        status = sa.get('Status') or ''
        if status == 'Completed':
            g['completed'] += 1
        if 'Cancel' in status:
            g['cancelled'] += 1
            reason = sa.get('ERS_Cancellation_Reason__c') or 'Unknown'
            cancel_reasons[reason] += 1

        # ATA calculation
        if status == 'Completed':
            dm = sa.get('ERS_Dispatch_Method__c') or ''
            created = _parse_dt(sa.get('CreatedDate'))
            arrival = None
            if dm == 'Field Services':
                arrival = _parse_dt(sa.get('ActualStartTime'))
            elif dm == 'Towbook':
                arrival = towbook_on_loc.get(sa.get('Id'))
            else:
                arrival = _parse_dt(sa.get('ActualStartTime'))

            if created and arrival:
                diff = (arrival - created).total_seconds() / 60
                if 0 < diff < 480:
                    g['ata_sum'] += diff
                    g['ata_count'] += 1
                    g['sla_eligible'] += 1
                    if diff <= 45:
                        g['sla_hits'] += 1
                    if diff < 30:
                        g['ata_under_30'] += 1
                    elif diff <= 45:
                        g['ata_30_45'] += 1
                    elif diff <= 60:
                        g['ata_45_60'] += 1
                    else:
                        g['ata_over_60'] += 1
                    if diff > 60:
                        long_ata_sas.append({
                            'number': sa.get('AppointmentNumber', ''),
                            'garage': garage,
                            'ata_min': round(diff),
                            'work_type': wt,
                            'dispatch_method': dm,
                        })

    # ── Build garage breakdown (with lat/lon from ops garages cache) ──
    from ops import get_ops_garages
    garage_locations = {}
    try:
        for g in get_ops_garages():
            if g.get('lat') and g.get('lon'):
                garage_locations[g['name']] = {'lat': g['lat'], 'lon': g['lon']}
    except Exception:
        pass

    all_garage_names = sorted(set(list(garage_surveys.keys()) + list(garage_ops.keys())))
    garage_breakdown = []
    for name in all_garage_names:
        if not _is_real_garage(name):
            continue
        sv = garage_surveys.get(name, {'totally_satisfied': 0, 'total': 0})
        ops = garage_ops.get(name, {'total': 0, 'completed': 0, 'cancelled': 0, 'ata_sum': 0, 'ata_count': 0, 'sla_hits': 0, 'sla_eligible': 0})
        ts_pct = round(100 * sv['totally_satisfied'] / sv['total']) if sv['total'] else None
        avg_ata = round(ops['ata_sum'] / ops['ata_count']) if ops['ata_count'] else None
        sla = round(100 * ops['sla_hits'] / ops['sla_eligible']) if ops['sla_eligible'] else None
        # Tier: Excellent >=90, OK >=82, Below >=60, Critical <60
        tier = ('excellent' if ts_pct is not None and ts_pct >= 90 else
                'ok' if ts_pct is not None and ts_pct >= 82 else
                'below' if ts_pct is not None and ts_pct >= 60 else
                'critical' if ts_pct is not None else None)
        loc = garage_locations.get(name, {})
        garage_breakdown.append({
            'name': name,
            'totally_satisfied_pct': ts_pct,
            'surveys': sv['total'],
            'dissatisfied': sv.get('dissatisfied', 0) + sv.get('totally_dissatisfied', 0),
            'sa_total': ops['total'],
            'sa_completed': ops['completed'],
            'sa_cancelled': ops['cancelled'],
            'avg_ata': avg_ata,
            'sla_pct': sla,
            'tier': tier,
            'lat': loc.get('lat'),
            'lon': loc.get('lon'),
        })
    # Sort: garages with low satisfaction first, then by volume
    garage_breakdown.sort(key=lambda g: (
        g['totally_satisfied_pct'] if g['totally_satisfied_pct'] is not None else 999,
        -(g['surveys'] or 0),
    ))

    # ── Summary stats ──
    total_surveys = sum(1 for _ in surveys)
    total_sas = sum(g['total'] for g in garage_ops.values())
    total_completed = sum(g['completed'] for g in garage_ops.values())
    total_cancelled = sum(g['cancelled'] for g in garage_ops.values())
    total_ata_sum = sum(g['ata_sum'] for g in garage_ops.values())
    total_ata_count = sum(g['ata_count'] for g in garage_ops.values())

    ts_pct = round(100 * total_ts / total_surveys) if total_surveys else None
    avg_ata = round(total_ata_sum / total_ata_count) if total_ata_count else None
    comp_pct = round(100 * total_completed / total_sas) if total_sas else None
    total_sla_hits = sum(g['sla_hits'] for g in garage_ops.values())
    total_sla_eligible = sum(g['sla_eligible'] for g in garage_ops.values())
    sla_pct = round(100 * total_sla_hits / total_sla_eligible) if total_sla_eligible else None
    total_ata_under_30 = sum(g['ata_under_30'] for g in garage_ops.values())
    total_ata_30_45 = sum(g['ata_30_45'] for g in garage_ops.values())
    total_ata_45_60 = sum(g['ata_45_60'] for g in garage_ops.values())
    total_ata_over_60 = sum(g['ata_over_60'] for g in garage_ops.values())

    # ── VP Briefing — Bottom Line Up Front ──
    # Analyze comments for themes, diagnose per-garage, write a real briefing
    insights = []
    target = 82
    dissat_count = total_d + total_td
    comments_with_text = [s for s in problem_surveys if s.get('comment')]

    # 1. Classify struggling garages
    struggling = [g for g in garage_breakdown
                  if g['totally_satisfied_pct'] is not None and g['totally_satisfied_pct'] < 70 and g['surveys'] >= 2]
    good_garages = [g for g in garage_breakdown
                    if g['totally_satisfied_pct'] is not None and g['totally_satisfied_pct'] >= 82 and g['surveys'] >= 2]

    # 2. Analyze comment themes
    theme_wait = 0      # long wait, hours, took forever
    theme_noshow = 0    # never showed, no one came, never received
    theme_comm = 0      # no communication, no update, no callback
    theme_quality = 0   # rude, unprofessional, wrong truck, refused
    theme_cancel = 0    # cancelled, gave up

    for sv in comments_with_text:
        c = (sv.get('comment') or '').lower()
        if any(w in c for w in ['hour', 'wait', 'took', 'long time', 'forever', 'stranded']):
            theme_wait += 1
        if any(w in c for w in ['never showed', 'no one came', 'never received', 'nobody', 'never got']):
            theme_noshow += 1
        if any(w in c for w in ['no communication', 'no update', 'no call', 'no follow', 'no notification', 'no status']):
            theme_comm += 1
        if any(w in c for w in ['rude', 'unprofessional', 'refused', 'wrong truck', 'condescend', 'smug', 'attitude']):
            theme_quality += 1
        if any(w in c for w in ['cancel', 'gave up', 'could not wait']):
            theme_cancel += 1

    # 3. Build garage-specific diagnoses
    garage_diagnoses = []
    for g in struggling[:3]:
        name = g['name'].split(' - ')[-1].strip() if ' - ' in g['name'] else g['name']
        ata = g.get('avg_ata')
        total = g.get('sa_total', 0)
        cancelled = g.get('sa_cancelled', 0)
        dissat = g.get('dissatisfied', 0)

        if ata and ata > 90:
            garage_diagnoses.append(f"{name} had {ata}-minute average wait times across {total} calls — severely overwhelmed")
        elif ata and ata > 60:
            garage_diagnoses.append(f"{name} averaged {ata}m response on {total} calls with {dissat} dissatisfied surveys")
        elif cancelled > 2:
            garage_diagnoses.append(f"{name} had {cancelled} cancellations out of {total} calls — members gave up waiting")
        elif dissat > 0:
            garage_diagnoses.append(f"{name} had {dissat} dissatisfied out of {g['surveys']} surveys ({g['totally_satisfied_pct']}%)")

    # 4. Build the briefing
    if ts_pct is not None and ts_pct < target:
        # ── BELOW TARGET ──
        gap = target - ts_pct

        # Headline
        pts = 'point' if gap == 1 else 'points'
        headline = f"{gap} {pts} below target. "
        if theme_wait > theme_quality and theme_wait > 0:
            headline += "Long wait times are the primary driver of dissatisfaction."
        elif theme_quality > theme_wait and theme_quality > 0:
            headline += "Driver quality and professionalism issues are driving dissatisfaction."
        elif theme_noshow > 0:
            headline += "Members reported service no-shows — calls dispatched but drivers never arrived."
        else:
            headline += f"{dissat_count} members reported dissatisfaction."

        insights.append({'type': 'critical', 'text': headline})

        # Garage details
        if garage_diagnoses:
            insights.append({
                'type': 'warning',
                'text': f"Facilities that drove the score down: {'. '.join(garage_diagnoses)}.",
            })

        # Comment themes
        themes = []
        if theme_wait > 0:
            themes.append(f"{theme_wait} members complained about long wait times")
        if theme_noshow > 0:
            themes.append(f"{theme_noshow} reported service never arrived")
        if theme_comm > 0:
            themes.append(f"{theme_comm} cited lack of communication or status updates")
        if theme_quality > 0:
            themes.append(f"{theme_quality} reported driver quality or professionalism issues")
        if themes:
            insights.append({
                'type': 'info',
                'text': f"Common themes from member feedback: {'; '.join(themes)}.",
            })

        # Network context
        if good_garages:
            insights.append({
                'type': 'info',
                'text': f"The problem was concentrated — {len(good_garages)} of {len(garage_breakdown)} garages met target. "
                        f"Corrective action should focus on the {len(struggling)} underperforming facilities.",
            })

    else:
        # ── MET TARGET ──
        # Even when meeting target, provide real analysis
        risks = []
        if struggling:
            garage_strs = [f"{g['name'].split(' - ')[-1].strip()} ({g['totally_satisfied_pct']}%)"
                           for g in struggling[:3]]
            risks.append(f"weak spots at {', '.join(garage_strs)}")
        if avg_ata and avg_ata > 50:
            risks.append(f"average response time at {avg_ata} minutes (above 45m SLA)")

        if risks and dissat_count > 0:
            insights.append({
                'type': 'warning' if len(risks) > 1 else 'success',
                'text': f"On target at {ts_pct}%, but with {', '.join(risks)}. "
                        f"The rest of the network ({len(good_garages)} garages) is performing well enough to compensate.",
            })

            # Garage details for struggling facilities
            if garage_diagnoses:
                insights.append({
                    'type': 'warning',
                    'text': f"Facilities needing attention: {'. '.join(garage_diagnoses)}.",
                })

            # Comment themes even when meeting target
            themes = []
            if theme_wait > 0:
                themes.append(f"{theme_wait} complained about wait times")
            if theme_quality > 0:
                themes.append(f"{theme_quality} reported driver quality issues")
            if theme_noshow > 0:
                themes.append(f"{theme_noshow} reported no-shows")
            if theme_comm > 0:
                themes.append(f"{theme_comm} cited poor communication")
            if themes:
                insights.append({
                    'type': 'info',
                    'text': f"From the {dissat_count} dissatisfied members: {'; '.join(themes)}. "
                            f"Address these to build margin above the 82% target.",
                })
        elif ts_pct and ts_pct >= 90:
            insights.append({
                'type': 'success',
                'text': f"Strong day — {ts_pct}% across {total_surveys} surveys with {avg_ata}m average response. "
                        f"Both speed and driver quality performing well across the network.",
            })
        else:
            insights.append({
                'type': 'success',
                'text': f"Steady performance at {ts_pct}%. No major issues identified.",
            })

    # Sort long ATA SAs by worst first
    long_ata_sas.sort(key=lambda x: -x['ata_min'])

    # Top cancel reasons
    top_cancels = sorted(cancel_reasons.items(), key=lambda x: -x[1])[:5]

    result = {
        'date': date,
        'summary': {
            'totally_satisfied_pct': ts_pct,
            'total_surveys': total_surveys,
            'dissatisfied_count': total_d + total_td,
            'neither_count': total_n,
            'satisfied_count': total_s,
            'totally_satisfied_count': total_ts,
            'avg_ata': avg_ata,
            'sla_pct': sla_pct,
            'sla_hits': total_sla_hits,
            'sla_eligible': total_sla_eligible,
            'ata_under_30': total_ata_under_30,
            'ata_30_45': total_ata_30_45,
            'ata_45_60': total_ata_45_60,
            'ata_over_60': total_ata_over_60,
            'total_sas': total_sas,
            'completed': total_completed,
            'completion_pct': comp_pct,
            'cancelled': total_cancelled,
        },
        'insights': insights,
        'garage_breakdown': garage_breakdown,
        'problem_surveys': problem_surveys[:30],  # cap at 30
        'long_ata_sas': long_ata_sas[:20],  # cap at 20
        'cancel_reasons': [{'reason': r, 'count': c} for r, c in top_cancels],
    }

    cache.put(cache_key, result, 7200)
    cache.disk_put(cache_key, result, 7200)
    return result
