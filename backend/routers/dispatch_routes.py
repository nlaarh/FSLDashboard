"""Dispatch optimization and insights drill-down endpoints."""

from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Query

from utils import parse_dt as _parse_dt, is_fleet_territory
from sf_client import sf_query_all, sanitize_soql
from dispatch import (
    get_live_queue, recommend_drivers, get_cascade_status,
    get_forecast,
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
    """Drill-down: all SAs with driver-level bounces (≥10 min gap) today.

    Returns each bounced SA with full driver assignment chain and total time wasted.
    Sorted by total time wasted descending.
    """
    today_start = _today_start_utc()

    def _fetch():
        import re
        _sf_id_pat = re.compile(r'^[a-zA-Z0-9]{15}$|^[a-zA-Z0-9]{18}$')

        # Query driver assignment changes (ERS_Assigned_Resource__c)
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
                   CreatedDate, OldValue, NewValue
            FROM ServiceAppointmentHistory
            WHERE ServiceAppointment.CreatedDate >= {today_start}
              AND Field = 'ERS_Assigned_Resource__c'
              AND ServiceAppointment.WorkType.Name != 'Tow Drop-Off'
            ORDER BY ServiceAppointmentId, CreatedDate ASC
        """)

        # Group by SA, dedup SF ID rows (keep name strings only)
        sa_assignments = defaultdict(list)
        sa_info = {}
        for r in rows:
            sa_id = r.get('ServiceAppointmentId')
            new_val = (r.get('NewValue') or '').strip()
            if not sa_id or not new_val or _sf_id_pat.match(new_val):
                continue  # Skip SF ID duplicate rows and empty values
            sa_obj = r.get('ServiceAppointment') or {}
            sa_assignments[sa_id].append({
                'time': _parse_dt(r.get('CreatedDate')),
                'driver': new_val,
            })
            sa_info[sa_id] = sa_obj

        _now = datetime.now(_ET)
        bounced_sas = []

        for sa_id, assignments in sa_assignments.items():
            if len(assignments) < 2:
                continue  # No bounce
            assignments.sort(key=lambda e: e['time'] if e['time'] else _now)

            # Build the bounce chain and calculate total time wasted
            chain = []
            total_wasted = 0
            has_bounce = False

            for i, a in enumerate(assignments):
                if i == 0:
                    # First assignment — no gap yet, just record the driver
                    chain.append({
                        'driver': a['driver'],
                        'assigned_at': _fmt_et(a['time'].isoformat()) if a['time'] else '',
                        'gap_min': None,  # No gap for first assignment
                    })
                    continue

                prev_time = assignments[i-1]['time']
                curr_time = a['time']
                gap_min = 0
                if prev_time and curr_time:
                    gap_min = (curr_time - prev_time).total_seconds() / 60

                is_bounce = 10 <= gap_min < 480
                if is_bounce:
                    has_bounce = True
                    total_wasted += gap_min

                chain.append({
                    'driver': a['driver'],
                    'assigned_at': _fmt_et(curr_time.isoformat()) if curr_time else '',
                    'gap_min': round(gap_min) if is_bounce else None,
                })

            if not has_bounce:
                continue

            sa = sa_info.get(sa_id, {})
            row = _sa_row(sa, minutes_lost=round(total_wasted))
            row['bounce_chain'] = chain
            row['bounce_count'] = sum(1 for c in chain if c['gap_min'] is not None)
            row['_created_iso'] = sa.get('CreatedDate') or ''
            bounced_sas.append(row)

        # Sort by most recent SA first
        bounced_sas.sort(key=lambda x: x.get('_created_iso') or '', reverse=True)
        bounced_sas = bounced_sas[:200]

        # Enrich: off-platform driver, dispatch method, and resolve Towbook codes to garage names
        if bounced_sas:
            # 1. Get driver name + dispatch method from SAs
            bounced_ids = [b['sa_id'] for b in bounced_sas if b.get('sa_id')]
            driver_info = {}
            batch_size = 150
            for i in range(0, len(bounced_ids), batch_size):
                batch = bounced_ids[i:i + batch_size]
                id_str = "','".join(batch)
                extras = sf_query_all(f"""
                    SELECT Id, Off_Platform_Driver__r.Name,
                           ERS_Dispatch_Method__c
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

            # 2. Resolve "Towbook-XXX" resource names to garage names
            # Collect unique Towbook codes from all chains
            tb_codes = set()
            for b in bounced_sas:
                for c in b.get('bounce_chain', []):
                    drv = c.get('driver', '')
                    if drv.startswith('Towbook-'):
                        code = drv.replace('Towbook-', '', 1)
                        if code:
                            tb_codes.add(code)

            # Query ServiceTerritory names matching those codes
            garage_names = {}  # "214" -> "214 - HESS TIRE SERVICE"
            if tb_codes:
                like_clauses = " OR ".join(
                    f"Name LIKE '{sanitize_soql(c)}%'" for c in tb_codes
                )
                territories = sf_query_all(f"""
                    SELECT Name FROM ServiceTerritory
                    WHERE {like_clauses}
                """)
                for t in territories:
                    tname = t.get('Name', '')
                    for code in tb_codes:
                        if tname.startswith(code):
                            garage_names[code] = tname
                            break

            # Replace "Towbook-XXX" with garage name in chain
            for b in bounced_sas:
                for c in b.get('bounce_chain', []):
                    drv = c.get('driver', '')
                    if drv.startswith('Towbook-'):
                        code = drv.replace('Towbook-', '', 1)
                        if code in garage_names:
                            c['driver'] = garage_names[code]

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
                   ERS_Dispatch_Method__c
            FROM ServiceAppointment
            WHERE CreatedDate >= {today_start}
              AND WorkType.Name IN ('Tow Pick-Up','Battery','Tire','Lockout','Winch Out','Fuel','Locksmith','EV')
        """)
        if not sas:
            return {'human': [], 'auto': [], 'human_count': 0, 'auto_count': 0}

        sa_map = {s['Id']: s for s in sas}
        sa_ids = list(sa_map.keys())

        # Batch query SAHistory — find SAs touched by Membership User
        human_sas = {}      # sa_id -> dispatcher name who touched it
        batch_size = 150
        for i in range(0, len(sa_ids), batch_size):
            batch = sa_ids[i:i + batch_size]
            id_str = "','".join(batch)
            rows = sf_query_all(f"""
                SELECT ServiceAppointmentId, CreatedBy.Name,
                       CreatedBy.Profile.Name, NewValue, CreatedDate
                FROM ServiceAppointmentHistory
                WHERE ServiceAppointmentId IN ('{id_str}')
                  AND Field = 'Status'
            """)
            for r in rows:
                sa_id = r.get('ServiceAppointmentId')
                cb = r.get('CreatedBy') or {}
                profile = (cb.get('Profile') or {}).get('Name', '')
                if profile == 'Membership User':
                    name = cb.get('Name', '?')
                    # Keep the first dispatcher who touched it
                    if sa_id not in human_sas:
                        human_sas[sa_id] = name

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
            row = _sa_row(sa, ata=ata)
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
              AND ERS_Driver__r.ERS_Driver_Type__c IN ('Fleet Driver', 'On-Platform Contractor Driver')
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
    import math
    from sf_client import sf_parallel

    def _haversine(lat1, lon1, lat2, lon2):
        R = 3958.8
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
        return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 1)

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

        def _get_members():
            return sf_query_all("""
                SELECT ServiceResourceId, ServiceTerritoryId
                FROM ServiceTerritoryMember
                WHERE TerritoryType IN ('P','S')
                  AND ServiceResource.IsActive = true
                  AND ServiceResource.ResourceType = 'T'
                  AND ServiceResource.ERS_Driver_Type__c IN ('Fleet Driver', 'On-Platform Contractor Driver')
            """)

        data = sf_parallel(
            sas=_get_sas, assigned=_get_assigned,
            drivers=_get_drivers, members=_get_members,
        )

        sas_raw = data['sas']
        assigned_raw = data['assigned']
        all_drivers = data['drivers']
        members_raw = data['members']
        # Exclude Tow Drop-Off
        sas = [s for s in sas_raw if 'drop' not in ((s.get('WorkType') or {}).get('Name', '') or '').lower()]

        if not sas:
            return {'calls': [], 'summary': {'evaluated': 0, 'closest_picked': 0, 'total_extra_miles': 0}}

        # SA → assigned driver + dispatcher info
        sa_to_driver = {}
        sa_to_driver_name = {}
        sa_to_dispatcher = {}
        for ar in assigned_raw:
            sa_id = ar.get('ServiceAppointmentId')
            dr_id = ar.get('ServiceResourceId')
            if sa_id and dr_id:
                sa_to_driver[sa_id] = dr_id
                sa_to_driver_name[sa_id] = (ar.get('ServiceResource') or {}).get('Name', '?')
                cb = ar.get('CreatedBy') or {}
                profile = (cb.get('Profile') or {}).get('Name', '')
                sa_to_dispatcher[sa_id] = {
                    'name': cb.get('Name', '?'),
                    'is_auto': profile != 'Membership User',
                }

        # Driver name lookup
        driver_names = {}
        for d in all_drivers:
            driver_names[d['Id']] = d.get('Name', '?')

        # Fleet GPS: drivers with GPS coordinates are active (FSL mobile app reports position)
        # The _get_drivers query already filters to Fleet Driver / Transit Auto Detail types
        fleet_driver_gps = {}
        for d in all_drivers:
            lat, lon = d.get('LastKnownLatitude'), d.get('LastKnownLongitude')
            if lat and lon:
                fleet_driver_gps[d['Id']] = (float(lat), float(lon))

        # Territory → fleet driver IDs with GPS
        territory_drivers = defaultdict(set)
        for m in members_raw:
            tid = m.get('ServiceTerritoryId')
            dr_id = m.get('ServiceResourceId')
            if tid and dr_id and dr_id in fleet_driver_gps:
                territory_drivers[tid].add(dr_id)

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
            if not assigned_dr or assigned_dr not in fleet_driver_gps:
                continue

            tid = s.get('ServiceTerritoryId')
            candidates = [(dr_id, fleet_driver_gps[dr_id]) for dr_id in territory_drivers.get(tid, set()) if dr_id in fleet_driver_gps]
            if len(candidates) < 2:
                continue

            # Dispatch-time geolocation for assigned driver if available
            disp_lat = s.get('ERS_Dispatched_Geolocation__Latitude__s')
            disp_lon = s.get('ERS_Dispatched_Geolocation__Longitude__s')

            drivers_list = []
            for dr_id, (dlat, dlon) in candidates:
                if dr_id == assigned_dr and disp_lat and disp_lon:
                    dist = _haversine(sa_lat, sa_lon, float(disp_lat), float(disp_lon))
                else:
                    dist = _haversine(sa_lat, sa_lon, dlat, dlon)
                drivers_list.append({
                    'name': driver_names.get(dr_id, '?'),
                    'distance_mi': dist,
                    'picked': dr_id == assigned_dr,
                })

            drivers_list.sort(key=lambda x: x['distance_mi'])
            total_evaluated += 1

            closest_dist = drivers_list[0]['distance_mi']
            picked_driver = next((d for d in drivers_list if d['picked']), None)
            picked_dist = picked_driver['distance_mi'] if picked_driver else closest_dist
            is_closest = drivers_list[0]['picked']
            extra_mi = round(picked_dist - closest_dist, 1) if not is_closest else 0

            if is_closest:
                total_closest_picked += 1
            else:
                total_extra += extra_mi

            disp_info = sa_to_dispatcher.get(s['Id'], {})

            results.append({
                'number': s.get('AppointmentNumber', ''),
                'work_type': (s.get('WorkType') or {}).get('Name', ''),
                'status': s.get('Status', ''),
                'territory': (s.get('ServiceTerritory') or {}).get('Name', ''),
                'created_time': _fmt_et(s.get('CreatedDate')),
                '_created_iso': s.get('CreatedDate', ''),
                'assigned_driver': sa_to_driver_name.get(s['Id'], '?'),
                'assigned_distance': picked_dist,
                'closest_driver': drivers_list[0]['name'],
                'closest_distance': closest_dist,
                'extra_miles': extra_mi,
                'is_closest': is_closest,
                'dispatcher': disp_info.get('name', '?'),
                'is_auto': disp_info.get('is_auto', True),
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
                       ServiceTerritory.Name, WorkType.Name
                FROM ServiceAppointment
                WHERE CreatedDate = LAST_N_DAYS:31
                  AND CreatedDate < TODAY
                  AND ServiceTerritoryId != null
            """)

        def _get_status_history():
            return sf_query_all("""
                SELECT ServiceAppointmentId, CreatedDate,
                       NewValue, CreatedBy.Profile.Name
                FROM ServiceAppointmentHistory
                WHERE CreatedDate = LAST_N_DAYS:31
                  AND CreatedDate < TODAY
                  AND Field = 'Status'
            """)

        def _get_reassignment_history():
            return sf_query_all("""
                SELECT ServiceAppointmentId, CreatedDate, NewValue
                FROM ServiceAppointmentHistory
                WHERE CreatedDate = LAST_N_DAYS:31
                  AND CreatedDate < TODAY
                  AND Field = 'ERS_Assigned_Resource__c'
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

        data = sf_parallel(
            sas=_get_sas,
            status_hist=_get_status_history,
            reassign_hist=_get_reassignment_history,
            satisfaction=_get_satisfaction,
        )

        all_sas = data['sas']
        status_hist = data['status_hist']
        reassign_hist = data['reassign_hist']
        satisfaction_rows = data['satisfaction']

        # ── Pre-process history data ─────────────────────────────────

        # 1. Human-touched SA IDs (any status change by Membership User)
        human_touched_ids = set()
        # 2. Towbook on-location times: {sa_id: earliest 'On Location' datetime}
        towbook_on_location = {}
        for r in status_hist:
            sa_id = r.get('ServiceAppointmentId')
            if not sa_id:
                continue
            profile = ((r.get('CreatedBy') or {}).get('Profile') or {}).get('Name', '')
            if profile == 'Membership User':
                human_touched_ids.add(sa_id)
            if r.get('NewValue') == 'On Location':
                ts = _parse_dt(r.get('CreatedDate'))
                if ts:
                    if sa_id not in towbook_on_location or ts < towbook_on_location[sa_id]:
                        towbook_on_location[sa_id] = ts

        # 3. Reassignments per day (name-only rows = real driver changes)
        reassign_by_day = defaultdict(int)
        for r in reassign_hist:
            new_val = (r.get('NewValue') or '').strip()
            if not new_val or _sf_id_pat.match(new_val):
                continue  # Skip SF ID duplicate rows
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

            # Auto dispatch tracking (all channels)
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

    return cache.cached_query_persistent('insights_trends_30d', _fetch, ttl=86400)


## NOTE: /api/garages/{territory_id}/decomposition is in routers/garages.py
## NOTE: /api/territory/{territory_id}/forecast is kept here (not in garages.py)

@router.get("/api/territory/{territory_id}/forecast")
def api_forecast(territory_id: str, weeks_history: int = Query(8, ge=2, le=16)):
    """16-day demand forecast using DOW patterns + weather."""
    territory_id = sanitize_soql(territory_id)
    return get_forecast(territory_id, weeks_history)
