"""Dispatch optimization and insights drill-down endpoints."""

from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict
from fastapi import APIRouter, HTTPException

from utils import parse_dt as _parse_dt
from sf_client import sf_query_all, sanitize_soql
from sf_batch import batch_soql_query
from dispatch import get_live_queue, recommend_drivers, get_cascade_status
import cache

from routers.dispatch_shared import _ET, _today_start_utc, _fmt_et, _sa_row

router = APIRouter()


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
            extras = batch_soql_query("""
                    SELECT Id, Off_Platform_Driver__r.Name, ERS_Dispatch_Method__c
                    FROM ServiceAppointment
                    WHERE Id IN ('{id_list}')
                """, bounced_ids, chunk_size=150)
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
        rows = batch_soql_query("""
                SELECT ServiceAppointmentId, CreatedBy.Name, CreatedBy.Profile.Name
                FROM ServiceAppointmentHistory
                WHERE ServiceAppointmentId IN ('{id_list}')
                  AND Field = 'ERS_Assigned_Resource__c'
            """, sa_ids, chunk_size=150)
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


