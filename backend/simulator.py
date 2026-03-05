"""Dispatch simulation engine — fast version using LastKnown positions.

For each SA on a given day, determines:
  - Which driver was actually assigned
  - Which driver was closest (by distance using LastKnown GPS)
  - Whether the closest driver was picked
"""

import math
from datetime import datetime, timedelta
from collections import defaultdict
from sf_client import sf_query_all, sf_query


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
    try:
        return datetime.fromisoformat(
            dt_str.replace('+0000', '+00:00').replace('Z', '+00:00'))
    except Exception:
        return None


def _to_eastern(dt_str):
    dt = _parse_dt(dt_str)
    return (dt - timedelta(hours=5)) if dt else None


def simulate_day(territory_id: str, date_str: str) -> list[dict]:
    """Fast simulation: SA list + driver distances using LastKnown GPS."""

    # 1. SAs for the day — all narrative fields
    sas = sf_query_all(f"""
        SELECT Id, AppointmentNumber, Status, CreatedDate,
               SchedStartTime, ActualStartTime, ActualEndTime,
               Street, City, State, Latitude, Longitude,
               ServiceTerritoryId, ServiceTerritory.Name,
               ServiceTerritory.Latitude, ServiceTerritory.Longitude,
               WorkType.Name, Off_Platform_Truck_Id__c,
               ERS_PTA__c, ERS_Dispatch_Method__c, ERS_Auto_Assign__c,
               FSL__Schedule_Mode__c, FSL__Auto_Schedule__c,
               ERS_Dispatched_Geolocation__c,
               ERS_Cancellation_Reason__c,
               FSL__Duration_In_Minutes__c
        FROM ServiceAppointment
        WHERE ServiceTerritoryId = '{territory_id}'
          AND CreatedDate >= {date_str}T00:00:00Z
          AND CreatedDate <= {date_str}T23:59:59Z
          AND Status IN ('Dispatched', 'Completed', 'Canceled',
                         'Cancel Call - Service Not En Route', 'Cancel Call - Service En Route',
                         'Unable to Complete', 'Assigned', 'No-Show')
        ORDER BY CreatedDate ASC
    """)

    if not sas:
        return []

    # Territory info
    territory = {
        'Id': territory_id,
        'Name': (sas[0].get('ServiceTerritory') or {}).get('Name', '?'),
        'Latitude': (sas[0].get('ServiceTerritory') or {}).get('Latitude'),
        'Longitude': (sas[0].get('ServiceTerritory') or {}).get('Longitude'),
    }

    # 2. Territory members with LastKnown GPS (single query)
    members = sf_query_all(f"""
        SELECT ServiceResourceId, ServiceResource.Name,
               ServiceResource.LastKnownLatitude, ServiceResource.LastKnownLongitude,
               ServiceResource.LastKnownLocationDate, TerritoryType
        FROM ServiceTerritoryMember
        WHERE ServiceTerritoryId = '{territory_id}'
    """)
    members = [m for m in members
               if not (m.get('ServiceResource') or {}).get('Name', '').lower().startswith('towbook')]

    driver_ids = list(set(m['ServiceResourceId'] for m in members))

    # 3. Driver skills (batched)
    driver_skills = defaultdict(set)
    for i in range(0, len(driver_ids), 40):
        batch = driver_ids[i:i+40]
        id_list = ",".join(f"'{d}'" for d in batch)
        recs = sf_query_all(f"""
            SELECT ServiceResourceId, Skill.MasterLabel
            FROM ServiceResourceSkill WHERE ServiceResourceId IN ({id_list})
        """)
        for r in recs:
            driver_skills[r['ServiceResourceId']].add(r['Skill']['MasterLabel'])

    # 4. Work type skills (for matching)
    wt_skills = {}
    wts = sf_query("SELECT Id, Name FROM WorkType")
    for w in wts.get('records', []):
        skills_q = sf_query(
            f"SELECT Skill.MasterLabel FROM SkillRequirement "
            f"WHERE RelatedRecordId = '{w['Id']}'")
        wt_skills[w['Name']] = [s['Skill']['MasterLabel']
                                for s in skills_q.get('records', [])]

    # 5. Simulate each SA
    results = []
    for sa in sas:
        sa_lat = sa.get('Latitude')
        sa_lon = sa.get('Longitude')
        if not sa_lat or not sa_lon:
            continue

        wt_name = (sa.get('WorkType') or {}).get('Name', '')
        required_skills = set(wt_skills.get(wt_name, []))

        # Use Off_Platform_Truck_Id__c as the actual truck dispatched
        truck_id = sa.get('Off_Platform_Truck_Id__c') or ''
        # Extract short truck label (e.g., "076DO-191666" → "Truck 191666")
        truck_label = f"Truck {truck_id.split('-')[-1]}" if truck_id else 'No Truck ID'
        actual_driver_id = None  # Towbook-dispatched, no SF driver ID
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
                d_lat = float(d_lat)
                d_lon = float(d_lon)

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
        # If no actual driver ID (Towbook dispatch), we can't determine if closest was picked
        if actual_driver_id and closest_id:
            closest_picked = actual_driver_id == closest_id
            extra_miles = round(actual_dist - closest_dist, 1) if actual_dist and closest_dist else None
        else:
            closest_picked = None  # Unknown — dispatched via external system
            extra_miles = None

        et = _to_eastern(sa.get('CreatedDate'))
        sched_et = _to_eastern(sa.get('SchedStartTime'))
        start_et = _to_eastern(sa.get('ActualStartTime'))
        end_et = _to_eastern(sa.get('ActualEndTime'))

        # Timeline calculations
        response_min = None
        if et and start_et:
            diff = (start_et - et).total_seconds() / 60
            if 0 < diff < 1440:
                response_min = round(diff)

        dispatch_min = None
        if et and sched_et:
            diff = (sched_et - et).total_seconds() / 60
            if 0 <= diff < 1440:
                dispatch_min = round(diff)

        service_min = None
        if start_et and end_et:
            diff = (end_et - start_et).total_seconds() / 60
            if 0 < diff < 1440:
                service_min = round(diff)

        total_min = None
        if et and end_et:
            diff = (end_et - et).total_seconds() / 60
            if 0 < diff < 1440:
                total_min = round(diff)

        # Dispatched GPS (where truck was when dispatched)
        disp_geo = sa.get('ERS_Dispatched_Geolocation__c') or {}
        disp_lat = disp_geo.get('latitude')
        disp_lon = disp_geo.get('longitude')
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
            'created_dt': sa.get('CreatedDate'),
            'address': f"{sa.get('Street', '')} {sa.get('City', '')}".strip(),
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
                territory.get('Latitude'), territory.get('Longitude'), sa_lat, sa_lon),
            'facility_lat': territory.get('Latitude'),
            'facility_lon': territory.get('Longitude'),
            'drivers': evaluations,
            'eligible_count': len(eligible_list),
            'total_drivers': len(evaluations),
            # Narrative timeline
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
                'schedule_mode': sa.get('FSL__Schedule_Mode__c') or 'Unknown',
                'cancel_reason': sa.get('ERS_Cancellation_Reason__c'),
                'duration_planned': sa.get('FSL__Duration_In_Minutes__c'),
                'dispatched_lat': disp_lat,
                'dispatched_lon': disp_lon,
                'dispatched_distance': disp_to_sa_dist,
            },
            'required_skills': list(required_skills),
        })

    return results
