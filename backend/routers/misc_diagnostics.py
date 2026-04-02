"""Diagnostic/analytics endpoints split from misc.py:
Scheduler Insights — auto vs manual dispatch quality analysis."""

from datetime import datetime, timedelta, timezone
from collections import defaultdict, Counter
from fastapi import APIRouter

from utils import (
    _ET, parse_dt as _parse_dt,
    haversine,
)
from sf_client import sf_query_all, sf_parallel
from sf_batch import batch_soql_query
from dispatch_utils import parse_assign_events, classify_dispatch
import cache

router = APIRouter()

_SYSTEM_DISPATCHERS = {
    'it system user', 'mulesoft integration', 'replicant integration user',
    'automated process', 'system', 'fsl optimizer',
}

def _is_system_dispatcher(name: str) -> bool:
    """True if the dispatcher is a system/automation user, not a human."""
    n = (name or '').strip().lower()
    return n in _SYSTEM_DISPATCHERS or 'integration' in n or 'system' in n or 'automated' in n


_haversine_mi = haversine  # alias — use haversine from utils


@router.get("/api/scheduler-insights")
def scheduler_insights():
    """Scheduler decision quality based on SA history — who actually dispatched. Today from midnight ET; falls back to last 24h if today is empty."""
    now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(_ET)
    today_cutoff = now_et.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    fallback_cutoff = (now_utc - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ')
    cutoff_utc = today_cutoff  # will switch to fallback if today is empty

    def _fetch():
        from sf_client import sf_parallel
        nonlocal cutoff_utc

        # 1) Parallel fetch: today's fleet + Towbook SAs, assigned resources, all drivers w/ GPS, territory members, Asset login
        def _get_sas():
            return sf_query_all(f"""
                SELECT Id, AppointmentNumber, Status, CreatedDate,
                       ActualStartTime, SchedStartTime,
                       ERS_Dispatch_Method__c, Latitude, Longitude,
                       ERS_Dispatched_Geolocation__Latitude__s,
                       ERS_Dispatched_Geolocation__Longitude__s,
                       ServiceTerritoryId, ServiceTerritory.Name,
                       WorkType.Name, CreatedBy.Profile.Name
                FROM ServiceAppointment
                WHERE CreatedDate >= {cutoff_utc}
                  AND ServiceTerritoryId != null
                  AND RecordType.Name = 'ERS Service Appointment'
                ORDER BY CreatedDate ASC
            """)

        def _get_assigned():
            return sf_query_all(f"""
                SELECT ServiceAppointmentId, ServiceResourceId,
                       ServiceResource.Name,
                       ServiceResource.LastKnownLatitude,
                       ServiceResource.LastKnownLongitude,
                       ServiceResource.ERS_Driver_Type__c
                FROM AssignedResource
                WHERE ServiceAppointment.CreatedDate >= {cutoff_utc}
                  AND ServiceAppointment.RecordType.Name = 'ERS Service Appointment'
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
                SELECT ServiceResourceId, ServiceTerritoryId, TerritoryType
                FROM ServiceTerritoryMember
                WHERE TerritoryType IN ('P','S')
                  AND ServiceResource.IsActive = true
                  AND ServiceResource.ResourceType = 'T'
            """)

        def _get_trucks():
            """On-shift drivers from Asset for filtering comparison pool."""
            return sf_query_all("""
                SELECT ERS_Driver__c
                FROM Asset
                WHERE RecordType.Name = 'ERS Truck'
                  AND ERS_Driver__c != null
            """)

        data = sf_parallel(
            sas=_get_sas,
            assigned=_get_assigned,
            drivers=_get_drivers,
            members=_get_members,
            trucks=_get_trucks,
        )

        sas_raw = data['sas']
        assigned_raw = data['assigned']
        all_drivers = data['drivers']
        members_raw = data['members']
        # On-shift driver IDs from Asset
        on_shift_ids = {t.get('ERS_Driver__c') for t in data['trucks'] if t.get('ERS_Driver__c')}

        # Exclude Tow Drop-Off
        sas = [s for s in sas_raw if 'drop' not in ((s.get('WorkType') or {}).get('Name', '') or '').lower()]

        # No fallback — at midnight, show zero until new calls come in
        is_fallback = False

        empty = {'total': 0, 'auto_count': 0, 'manual_count': 0, 'auto_pct': 0,
                 'auto_avg_response': None, 'manual_avg_response': None,
                 'auto_avg_speed': None, 'manual_avg_speed': None,
                 'auto_sla': None, 'manual_sla': None,
                 'closest_pct': None, 'closest_evaluated': 0,
                 'dispatchers': [], 'is_fallback': False}
        if not sas:
            return empty

        sa_by_id = {s['Id']: s for s in sas}
        sa_ids = list(sa_by_id.keys())

        # Build lookup: SA -> assigned driver ID
        sa_to_driver = {}
        for ar in assigned_raw:
            sa_id = ar.get('ServiceAppointmentId')
            dr_id = ar.get('ServiceResourceId')
            if sa_id and dr_id:
                sa_to_driver[sa_id] = dr_id

        # Build lookup: driver ID -> GPS
        fleet_driver_gps = {}
        for d in all_drivers:
            lat, lon = d.get('LastKnownLatitude'), d.get('LastKnownLongitude')
            if lat and lon:
                fleet_driver_gps[d['Id']] = (float(lat), float(lon))

        # Build lookup: territory -> fleet driver IDs with GPS
        territory_drivers = defaultdict(set)
        for m in members_raw:
            tid = m.get('ServiceTerritoryId')
            dr_id = m.get('ServiceResourceId')
            if tid and dr_id and dr_id in fleet_driver_gps:
                territory_drivers[tid].add(dr_id)

        # 2) Batch query ServiceAppointmentHistory for assignment changes
        dispatched_by = {}
        all_hist_rows = batch_soql_query("""
                SELECT ServiceAppointmentId, NewValue,
                       CreatedBy.Name, CreatedBy.Profile.Name
                FROM ServiceAppointmentHistory
                WHERE ServiceAppointmentId IN ('{id_list}')
                  AND Field = 'ERS_Assigned_Resource__c'
                ORDER BY CreatedDate ASC
            """, sa_ids, chunk_size=150)
        _assign_events = parse_assign_events(all_hist_rows, set(sa_ids))
        _dispatch_class = classify_dispatch(_assign_events)
        history_sa_ids = {r.get('ServiceAppointmentId') for r in all_hist_rows if r.get('ServiceAppointmentId')}
        human_touched = {sa_id for sa_id, cls in _dispatch_class.items() if cls['is_manual']}
        for sa_id in human_touched:
            dispatched_by[sa_id] = {'name': _dispatch_class[sa_id]['dispatcher_name']}

        # 3) Classify each SA
        auto_sas, manual_sas, towbook_sas, towbook_human_sas = [], [], [], []
        for s in sas:
            dispatch_method = s.get('ERS_Dispatch_Method__c') or ''
            human = s['Id'] in human_touched
            if dispatch_method == 'Towbook':
                if human:
                    towbook_human_sas.append(s)
                else:
                    towbook_sas.append(s)
            elif human:
                manual_sas.append(s)
            else:
                auto_sas.append(s)

        auto_count = len(auto_sas)
        manual_count = len(manual_sas)
        towbook_count = len(towbook_sas) + len(towbook_human_sas)
        towbook_auto_count = len(towbook_sas)
        towbook_human_count = len(towbook_human_sas)
        fleet_total = auto_count + manual_count
        total = fleet_total + towbook_count
        auto_pct = round(100 * auto_count / max(fleet_total, 1))
        no_human_count = auto_count + towbook_auto_count
        human_count = manual_count + towbook_human_count
        no_human_pct = round(100 * no_human_count / max(total, 1))

        # 4) Avg response time: auto vs manual (completed only)
        def _response_times(sa_list):
            times = []
            for s in sa_list:
                if s.get('Status') != 'Completed':
                    continue
                c = _parse_dt(s.get('CreatedDate'))
                a = _parse_dt(s.get('ActualStartTime'))
                if c and a:
                    diff = (a - c).total_seconds() / 60
                    if 0 < diff < 480:
                        times.append(diff)
            return times

        auto_times = _response_times(auto_sas)
        manual_times = _response_times(manual_sas)

        auto_avg_response = round(sum(auto_times) / len(auto_times)) if auto_times else None
        manual_avg_response = round(sum(manual_times) / len(manual_times)) if manual_times else None

        # 5) Avg dispatch speed (CreatedDate -> SchedStartTime)
        def _dispatch_speeds(sa_list):
            speeds = []
            for s in sa_list:
                c = _parse_dt(s.get('CreatedDate'))
                sc = _parse_dt(s.get('SchedStartTime'))
                if c and sc:
                    speed = (sc - c).total_seconds() / 60
                    if 0 < speed < 120:
                        speeds.append(speed)
            return speeds

        auto_speeds = _dispatch_speeds(auto_sas)
        manual_speeds = _dispatch_speeds(manual_sas)

        auto_avg_speed = round(sum(auto_speeds) / len(auto_speeds)) if auto_speeds else None
        manual_avg_speed = round(sum(manual_speeds) / len(manual_speeds)) if manual_speeds else None

        # 6) SLA hit rate
        auto_sla = round(100 * sum(1 for t in auto_times if t <= 45) / max(len(auto_times), 1)) if auto_times else None
        manual_sla = round(100 * sum(1 for t in manual_times if t <= 45) / max(len(manual_times), 1)) if manual_times else None

        # 7) "Closest driver" metric — split by system vs dispatcher
        def _closest_driver_analysis(sa_list):
            """Check if the assigned driver was the closest fleet driver (by GPS)."""
            hits, evaluated = 0, 0
            total_extra_miles = 0.0
            for s in sa_list:
                sa_lat, sa_lon = s.get('Latitude'), s.get('Longitude')
                if not sa_lat or not sa_lon:
                    continue
                sa_lat, sa_lon = float(sa_lat), float(sa_lon)
                assigned_dr = sa_to_driver.get(s['Id'])
                if not assigned_dr or assigned_dr not in fleet_driver_gps:
                    continue
                tid = s.get('ServiceTerritoryId')
                terr_drivers_set = territory_drivers.get(tid, set())
                candidates = [(dr_id, fleet_driver_gps[dr_id]) for dr_id in terr_drivers_set if dr_id in fleet_driver_gps]
                if len(candidates) < 2:
                    continue

                disp_lat = s.get('ERS_Dispatched_Geolocation__Latitude__s')
                disp_lon = s.get('ERS_Dispatched_Geolocation__Longitude__s')

                distances = []
                for dr_id, (dlat, dlon) in candidates:
                    if dr_id == assigned_dr and disp_lat and disp_lon:
                        dist = _haversine_mi(sa_lat, sa_lon, float(disp_lat), float(disp_lon))
                    else:
                        dist = _haversine_mi(sa_lat, sa_lon, dlat, dlon)
                    distances.append((dr_id, dist))
                distances.sort(key=lambda x: x[1])
                evaluated += 1
                closest_dist = distances[0][1]
                assigned_dist = next((d for dr, d in distances if dr == assigned_dr), closest_dist)
                if assigned_dr == distances[0][0]:
                    hits += 1
                else:
                    total_extra_miles += (assigned_dist - closest_dist)
            pct = round(100 * hits / max(evaluated, 1)) if evaluated > 0 else None
            extra = round(total_extra_miles, 1) if evaluated > 0 else None
            wrong = (evaluated - hits) if evaluated > 0 else None
            return pct, evaluated, extra, wrong

        auto_closest_pct, auto_closest_eval, auto_extra_miles, auto_wrong = _closest_driver_analysis(auto_sas)
        manual_closest_pct, manual_closest_eval, manual_extra_miles, manual_wrong = _closest_driver_analysis(manual_sas)
        towbook_closest_pct, towbook_closest_eval, towbook_extra_miles, towbook_wrong = None, 0, None, None
        _extras = [x for x in [auto_extra_miles, manual_extra_miles] if x is not None]
        total_extra_miles_today = round(sum(_extras), 1) if _extras else None

        # 8) Top dispatchers
        dispatcher_counts = Counter()
        for s in sas:
            info = dispatched_by.get(s['Id'])
            if info:
                dispatcher_counts[info['name']] += 1
        top_dispatchers = [{'name': n, 'count': c} for n, c in dispatcher_counts.most_common(5)]

        return {
            'total': total,
            'fleet_total': fleet_total,
            'auto_count': auto_count,
            'manual_count': manual_count,
            'towbook_count': towbook_count,
            'auto_pct': auto_pct,
            'no_human_count': no_human_count,
            'no_human_pct': no_human_pct,
            'human_count': human_count,
            'towbook_auto_count': towbook_auto_count,
            'towbook_human_count': towbook_human_count,
            'auto_avg_response': auto_avg_response,
            'manual_avg_response': manual_avg_response,
            'auto_avg_speed': auto_avg_speed,
            'manual_avg_speed': manual_avg_speed,
            'auto_sla': auto_sla,
            'manual_sla': manual_sla,
            'auto_closest_pct': auto_closest_pct,
            'auto_closest_eval': auto_closest_eval,
            'auto_extra_miles': auto_extra_miles,
            'auto_wrong': auto_wrong,
            'manual_closest_pct': manual_closest_pct,
            'manual_closest_eval': manual_closest_eval,
            'manual_extra_miles': manual_extra_miles,
            'manual_wrong': manual_wrong,
            'towbook_closest_pct': towbook_closest_pct,
            'towbook_closest_eval': towbook_closest_eval,
            'towbook_extra_miles': towbook_extra_miles,
            'towbook_wrong': towbook_wrong,
            'total_extra_miles': total_extra_miles_today,
            'dispatchers': top_dispatchers,
            'is_fallback': is_fallback,
            'sas_with_history': len(history_sa_ids),
            'sas_queried': len(sas),
            'sas_excluded_creator': 0,  # all SAs now included
        }

    return cache.cached_query('scheduler_insights_today', _fetch, ttl=60)
