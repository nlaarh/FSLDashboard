"""FSL App — FastAPI backend serving garage schedules, scorecards, and dispatch simulation."""

import os, sys, re, requests as _requests
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# WMO weather interpretation codes (Open-Meteo standard)
_WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm+hail", 99: "Thunderstorm+heavy hail",
}


def _parse_kml_coords(kml: str) -> list:
    """Extract [[lon, lat], ...] from a KML string."""
    m = re.search(r'<coordinates[^>]*>(.*?)</coordinates>', kml, re.DOTALL | re.IGNORECASE)
    if not m:
        return []
    coords = []
    for point in m.group(1).strip().split():
        parts = point.split(',')
        if len(parts) >= 2:
            try:
                coords.append([float(parts[0]), float(parts[1])])
            except ValueError:
                pass
    return coords

from sf_client import sf_query, sf_query_all, refresh_auth
from scheduler import generate_schedule
from simulator import simulate_day, haversine, _to_eastern
from scorer import compute_score
import cache

app = FastAPI(title="FSL App", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok"}


# ── Garages ──────────────────────────────────────────────────────────────────

@app.get("/api/garages")
def list_garages():
    """List roadside garages — territories with recent SA volume."""
    recs = sf_query_all("""
        SELECT ServiceTerritoryId, ServiceTerritory.Name, COUNT(Id) cnt
        FROM ServiceAppointment
        WHERE CreatedDate = LAST_N_DAYS:28
          AND ServiceTerritoryId != NULL
          AND Status IN ('Dispatched', 'Completed', 'Assigned')
        GROUP BY ServiceTerritoryId, ServiceTerritory.Name
        ORDER BY COUNT(Id) DESC
    """)
    # Get territory details (lat/lon)
    t_ids = [r['ServiceTerritoryId'] for r in recs if r.get('ServiceTerritoryId')]
    territories = {}
    if t_ids:
        for i in range(0, len(t_ids), 50):
            batch = t_ids[i:i+50]
            id_list = ",".join(f"'{t}'" for t in batch)
            details = sf_query_all(f"""
                SELECT Id, Name, Street, City, State, PostalCode,
                       Latitude, Longitude, IsActive
                FROM ServiceTerritory
                WHERE Id IN ({id_list})
            """)
            for d in details:
                territories[d['Id']] = d

    garages = []
    for r in recs:
        tid = r['ServiceTerritoryId']
        t = territories.get(tid, {})
        garages.append({
            'id': tid,
            'name': (r.get('ServiceTerritory') or {}).get('Name', t.get('Name', '?')),
            'sa_count_28d': r.get('cnt', 0),
            'city': t.get('City'),
            'state': t.get('State'),
            'lat': t.get('Latitude'),
            'lon': t.get('Longitude'),
            'active': t.get('IsActive', True),
        })
    return garages


# ── Schedule ─────────────────────────────────────────────────────────────────

@app.get("/api/garages/{territory_id}/schedule")
def get_schedule(territory_id: str,
                 weeks: int = Query(4, ge=1, le=12),
                 start_date: str = Query(None),
                 end_date: str = Query(None)):
    """Generate dynamic schedule for a garage based on real SA data."""
    result = generate_schedule(territory_id, weeks,
                               start_date=start_date, end_date=end_date)
    if 'error' in result and not result.get('schedule'):
        raise HTTPException(status_code=404, detail=result['error'])
    return result


# ── Scorecard — Goal-Based Performance ───────────────────────────────────────

@app.get("/api/garages/{territory_id}/scorecard")
def get_scorecard(territory_id: str, weeks: int = Query(4, ge=1, le=12)):
    """Performance scorecard: SLA compliance, fleet capacity, and gap analysis."""
    days = weeks * 7

    # 1. SAs with PTA and timing data (cached 5 min)
    sas = cache.cached_query(f"scorecard_sas_{territory_id}_{days}", lambda: sf_query_all(f"""
        SELECT Id, CreatedDate, Status, WorkType.Name, WorkTypeId,
               ActualStartTime, ActualEndTime,
               ERS_PTA__c
        FROM ServiceAppointment
        WHERE ServiceTerritoryId = '{territory_id}'
          AND CreatedDate = LAST_N_DAYS:{days}
          AND Status IN ('Dispatched', 'Completed', 'Canceled', 'Assigned')
        ORDER BY CreatedDate ASC
    """), ttl=300)

    if not sas:
        raise HTTPException(status_code=404, detail="No SAs found")

    total = len(sas)
    completed = [s for s in sas if s.get('Status') == 'Completed']

    # 2. Fleet by type — query members + their assigned work type history
    members = sf_query_all(f"""
        SELECT ServiceResourceId, ServiceResource.Name, TerritoryType
        FROM ServiceTerritoryMember
        WHERE ServiceTerritoryId = '{territory_id}'
    """)
    members = [m for m in members
               if not (m.get('ServiceResource') or {}).get('Name', '').lower().startswith('towbook')]

    # Classify drivers by their actual SA work types (direct AssignedResource query — no GROUP BY)
    driver_ids = set(m['ServiceResourceId'] for m in members)

    # Build WorkTypeId → type map
    wt_map_q = sf_query("SELECT Id, Name FROM WorkType")
    tow_wt_ids = set(w['Id'] for w in wt_map_q.get('records', []) if 'tow' in w['Name'].lower())

    # Query AssignedResource directly (FLS allows this, just not GROUP BY with nested fields)
    ar_recs = sf_query_all(f"""
        SELECT ServiceResourceId, ServiceAppointment.WorkTypeId
        FROM AssignedResource
        WHERE ServiceAppointment.ServiceTerritoryId = '{territory_id}'
          AND ServiceAppointment.CreatedDate = LAST_N_DAYS:{days}
          AND ServiceAppointment.WorkTypeId != null
    """)

    tow_drivers = set()
    battery_light_drivers = set()
    driver_tow_ct = defaultdict(int)
    driver_other_ct = defaultdict(int)

    for r in ar_recs:
        did = r.get('ServiceResourceId')
        if not did:
            continue
        sa = r.get('ServiceAppointment') or {}
        wt_id = sa.get('WorkTypeId', '')
        if wt_id in tow_wt_ids:
            driver_tow_ct[did] += 1
        else:
            driver_other_ct[did] += 1

    for did in driver_ids:
        tc = driver_tow_ct.get(did, 0)
        oc = driver_other_ct.get(did, 0)
        if tc + oc == 0:
            continue
        if tc >= oc:
            tow_drivers.add(did)
        else:
            battery_light_drivers.add(did)

    classified = tow_drivers | battery_light_drivers
    unclassified = driver_ids - classified

    # Also count unique trucks (from Off_Platform_Truck_Id__c)
    truck_recs = sf_query_all(f"""
        SELECT Off_Platform_Truck_Id__c, WorkTypeId
        FROM ServiceAppointment
        WHERE ServiceTerritoryId = '{territory_id}'
          AND CreatedDate = LAST_N_DAYS:{days}
          AND Off_Platform_Truck_Id__c != null
    """)
    tow_trucks = set()
    other_trucks = set()
    for tr in truck_recs:
        tid = tr.get('Off_Platform_Truck_Id__c', '')
        if tr.get('WorkTypeId') in tow_wt_ids:
            tow_trucks.add(tid)
        else:
            other_trucks.add(tid)
    # Trucks that do both get classified by majority (already in both sets → keep in tow)
    pure_other_trucks = other_trucks - tow_trucks

    # 3. Work type volume split
    type_counts = defaultdict(int)
    for s in sas:
        wt = (s.get('WorkType') or {}).get('Name', 'Unknown')
        type_counts[wt] += 1

    tow_sa_count = sum(v for k, v in type_counts.items() if 'tow' in k.lower())
    batt_sa_count = sum(v for k, v in type_counts.items()
                        if k.lower() in ('battery', 'jumpstart'))
    light_sa_count = sum(v for k, v in type_counts.items()
                         if k.lower() in ('tire', 'lockout', 'locksmith', 'winch out',
                                          'fuel / miscellaneous', 'pvs'))

    # 4. SLA Analysis — 45-minute target
    pta_values = []
    pta_under_45 = 0
    pta_under_90 = 0
    response_times = []

    for s in sas:
        pta = s.get('ERS_PTA__c')
        if pta is not None:
            pv = float(pta)
            pta_values.append(pv)
            if pv <= 45:
                pta_under_45 += 1
            if pv <= 90:
                pta_under_90 += 1

    for s in completed:
        created = _to_eastern(s.get('CreatedDate'))
        started = _to_eastern(s.get('ActualStartTime'))
        if created and started:
            diff = (started - created).total_seconds() / 60
            if 0 < diff < 1440:
                response_times.append(diff)

    median_pta = round(sorted(pta_values)[len(pta_values)//2]) if pta_values else None
    median_response = round(sorted(response_times)[len(response_times)//2]) if response_times else None
    avg_response = round(sum(response_times)/len(response_times)) if response_times else None
    resp_under_45 = sum(1 for r in response_times if r <= 45)

    # PTA buckets
    pta_buckets = []
    ranges = [('Under 45 min', 0, 45), ('45-90 min', 45, 90), ('90-120 min', 90, 120),
              ('2-3 hours', 120, 180), ('3+ hours', 180, 999), ('No ETA (999)', 999, 10000)]
    for label, lo, hi in ranges:
        ct = sum(1 for v in pta_values if lo < v <= hi) if lo > 0 else sum(1 for v in pta_values if v <= hi)
        if lo == 999:
            ct = sum(1 for v in pta_values if v >= 999)
        elif lo == 180:
            ct = sum(1 for v in pta_values if 180 < v < 999)
        pta_buckets.append({'label': label, 'count': ct,
                            'pct': round(100*ct/max(len(pta_values),1), 1)})

    no_pta = total - len(pta_values)
    if no_pta > 0:
        pta_buckets.append({'label': 'No PTA set', 'count': no_pta,
                            'pct': round(100*no_pta/max(total,1), 1)})

    # 5. Volume by DOW (for demand analysis)
    dow_volume = defaultdict(int)
    for s in sas:
        et = _to_eastern(s.get('CreatedDate'))
        if et:
            dow_volume[et.strftime('%a')] += 1

    # Scale to weekly average
    n_weeks = max(weeks, 1)
    dow_avg = {d: round(v / n_weeks) for d, v in dow_volume.items()}

    return {
        'sla': {
            'target_minutes': 45,
            'pta_compliance_45min': round(100*pta_under_45/max(len(pta_values),1), 1),
            'pta_compliance_90min': round(100*pta_under_90/max(len(pta_values),1), 1),
            'median_pta_promised': median_pta,
            'actual_median_response': median_response,
            'actual_avg_response': avg_response,
            'actual_under_45min': resp_under_45,
            'actual_under_45min_pct': round(100*resp_under_45/max(len(response_times),1), 1),
            'response_sample_size': len(response_times),
            'gap_vs_target': (median_response - 45) if median_response else None,
            'pta_buckets': pta_buckets,
        },
        'fleet': {
            'total_members': len(members),
            'tow_drivers': len(tow_drivers),
            'battery_light_drivers': len(battery_light_drivers),
            'unclassified': len(unclassified),
            'tow_trucks': len(tow_trucks),
            'other_trucks': len(pure_other_trucks),
            'total_trucks': len(tow_trucks | pure_other_trucks),
        },
        'volume': {
            'total': total,
            'completed': len(completed),
            'daily_average': round(total / max(days, 1), 1),
            'weekly_average': round(total / n_weeks),
            'tow_sas': tow_sa_count,
            'battery_sas': batt_sa_count,
            'light_sas': light_sa_count,
            'by_type': dict(type_counts),
            'by_dow': dow_avg,
        },
        'goals': [
            {
                'name': '45-Min Response SLA',
                'target': '45 min',
                'actual': f'{median_response} min' if median_response else 'N/A',
                'met': (median_response or 999) <= 45,
                'gap': f'+{round(median_response - 45)} min' if median_response and median_response > 45 else 'On target',
            },
            {
                'name': 'PTA Promise ≤ 45 min',
                'target': '100%',
                'actual': f'{round(100*pta_under_45/max(len(pta_values),1), 1)}%',
                'met': pta_under_45 == len(pta_values),
                'gap': f'Only {round(100*pta_under_45/max(len(pta_values),1), 1)}% promised ≤45 min',
            },
            {
                'name': 'Completion Rate',
                'target': '95%',
                'actual': f'{round(100*len(completed)/max(total,1), 1)}%',
                'met': len(completed)/max(total,1) >= 0.95,
                'gap': f'{round(100*len(completed)/max(total,1), 1)}%',
            },
        ],
    }


# ── Appointments (Day View) ─────────────────────────────────────────────────

@app.get("/api/garages/{territory_id}/appointments")
def get_appointments(territory_id: str, date: str = Query(...)):
    """Get all SAs for a territory on a specific date."""
    sas = sf_query_all(f"""
        SELECT Id, AppointmentNumber, Status, CreatedDate,
               SchedStartTime, ActualStartTime, ActualEndTime,
               Street, City, State, PostalCode, Latitude, Longitude,
               WorkType.Name,
               (SELECT ServiceResourceId, ServiceResource.Name FROM ServiceResources)
        FROM ServiceAppointment
        WHERE ServiceTerritoryId = '{territory_id}'
          AND CreatedDate >= {date}T00:00:00Z
          AND CreatedDate <= {date}T23:59:59Z
          AND Status IN ('Dispatched', 'Completed', 'Canceled', 'Assigned')
        ORDER BY CreatedDate ASC
    """)

    appointments = []
    for sa in sas:
        ars = (sa.get('ServiceResources') or {}).get('records', [])
        driver_name = (ars[0].get('ServiceResource') or {}).get('Name', '?') if ars else 'Unassigned'
        if driver_name.lower().startswith('towbook'):
            driver_name = f"Towbook ({driver_name})"

        et = _to_eastern(sa.get('CreatedDate'))
        appointments.append({
            'id': sa['Id'],
            'number': sa.get('AppointmentNumber', '?'),
            'status': sa.get('Status'),
            'work_type': (sa.get('WorkType') or {}).get('Name', '?'),
            'created_time': et.strftime('%I:%M %p') if et else '?',
            'address': f"{sa.get('Street', '')} {sa.get('City', '')}".strip(),
            'lat': sa.get('Latitude'),
            'lon': sa.get('Longitude'),
            'driver': driver_name,
        })
    return appointments


# ── Simulation ───────────────────────────────────────────────────────────────

@app.get("/api/garages/{territory_id}/simulate")
def run_simulation(territory_id: str, date: str = Query(...)):
    """Run full dispatch simulation for a territory on a specific date.
    Returns detailed driver analysis for each SA including closest driver.
    """
    results = simulate_day(territory_id, date)
    if not results:
        raise HTTPException(status_code=404, detail="No simulatable SAs found")

    # Summary stats
    total = len(results)
    # Separate known (actual driver in SF) from unknown (Towbook-dispatched)
    known = [r for r in results if r.get('closest_picked') is not None]
    unknown = [r for r in results if r.get('closest_picked') is None]
    closest_picked = sum(1 for r in known if r.get('closest_picked'))
    total_extra = sum(r.get('extra_miles', 0) or 0 for r in known if not r.get('closest_picked'))
    has_closest = [r for r in results if r.get('closest_distance') is not None]

    return {
        'results': results,
        'summary': {
            'total_sas': total,
            'closest_picked': closest_picked,
            'closest_pct': round(100 * closest_picked / max(len(known), 1), 1) if known else None,
            'known_assignments': len(known),
            'unknown_assignments': len(unknown),
            'wrong_decisions': len(known) - closest_picked if known else None,
            'total_extra_miles': round(total_extra, 1) if known else None,
            'avg_extra_miles': round(total_extra / max(len(known) - closest_picked, 1), 1) if known else None,
            'avg_closest_distance': round(sum(r['closest_distance'] for r in has_closest) / max(len(has_closest), 1), 1) if has_closest else None,
            'dispatched_via': 'Towbook' if len(unknown) > len(known) else 'Salesforce FSL',
        },
    }


# ── Performance Score ────────────────────────────────────────────────────────

@app.get("/api/garages/{territory_id}/score")
def get_score(territory_id: str, weeks: int = Query(4, ge=1, le=12)):
    """Compute composite performance score (0-100) across 8 dimensions."""
    result = compute_score(territory_id, weeks)
    if result.get('error'):
        raise HTTPException(status_code=404, detail=result['error'])
    return result


# ── Command Center — Live Territory Overview ─────────────────────────────────

@app.get("/api/command-center")
def command_center(hours: int = Query(24, ge=1, le=168)):
    """Live operational dashboard across all territories."""
    now_utc = datetime.now(timezone.utc)
    cutoff = (now_utc - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%SZ')

    sas = cache.cached_query(f"cc_sas_{hours}", lambda: sf_query_all(f"""
        SELECT Id, AppointmentNumber, Status, CreatedDate,
               ActualStartTime, SchedStartTime, Latitude, Longitude,
               PostalCode, Street, City,
               Account.Name, Account.Phone, Account.PersonMobilePhone,
               ServiceTerritoryId, ServiceTerritory.Name,
               ServiceTerritory.Latitude, ServiceTerritory.Longitude,
               WorkType.Name
        FROM ServiceAppointment
        WHERE CreatedDate >= {cutoff}
          AND ServiceTerritoryId != NULL
          AND Status IN ('Dispatched', 'Completed', 'Canceled',
                         'Cancel Call - Service Not En Route',
                         'Cancel Call - Service En Route',
                         'Unable to Complete', 'Assigned', 'No-Show')
        ORDER BY CreatedDate ASC
    """), ttl=120)

    # Group by territory
    by_territory = defaultdict(list)
    territory_meta = {}
    for sa in sas:
        tid = sa.get('ServiceTerritoryId')
        if not tid:
            continue
        by_territory[tid].append(sa)
        if tid not in territory_meta:
            t = sa.get('ServiceTerritory') or {}
            territory_meta[tid] = {
                'name': t.get('Name', '?'),
                'lat': t.get('Latitude'),
                'lon': t.get('Longitude'),
            }

    territories = []
    for tid, sa_list in by_territory.items():
        meta = territory_meta[tid]
        if not meta['lat'] or not meta['lon']:
            continue

        total = len(sa_list)
        open_list = [s for s in sa_list if s.get('Status') in ('Dispatched', 'Assigned')]
        completed = [s for s in sa_list if s.get('Status') == 'Completed']
        canceled = [s for s in sa_list
                     if s.get('Status') in ('Canceled', 'Cancel Call - Service Not En Route',
                                            'Cancel Call - Service En Route',
                                            'Unable to Complete', 'No-Show')]

        # Response times for completed SAs
        response_times = []
        for s in completed:
            c = _to_eastern(s.get('CreatedDate'))
            a = _to_eastern(s.get('ActualStartTime'))
            if c and a:
                diff = (a - c).total_seconds() / 60
                if 0 < diff < 1440:
                    response_times.append(diff)

        sla_pct = round(100 * sum(1 for r in response_times if r <= 45)
                        / max(len(response_times), 1)) if response_times else None
        avg_response = round(sum(response_times) / len(response_times)) if response_times else None
        completion_rate = round(100 * len(completed) / max(total, 1))

        # Wait times for open SAs
        open_waits = []
        for s in open_list:
            cdt = s.get('CreatedDate')
            if cdt:
                try:
                    created = datetime.fromisoformat(
                        cdt.replace('+0000', '+00:00').replace('Z', '+00:00'))
                    wt = (now_utc - created).total_seconds() / 60
                    if 0 < wt < 1440:
                        open_waits.append(round(wt))
                except Exception:
                    pass
        avg_wait = round(sum(open_waits) / len(open_waits)) if open_waits else 0
        max_wait = max(open_waits) if open_waits else 0

        # Health status
        if total < 3:
            status = 'good'
        elif avg_wait > 90 or (sla_pct is not None and sla_pct < 25):
            status = 'critical'
        elif avg_wait > 45 or (sla_pct is not None and sla_pct < 45) or completion_rate < 55:
            status = 'behind'
        else:
            status = 'good'

        # SA points for map
        sa_points = []
        for s in sa_list:
            lat, lon = s.get('Latitude'), s.get('Longitude')
            if lat and lon:
                et = _to_eastern(s.get('CreatedDate'))
                sa_points.append({
                    'lat': lat, 'lon': lon,
                    'status': s.get('Status'),
                    'work_type': (s.get('WorkType') or {}).get('Name', '?'),
                    'time': et.strftime('%I:%M %p') if et else '?',
                })

        territories.append({
            'id': tid, 'name': meta['name'],
            'lat': meta['lat'], 'lon': meta['lon'],
            'total': total, 'open': len(open_list),
            'completed': len(completed), 'canceled': len(canceled),
            'completion_rate': completion_rate,
            'sla_pct': sla_pct, 'avg_response': avg_response,
            'avg_wait': avg_wait, 'max_wait': max_wait,
            'status': status, 'sa_points': sa_points,
        })

    status_order = {'critical': 0, 'behind': 1, 'good': 2}
    territories.sort(key=lambda t: (status_order.get(t['status'], 3), -t['total']))

    # Collect ASAP open SAs with customer details for "longest waiting" panel
    # Filter out scheduled-for-later: if SchedStartTime > CreatedDate + 30 min, it's a scheduled appt
    open_customers = []
    for tid, sa_list in by_territory.items():
        meta = territory_meta[tid]
        for s in sa_list:
            if s.get('Status') not in ('Dispatched', 'Assigned'):
                continue

            cdt = s.get('CreatedDate')
            sched = s.get('SchedStartTime')
            wait_min = 0
            is_asap = True  # assume ASAP unless we can prove scheduled-for-later

            if cdt:
                try:
                    created = datetime.fromisoformat(
                        cdt.replace('+0000', '+00:00').replace('Z', '+00:00'))
                    wait_min = round((now_utc - created).total_seconds() / 60)
                    # Check if scheduled for later (SchedStart > Created + 30 min)
                    if sched:
                        sched_dt = datetime.fromisoformat(
                            sched.replace('+0000', '+00:00').replace('Z', '+00:00'))
                        gap_min = (sched_dt - created).total_seconds() / 60
                        if gap_min > 30:
                            is_asap = False
                except Exception:
                    pass

            if not is_asap:
                continue  # skip scheduled-for-later appointments

            acct = s.get('Account') or {}
            phone = acct.get('Phone') or acct.get('PersonMobilePhone') or ''
            open_customers.append({
                'number': s.get('AppointmentNumber', '?'),
                'customer': acct.get('Name') or '',
                'phone': phone,
                'zip': s.get('PostalCode') or '',
                'address': f"{s.get('Street') or ''} {s.get('City') or ''}".strip(),
                'wait_min': wait_min,
                'work_type': (s.get('WorkType') or {}).get('Name', '?'),
                'territory': meta['name'],
                'lat': s.get('Latitude'),
                'lon': s.get('Longitude'),
            })
    open_customers.sort(key=lambda x: x['wait_min'], reverse=True)

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
        },
        'hours': hours,
    }


# ── SA Lookup — Zoom-to with Driver Positions ────────────────────────────────

@app.get("/api/sa/{sa_number}")
def lookup_sa(sa_number: str):
    """Lookup an SA by AppointmentNumber and return driver positions."""
    sas = sf_query_all(f"""
        SELECT Id, AppointmentNumber, Status, CreatedDate,
               ActualStartTime, ActualEndTime,
               Latitude, Longitude, Street, City, State, PostalCode,
               Account.Name, Account.Phone, Account.PersonMobilePhone,
               WorkType.Name,
               ServiceTerritoryId, ServiceTerritory.Name,
               Off_Platform_Truck_Id__c, ERS_PTA__c,
               ERS_Dispatched_Geolocation__c
        FROM ServiceAppointment
        WHERE AppointmentNumber = '{sa_number}'
        LIMIT 1
    """)
    if not sas:
        raise HTTPException(status_code=404, detail=f"SA {sa_number} not found")

    sa = sas[0]
    tid = sa.get('ServiceTerritoryId')
    et = _to_eastern(sa.get('CreatedDate'))
    start_et = _to_eastern(sa.get('ActualStartTime'))
    end_et = _to_eastern(sa.get('ActualEndTime'))

    # Response time
    response_min = None
    if et and start_et:
        diff = (start_et - et).total_seconds() / 60
        if 0 < diff < 1440:
            response_min = round(diff)

    # Dispatched GPS
    disp_geo = sa.get('ERS_Dispatched_Geolocation__c') or {}
    disp_lat = disp_geo.get('latitude')
    disp_lon = disp_geo.get('longitude')

    acct = sa.get('Account') or {}
    cust_phone = acct.get('Phone') or acct.get('PersonMobilePhone') or ''

    result = {
        'sa': {
            'id': sa['Id'],
            'number': sa.get('AppointmentNumber'),
            'status': sa.get('Status'),
            'work_type': (sa.get('WorkType') or {}).get('Name', '?'),
            'customer': acct.get('Name', ''),
            'phone': cust_phone,
            'address': f"{sa.get('Street') or ''} {sa.get('City') or ''} {sa.get('State') or ''}".strip(),
            'zip': sa.get('PostalCode') or '',
            'lat': sa.get('Latitude'),
            'lon': sa.get('Longitude'),
            'territory': (sa.get('ServiceTerritory') or {}).get('Name', '?'),
            'territory_id': tid,
            'truck_id': sa.get('Off_Platform_Truck_Id__c') or '',
            'pta': sa.get('ERS_PTA__c'),
            'created': et.strftime('%I:%M %p') if et else '?',
            'started': start_et.strftime('%I:%M %p') if start_et else None,
            'completed': end_et.strftime('%I:%M %p') if end_et else None,
            'response_min': response_min,
            'dispatched_lat': disp_lat,
            'dispatched_lon': disp_lon,
        },
        'drivers': [],
    }

    # Get territory drivers with GPS if we have a territory
    if tid:
        members = sf_query_all(f"""
            SELECT ServiceResourceId, ServiceResource.Name,
                   ServiceResource.RelatedRecord.Phone,
                   ServiceResource.LastKnownLatitude,
                   ServiceResource.LastKnownLongitude,
                   ServiceResource.LastKnownLocationDate,
                   TerritoryType
            FROM ServiceTerritoryMember
            WHERE ServiceTerritoryId = '{tid}'
        """)
        members = [m for m in members
                    if not (m.get('ServiceResource') or {}).get('Name', '').lower().startswith('towbook')]

        sa_lat = sa.get('Latitude')
        sa_lon = sa.get('Longitude')

        for m in members:
            sr = m.get('ServiceResource') or {}
            d_lat = sr.get('LastKnownLatitude')
            d_lon = sr.get('LastKnownLongitude')
            dist = haversine(d_lat, d_lon, sa_lat, sa_lon) if d_lat and d_lon and sa_lat and sa_lon else None

            # Get current/next assignment for this driver
            driver_id = m['ServiceResourceId']
            current_jobs = sf_query_all(f"""
                SELECT AppointmentNumber, Status, Street, City,
                       Latitude, Longitude,
                       WorkType.Name, SchedStartTime
                FROM ServiceAppointment
                WHERE Id IN (
                    SELECT ServiceAppointmentId FROM AssignedResource
                    WHERE ServiceResourceId = '{driver_id}'
                )
                AND Status IN ('Dispatched', 'Assigned')
                ORDER BY SchedStartTime ASC
                LIMIT 2
            """)

            next_job = None
            if current_jobs:
                j = current_jobs[0]
                sched = _to_eastern(j.get('SchedStartTime'))
                next_job = {
                    'number': j.get('AppointmentNumber'),
                    'status': j.get('Status'),
                    'address': f"{j.get('Street') or ''} {j.get('City') or ''}".strip(),
                    'work_type': (j.get('WorkType') or {}).get('Name', '?'),
                    'sched_time': sched.strftime('%I:%M %p') if sched else '?',
                    'lat': j.get('Latitude'),
                    'lon': j.get('Longitude'),
                }

            gps_date = _to_eastern(sr.get('LastKnownLocationDate'))
            result['drivers'].append({
                'id': driver_id,
                'name': sr.get('Name', '?'),
                'phone': (sr.get('RelatedRecord') or {}).get('Phone') or '',
                'lat': float(d_lat) if d_lat else None,
                'lon': float(d_lon) if d_lon else None,
                'gps_time': gps_date.strftime('%I:%M %p') if gps_date else '?',
                'distance': dist,
                'territory_type': m.get('TerritoryType', '?'),
                'next_job': next_job,
            })

        # Sort by distance
        result['drivers'].sort(key=lambda d: d.get('distance') or 9999)

    return result


# ── Map — Grid Boundaries ────────────────────────────────────────────────────

@app.get("/api/map/grids")
def get_map_grids():
    """All FSL polygon boundaries as GeoJSON FeatureCollection (cached 1 hour)."""
    def _fetch():
        recs = sf_query_all("""
            SELECT Id, Name,
                   FSL__KML__c,
                   FSL__Service_Territory__c,
                   FSL__Service_Territory__r.Name,
                   FSL__Color__c
            FROM FSL__Polygon__c
            ORDER BY Name
        """)
        features = []
        for rec in recs:
            kml = rec.get('FSL__KML__c') or ''
            if not kml:
                continue
            coords = _parse_kml_coords(kml)
            if len(coords) < 3:
                continue
            st = rec.get('FSL__Service_Territory__r') or {}
            color = rec.get('FSL__Color__c') or '#818cf8'
            features.append({
                'type': 'Feature',
                'properties': {
                    'id': rec['Id'],
                    'name': rec.get('Name', ''),
                    'territory_name': st.get('Name', ''),
                    'territory_id': rec.get('FSL__Service_Territory__c', ''),
                    'color': color,
                },
                'geometry': {
                    'type': 'Polygon',
                    'coordinates': [coords],
                },
            })
        return {'type': 'FeatureCollection', 'features': features}

    return cache.cached_query('map_grids', _fetch, ttl=3600)


# ── Map — Driver GPS Positions ────────────────────────────────────────────────

@app.get("/api/map/drivers")
def get_map_drivers():
    """Active drivers with last known GPS positions (cached 2 minutes)."""
    def _fetch():
        drivers = sf_query_all("""
            SELECT Id, Name,
                   LastKnownLatitude, LastKnownLongitude, LastKnownLocationDate,
                   ERS_Driver_Type__c
            FROM ServiceResource
            WHERE IsActive = true
              AND ResourceType = 'T'
              AND LastKnownLatitude != null
            ORDER BY Name
        """)
        drivers = [d for d in drivers if not d.get('Name', '').lower().startswith('towbook')]
        result = []
        for d in drivers:
            gps_date = _to_eastern(d.get('LastKnownLocationDate'))
            result.append({
                'id': d['Id'],
                'name': d.get('Name', '?'),
                'lat': float(d['LastKnownLatitude']),
                'lon': float(d['LastKnownLongitude']),
                'gps_time': gps_date.strftime('%I:%M %p') if gps_date else '?',
                'driver_type': d.get('ERS_Driver_Type__c', ''),
            })
        return result

    return cache.cached_query('map_drivers', _fetch, ttl=120)


# ── Map — Weather ─────────────────────────────────────────────────────────────

@app.get("/api/map/weather")
def get_map_weather():
    """Current weather at Buffalo, Rochester, Syracuse from Open-Meteo (cached 15 min)."""
    def _fetch():
        stations = [
            {'name': 'Buffalo',   'lat': 42.89, 'lon': -78.86},
            {'name': 'Rochester', 'lat': 43.15, 'lon': -77.61},
            {'name': 'Syracuse',  'lat': 43.05, 'lon': -76.15},
        ]
        results = []
        for s in stations:
            try:
                r = _requests.get(
                    'https://api.open-meteo.com/v1/forecast',
                    params={
                        'latitude': s['lat'],
                        'longitude': s['lon'],
                        'current': 'temperature_2m,precipitation,snowfall,weathercode,windspeed_10m',
                        'temperature_unit': 'fahrenheit',
                        'timezone': 'America/New_York',
                        'forecast_days': 1,
                    },
                    timeout=10,
                )
                if r.status_code == 200:
                    cur = r.json().get('current', {})
                    wcode = cur.get('weathercode', 0)
                    results.append({
                        **s,
                        'temp_f': round(cur.get('temperature_2m', 0)),
                        'precip': round(cur.get('precipitation', 0), 2),
                        'snow': round(cur.get('snowfall', 0), 2),
                        'wind': round(cur.get('windspeed_10m', 0)),
                        'weather_code': wcode,
                        'condition': _WMO_CODES.get(wcode, 'Unknown'),
                    })
                else:
                    results.append({**s, 'error': f'HTTP {r.status_code}'})
            except Exception as e:
                results.append({**s, 'error': str(e)})
        return results

    return cache.cached_query('map_weather', _fetch, ttl=900)


# ── Cache Control ────────────────────────────────────────────────────────────

@app.post("/api/cache/clear")
def clear_cache():
    """Clear all cached data."""
    cache.invalidate()
    return {"status": "cleared"}


# ── Run ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
