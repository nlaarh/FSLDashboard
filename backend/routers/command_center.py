"""Command Center endpoint -- live territory overview."""

from fastapi import APIRouter, Query
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from sf_client import sf_query_all, sf_parallel
from utils import (
    _ET, parse_dt as _parse_dt,
)
from routers.command_center_helpers import (
    build_driver_availability, build_territory_data,
    build_today_metrics, build_reassignment_cost,
)
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

        now = datetime.now(_tz.utc)

        # ── Driver availability ──
        (drivers_by_territory, drivers_by_territory_tier,
         driver_tier_map, logged_in_ids, busy_driver_ids_set) = build_driver_availability(
            cc_trucks, driver_members, busy_ar, now)

        # ── Territory aggregation ──
        by_territory = defaultdict(list)
        for sa in sas:
            tid = sa.get('ServiceTerritoryId')
            if tid:
                by_territory[tid].append(sa)

        territories = build_territory_data(
            by_territory, now_utc, drivers_by_territory, drivers_by_territory_tier)

        # ── Open customers ──
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

        # ── Fleet & On-Platform GPS Tile ──
        fleet_visible = 0
        fleet_recent = 0
        for d in all_fleet_drivers:
            lat = d.get('LastKnownLatitude')
            lkd = d.get('LastKnownLocationDate')
            if not lat or not lkd:
                continue
            age = now - _parse_dt(lkd)
            if age < timedelta(hours=1):
                fleet_visible += 1
            elif age < timedelta(hours=4):
                fleet_recent += 1
        fleet_on_shift = fleet_visible + fleet_recent
        fleet_total_roster = len(all_fleet_drivers)

        # ── Today's metrics (status, leaderboard, utilization, cancels, hourly) ──
        today_metrics = build_today_metrics(
            today_sas_all, fleet_lb_sas, fleet_ar, cc_trucks, busy_ar, now_utc)

        # ── Reassignment cost ──
        reassignment = build_reassignment_cost(reassign_history, today_sas_all, now)

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
                'total_roster': fleet_total_roster,
                'on_shift': fleet_on_shift,
                'visible': fleet_visible,
                'recent': fleet_recent,
                # Keep legacy keys for compatibility
                'total': fleet_on_shift,
                'active': fleet_visible,
                'fresh': fleet_visible,
                'stale': 0,
                'no_gps': 0,
                'pct': round(100 * fleet_visible / max(fleet_on_shift, 1)) if fleet_on_shift else 0,
            },
            'today_status': {**today_metrics['status_counts'], 'total': sum(today_metrics['status_counts'].values())},
            'today_split': today_metrics['today_split'],
            'fleet_leaderboard': today_metrics['fleet_leaderboard'],
            'reassignment': reassignment,
            'cancel_breakdown': today_metrics['cancel_breakdown'],
            'decline_breakdown': today_metrics['decline_breakdown'],
            'fleet_utilization': today_metrics['fleet_utilization'],
            'hourly_volume': today_metrics['hourly_volume'],
            'hours': hours,
        }

    return cache.cached_query(f'command_center_{hours}', _fetch, ttl=120)
