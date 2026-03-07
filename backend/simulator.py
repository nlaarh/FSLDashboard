"""Dispatch simulation engine — fast version using LastKnown positions.

For each SA on a given day, determines:
  - Which driver was actually assigned
  - Which driver was closest (by distance using LastKnown GPS)
  - Whether the closest driver was picked

SAs, skills: from Salesforce (relationship queries)
Driver GPS positions: from Salesforce (live data)
"""

import math
from datetime import datetime, date, timedelta
from collections import defaultdict
from sf_client import sf_query_all, sf_parallel
import cache


def haversine(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    R = 3959
    la1, la2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lat2 - lat1)
    dn = math.radians(lon2 - lon1)
    a = math.sin(dl / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dn / 2) ** 2
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 2)


def _parse_dt(dt_str):
    if not dt_str:
        return None
    if isinstance(dt_str, datetime):
        return dt_str
    try:
        return datetime.fromisoformat(
            str(dt_str).replace('+0000', '+00:00').replace('Z', '+00:00'))
    except Exception:
        return None


def _to_eastern(dt_str):
    """Convert SF datetime string to Eastern. Also handles datetime objects."""
    if isinstance(dt_str, datetime):
        return dt_str - timedelta(hours=5)
    dt = _parse_dt(dt_str)
    return (dt - timedelta(hours=5)) if dt else None


def simulate_day(territory_id: str, date_str: str) -> list[dict]:
    """Fast simulation: SA list + driver distances using LastKnown GPS."""
    next_day = (date.fromisoformat(date_str) + timedelta(days=1)).isoformat()

    # 1. SAs for the day + territory info + members — parallel
    data = sf_parallel(
        sas=lambda: sf_query_all(f"""
            SELECT Id, AppointmentNumber, Status, CreatedDate,
                   SchedStartTime, ActualStartTime, ActualEndTime,
                   Street, City, State, Latitude, Longitude,
                   ServiceTerritoryId, ServiceTerritory.Name,
                   WorkType.Name, Off_Platform_Truck_Id__c,
                   ERS_PTA__c, ERS_Dispatch_Method__c, ERS_Auto_Assign__c,
                   ERS_Dispatched_Geolocation__Latitude__s,
                   ERS_Dispatched_Geolocation__Longitude__s,
                   ERS_Cancellation_Reason__c, FSL__Duration_In_Minutes__c
            FROM ServiceAppointment
            WHERE ServiceTerritoryId = '{territory_id}'
              AND CreatedDate >= {date_str}T00:00:00Z
              AND CreatedDate < {next_day}T00:00:00Z
              AND Status IN ('Dispatched','Completed','Canceled',
                             'Cancel Call - Service Not En Route',
                             'Cancel Call - Service En Route',
                             'Unable to Complete','Assigned','No-Show')
            ORDER BY CreatedDate ASC
        """),
        territory=lambda: sf_query_all(f"""
            SELECT Id, Name, Latitude, Longitude
            FROM ServiceTerritory
            WHERE Id = '{territory_id}'
        """),
        members=lambda: sf_query_all(f"""
            SELECT ServiceResourceId, ServiceResource.Name,
                   ServiceResource.LastKnownLatitude, ServiceResource.LastKnownLongitude,
                   ServiceResource.LastKnownLocationDate, TerritoryType
            FROM ServiceTerritoryMember
            WHERE ServiceTerritoryId = '{territory_id}'
        """),
    )

    sas = data['sas']
    if not sas:
        return []

    t_row = data['territory'][0] if data['territory'] else {}
    territory = {
        'id': territory_id,
        'name': t_row.get('Name', '?'),
        'lat': t_row.get('Latitude'),
        'lon': t_row.get('Longitude'),
    }

    members = [m for m in data['members']
               if not ((m.get('ServiceResource') or {}).get('Name') or '').lower().startswith('towbook')]
    driver_ids = list(set(m['ServiceResourceId'] for m in members))

    # 2. Driver skills + work type skills — parallel, cached 1hr
    def _get_skills():
        if not driver_ids:
            return {'driver_skills': [], 'wt_skills': []}
        id_list = ",".join(f"'{d}'" for d in driver_ids)
        sk = sf_parallel(
            driver_skills=lambda: sf_query_all(f"""
                SELECT ServiceResourceId, Skill.MasterLabel
                FROM ServiceResourceSkill
                WHERE ServiceResourceId IN ({id_list})
            """),
            wt_rows=lambda: sf_query_all("SELECT Id, Name FROM WorkType"),
        )
        # Get skill requirements for work types
        wt_ids = [w['Id'] for w in sk['wt_rows']]
        wt_sk = []
        if wt_ids:
            wt_id_list = ",".join(f"'{w}'" for w in wt_ids)
            wt_sk = sf_query_all(f"""
                SELECT RelatedRecordId, Skill.MasterLabel
                FROM SkillRequirement
                WHERE RelatedRecordId IN ({wt_id_list})
            """)
        return {
            'driver_skills': sk['driver_skills'],
            'wt_rows': sk['wt_rows'],
            'wt_skill_reqs': wt_sk,
        }

    skills_data = cache.cached_query(f'skills_{territory_id}', _get_skills, ttl=3600)

    # Build skill maps
    driver_skills = defaultdict(set)
    for r in skills_data['driver_skills']:
        sk = (r.get('Skill') or {}).get('MasterLabel')
        if sk:
            driver_skills[r['ServiceResourceId']].add(sk)

    wt_skills = {}
    wt_id_to_name = {w['Id']: w.get('Name', '') for w in skills_data.get('wt_rows', [])}
    wt_id_skills = defaultdict(list)
    for s in skills_data.get('wt_skill_reqs', []):
        sk = (s.get('Skill') or {}).get('MasterLabel')
        if sk:
            wt_id_skills[s['RelatedRecordId']].append(sk)
    for wid, name in wt_id_to_name.items():
        wt_skills[name] = wt_id_skills.get(wid, [])

    # 3. Simulate each SA
    results = []
    for sa in sas:
        sa_lat = sa.get('Latitude')
        sa_lon = sa.get('Longitude')
        if not sa_lat or not sa_lon:
            continue
        sa_lat, sa_lon = float(sa_lat), float(sa_lon)

        wt_name = (sa.get('WorkType') or {}).get('Name') or ''
        required_skills = set(wt_skills.get(wt_name, []))

        truck_id = sa.get('Off_Platform_Truck_Id__c') or ''
        truck_label = f"Truck {truck_id.split('-')[-1]}" if truck_id else 'No Truck ID'
        actual_driver_id = None
        actual_driver_name = truck_label

        evaluations = []
        for member in members:
            d_id = member['ServiceResourceId']
            sr = member.get('ServiceResource') or {}
            d_name = sr.get('Name', '?')
            d_lat = sr.get('LastKnownLatitude')
            d_lon = sr.get('LastKnownLongitude')

            has_gps = d_lat is not None and d_lon is not None
            if has_gps:
                d_lat, d_lon = float(d_lat), float(d_lon)

            d_skills = set(driver_skills.get(d_id, []))
            has_skills = required_skills.issubset(d_skills) if required_skills else True
            dist = haversine(d_lat, d_lon, sa_lat, sa_lon) if has_gps else None
            eligible = has_gps and has_skills

            evaluations.append({
                'driver_id': d_id,
                'name': d_name,
                'eff_lat': d_lat if has_gps else None,
                'eff_lon': d_lon if has_gps else None,
                'distance': dist,
                'has_gps': has_gps,
                'has_skills': has_skills,
                'skills': list(d_skills),
                'eligible': eligible,
                'is_actual': d_id == actual_driver_id,
                'territory_type': member.get('TerritoryType', '?'),
            })

        eligible_list = [e for e in evaluations if e['eligible'] and e['distance'] is not None]
        closest = min(eligible_list, key=lambda e: e['distance']) if eligible_list else None
        closest_id = closest['driver_id'] if closest else None

        for e in evaluations:
            e['is_closest'] = (e['driver_id'] == closest_id) if closest_id else False

        actual_eval = next((e for e in evaluations if e['is_actual']), None)
        actual_dist = actual_eval['distance'] if actual_eval else None
        closest_dist = closest['distance'] if closest else None
        if actual_driver_id and closest_id:
            closest_picked = actual_driver_id == closest_id
            extra_miles = round(actual_dist - closest_dist, 1) if actual_dist and closest_dist else None
        else:
            closest_picked = None
            extra_miles = None

        cd = _parse_dt(sa.get('CreatedDate'))
        et = _to_eastern(sa.get('CreatedDate'))
        ss = _parse_dt(sa.get('SchedStartTime'))
        sched_et = _to_eastern(sa.get('SchedStartTime'))
        ast = _parse_dt(sa.get('ActualStartTime'))
        start_et = _to_eastern(sa.get('ActualStartTime'))
        aet = _parse_dt(sa.get('ActualEndTime'))
        end_et = _to_eastern(sa.get('ActualEndTime'))

        response_min = None
        if cd and ast:
            diff = (ast - cd).total_seconds() / 60
            if 0 < diff < 1440:
                response_min = round(diff)

        dispatch_min = None
        if cd and ss:
            diff = (ss - cd).total_seconds() / 60
            if 0 <= diff < 1440:
                dispatch_min = round(diff)

        service_min = None
        if ast and aet:
            diff = (aet - ast).total_seconds() / 60
            if 0 < diff < 1440:
                service_min = round(diff)

        total_min = None
        if cd and aet:
            diff = (aet - cd).total_seconds() / 60
            if 0 < diff < 1440:
                total_min = round(diff)

        disp_lat = sa.get('ERS_Dispatched_Geolocation__Latitude__s')
        disp_lon = sa.get('ERS_Dispatched_Geolocation__Longitude__s')
        if disp_lat: disp_lat = float(disp_lat)
        if disp_lon: disp_lon = float(disp_lon)
        disp_to_sa_dist = haversine(disp_lat, disp_lon, sa_lat, sa_lon) if disp_lat and disp_lon else None

        pta = sa.get('ERS_PTA__c')
        sla_met = response_min is not None and response_min <= 45
        pta_met = pta is not None and response_min is not None and response_min <= float(pta)

        results.append({
            'sa_id': sa['Id'],
            'appointment_number': sa.get('AppointmentNumber', '?'),
            'status': sa.get('Status'),
            'work_type': wt_name,
            'created_time': et.strftime('%I:%M %p') if et else '?',
            'created_dt': cd.isoformat() if cd else None,
            'address': f"{sa.get('Street') or ''} {sa.get('City') or ''}".strip(),
            'sa_lat': sa_lat,
            'sa_lon': sa_lon,
            'actual_driver': actual_driver_name,
            'actual_driver_id': actual_driver_id,
            'actual_distance': actual_dist,
            'truck_id': truck_id,
            'closest_driver': closest['name'] if closest else '?',
            'closest_driver_id': closest_id,
            'closest_distance': closest_dist,
            'closest_picked': closest_picked,
            'extra_miles': extra_miles,
            'facility_distance': haversine(
                territory.get('lat'), territory.get('lon'), sa_lat, sa_lon),
            'facility_lat': territory.get('lat'),
            'facility_lon': territory.get('lon'),
            'drivers': evaluations,
            'eligible_count': len(eligible_list),
            'total_drivers': len(evaluations),
            'timeline': {
                'created': et.strftime('%I:%M %p') if et else None,
                'scheduled': sched_et.strftime('%I:%M %p') if sched_et else None,
                'on_location': start_et.strftime('%I:%M %p') if start_et else None,
                'completed': end_et.strftime('%I:%M %p') if end_et else None,
                'dispatch_min': dispatch_min,
                'response_min': response_min,
                'service_min': service_min,
                'total_min': total_min,
                'pta_promised': float(pta) if pta else None,
                'sla_met': sla_met,
                'pta_met': pta_met,
                'dispatch_method': sa.get('ERS_Dispatch_Method__c') or 'Unknown',
                'auto_assign': sa.get('ERS_Auto_Assign__c'),
                'schedule_mode': 'Unknown',
                'cancel_reason': sa.get('ERS_Cancellation_Reason__c'),
                'duration_planned': sa.get('FSL__Duration_In_Minutes__c'),
                'dispatched_lat': disp_lat,
                'dispatched_lon': disp_lon,
                'dispatched_distance': disp_to_sa_dist,
            },
            'required_skills': list(required_skills),
        })

    return results
