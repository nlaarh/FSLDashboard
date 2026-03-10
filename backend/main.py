"""FSL App — FastAPI backend. All data live from Salesforce with in-memory caching."""

import os, sys, re, requests as _requests
sys.path.insert(0, os.path.dirname(__file__))

import hashlib, hmac, secrets, time, json as _json
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, JSONResponse
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo
from collections import defaultdict

_ET = ZoneInfo('America/New_York')

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
    dt = _parse_dt(dt_str)
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_ET)


from sf_client import sf_query_all, sf_parallel, get_stats as sf_stats, sanitize_soql
from scheduler import generate_schedule
from simulator import simulate_day, haversine
from scorer import compute_score
from ops import get_ops_territories, get_ops_territory_detail, get_ops_garages
import users
from dispatch import (
    get_live_queue, recommend_drivers, get_cascade_status,
    get_response_decomposition, get_forecast,
)
import cache

app = FastAPI(title="FSL App", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Admin Auth (SSO bypass) ──────────────────────────────────────────────────
_ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
_ADMIN_PASS = os.environ.get("ADMIN_PASSWORD", "admin2026!@")
_AUTH_SECRET = os.environ.get("AUTH_SECRET", secrets.token_hex(32))
_PUBLIC_PATHS = {"/login", "/api/auth/login", "/api/health", "/favicon.ico"}


def _sign_cookie(payload: str) -> str:
    sig = hmac.new(_AUTH_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _verify_cookie(cookie: str) -> str | None:
    if not cookie or "." not in cookie:
        return None
    payload, sig = cookie.rsplit(".", 1)
    expected = hmac.new(_AUTH_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(sig, expected):
        return payload
    return None


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Always allow public paths and static assets
    if path in _PUBLIC_PATHS or path.startswith("/assets/"):
        return await call_next(request)
    # Azure Easy Auth: if SSO is active, this header is set by Azure
    if request.headers.get("x-ms-client-principal"):
        return await call_next(request)
    # Admin cookie
    cookie = request.cookies.get("fslapp_auth")
    if cookie and _verify_cookie(cookie):
        return await call_next(request)
    # Local dev: no auth needed
    if os.environ.get("WEBSITE_SITE_NAME") is None:
        return await call_next(request)
    # Not authenticated → redirect to login
    if path.startswith("/api/"):
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    return RedirectResponse("/login")


_LOGIN_HTML = """<!DOCTYPE html>
<html><head><title>FSLAPP Login</title>
<style>
body{font-family:system-ui;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;background:#f0f2f5}
.card{background:#fff;padding:2.5rem;border-radius:12px;box-shadow:0 4px 16px rgba(0,0,0,.1);width:360px}
h2{margin:0 0 .5rem;text-align:center;color:#1a1a2e;font-size:1.4rem}
.subtitle{text-align:center;color:#666;margin-bottom:2rem;font-size:.9rem}
input{width:100%;padding:.6rem;margin:.3rem 0 .8rem;border:1px solid #ddd;border-radius:4px;box-sizing:border-box;font-size:.95rem}
.login-btn{width:100%;padding:.7rem;background:#333;color:#fff;border:none;border-radius:6px;font-size:.95rem;cursor:pointer}
.login-btn:hover{background:#555}
.err{color:#cc0000;text-align:center;margin-bottom:.8rem;font-size:.9rem}
</style></head>
<body><div class="card">
<h2>FSLAPP</h2>
<div class="subtitle">Field Service Lightning Analytics</div>
<div class="err" id="err"></div>
<form onsubmit="return doLogin(event)">
<input name="username" placeholder="Username" required>
<input name="password" type="password" placeholder="Password" required>
<button type="submit" class="login-btn">Sign In</button>
</form>
</div>
<script>
async function doLogin(e){e.preventDefault();
const f=new FormData(e.target);
const r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({username:f.get('username'),password:f.get('password')})});
if(r.ok){window.location.href='/'}
else{document.getElementById('err').textContent='Invalid credentials'}}
</script></body></html>"""


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return _LOGIN_HTML


@app.post("/api/auth/login")
def admin_login(request: Request, creds: dict, response: Response):
    user = users.authenticate(creds.get("username", ""), creds.get("password", ""))
    if user:
        token = users.create_session(user["username"], user["role"], user["name"])
        payload = f"{user['username']}:{user['role']}:{token}"
        response.set_cookie("fslapp_auth", _sign_cookie(payload), httponly=True, samesite="lax", max_age=86400)
        return {"ok": True, "user": user["username"], "name": user["name"], "role": user["role"]}
    raise HTTPException(status_code=401, detail="Invalid credentials")


@app.get("/api/auth/me")
def auth_me(request: Request):
    # Azure Easy Auth
    principal = request.headers.get("x-ms-client-principal-name")
    if principal:
        return {"user": principal, "method": "sso", "role": "admin", "name": principal}
    # Admin cookie
    cookie = request.cookies.get("fslapp_auth")
    payload = _verify_cookie(cookie) if cookie else None
    if payload:
        parts = payload.split(":")
        username = parts[0]
        role = parts[1] if len(parts) > 1 else "admin"
        name = username
        # Try to get session info for richer data
        if len(parts) > 2:
            sess = users.get_session(parts[2])
            if sess:
                name = sess.get("name", username)
                role = sess.get("role", role)
        return {"user": username, "name": name, "role": role, "method": "admin"}
    return {"user": "dev", "name": "Developer", "role": "admin", "method": "local"}


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response):
    cookie = request.cookies.get("fslapp_auth")
    payload = _verify_cookie(cookie) if cookie else None
    if payload:
        parts = payload.split(":")
        if len(parts) > 2:
            users.destroy_session(parts[2])
    response.delete_cookie("fslapp_auth")
    return {"ok": True}


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "db_seeded": True, "sync_in_progress": False,
            "cache": cache.stats(), "salesforce": sf_stats()}


# ── Compat endpoints (frontend expects these) ───────────────────────────────

@app.get("/api/db/status")
def db_status():
    return {"seeded": True, "db_size_mb": 0, "tables": [], "mode": "live_sf"}


@app.post("/api/sync")
def run_sync():
    cache.invalidate()
    return {"status": "cache_cleared", "message": "In-memory cache cleared. All data live from SF."}


# ── Daily Operations ──────────────────────────────────────────────────────────

@app.get("/api/ops/territories")
def ops_territories():
    """Today's operational view — all territories with correct PTA/ATA."""
    return get_ops_territories()


@app.get("/api/ops/territory/{territory_id}")
def ops_territory_detail(territory_id: str):
    """Today's SA list for a single territory with PTA/ATA per call."""
    territory_id = sanitize_soql(territory_id)
    return get_ops_territory_detail(territory_id)


@app.get("/api/ops/garages")
def ops_garages():
    """All garage territories with location, phone, and priority matrix info."""
    return get_ops_garages()


# ── Garages ──────────────────────────────────────────────────────────────────

@app.get("/api/garages")
def list_garages():
    """List roadside garages — territories with recent SA volume."""
    def _fetch():
        d28 = (date.today() - timedelta(days=28)).isoformat()
        data = sf_parallel(
            counts=lambda: sf_query_all(f"""
                SELECT ServiceTerritoryId, ServiceTerritory.Name, COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE CreatedDate >= {d28}T00:00:00Z
                  AND ServiceTerritoryId != null
                  AND Status IN ('Dispatched','Completed','Assigned')
                GROUP BY ServiceTerritoryId, ServiceTerritory.Name
                ORDER BY COUNT(Id) DESC
            """),
            territories=lambda: sf_query_all(
                "SELECT Id, Name, City, State, Latitude, Longitude, IsActive "
                "FROM ServiceTerritory WHERE IsActive = true"),
        )
        terr_map = {r['Id']: r for r in data['territories']}
        garages = []
        for r in data['counts']:
            tid = r.get('ServiceTerritoryId')
            t = terr_map.get(tid, {})
            garages.append({
                'id': tid,
                'name': (r.get('ServiceTerritory') or {}).get('Name') or t.get('Name', '?'),
                'sa_count_28d': r.get('cnt', 0),
                'city': t.get('City'),
                'state': t.get('State'),
                'lat': t.get('Latitude'),
                'lon': t.get('Longitude'),
                'active': t.get('IsActive', True),
            })
        return garages

    return cache.cached_query('garages_list', _fetch, ttl=600)


# ── Schedule ─────────────────────────────────────────────────────────────────

@app.get("/api/garages/{territory_id}/schedule")
def get_schedule(territory_id: str,
                 weeks: int = Query(4, ge=1, le=12),
                 start_date: str = Query(None),
                 end_date: str = Query(None)):
    territory_id = sanitize_soql(territory_id)
    if start_date:
        start_date = sanitize_soql(start_date)
    if end_date:
        end_date = sanitize_soql(end_date)
    cache_key = f"schedule_{territory_id}_{start_date or 'none'}_{end_date or 'none'}_{weeks}"
    result = cache.cached_query(
        cache_key,
        lambda: generate_schedule(territory_id, weeks, start_date=start_date, end_date=end_date),
        ttl=3600,
    )
    if 'error' in result and not result.get('schedule'):
        raise HTTPException(status_code=404, detail=result['error'])
    return result


# ── Scorecard — Goal-Based Performance ───────────────────────────────────────

@app.get("/api/garages/{territory_id}/scorecard")
def get_scorecard(territory_id: str, weeks: int = Query(4, ge=1, le=12)):
    """Performance scorecard: SLA compliance, fleet capacity, and gap analysis."""
    territory_id = sanitize_soql(territory_id)
    days = weeks * 7
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    since = f"{cutoff}T00:00:00Z"

    def _fetch():
        # Get member IDs first for skills query
        members_raw = sf_query_all(f"""
            SELECT ServiceResourceId, ServiceResource.Name, TerritoryType
            FROM ServiceTerritoryMember
            WHERE ServiceTerritoryId = '{territory_id}'
        """)
        members = [m for m in members_raw
                   if not ((m.get('ServiceResource') or {}).get('Name') or '').lower().startswith('towbook')]
        driver_ids = set(m['ServiceResourceId'] for m in members)
        id_list = ",".join(f"'{d}'" for d in driver_ids) if driver_ids else "'NONE'"

        # 6 parallel queries: volume, response times, skills, trucks, PTA aggregate, DOW
        data = sf_parallel(
            vol=lambda: sf_query_all(f"""
                SELECT WorkType.Name, Status, COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                  AND Status IN ('Dispatched','Completed','Canceled','Assigned')
                GROUP BY WorkType.Name, Status
            """),
            rt=lambda: sf_query_all(f"""
                SELECT CreatedDate, ActualStartTime, ERS_PTA__c, ERS_Dispatch_Method__c
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                  AND Status = 'Completed'
                  AND ActualStartTime != null
                  AND WorkType.Name != 'Tow Drop-Off'
                  AND ERS_Dispatch_Method__c = 'Field Services'
                ORDER BY CreatedDate DESC
                LIMIT 500
            """),
            skills=lambda: sf_query_all(f"""
                SELECT ServiceResourceId, Skill.MasterLabel
                FROM ServiceResourceSkill
                WHERE ServiceResourceId IN ({id_list})
            """),
            trucks=lambda: sf_query_all(f"""
                SELECT Off_Platform_Truck_Id__c, WorkType.Name, COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                  AND Off_Platform_Truck_Id__c != null
                GROUP BY Off_Platform_Truck_Id__c, WorkType.Name
            """),
            pta_agg=lambda: sf_query_all(f"""
                SELECT COUNT(Id) total,
                       AVG(ERS_PTA__c) avg_pta
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                  AND ERS_PTA__c != null AND ERS_PTA__c > 0 AND ERS_PTA__c < 999
                  AND Status IN ('Dispatched','Completed','Canceled','Assigned')
            """),
            dow=lambda: sf_query_all(f"""
                SELECT DAY_IN_WEEK(CreatedDate) dow, COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                  AND Status IN ('Dispatched','Completed','Canceled','Assigned')
                GROUP BY DAY_IN_WEEK(CreatedDate)
            """),
        )
        # Volume breakdown
        type_counts = defaultdict(int)
        total = 0
        completed_count = 0
        for r in data['vol']:
            wt = r.get('Name') or 'Unknown'  # Aggregate flattens WorkType.Name → Name
            status = r.get('Status')
            cnt = r.get('cnt', 0)
            type_counts[wt] += cnt
            total += cnt
            if status == 'Completed':
                completed_count += cnt

        if total == 0:
            raise HTTPException(status_code=404, detail="No SAs found")

        tow_sa_count = sum(v for k, v in type_counts.items() if 'tow' in k.lower())
        batt_sa_count = sum(v for k, v in type_counts.items() if k.lower() in ('battery', 'jumpstart'))
        light_sa_count = sum(v for k, v in type_counts.items()
                             if k.lower() in ('tire', 'lockout', 'locksmith', 'winch out', 'fuel / miscellaneous', 'pvs'))

        # Fleet classification from skills (Tow/Flat Bed/Wheel Lift = tow driver, else battery/light)
        tow_skill_names = {'tow', 'flat bed', 'wheel lift'}
        driver_skills = defaultdict(set)
        for r in data['skills']:
            sk = (r.get('Skill') or {}).get('MasterLabel', '')
            if sk:
                driver_skills[r['ServiceResourceId']].add(sk.lower())

        tow_drivers = set()
        battery_light_drivers = set()
        for did in driver_ids:
            skills = driver_skills.get(did, set())
            if not skills:
                continue
            if skills & tow_skill_names:
                tow_drivers.add(did)
            else:
                battery_light_drivers.add(did)
        classified = tow_drivers | battery_light_drivers
        unclassified = driver_ids - classified

        # Trucks
        tow_wt_names = set(k for k in type_counts if 'tow' in k.lower())
        tow_trucks = set()
        other_trucks = set()
        for tr in data['trucks']:
            tid_truck = tr.get('Off_Platform_Truck_Id__c', '')
            wt_n = tr.get('Name', '')  # Aggregate flattens WorkType.Name → Name
            if wt_n.lower() in [n.lower() for n in tow_wt_names]:
                tow_trucks.add(tid_truck)
            else:
                other_trucks.add(tid_truck)
        pure_other_trucks = other_trucks - tow_trucks

        # Response times + PTA from individual completed SAs
        pta_values = []
        pta_under_45 = 0
        pta_under_90 = 0
        response_times = []

        for s in data['rt']:
            created = _parse_dt(s.get('CreatedDate'))
            started = _parse_dt(s.get('ActualStartTime'))
            pta = s.get('ERS_PTA__c')

            if pta is not None:
                pv = float(pta)
                pta_values.append(pv)
                if pv <= 45:
                    pta_under_45 += 1
                if pv <= 90:
                    pta_under_90 += 1

            if created and started:
                diff = (started - created).total_seconds() / 60
                if 0 < diff < 480:
                    response_times.append(diff)

        # PTA aggregate for total PTA stats (all SAs, not just completed)
        pta_agg = data['pta_agg'][0] if data['pta_agg'] else {}
        total_with_pta = pta_agg.get('total', len(pta_values))
        avg_pta = pta_agg.get('avg_pta')
        median_pta = round(avg_pta) if avg_pta else None  # Use avg as proxy

        median_response = round(sorted(response_times)[len(response_times)//2]) if response_times else None
        avg_response = round(sum(response_times)/len(response_times)) if response_times else None
        resp_under_45 = sum(1 for r in response_times if r <= 45)

        # PTA buckets from completed SAs
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

        no_pta = total - int(total_with_pta or 0)
        if no_pta > 0:
            pta_buckets.append({'label': 'No PTA set', 'count': no_pta,
                                'pct': round(100*no_pta/max(total,1), 1)})

        # DOW volume from parallel aggregate
        dow_data = data['dow']
        # SOQL DOW: 1=Sun..7=Sat → Python strftime %a
        _DOW_MAP = {1: 'Sun', 2: 'Mon', 3: 'Tue', 4: 'Wed', 5: 'Thu', 6: 'Fri', 7: 'Sat'}
        dow_volume = {_DOW_MAP.get(int(r.get('dow', 0)), '?'): r.get('cnt', 0) for r in dow_data}
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
                'completed': completed_count,
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
                    'actual': f'{round(100*completed_count/max(total,1), 1)}%',
                    'met': completed_count/max(total,1) >= 0.95,
                    'gap': f'{round(100*completed_count/max(total,1), 1)}%',
                },
            ],
        }

    return cache.cached_query(f'scorecard_{territory_id}_{weeks}', _fetch, ttl=3600)


# ── Appointments (Day View) ─────────────────────────────────────────────────

@app.get("/api/garages/{territory_id}/appointments")
def get_appointments(territory_id: str, date_str: str = Query(..., alias='date')):
    """Get all SAs for a territory on a specific date."""
    territory_id = sanitize_soql(territory_id)
    date_str = sanitize_soql(date_str)
    def _fetch():
        next_day = (date.fromisoformat(date_str) + timedelta(days=1)).isoformat()
        sas = sf_query_all(f"""
            SELECT Id, AppointmentNumber, Status, CreatedDate,
                   SchedStartTime, ActualStartTime, ActualEndTime,
                   Street, City, State, PostalCode, Latitude, Longitude,
                   WorkType.Name,
                   (SELECT ServiceResource.Name FROM ServiceResources)
            FROM ServiceAppointment
            WHERE ServiceTerritoryId = '{territory_id}'
              AND CreatedDate >= {date_str}T00:00:00Z
              AND CreatedDate < {next_day}T00:00:00Z
              AND Status IN ('Dispatched','Completed','Canceled','Assigned')
            ORDER BY CreatedDate ASC
        """)

        appointments = []
        for sa in sas:
            ars = sa.get('ServiceResources')
            driver_name = 'Unassigned'
            if ars and ars.get('records'):
                sr = ars['records'][0].get('ServiceResource') or {}
                driver_name = sr.get('Name', 'Unassigned')
            if driver_name.lower().startswith('towbook'):
                driver_name = f"Towbook ({driver_name})"

            et = _to_eastern(sa.get('CreatedDate'))
            appointments.append({
                'id': sa['Id'],
                'number': sa.get('AppointmentNumber', '?'),
                'status': sa.get('Status'),
                'work_type': (sa.get('WorkType') or {}).get('Name', '?'),
                'created_time': et.strftime('%I:%M %p') if et else '?',
                'address': f"{sa.get('Street') or ''} {sa.get('City') or ''}".strip(),
                'lat': sa.get('Latitude'),
                'lon': sa.get('Longitude'),
                'driver': driver_name,
            })
        return appointments
    return cache.cached_query(f'appointments_{territory_id}_{date_str}', _fetch, ttl=120)


# ── Simulation ───────────────────────────────────────────────────────────────

@app.get("/api/garages/{territory_id}/simulate")
def run_simulation(territory_id: str, date_str: str = Query(..., alias='date')):
    territory_id = sanitize_soql(territory_id)
    date_str = sanitize_soql(date_str)
    def _fetch():
        results = simulate_day(territory_id, date_str)
        if not results:
            return None

        total = len(results)
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

    result = cache.cached_query(f'simulate_{territory_id}_{date_str}', _fetch, ttl=120)
    if result is None:
        raise HTTPException(status_code=404, detail="No simulatable SAs found")
    return result


# ── Performance Score ────────────────────────────────────────────────────────

@app.get("/api/garages/{territory_id}/score")
def get_score(territory_id: str, weeks: int = Query(4, ge=1, le=12)):
    territory_id = sanitize_soql(territory_id)
    result = compute_score(territory_id, weeks)
    if result.get('error'):
        raise HTTPException(status_code=404, detail=result['error'])
    return result


# ── Command Center — Live Territory Overview ─────────────────────────────────

@app.get("/api/command-center")
def command_center(hours: int = Query(24, ge=1, le=168)):
    """Live operational dashboard across all territories."""
    now_utc = datetime.now(timezone.utc)
    cutoff_utc = (now_utc - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%SZ')

    def _fetch():
        # Single query with territory relationship — ~1-2s for last 24h
        sas = sf_query_all(f"""
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
              AND Status IN ('Dispatched','Completed','Canceled',
                             'Cancel Call - Service Not En Route',
                             'Cancel Call - Service En Route',
                             'Unable to Complete','Assigned','No-Show')
            ORDER BY CreatedDate ASC
        """)

        # Group by territory
        by_territory = defaultdict(list)
        for sa in sas:
            tid = sa.get('ServiceTerritoryId')
            if tid:
                by_territory[tid].append(sa)

        territories = []
        for tid, sa_list in by_territory.items():
            st = (sa_list[0].get('ServiceTerritory') or {})
            t_lat = st.get('Latitude')
            t_lon = st.get('Longitude')
            t_name = st.get('Name') or '?'
            if not t_lat or not t_lon:
                continue

            total_t = len(sa_list)
            open_list = [s for s in sa_list if s.get('Status') in ('Dispatched', 'Assigned')]
            completed_list = [s for s in sa_list if s.get('Status') == 'Completed']
            canceled_list = [s for s in sa_list
                             if s.get('Status') in ('Canceled', 'Cancel Call - Service Not En Route',
                                                    'Cancel Call - Service En Route',
                                                    'Unable to Complete', 'No-Show')]

            response_times = []
            for s in completed_list:
                wt_name = (s.get('WorkType') or {}).get('Name', '') or ''
                if 'drop' in wt_name.lower():
                    continue
                c = _parse_dt(s.get('CreatedDate'))
                a = _parse_dt(s.get('ActualStartTime'))
                if c and a:
                    diff = (a - c).total_seconds() / 60
                    dispatch_method = s.get('ERS_Dispatch_Method__c', '')
                    if dispatch_method == 'Field Services':
                        if 0 < diff < 480:
                            response_times.append(diff)
                    else:
                        # Towbook: only trust if < 4 hours (midnight sync = 300+ min)
                        if 0 < diff < 240:
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
            for s in sa_list:
                lat, lon = s.get('Latitude'), s.get('Longitude')
                if lat and lon:
                    et = _to_eastern(s.get('CreatedDate'))
                    sa_points.append({
                        'lat': float(lat), 'lon': float(lon),
                        'status': s.get('Status'),
                        'work_type': (s.get('WorkType') or {}).get('Name', '?'),
                        'time': et.strftime('%I:%M %p') if et else '?',
                    })

            territories.append({
                'id': tid, 'name': t_name,
                'lat': t_lat, 'lon': t_lon,
                'total': total_t, 'open': len(open_list),
                'completed': len(completed_list), 'canceled': len(canceled_list),
                'completion_rate': completion_rate,
                'sla_pct': sla_pct, 'avg_response': avg_response,
                'avg_wait': avg_wait, 'max_wait': max_wait,
                'status': health_status, 'sa_points': sa_points,
            })

        status_order = {'critical': 0, 'behind': 1, 'good': 2}
        territories.sort(key=lambda t: (status_order.get(t['status'], 3), -t['total']))

        # Open customers
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

    return cache.cached_query(f'command_center_{hours}', _fetch, ttl=120)


# ── Ops Brief — Fleet Status + Coverage + Suggestions ────────────────────────

import math as _math

def _haversine_mi(lat1, lon1, lat2, lon2):
    R = 3958.8  # Earth radius in miles
    dlat = _math.radians(lat2 - lat1)
    dlon = _math.radians(lon2 - lon1)
    a = _math.sin(dlat/2)**2 + _math.cos(_math.radians(lat1)) * _math.cos(_math.radians(lat2)) * _math.sin(dlon/2)**2
    return round(R * 2 * _math.atan2(_math.sqrt(a), _math.sqrt(1-a)), 1)


# ── Skill hierarchy for driver-call matching ─────────────────────────────────
# 4 call types: Tow, Winch, Battery, Light (everything else)
# Driver tiers: Tow can do all 4. Light can do winch+light+battery. Battery only battery.
_TOW_CAPS = {'tow', 'flat bed', 'wheel lift'}
_BATTERY_CAPS = {'battery', 'battery service', 'jumpstart'}

def _driver_tier(truck_capabilities: str) -> str:
    """Classify driver tier from truck capabilities string (semicolon-separated)."""
    caps = {c.strip().lower() for c in (truck_capabilities or '').split(';') if c.strip()}
    if caps & _TOW_CAPS:
        return 'tow'
    if caps & _BATTERY_CAPS:
        # Has battery but NOT light-service items like Tire/Lockout → battery-only
        light_caps = {'tire', 'lockout', 'locksmith', 'fuel - gasoline', 'fuel - diesel',
                      'extrication- driveway', 'extrication- highway/roadway', 'winch'}
        if caps & light_caps:
            return 'light'
        return 'battery'
    # Has light-service caps (tire, lockout, etc.) but no tow and no battery
    return 'light'

def _call_tier(work_type: str) -> str:
    """Classify call tier from work type name. 4 types: tow, winch, battery, light."""
    wt = (work_type or '').lower()
    if 'tow' in wt:
        return 'tow'
    if 'winch' in wt or 'extrication' in wt:
        return 'winch'
    if wt in ('battery', 'jumpstart'):
        return 'battery'
    return 'light'

def _can_serve(driver_tier: str, call_tier: str) -> bool:
    """Check if a driver tier can serve a call tier (skill hierarchy)."""
    hierarchy = {
        'tow': {'tow', 'winch', 'light', 'battery'},
        'light': {'winch', 'light', 'battery'},
        'battery': {'battery'},
    }
    return call_tier in hierarchy.get(driver_tier, set())


@app.get("/api/ops/brief")
def ops_brief():
    """Proactive ops brief: fleet status, coverage gaps, demand, suggestions."""
    from ops import _get_priority_matrix

    def _fetch():
        now_utc = datetime.now(timezone.utc)
        now_et = now_utc.astimezone(_ET)
        today_start = now_et.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        cutoff = today_start.strftime('%Y-%m-%dT%H:%M:%SZ')

        # 1) Parallel fetch: drivers, active SAs, priority matrix, hourly baseline
        from sf_client import sf_parallel, sf_query_all as _sqa

        def _get_drivers():
            return _sqa("""
                SELECT Id, Name, LastKnownLatitude, LastKnownLongitude,
                       LastKnownLocationDate, ERS_Driver_Type__c, ERS_Tech_ID__c,
                       RelatedRecord.Phone
                FROM ServiceResource
                WHERE IsActive = true AND ResourceType = 'T'
                  AND LastKnownLatitude != null
            """)

        def _get_active_sas():
            return _sqa(f"""
                SELECT Id, AppointmentNumber, Status, CreatedDate, ActualStartTime,
                       ERS_PTA__c, ERS_Dispatch_Method__c, ERS_Parent_Territory__c,
                       ERS_Parent_Territory__r.Name,
                       ServiceTerritoryId, ServiceTerritory.Name,
                       WorkType.Name, Latitude, Longitude, Street, City, PostalCode
                FROM ServiceAppointment
                WHERE CreatedDate >= {cutoff}
                  AND ServiceTerritoryId != null
                  AND Status IN ('Dispatched','Completed','Canceled',
                                 'Cancel Call - Service Not En Route',
                                 'Cancel Call - Service En Route',
                                 'Unable to Complete','Assigned','No-Show')
                ORDER BY CreatedDate ASC
            """)

        def _get_assigned_resources():
            return _sqa(f"""
                SELECT ServiceResourceId, ServiceAppointmentId,
                       ServiceResource.Name
                FROM AssignedResource
                WHERE ServiceAppointment.CreatedDate >= {cutoff}
                  AND ServiceAppointment.Status IN ('Dispatched','Assigned')
            """)

        def _get_logged_in_drivers():
            """Drivers currently logged into a vehicle (Asset.ERS_Driver__c)."""
            return _sqa("""
                SELECT ERS_Driver__c, Name, ERS_Truck_Capabilities__c, ERS_LegacyTruckID__c
                FROM Asset
                WHERE RecordType.Name = 'ERS Truck'
                  AND ERS_Driver__c != null
            """)

        def _get_hourly_baseline():
            """Historical hourly volume for same DOW (last 8 weeks)."""
            dow = now_utc.weekday()  # 0=Mon ... 6=Sun
            # SF DAY_IN_WEEK: 1=Sun, 2=Mon, ... 7=Sat
            sf_dow = dow + 2 if dow < 6 else 1
            eight_weeks_ago = (now_utc - timedelta(weeks=8)).strftime('%Y-%m-%dT00:00:00Z')
            return _sqa(f"""
                SELECT HOUR_IN_DAY(CreatedDate) hr, COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE CreatedDate >= {eight_weeks_ago}
                  AND DAY_IN_WEEK(CreatedDate) = {sf_dow}
                  AND ServiceTerritoryId != null
                  AND Status != 'Canceled'
                GROUP BY HOUR_IN_DAY(CreatedDate)
                ORDER BY HOUR_IN_DAY(CreatedDate)
            """)

        data = sf_parallel(
            drivers=_get_drivers,
            sas=_get_active_sas,
            assigned=_get_assigned_resources,
            baseline=_get_hourly_baseline,
            logged_in=_get_logged_in_drivers,
        )

        # Filter: only drivers logged into a vehicle (Asset.ERS_Driver__c)
        logged_in_ids = set()
        truck_info = {}  # driver_id -> truck info
        for asset in data['logged_in']:
            dr_id = asset.get('ERS_Driver__c')
            if dr_id:
                logged_in_ids.add(dr_id)
                truck_info[dr_id] = {
                    'truck_name': asset.get('Name', ''),
                    'truck_capabilities': asset.get('ERS_Truck_Capabilities__c', ''),
                    'truck_legacy_id': asset.get('ERS_LegacyTruckID__c', ''),
                }
        all_drivers_raw = []
        for d in data['drivers']:
            if d.get('Name', '').lower().startswith('towbook'):
                continue
            if d['Id'] not in logged_in_ids:
                continue
            all_drivers_raw.append(d)
        all_sas = data['sas']
        assigned_raw = data['assigned']
        baseline_raw = data['baseline']
        matrix = _get_priority_matrix()

        # 2) Build assigned driver set (drivers with active/dispatched SAs)
        busy_driver_ids = set()
        busy_driver_sa = {}  # driver_id -> SA info
        for ar in assigned_raw:
            dr_id = ar.get('ServiceResourceId')
            sa_id = ar.get('ServiceAppointmentId')
            if dr_id:
                busy_driver_ids.add(dr_id)
                busy_driver_sa[dr_id] = sa_id

        # 3) Classify drivers
        idle_drivers = []
        busy_drivers = []
        for d in all_drivers_raw:
            gps_date = _to_eastern(d.get('LastKnownLocationDate'))
            truck = truck_info.get(d['Id'], {})
            caps = truck.get('truck_capabilities', '')
            driver_info = {
                'id': d['Id'],
                'name': d.get('Name', '?'),
                'lat': float(d['LastKnownLatitude']),
                'lon': float(d['LastKnownLongitude']),
                'gps_time': gps_date.strftime('%I:%M %p') if gps_date else '?',
                'driver_type': d.get('ERS_Driver_Type__c', ''),
                'tier': _driver_tier(caps),
                'phone': (d.get('RelatedRecord') or {}).get('Phone'),
                'truck': truck.get('truck_name', ''),
                'truck_capabilities': caps,
            }
            if d['Id'] in busy_driver_ids:
                busy_drivers.append(driver_info)
            else:
                idle_drivers.append(driver_info)

        fleet_status = {
            'total': len(all_drivers_raw),
            'busy': len(busy_drivers),
            'idle': len(idle_drivers),
            'idle_drivers': idle_drivers,
            'busy_drivers': busy_drivers,
        }

        # 4) Open calls (waiting for service) — exclude Tow Drop-Off (paired SAs, not actionable)
        open_sas = []
        for sa in all_sas:
            if sa.get('Status') not in ('Dispatched', 'Assigned'):
                continue
            wt = (sa.get('WorkType') or {}).get('Name', '')
            if 'drop-off' in wt.lower():
                continue
            cdt = _parse_dt(sa.get('CreatedDate'))
            wait_min = 0
            if cdt:
                if cdt.tzinfo is None:
                    cdt = cdt.replace(tzinfo=timezone.utc)
                wait_min = round((now_utc - cdt).total_seconds() / 60)
            lat, lon = sa.get('Latitude'), sa.get('Longitude')
            pta = sa.get('ERS_PTA__c')
            wt_name = (sa.get('WorkType') or {}).get('Name', '?')
            open_sas.append({
                'id': sa.get('Id'),
                'number': sa.get('AppointmentNumber', '?'),
                'wait_min': wait_min,
                'pta_min': round(float(pta)) if pta else None,
                'work_type': wt_name,
                'call_tier': _call_tier(wt_name),
                'lat': float(lat) if lat else None,
                'lon': float(lon) if lon else None,
                'territory': (sa.get('ServiceTerritory') or {}).get('Name', '?'),
                'territory_id': sa.get('ServiceTerritoryId'),
                'zone': (sa.get('ERS_Parent_Territory__r') or {}).get('Name', '?'),
                'zone_id': sa.get('ERS_Parent_Territory__c'),
                'address': f"{sa.get('Street') or ''} {sa.get('City') or ''}".strip(),
                'zip': sa.get('PostalCode') or '',
            })
        open_sas.sort(key=lambda x: x['wait_min'], reverse=True)

        # 5) At-risk calls (approaching SLA)
        at_risk = []
        for oc in open_sas:
            sla_target = oc['pta_min'] or 45
            time_left = sla_target - oc['wait_min']
            if time_left < 15 and oc['lat'] and oc['lon']:
                # Find nearest idle driver WITH matching skills
                ct = oc.get('call_tier', 'light')
                nearest = None
                nearest_dist = 999
                for drv in idle_drivers:
                    if not _can_serve(drv.get('tier', 'light'), ct):
                        continue
                    d = _haversine_mi(oc['lat'], oc['lon'], drv['lat'], drv['lon'])
                    if d < nearest_dist:
                        nearest_dist = d
                        nearest = drv
                at_risk.append({
                    **oc,
                    'time_left_min': max(time_left, 0),
                    'sla_target': sla_target,
                    'nearest_idle_driver': nearest['name'] if nearest else None,
                    'nearest_idle_dist_mi': nearest_dist if nearest and nearest_dist < 999 else None,
                    'nearest_idle_tier': nearest.get('tier') if nearest else None,
                })

        # 6) Zone-level coverage analysis using priority matrix
        # Group open calls by zone
        calls_by_zone = defaultdict(list)
        for oc in open_sas:
            if oc['zone_id']:
                calls_by_zone[oc['zone_id']].append(oc)

        # Also count completed today by zone
        completed_by_zone = defaultdict(int)
        for sa in all_sas:
            if sa.get('Status') == 'Completed':
                zone_id = sa.get('ERS_Parent_Territory__c')
                if zone_id:
                    completed_by_zone[zone_id] += 1

        # Build zone summaries
        zones = []
        zone_names = {}
        zone_cities = defaultdict(lambda: defaultdict(int))
        for sa in all_sas:
            zid = sa.get('ERS_Parent_Territory__c')
            zname = (sa.get('ERS_Parent_Territory__r') or {}).get('Name')
            if zid and zname:
                zone_names[zid] = zname
                city = (sa.get('City') or '').strip()
                if city:
                    zone_cities[zid][city] += 1

        # Build display name: "CM011 — Buffalo" (code + most common city)
        zone_display = {}
        for zid, code in zone_names.items():
            cities = zone_cities.get(zid, {})
            if cities:
                top_city = max(cities, key=cities.get)
                zone_display[zid] = f"{code} — {top_city}"
            else:
                zone_display[zid] = code

        for zone_id, zone_name in zone_names.items():
            open_calls = calls_by_zone.get(zone_id, [])
            completed = completed_by_zone.get(zone_id, 0)

            # Find primary garage for this zone from matrix
            primary_garage = None
            for (pid, sid), rank in matrix['rank_lookup'].items():
                if pid == zone_id and rank == 1:
                    # Get garage name from by_garage entries
                    for entry in matrix['by_garage'].get(sid, []):
                        if entry['parent_id'] == zone_id:
                            primary_garage = sid
                            break
                    break

            # Find nearest driver to zone centroid — must match skill of longest-waiting call
            nearest_driver = None
            nearest_dist = 999
            zone_lat = None
            zone_lon = None
            if open_calls:
                lats = [c['lat'] for c in open_calls if c['lat']]
                lons = [c['lon'] for c in open_calls if c['lon']]
                # Use the tier of the longest-waiting call for matching
                longest_call_tier = open_calls[0].get('call_tier', 'light') if open_calls else 'light'
                if lats and lons:
                    zone_lat = sum(lats) / len(lats)
                    zone_lon = sum(lons) / len(lons)
                    for drv in idle_drivers:
                        if not _can_serve(drv.get('tier', 'light'), longest_call_tier):
                            continue
                        d = _haversine_mi(zone_lat, zone_lon, drv['lat'], drv['lon'])
                        if d < nearest_dist:
                            nearest_dist = d
                            nearest_driver = drv

            # Zone health
            max_wait = max((c['wait_min'] for c in open_calls), default=0)
            status = 'clear'
            if len(open_calls) >= 3 and max_wait > 45:
                status = 'critical'
            elif len(open_calls) >= 2 and max_wait > 30:
                status = 'strained'
            elif len(open_calls) > 0:
                status = 'active'

            zones.append({
                'zone_id': zone_id,
                'zone_name': zone_display.get(zone_id, zone_name),
                'open_calls': len(open_calls),
                'completed_today': completed,
                'total_today': len(open_calls) + completed,
                'max_wait_min': max_wait,
                'status': status,
                'nearest_idle_driver': nearest_driver['name'] if nearest_driver else None,
                'nearest_idle_dist_mi': nearest_dist if nearest_driver and nearest_dist < 999 else None,
                'coverage': 'covered' if nearest_driver and nearest_dist < 15 else ('thin' if nearest_driver and nearest_dist < 30 else 'gap'),
            })
        zones.sort(key=lambda z: (-z['open_calls'], -z['max_wait_min']))

        # 7) Volume baseline comparison
        # Current hour volume
        current_hour = _to_eastern(now_utc.isoformat()).hour if _to_eastern(now_utc.isoformat()) else now_utc.hour
        current_hour_calls = sum(1 for sa in all_sas
                                 if _to_eastern(sa.get('CreatedDate'))
                                 and _to_eastern(sa.get('CreatedDate')).hour == current_hour)

        # Parse baseline
        hourly_baseline = {}
        for row in baseline_raw:
            hr = row.get('hr')
            cnt = row.get('cnt', 0)
            if hr is not None:
                hourly_baseline[hr] = round(cnt / 8)  # avg over 8 weeks

        normal_for_hour = hourly_baseline.get(current_hour, 0)
        pct_vs_normal = round(100 * (current_hour_calls - normal_for_hour) / max(normal_for_hour, 1)) if normal_for_hour > 0 else 0

        demand = {
            'current_hour': current_hour,
            'current_hour_calls': current_hour_calls,
            'normal_for_hour': normal_for_hour,
            'pct_vs_normal': pct_vs_normal,
            'trend': 'surge' if pct_vs_normal > 30 else ('above' if pct_vs_normal > 10 else ('normal' if pct_vs_normal > -15 else 'quiet')),
            'hourly_baseline': hourly_baseline,
            'today_total': len(all_sas),
        }

        # 8) Actionable suggestions
        suggestions = []

        # Reposition idle drivers toward uncovered zones (skill-matched)
        for z in zones:
            if z['open_calls'] > 0 and z['coverage'] == 'gap':
                # Find closest idle driver with matching skills
                best_drv = None
                best_dist = 999
                zone_calls = calls_by_zone.get(z['zone_id'], [])
                if zone_calls:
                    zc = zone_calls[0]
                    zc_tier = zc.get('call_tier', 'light')
                    if zc['lat'] and zc['lon']:
                        for drv in idle_drivers:
                            if not _can_serve(drv.get('tier', 'light'), zc_tier):
                                continue
                            d = _haversine_mi(zc['lat'], zc['lon'], drv['lat'], drv['lon'])
                            if d < best_dist:
                                best_dist = d
                                best_drv = drv
                if best_drv:
                    suggestions.append({
                        'type': 'reposition',
                        'priority': 'high',
                        'driver': best_drv['name'],
                        'driver_type': best_drv['driver_type'],
                        'to_zone': z['zone_name'],
                        'distance_mi': best_dist,
                        'reason': f"{z['open_calls']} call(s) waiting, no driver within 30 mi",
                    })

        # Escalate calls at risk of missing SLA
        for ar in at_risk:
            suggestions.append({
                'type': 'escalate',
                'priority': 'critical' if ar['time_left_min'] <= 5 else 'high',
                'call_number': ar['number'],
                'wait_min': ar['wait_min'],
                'sla_target': ar['sla_target'],
                'time_left_min': ar['time_left_min'],
                'work_type': ar['work_type'],
                'nearest_driver': ar.get('nearest_idle_driver'),
                'nearest_dist_mi': ar.get('nearest_idle_dist_mi'),
                'reason': f"SA {ar['number']} at {ar['wait_min']} min — " + ('PAST SLA' if ar['time_left_min'] <= 0 else f"{ar['time_left_min']} min to SLA"),
            })

        # Surge warning
        if demand['trend'] == 'surge':
            suggestions.append({
                'type': 'surge',
                'priority': 'medium',
                'reason': f"Volume {pct_vs_normal}% above normal for {current_hour}:00. Consider activating backup drivers.",
            })

        # Coverage thin warnings
        thin_zones = [z for z in zones if z['coverage'] == 'thin' and z['open_calls'] > 0]
        if thin_zones:
            for tz in thin_zones[:3]:
                suggestions.append({
                    'type': 'coverage',
                    'priority': 'medium',
                    'zone': tz['zone_name'],
                    'nearest_driver': tz['nearest_idle_driver'],
                    'distance_mi': tz['nearest_idle_dist_mi'],
                    'reason': f"{tz['zone_name']}: nearest idle driver is {tz['nearest_idle_dist_mi']} mi away",
                })

        # Sort suggestions by priority
        pri_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        suggestions.sort(key=lambda s: pri_order.get(s['priority'], 9))

        return {
            'fleet': fleet_status,
            'open_calls': open_sas[:30],
            'at_risk': at_risk,
            'zones': zones,
            'demand': demand,
            'suggestions': suggestions[:15],
            'generated_at': now_utc.isoformat(),
        }

    return cache.cached_query('ops_brief', _fetch, ttl=60)


# ── SA Lookup — Zoom-to with Driver Positions ────────────────────────────────

@app.get("/api/sa/{sa_number}")
def lookup_sa(sa_number: str):
    """Lookup an SA by AppointmentNumber and return driver positions."""
    sa_number = sanitize_soql(sa_number)
    def _fetch():
        return _lookup_sa_impl(sa_number)
    result = cache.cached_query(f'sa_lookup_{sa_number}', _fetch, ttl=30)
    if result is None:
        raise HTTPException(status_code=404, detail=f"SA {sa_number} not found")
    return result


def _lookup_sa_impl(sa_number: str):
    sa_list = sf_query_all(f"""
        SELECT Id, AppointmentNumber, Status, CreatedDate,
               ActualStartTime, ActualEndTime,
               Latitude, Longitude, Street, City, State, PostalCode,
               WorkType.Name, ServiceTerritoryId, ServiceTerritory.Name,
               Off_Platform_Truck_Id__c, ERS_PTA__c,
               ERS_Dispatched_Geolocation__Latitude__s,
               ERS_Dispatched_Geolocation__Longitude__s
        FROM ServiceAppointment
        WHERE AppointmentNumber = '{sa_number}'
        LIMIT 1
    """)
    if not sa_list:
        return None

    sa = sa_list[0]
    tid = sa.get('ServiceTerritoryId')
    et = _to_eastern(sa.get('CreatedDate'))
    start_et = _to_eastern(sa.get('ActualStartTime'))
    end_et = _to_eastern(sa.get('ActualEndTime'))

    cd = _parse_dt(sa.get('CreatedDate'))
    ast = _parse_dt(sa.get('ActualStartTime'))
    response_min = None
    if cd and ast:
        diff = (ast - cd).total_seconds() / 60
        if 0 < diff < 1440:
            response_min = round(diff)

    result = {
        'sa': {
            'id': sa['Id'],
            'number': sa.get('AppointmentNumber'),
            'status': sa.get('Status'),
            'work_type': (sa.get('WorkType') or {}).get('Name', '?'),
            'customer': '',
            'phone': '',
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
            'dispatched_lat': sa.get('ERS_Dispatched_Geolocation__Latitude__s'),
            'dispatched_lon': sa.get('ERS_Dispatched_Geolocation__Longitude__s'),
        },
        'drivers': [],
    }

    # Live driver GPS — only drivers logged into a vehicle
    if tid:
        from sf_client import sf_parallel as _sf_par, sf_query_all as _sqa_local

        def _get_members():
            return _sqa_local(f"""
                SELECT ServiceResourceId, ServiceResource.Name,
                       ServiceResource.LastKnownLatitude,
                       ServiceResource.LastKnownLongitude,
                       ServiceResource.LastKnownLocationDate,
                       TerritoryType
                FROM ServiceTerritoryMember
                WHERE ServiceTerritoryId = '{tid}'
            """)

        def _get_vehicles():
            return _sqa_local("""
                SELECT ERS_Driver__c, Name, ERS_Truck_Capabilities__c
                FROM Asset
                WHERE RecordType.Name = 'ERS Truck'
                  AND ERS_Driver__c != null
            """)

        fetched = _sf_par(members=_get_members, vehicles=_get_vehicles)
        members = fetched['members']
        members = [m for m in members
                    if not ((m.get('ServiceResource') or {}).get('Name') or '').lower().startswith('towbook')]

        # Build vehicle login set
        vehicle_login_ids = set()
        vehicle_info = {}
        for asset in fetched['vehicles']:
            dr_id = asset.get('ERS_Driver__c')
            if dr_id:
                vehicle_login_ids.add(dr_id)
                vehicle_info[dr_id] = {
                    'truck': asset.get('Name', ''),
                    'capabilities': asset.get('ERS_Truck_Capabilities__c', ''),
                }

        sa_lat = sa.get('Latitude')
        sa_lon = sa.get('Longitude')
        if sa_lat: sa_lat = float(sa_lat)
        if sa_lon: sa_lon = float(sa_lon)

        for m in members:
            sr = m.get('ServiceResource') or {}
            sr_id = m.get('ServiceResourceId')
            # Only include drivers logged into a vehicle
            if sr_id not in vehicle_login_ids:
                continue
            d_lat = sr.get('LastKnownLatitude')
            d_lon = sr.get('LastKnownLongitude')
            if d_lat: d_lat = float(d_lat)
            if d_lon: d_lon = float(d_lon)
            dist = haversine(d_lat, d_lon, sa_lat, sa_lon) if d_lat and d_lon and sa_lat and sa_lon else None

            gps_date = _to_eastern(sr.get('LastKnownLocationDate'))
            truck = vehicle_info.get(sr_id, {})
            result['drivers'].append({
                'id': sr_id,
                'name': sr.get('Name', '?'),
                'phone': '',
                'lat': d_lat,
                'lon': d_lon,
                'gps_time': gps_date.strftime('%I:%M %p') if gps_date else '?',
                'distance': dist,
                'territory_type': m.get('TerritoryType', '?'),
                'truck': truck.get('truck', ''),
                'truck_capabilities': truck.get('capabilities', ''),
                'next_job': None,
            })

        result['drivers'].sort(key=lambda d: d.get('distance') or 9999)

    return result


# ── Performance Dashboard ─────────────────────────────────────────────────────

@app.get("/api/garages/{territory_id}/performance")
def get_performance(
    territory_id: str,
    period_start: str = Query(...),
    period_end: str = Query(...),
):
    territory_id = sanitize_soql(territory_id)
    period_start = sanitize_soql(period_start)
    period_end = sanitize_soql(period_end)
    cache_key = f"perf_{territory_id}_{period_start}_{period_end}"
    return cache.cached_query(cache_key, lambda: _compute_performance(territory_id, period_start, period_end), ttl=3600)


def _compute_performance(territory_id: str, period_start: str, period_end: str) -> dict:
    """All from Salesforce — parallel queries."""
    is_single_day = period_start == period_end
    next_day = (date.fromisoformat(period_end) + timedelta(days=1)).isoformat()
    since = f"{period_start}T00:00:00Z"
    until = f"{next_day}T00:00:00Z"

    # Parallel: individual SAs + WO IDs for surveys + trend aggregate
    data = sf_parallel(
        sas=lambda: sf_query_all(f"""
            SELECT Id, Status, CreatedDate, ActualStartTime, ActualEndTime,
                   SchedStartTime, ERS_Auto_Assign__c, ERS_PTA__c,
                   ERS_Facility_Decline_Reason__c, ERS_Cancellation_Reason__c,
                   ERS_Dispatch_Method__c, ERS_Spotting_Number__c, WorkType.Name
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
        wo_ids=lambda: sf_query_all(f"""
            SELECT WorkOrderNumber FROM WorkOrder
            WHERE ServiceTerritoryId = '{territory_id}'
              AND CreatedDate >= {since}
              AND CreatedDate < {until}
            ORDER BY CreatedDate DESC
            LIMIT 1000
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
        sa_history=lambda: sf_query_all(f"""
            SELECT ServiceAppointmentId, OldValue, NewValue, CreatedDate
            FROM ServiceAppointmentHistory
            WHERE Field = 'ServiceTerritory'
              AND ServiceAppointment.ServiceTerritoryId = '{territory_id}'
              AND ServiceAppointment.CreatedDate >= {since}
              AND ServiceAppointment.CreatedDate < {until}
              AND NewValue LIKE '0Hh%'
            ORDER BY ServiceAppointmentId, CreatedDate ASC
        """),
    )

    sas = data['sas']
    if not sas:
        raise HTTPException(status_code=404, detail="No SAs found for this period")

    total = len(sas)
    completed = [s for s in sas if s.get('Status') == 'Completed']

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

    # 1st Call vs 2nd+ Call — from SA history (territory assignment sequence)
    # If this garage's territory was the FIRST ServiceTerritory assigned → 1st call
    # If it was 2nd or later (SA was reassigned from another garage) → 2nd+ call
    sa_history = data.get('sa_history', [])

    # Build assignment order per SA: list of territory IDs in chronological order
    sa_territory_order = defaultdict(list)  # sa_id -> [territory_id_1, territory_id_2, ...]
    for h in sa_history:
        sa_id = h.get('ServiceAppointmentId')
        new_val = h.get('NewValue', '')
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
            # No history found — treat as 1st call (initial assignment, no reassignment)
            first_call_sas.append(s)
        elif order[0] == territory_id:
            first_call_sas.append(s)
        else:
            second_call_sas.append(s)

    first_call_accepted = [s for s in first_call_sas if not s.get('ERS_Facility_Decline_Reason__c')]
    second_call_accepted = [s for s in second_call_sas if not s.get('ERS_Facility_Decline_Reason__c')]

    # Completion of accepted — of SAs they didn't decline, how many completed?
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

    # Response times (exclude Tow Drop-Off + Towbook SAs)
    # Towbook ActualStartTime is bulk-updated at midnight — not real arrival time
    response_times = []
    for s in completed:
        wt_name = (s.get('WorkType') or {}).get('Name', '') or ''
        if 'drop' in wt_name.lower():
            continue
        if (s.get('ERS_Dispatch_Method__c') or '') == 'Towbook':
            continue
        created = _parse_dt(s.get('CreatedDate'))
        started = _parse_dt(s.get('ActualStartTime'))
        if created and started:
            diff = (started - created).total_seconds() / 60
            if 0 < diff < 480:  # >8hr is bad data
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

    # PTS-ATA (exclude Towbook — ActualStartTime unreliable)
    pts_deltas = []
    for s in completed:
        if (s.get('ERS_Dispatch_Method__c') or '') == 'Towbook':
            continue
        pta = s.get('ERS_PTA__c')
        created = _parse_dt(s.get('CreatedDate'))
        started = _parse_dt(s.get('ActualStartTime'))
        if pta is not None and created and started:
            pv = float(pta)
            if pv >= 999 or pv <= 0:
                continue
            expected = created + timedelta(minutes=pv)
            delta = (started - expected).total_seconds() / 60
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
                {'label': '1–10 min late', 'count': sum(1 for d in pts_deltas if 0 < d <= 10)},
                {'label': '10–20 min late', 'count': sum(1 for d in pts_deltas if 10 < d <= 20)},
                {'label': '20–30 min late', 'count': sum(1 for d in pts_deltas if 20 < d <= 30)},
                {'label': '30+ min late', 'count': sum(1 for d in pts_deltas if d > 30)},
            ],
        }
        for b in pts_ata['buckets']:
            b['pct'] = round(100 * b['count'] / n, 1)

    # Satisfaction — use WO IDs to find surveys
    wo_nums = [r.get('WorkOrderNumber') for r in data.get('wo_ids', []) if r.get('WorkOrderNumber')]

    satisfaction = None
    if wo_nums:
        wo_list = ",".join(f"'{w}'" for w in wo_nums[:500])
        survey_rows = sf_query_all(f"""
            SELECT ERS_Overall_Satisfaction__c
            FROM Survey_Result__c
            WHERE ERS_Work_Order_Number__c IN ({wo_list})
              AND ERS_Overall_Satisfaction__c != null
        """)

        counts = defaultdict(int)
        for sv in survey_rows:
            sat = (sv.get('ERS_Overall_Satisfaction__c') or '').lower().strip()
            counts['total'] += 1
            if sat == 'totally satisfied':
                counts['totally_satisfied'] += 1
            elif sat == 'satisfied':
                counts['satisfied'] += 1
            elif sat == 'neither':
                counts['neither'] += 1
            elif sat == 'dissatisfied':
                counts['dissatisfied'] += 1
            elif sat == 'totally dissatisfied':
                counts['totally_dissatisfied'] += 1

        if counts['total'] > 0:
            n = counts['total']
            total_sat = counts['totally_satisfied'] + counts['satisfied']
            total_dis = counts['dissatisfied'] + counts['totally_dissatisfied']
            satisfaction = {
                'total': n,
                'totally_satisfied': counts['totally_satisfied'],
                'satisfied': counts['satisfied'],
                'neither': counts['neither'],
                'dissatisfied': counts['dissatisfied'],
                'totally_dissatisfied': counts['totally_dissatisfied'],
                'total_satisfied_pct': round(100 * total_sat / n, 1),
                'totally_satisfied_pct': round(100 * counts['totally_satisfied'] / n, 1),
                'dissatisfied_pct': round(100 * total_dis / n, 1),
                'accreditation_target': 82.0,
                'meets_target': (100 * total_sat / n) >= 82.0,
            }

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
        'satisfaction': satisfaction,
        'dispatch_mix': dispatch_mix,
        'trend': trend,
        'period': {
            'start': period_start,
            'end': period_end,
            'single_day': is_single_day,
        },
        'definitions': {
            'total_calls': 'Count of all Service Appointments dispatched to this garage in the selected period. Includes all statuses: Completed, Canceled, Unable to Complete, No-Show, Dispatched, Assigned.',
            'completion': 'Completed SAs / Total SAs. Target: 95%. Measures how many dispatched calls this garage actually finished.',
            'first_call_acceptance': 'Based on SA history: if this garage was the FIRST territory assigned to the SA, it counts as 1st call. If the SA was reassigned from another garage, it counts as 2nd+ call. Shows acceptance rate (no decline) for each group.',
            'completion_of_accepted': 'Of all SAs this garage accepted (did not decline), what % were Completed? This isolates operational effectiveness from acceptance behavior.',
            'median_response': 'Median time from SA Created to driver ActualStartTime (on-site arrival). Only Field Services SAs — Towbook arrival times are unreliable (bulk-updated at midnight). Excludes Tow Drop-Off SAs. Target: 45 min. Shows N/A for Towbook-only garages.',
            'eta_accuracy': 'Of completed Field Services SAs, what % had actual response time within the promised PTA (ERS_PTA__c)? Measures whether the ETA given to the member was accurate. Shows N/A for Towbook-only garages.',
            'acceptance': 'Of SAs auto-assigned to this garage, what % were accepted (not declined by facility)? Based on ERS_Auto_Assign__c = true and absence of ERS_Facility_Decline_Reason__c.',
            'satisfaction': 'Totally Satisfied / Total Survey Responses. Surveys are matched by Work Order number. Target: 82% (AAA accreditation requirement). Surveys arrive days after the call.',
            'dispatch_mix': 'Percentage of SAs dispatched via Field Services (internal fleet) vs Towbook (external contractor). Based on ERS_Dispatch_Method__c formula field.',
        },
    }


# ── Map — Grid Boundaries ────────────────────────────────────────────────────

@app.get("/api/map/grids")
def get_map_grids():
    """All FSL polygon boundaries as GeoJSON FeatureCollection."""
    def _fetch():
        recs = sf_query_all("""
            SELECT Id, Name, FSL__Service_Territory__c,
                   FSL__Service_Territory__r.Name,
                   FSL__Color__c, FSL__KML__c
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
            color = rec.get('FSL__Color__c') or '#818cf8'
            features.append({
                'type': 'Feature',
                'properties': {
                    'id': rec['Id'],
                    'name': rec.get('Name', ''),
                    'territory_name': (rec.get('FSL__Service_Territory__r') or {}).get('Name', ''),
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
    """Active drivers logged into vehicles with last known GPS positions (cached 2 minutes)."""
    def _fetch():
        from sf_client import sf_query_all as _sqa_local, sf_parallel as _sf_par

        def _drv():
            return _sqa_local("""
                SELECT Id, Name,
                       LastKnownLatitude, LastKnownLongitude, LastKnownLocationDate,
                       ERS_Driver_Type__c, ERS_Tech_ID__c,
                       RelatedRecord.Phone
                FROM ServiceResource
                WHERE IsActive = true
                  AND ResourceType = 'T'
                  AND LastKnownLatitude != null
                ORDER BY Name
            """)

        def _trucks():
            return _sqa_local("""
                SELECT ERS_Driver__c, Name, ERS_Truck_Capabilities__c, ERS_LegacyTruckID__c
                FROM Asset
                WHERE RecordType.Name = 'ERS Truck'
                  AND ERS_Driver__c != null
            """)

        fetched = _sf_par(drivers=_drv, trucks=_trucks)
        drivers = fetched['drivers']
        logged_in_ids = set()
        truck_map = {}
        for asset in fetched['trucks']:
            dr_id = asset.get('ERS_Driver__c')
            if dr_id:
                logged_in_ids.add(dr_id)
                truck_map[dr_id] = {
                    'truck_name': asset.get('Name', ''),
                    'truck_capabilities': asset.get('ERS_Truck_Capabilities__c', ''),
                }

        result = []
        for d in drivers:
            if d.get('Name', '').lower().startswith('towbook'):
                continue
            # Only show drivers logged into a vehicle
            if d['Id'] not in logged_in_ids:
                continue
            gps_date = _to_eastern(d.get('LastKnownLocationDate'))
            rr = d.get('RelatedRecord') or {}
            truck = truck_map.get(d['Id'], {})
            result.append({
                'id': d['Id'],
                'name': d.get('Name', '?'),
                'lat': float(d['LastKnownLatitude']),
                'lon': float(d['LastKnownLongitude']),
                'gps_time': gps_date.strftime('%I:%M %p') if gps_date else '?',
                'driver_type': d.get('ERS_Driver_Type__c', ''),
                'tech_id': d.get('ERS_Tech_ID__c', ''),
                'phone': rr.get('Phone') or None,
                'truck': truck.get('truck_name', ''),
                'truck_capabilities': truck.get('truck_capabilities', ''),
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
                data = r.json().get('current', {})
                code = data.get('weathercode', 0)
                results.append({
                    'name': s['name'],
                    'lat': s['lat'], 'lon': s['lon'],
                    'temp_f': data.get('temperature_2m'),
                    'precipitation_mm': data.get('precipitation'),
                    'snowfall_cm': data.get('snowfall'),
                    'wind_mph': data.get('windspeed_10m'),
                    'condition': _WMO_CODES.get(code, f'Code {code}'),
                    'weather_code': code,
                })
            except Exception as e:
                results.append({
                    'name': s['name'],
                    'lat': s['lat'], 'lon': s['lon'],
                    'error': str(e),
                })
        return results

    return cache.cached_query('map_weather', _fetch, ttl=900)


# ── Dispatch Optimization ────────────────────────────────────────────────────

@app.get("/api/dispatch/queue")
def api_dispatch_queue():
    """Live queue board — all open SAs with aging and urgency."""
    return get_live_queue()

@app.get("/api/dispatch/recommend/{sa_id}")
def api_dispatch_recommend(sa_id: str):
    """Top driver recommendations for a specific SA."""
    sa_id = sanitize_soql(sa_id)
    result = recommend_drivers(sa_id)
    if 'error' in result:
        raise HTTPException(status_code=404, detail=result['error'])
    return result

@app.get("/api/dispatch/cascade/{territory_id}")
def api_dispatch_cascade(territory_id: str):
    """Cross-skill cascade opportunities for a territory."""
    territory_id = sanitize_soql(territory_id)
    return get_cascade_status(territory_id)

@app.get("/api/garages/{territory_id}/decomposition")
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

@app.get("/api/territory/{territory_id}/forecast")
def api_forecast(territory_id: str, weeks_history: int = Query(8, ge=2, le=16)):
    """16-day demand forecast using DOW patterns + weather."""
    territory_id = sanitize_soql(territory_id)
    return get_forecast(territory_id, weeks_history)


# ── Admin PIN (used by PTA advisor refresh + admin panel) ────────────────────
_ADMIN_PIN = os.getenv('ADMIN_PIN', '121838')

def _check_pin(request: Request):
    pin = request.headers.get('X-Admin-Pin', '')
    if pin != _ADMIN_PIN:
        raise HTTPException(status_code=403, detail="Invalid PIN")


# ── PTA Advisor — Projected PTA for all garages ─────────────────────────────
# Pre-computed every 15 min, cached. Compares projected vs current PTA settings.

# Cycle times in minutes (verified from 8,500+ SAs, Mar 2026)
_CYCLE_TIMES = {'tow': 115, 'winch': 40, 'battery': 38, 'light': 33}
_ONSITE_TIMES = {'tow': 60, 'winch': 15, 'battery': 20, 'light': 13}
# Dispatch + travel buffer per type (dispatch processing + avg travel-to from verified data)
_DISPATCH_TRAVEL = {'tow': 30, 'winch': 25, 'battery': 25, 'light': 25}
_DEFAULT_PTA = {'tow': 60, 'winch': 50, 'battery': 45, 'light': 45}  # fallback if no setting exists

# PTA type mapping: ERS_Type__c → our call tier
_PTA_TYPE_MAP = {
    'D': 'default',
    'F': 'tow',       # Full Service = tow/flatbed
    'Battery': 'battery',
    'BA': 'battery',
    'Lockout': 'light',
    'Winch': 'winch',
}

# Settings file for configurable refresh interval
_SETTINGS_FILE = os.path.expanduser('~/.fslapp/settings.json')

def _load_settings():
    try:
        with open(_SETTINGS_FILE) as f:
            return _json.load(f)
    except Exception:
        return {}

def _save_settings(settings: dict):
    os.makedirs(os.path.dirname(_SETTINGS_FILE), exist_ok=True)
    with open(_SETTINGS_FILE, 'w') as f:
        _json.dump(settings, f, indent=2)

def _pta_refresh_interval():
    return _load_settings().get('pta_refresh_interval', 900)


@app.get("/api/pta-advisor")
def pta_advisor():
    """Projected PTA for all active garages. Pre-cached, auto-refreshes."""
    ttl = _pta_refresh_interval()

    def _fetch():
        now_utc = datetime.now(timezone.utc)
        now_et = now_utc.astimezone(_ET)
        today_start = now_et.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        cutoff = today_start.strftime('%Y-%m-%dT%H:%M:%SZ')

        from sf_client import sf_parallel, sf_query_all as _sqa

        data = sf_parallel(
            # Today's SAs with territory and work type
            sas=lambda: _sqa(f"""
                SELECT Id, Status, CreatedDate, ActualStartTime,
                       ERS_PTA__c, ERS_Dispatch_Method__c,
                       Off_Platform_Driver__r.Name, Off_Platform_Truck_Id__c,
                       ServiceTerritoryId, ServiceTerritory.Name,
                       WorkType.Name
                FROM ServiceAppointment
                WHERE CreatedDate >= {cutoff}
                  AND ServiceTerritoryId != null
                  AND Status IN ('Dispatched','Completed','Assigned',
                                 'Cancel Call - Service Not En Route',
                                 'Cancel Call - Service En Route',
                                 'Unable to Complete','Canceled','No-Show')
            """),
            # Assigned resources for active SAs (driver → SA mapping)
            assigned=lambda: _sqa(f"""
                SELECT ServiceResourceId, ServiceResource.Name, ServiceAppointmentId
                FROM AssignedResource
                WHERE ServiceAppointment.CreatedDate >= {cutoff}
                  AND ServiceAppointment.Status IN ('Dispatched','Assigned')
            """),
            # Logged-in drivers (Asset = truck with driver)
            logged_in=lambda: _sqa("""
                SELECT ERS_Driver__c, Name, ERS_Truck_Capabilities__c
                FROM Asset
                WHERE RecordType.Name = 'ERS Truck'
                  AND ERS_Driver__c != null
            """),
            # Territory membership (driver → territory)
            members=lambda: _sqa("""
                SELECT ServiceResourceId, ServiceTerritoryId
                FROM ServiceTerritoryMember
                WHERE ServiceTerritory.IsActive = true
                  AND EffectiveStartDate <= TODAY
                  AND (EffectiveEndDate = null OR EffectiveEndDate >= TODAY)
            """),
            # Current PTA settings per territory+type
            pta_settings=lambda: _sqa("""
                SELECT ERS_Service_Territory__c, ERS_Type__c, ERS_Minutes__c
                FROM ERS_Service_Appointment_PTA__c
            """),
        )

        # ── Build lookup maps ──

        # Driver capabilities from truck assignment
        driver_caps = {}
        for asset in data['logged_in']:
            dr_id = asset.get('ERS_Driver__c')
            if dr_id:
                driver_caps[dr_id] = asset.get('ERS_Truck_Capabilities__c', '')
        logged_in_ids = set(driver_caps.keys())

        # Territory → set of logged-in driver IDs
        terr_drivers = defaultdict(set)
        for m in data['members']:
            dr_id = m.get('ServiceResourceId')
            tid = m.get('ServiceTerritoryId')
            if dr_id and tid and dr_id in logged_in_ids:
                terr_drivers[tid].add(dr_id)

        # SA → driver, driver → SA IDs, driver names
        sa_driver = {}
        driver_sa_ids = defaultdict(set)
        driver_names = {}
        for ar in data['assigned']:
            dr_id = ar.get('ServiceResourceId')
            sa_id = ar.get('ServiceAppointmentId')
            if dr_id and sa_id:
                sa_driver[sa_id] = dr_id
                driver_sa_ids[dr_id].add(sa_id)
                if dr_id not in driver_names:
                    driver_names[dr_id] = (ar.get('ServiceResource') or {}).get('Name', '?')
        busy_driver_ids = set(driver_sa_ids.keys())

        # Current PTA settings: territory_id → {call_tier: minutes, 'default': minutes}
        pta_map = defaultdict(dict)
        for p in data['pta_settings']:
            tid = p.get('ERS_Service_Territory__c')
            ptype = p.get('ERS_Type__c', '')
            mins = p.get('ERS_Minutes__c')
            if tid and mins is not None:
                mapped = _PTA_TYPE_MAP.get(ptype, 'default')
                pta_map[tid][mapped] = round(mins)

        # SA by ID for quick lookup
        sa_by_id = {}
        by_territory = defaultdict(list)
        for sa in data['sas']:
            tid = sa.get('ServiceTerritoryId')
            if tid:
                by_territory[tid].append(sa)
                sa_by_id[sa['Id']] = sa

        # ── Process each territory ──
        import heapq
        garages = []

        for tid, sa_list in by_territory.items():
            t_name = (sa_list[0].get('ServiceTerritory') or {}).get('Name', '?')

            # Today's stats — separate assigned (have driver) vs unassigned (true queue)
            open_sas = []       # unassigned open calls (true queue)
            assigned_open = []  # open calls already assigned to a driver
            completed_count = 0
            tb_drivers_seen = set()  # unique Towbook driver names from ALL today's SAs
            for sa in sa_list:
                st = sa.get('Status')
                wt = (sa.get('WorkType') or {}).get('Name', '')
                # Track all Towbook drivers seen today (active + completed)
                opd_name = (sa.get('Off_Platform_Driver__r') or {}).get('Name')
                if opd_name:
                    tb_drivers_seen.add(opd_name)
                if st == 'Completed':
                    completed_count += 1
                elif st in ('Dispatched', 'Assigned'):
                    if 'drop-off' in wt.lower():
                        continue
                    ct = _call_tier(wt)
                    cdt = _parse_dt(sa.get('CreatedDate'))
                    wait_min = 0
                    if cdt:
                        if cdt.tzinfo is None:
                            cdt = cdt.replace(tzinfo=timezone.utc)
                        wait_min = round((now_utc - cdt).total_seconds() / 60)
                    sa_info = {
                        'id': sa['Id'], 'tier': ct,
                        'wait_min': wait_min,
                        'pta_min': round(float(sa['ERS_PTA__c'])) if sa.get('ERS_PTA__c') else None,
                    }
                    if sa['Id'] in sa_driver:
                        assigned_open.append(sa_info)  # already on a driver's plate
                    else:
                        open_sas.append(sa_info)  # truly unassigned
            all_open = assigned_open + open_sas
            all_open.sort(key=lambda x: x['wait_min'], reverse=True)
            open_sas.sort(key=lambda x: x['wait_min'], reverse=True)

            # Territory's drivers (logged-in only — Fleet drivers)
            all_driver_ids = terr_drivers.get(tid, set())
            has_pta_setting = tid in pta_map
            if not all_driver_ids and not all_open and not has_pta_setting:
                continue  # Skip territories with no drivers, no open calls, and no PTA settings

            idle_list = []
            busy_list = []
            for dr_id in all_driver_ids:
                tier = _driver_tier(driver_caps.get(dr_id, ''))
                if dr_id in busy_driver_ids:
                    # Total sequential remaining: count assigned pick-up SAs
                    # Driver works jobs sequentially. Total work = num_jobs × cycle_time.
                    # Subtract elapsed since oldest job started.
                    driver_sas = []
                    for sa_id in driver_sa_ids[dr_id]:
                        sa = sa_by_id.get(sa_id)
                        if not sa:
                            continue
                        wt = (sa.get('WorkType') or {}).get('Name', '')
                        if 'drop-off' in wt.lower():
                            continue  # drop-off is part of pick-up cycle
                        driver_sas.append(sa)

                    if driver_sas:
                        # Sort by CreatedDate to find oldest (current job)
                        driver_sas.sort(key=lambda s: s.get('CreatedDate', ''))
                        oldest = driver_sas[0]

                        # Sum ACTUAL per-job cycle times (tow=115, battery=38, light=33)
                        total_work = 0
                        for ds in driver_sas:
                            jct = _call_tier((ds.get('WorkType') or {}).get('Name', ''))
                            total_work += _CYCLE_TIMES.get(jct, 40)

                        # Subtract elapsed since oldest job
                        ast = _parse_dt(oldest.get('ActualStartTime'))
                        cdt = _parse_dt(oldest.get('CreatedDate'))
                        dm = oldest.get('ERS_Dispatch_Method__c', '')
                        if ast and dm == 'Field Services':
                            if ast.tzinfo is None:
                                ast = ast.replace(tzinfo=timezone.utc)
                            elapsed = (now_utc - ast).total_seconds() / 60
                        elif cdt:
                            if cdt.tzinfo is None:
                                cdt = cdt.replace(tzinfo=timezone.utc)
                            elapsed = (now_utc - cdt).total_seconds() / 60
                        else:
                            elapsed = 0
                        remaining = max(0, total_work - elapsed)
                    else:
                        remaining = 0
                    # Build job list for display
                    job_details = []
                    for s in driver_sas:
                        wt_n = (s.get('WorkType') or {}).get('Name', '?')
                        scdt = _parse_dt(s.get('CreatedDate'))
                        swait = 0
                        if scdt:
                            if scdt.tzinfo is None:
                                scdt = scdt.replace(tzinfo=timezone.utc)
                            swait = round((now_utc - scdt).total_seconds() / 60)
                        job_details.append({
                            'work_type': wt_n,
                            'wait_min': swait,
                            'pta_min': round(float(s['ERS_PTA__c'])) if s.get('ERS_PTA__c') else None,
                            'has_arrived': s.get('ActualStartTime') is not None,
                        })
                    busy_list.append({
                        'name': driver_names.get(dr_id, '?'),
                        'tier': tier,
                        'remaining_min': round(remaining),
                        'jobs': len(driver_sas),
                        'job_details': job_details,
                    })
                else:
                    idle_list.append({'tier': tier})

            # ── Towbook (off-platform) drivers from active SAs ──
            tb_drivers = defaultdict(list)  # driver_name → [sa, ...]
            for sa in sa_list:
                st = sa.get('Status')
                if st not in ('Dispatched', 'Assigned'):
                    continue
                wt = (sa.get('WorkType') or {}).get('Name', '')
                if 'drop-off' in wt.lower():
                    continue
                opd = (sa.get('Off_Platform_Driver__r') or {}).get('Name')
                if opd:
                    tb_drivers[opd].append(sa)

            for tb_name, tb_sas in tb_drivers.items():
                tb_sas.sort(key=lambda s: s.get('CreatedDate', ''))
                total_work = 0
                for ds in tb_sas:
                    jct = _call_tier((ds.get('WorkType') or {}).get('Name', ''))
                    total_work += _CYCLE_TIMES.get(jct, 40)
                oldest = tb_sas[0]
                cdt = _parse_dt(oldest.get('CreatedDate'))
                elapsed = 0
                if cdt:
                    if cdt.tzinfo is None:
                        cdt = cdt.replace(tzinfo=timezone.utc)
                    elapsed = (now_utc - cdt).total_seconds() / 60
                remaining = max(0, total_work - elapsed)
                job_details = []
                for s in tb_sas:
                    wt_n = (s.get('WorkType') or {}).get('Name', '?')
                    scdt = _parse_dt(s.get('CreatedDate'))
                    swait = 0
                    if scdt:
                        if scdt.tzinfo is None:
                            scdt = scdt.replace(tzinfo=timezone.utc)
                        swait = round((now_utc - scdt).total_seconds() / 60)
                    job_details.append({
                        'work_type': wt_n,
                        'wait_min': swait,
                        'pta_min': round(float(s['ERS_PTA__c'])) if s.get('ERS_PTA__c') else None,
                        'has_arrived': s.get('ActualStartTime') is not None,
                    })
                # Infer tier from truck ID pattern or default to 'tow' for Towbook
                busy_list.append({
                    'name': tb_name,
                    'tier': 'tow',  # Towbook drivers are typically tow-capable
                    'remaining_min': round(remaining),
                    'jobs': len(tb_sas),
                    'job_details': job_details,
                    'towbook': True,
                })

            # ── Project PTA for each call type ──
            # Algorithm: simulate FIFO dispatch with skill hierarchy
            has_fleet_drivers = len(all_driver_ids) > 0
            projected = {}
            current_settings = pta_map.get(tid, {})

            for call_type in ('tow', 'winch', 'battery', 'light'):
                # Drivers that can serve this call type
                capable_idle = [d for d in idle_list if _can_serve(d['tier'], call_type)]
                capable_busy = [d for d in busy_list if _can_serve(d['tier'], call_type)]

                # Current PTA setting for this type (exact → default fallback)
                current_min = current_settings.get(call_type) or current_settings.get('default')
                travel = _DISPATCH_TRAVEL.get(call_type, 25)

                if capable_idle:
                    # Idle driver available → use type-specific PTA if set,
                    # otherwise scale the default by call complexity
                    type_specific = current_settings.get(call_type)
                    if type_specific:
                        projected_min = type_specific
                    elif current_min:
                        # Default setting exists but no per-type override
                        # Scale: default is typically calibrated for tow (most common)
                        # Battery/light are faster service → shorter PTA
                        type_scale = {'tow': 1.0, 'winch': 0.75, 'battery': 0.65, 'light': 0.7}
                        projected_min = round(current_min * type_scale.get(call_type, 1.0))
                    else:
                        projected_min = _DEFAULT_PTA.get(call_type, 45)
                elif capable_busy:
                    if not has_fleet_drivers:
                        # Towbook garage: use ERS_PTA__c from live SAs — the actual
                        # promise the dispatch system gave the member.
                        live_ptas = [oc['pta_min'] for oc in all_open if oc.get('pta_min')]
                        if live_ptas:
                            projected_min = round(sum(live_ptas) / len(live_ptas))
                        elif current_min:
                            projected_min = current_min
                        else:
                            projected_min = _DEFAULT_PTA.get(call_type, 45)
                    else:
                        # Fleet garage: simulate — busy drivers become free,
                        # serve queued calls, then our new call
                        heap = [d['remaining_min'] for d in capable_busy]
                        heapq.heapify(heap)

                        for oc in open_sas:
                            if any(_can_serve(d['tier'], oc['tier']) for d in capable_busy):
                                t = heapq.heappop(heap)
                                cycle = _CYCLE_TIMES.get(oc['tier'], 40)
                                heapq.heappush(heap, t + cycle)

                        next_free = heapq.heappop(heap) if heap else 0
                        projected_min = round(next_free + travel)
                else:
                    # No capable drivers — Towbook: use live PTA or setting
                    if not has_fleet_drivers:
                        live_ptas = [oc['pta_min'] for oc in all_open if oc.get('pta_min')]
                        if live_ptas:
                            projected_min = round(sum(live_ptas) / len(live_ptas))
                        elif current_min:
                            projected_min = current_min
                        else:
                            projected_min = _DEFAULT_PTA.get(call_type, 45)
                    else:
                        projected_min = None  # No coverage for this type

                # Recommendation
                if projected_min is None:
                    rec = 'no_coverage'
                elif current_min is None:
                    rec = 'no_setting'
                elif projected_min > current_min * 1.2:
                    rec = 'increase'
                elif projected_min < current_min * 0.6:
                    rec = 'decrease'
                else:
                    rec = 'ok'

                projected[call_type] = {
                    'projected_min': projected_min,
                    'current_setting_min': current_min,
                    'recommendation': rec,
                }

            # Queue stats (all_open = assigned + unassigned, for display)
            queue_by_type = defaultdict(int)
            for oc in all_open:
                queue_by_type[oc['tier']] += 1

            longest_wait = all_open[0]['wait_min'] if all_open else 0
            avg_wait = round(sum(oc['wait_min'] for oc in all_open) / max(len(all_open), 1)) if all_open else 0

            # Average projected PTA across all service types
            proj_vals = [p['projected_min'] for p in projected.values() if p.get('projected_min') is not None]
            avg_projected = round(sum(proj_vals) / len(proj_vals)) if proj_vals else None

            garages.append({
                'id': tid,
                'name': t_name,
                'has_fleet_drivers': has_fleet_drivers,
                'queue_depth': len(all_open),
                'queue_by_type': dict(queue_by_type),
                'drivers': {
                    'total': len(all_driver_ids) if has_fleet_drivers else len(tb_drivers_seen),
                    'idle': len(idle_list),
                    'busy': len(busy_list),
                    'idle_by_tier': _count_by_tier(idle_list),
                    'busy_by_tier': _count_by_tier(busy_list),
                    'capable_idle': {ct: len([d for d in idle_list if _can_serve(d['tier'], ct)]) for ct in ('tow','winch','battery','light')},
                    'capable_busy': {ct: len([d for d in busy_list if _can_serve(d['tier'], ct)]) for ct in ('tow','winch','battery','light')},
                    'is_towbook': not has_fleet_drivers,
                    'busy_details': busy_list,
                    'tb_seen_today': len(tb_drivers_seen),
                    'tb_active': len(tb_drivers),
                },
                'completed_today': completed_count,
                'projected_pta': projected,
                'avg_projected_pta': avg_projected,
                'longest_wait': longest_wait,
                'avg_wait': avg_wait,
            })

        # Sort: most urgent first (highest projected tow PTA, then queue depth)
        def _urgency(g):
            tow_proj = (g['projected_pta'].get('tow') or {}).get('projected_min') or 0
            return (-tow_proj, -g['queue_depth'], g['name'])
        garages.sort(key=_urgency)

        return {
            'garages': garages,
            'computed_at': now_utc.isoformat(),
            'refresh_interval': ttl,
            'totals': {
                'garages_active': len(garages),
                'total_queue': sum(g['queue_depth'] for g in garages),
                'total_drivers': sum(g['drivers']['total'] for g in garages),
                'total_idle': sum(g['drivers']['idle'] for g in garages),
            },
        }

    return cache.cached_query('pta_advisor', _fetch, ttl=ttl)


def _count_by_tier(driver_list):
    counts = defaultdict(int)
    for d in driver_list:
        counts[d['tier']] += 1
    return dict(counts)


@app.post("/api/pta-advisor/refresh")
def pta_advisor_refresh(request: Request):
    """Force refresh PTA advisor cache. PIN-protected."""
    _check_pin(request)
    cache.invalidate('pta_advisor')
    return pta_advisor()


@app.get("/api/admin/settings")
def admin_get_settings(request: Request):
    """Get app settings. PIN-protected."""
    _check_pin(request)
    settings = _load_settings()
    settings.setdefault('pta_refresh_interval', 900)
    return settings


@app.put("/api/admin/settings")
def admin_update_settings(request: Request, body: dict):
    """Update app settings. PIN-protected."""
    _check_pin(request)
    settings = _load_settings()
    if 'pta_refresh_interval' in body:
        val = int(body['pta_refresh_interval'])
        if val < 60 or val > 3600:
            raise HTTPException(status_code=400, detail="Interval must be 60-3600 seconds")
        settings['pta_refresh_interval'] = val
    _save_settings(settings)
    return settings


# ── Admin Panel API ──────────────────────────────────────────────────────────

@app.post("/api/admin/verify")
def admin_verify(request: Request):
    """Verify admin PIN."""
    _check_pin(request)
    return {"ok": True}


@app.get("/api/admin/status")
def admin_status(request: Request):
    """Full system status: cache + SF health + uptime."""
    _check_pin(request)
    return {
        "cache": cache.stats(),
        "salesforce": sf_stats(),
        "uptime_seconds": round(time.time() - _start_time),
    }


@app.post("/api/admin/flush")
def admin_flush(request: Request, prefix: str = Query('', description="Cache key prefix to flush, empty = all")):
    """Flush cache entries. Empty prefix = flush everything."""
    _check_pin(request)
    cache.invalidate(prefix)
    return {"flushed": prefix or "ALL", "cache_after": cache.stats()}


@app.post("/api/admin/flush/live")
def admin_flush_live(request: Request):
    """Flush only live/operational caches (command center, queue, drivers)."""
    _check_pin(request)
    for p in ['command_center', 'queue_live', 'map_drivers', 'sa_lookup', 'simulate', 'pta_advisor']:
        cache.invalidate(p)
    return {"flushed": "live_caches", "cache_after": cache.stats()}


@app.post("/api/admin/flush/historical")
def admin_flush_historical(request: Request):
    """Flush historical caches (scorecard, performance, decomposition, forecast)."""
    _check_pin(request)
    for p in ['scorecard', 'perf_', 'scorer_', 'decomp_', 'forecast_']:
        cache.invalidate(p)
    return {"flushed": "historical_caches", "cache_after": cache.stats()}


@app.post("/api/admin/flush/static")
def admin_flush_static(request: Request):
    """Flush static reference caches (garages, grids, skills, weather)."""
    _check_pin(request)
    for p in ['garages_list', 'map_grids', 'map_weather', 'skills_', 'ops_garages', 'ops_territories']:
        cache.invalidate(p)
    return {"flushed": "static_caches", "cache_after": cache.stats()}


# ── User Management (PIN-protected) ──────────────────────────────────────────

@app.get("/api/admin/users")
def admin_list_users(request: Request):
    """List all users."""
    _check_pin(request)
    return users.list_users()


@app.post("/api/admin/users")
def admin_create_user(request: Request, body: dict):
    """Create a new user."""
    _check_pin(request)
    username = body.get("username", "").strip().lower()
    password = body.get("password", "")
    name = body.get("name", "").strip()
    role = body.get("role", "viewer")
    if not username or not password or not name:
        raise HTTPException(status_code=400, detail="username, password, and name are required")
    if role not in ("admin", "supervisor", "viewer"):
        raise HTTPException(status_code=400, detail="role must be admin, supervisor, or viewer")
    try:
        return users.create_user(username, password, name, role)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.put("/api/admin/users/{username}")
def admin_update_user(request: Request, username: str, body: dict):
    """Update a user."""
    _check_pin(request)
    try:
        return users.update_user(
            username,
            name=body.get("name"),
            role=body.get("role"),
            password=body.get("password") or None,
            active=body.get("active"),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/api/admin/users/{username}")
def admin_delete_user(request: Request, username: str):
    """Delete a user."""
    _check_pin(request)
    try:
        users.delete_user(username)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/admin/sessions")
def admin_list_sessions(request: Request):
    """List active sessions (who's logged in)."""
    _check_pin(request)
    return users.list_sessions()


# ── Matrix Advisor ───────────────────────────────────────────────────────────

def _matrix_period_bounds(period: str):
    """Return (start_iso, end_iso, cache_ttl) for a period key."""
    now = datetime.now(_ET)
    if period == 'this_week':
        start = now - timedelta(days=now.weekday())
        return start.strftime('%Y-%m-%dT00:00:00Z'), now.strftime('%Y-%m-%dT%H:%M:%SZ'), 300
    if period == 'last_month':
        first = now.replace(day=1)
        end = first - timedelta(days=1)
        start = end.replace(day=1)
        return start.strftime('%Y-%m-%dT00:00:00Z'), first.strftime('%Y-%m-%dT00:00:00Z'), 86400
    if period in ('mtd', 'current'):
        start = now.replace(day=1)
        return start.strftime('%Y-%m-%dT00:00:00Z'), now.strftime('%Y-%m-%dT%H:%M:%SZ'), 900
    if period == 'ytd':
        start = now.replace(month=5, day=1) if now.month >= 5 else now.replace(year=now.year - 1, month=5, day=1)
        return start.strftime('%Y-%m-%dT00:00:00Z'), now.strftime('%Y-%m-%dT%H:%M:%SZ'), 900
    # Custom month: '2026-01', '2026-02', etc.
    if len(period) == 7 and '-' in period:
        y, m = int(period[:4]), int(period[5:])
        start = datetime(y, m, 1, tzinfo=_ET)
        if m == 12:
            end = datetime(y + 1, 1, 1, tzinfo=_ET)
        else:
            end = datetime(y, m + 1, 1, tzinfo=_ET)
        is_past = end <= now
        return start.strftime('%Y-%m-%dT00:00:00Z'), end.strftime('%Y-%m-%dT00:00:00Z'), 86400 if is_past else 900
    # Default: last 4 weeks
    start = now - timedelta(weeks=4)
    return start.strftime('%Y-%m-%dT00:00:00Z'), now.strftime('%Y-%m-%dT%H:%M:%SZ'), 900


def _compute_matrix(start_iso: str, end_iso: str):
    """Run parallel SF aggregate queries and compute cascade/decline metrics.

    Key insight: Most zones start at rank 2 (rank 1 is rare or placeholder like
    'LS - LOCKSMITH REQUIRED'). The 'primary' garage is the first real garage in
    the chain. ERS_Spotting_Number__c on the SA matches the rank of the accepting
    garage in the priority matrix chain.
    """

    # Placeholder garage prefixes to skip when finding primary
    _PLACEHOLDER_PREFIXES = ('LS ', '000-', '000 ')

    # 5 parallel SF queries
    data = sf_parallel(
        volume=lambda: sf_query_all(f"""
            SELECT ServiceTerritory.Name, ServiceTerritoryId,
                   Status, StatusCategory, ERS_Dispatch_Method__c,
                   ERS_Spotting_Number__c, ERS_PTA__c,
                   ERS_Cancellation_Reason__c,
                   WorkType.Name, CreatedDate
            FROM ServiceAppointment
            WHERE CreatedDate >= {start_iso}
              AND CreatedDate < {end_iso}
              AND ServiceTerritoryId != null
        """),
        declines=lambda: sf_query_all(f"""
            SELECT ERS_Facility_Decline_Reason__c,
                   ServiceTerritory.Name, COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE CreatedDate >= {start_iso}
              AND CreatedDate < {end_iso}
              AND ERS_Facility_Decline_Reason__c != null
              AND ServiceTerritoryId != null
            GROUP BY ERS_Facility_Decline_Reason__c, ServiceTerritory.Name
            ORDER BY COUNT(Id) DESC
            LIMIT 2000
        """),
        cancellations=lambda: sf_query_all(f"""
            SELECT ERS_Cancellation_Reason__c,
                   ServiceTerritory.Name, COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE CreatedDate >= {start_iso}
              AND CreatedDate < {end_iso}
              AND ERS_Cancellation_Reason__c != null
              AND ServiceTerritoryId != null
            GROUP BY ERS_Cancellation_Reason__c, ServiceTerritory.Name
            ORDER BY COUNT(Id) DESC
            LIMIT 2000
        """),
        matrix=lambda: sf_query_all("""
            SELECT ERS_Parent_Service_Territory__r.Name,
                   ERS_Parent_Service_Territory__c,
                   ERS_Spotted_Territory__r.Name,
                   ERS_Spotted_Territory__c,
                   ERS_Priority__c
            FROM ERS_Territory_Priority_Matrix__c
            WHERE ERS_Parent_Service_Territory__r.IsActive = true
            ORDER BY ERS_Parent_Service_Territory__r.Name, ERS_Priority__c
        """),
        hour_decline=lambda: sf_query_all(f"""
            SELECT HOUR_IN_DAY(CreatedDate) hr,
                   ServiceTerritory.Name, COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE CreatedDate >= {start_iso}
              AND CreatedDate < {end_iso}
              AND ERS_Facility_Decline_Reason__c != null
              AND ServiceTerritoryId != null
            GROUP BY HOUR_IN_DAY(CreatedDate), ServiceTerritory.Name
            ORDER BY COUNT(Id) DESC
            LIMIT 2000
        """),
        surveys=lambda: sf_query_all(f"""
            SELECT ERS_Work_Order__r.ServiceTerritory.Name,
                   ERS_Overall_Satisfaction__c, COUNT(Id) cnt
            FROM Survey_Result__c
            WHERE ERS_Work_Order__r.CreatedDate >= {start_iso}
              AND ERS_Work_Order__r.CreatedDate < {end_iso}
              AND ERS_Overall_Satisfaction__c != null
              AND ERS_Work_Order__r.ServiceTerritoryId != null
            GROUP BY ERS_Work_Order__r.ServiceTerritory.Name, ERS_Overall_Satisfaction__c
            ORDER BY ERS_Work_Order__r.ServiceTerritory.Name
            LIMIT 2000
        """),
    )

    sa_list = data['volume']
    decline_rows = data['declines']
    cancel_rows = data['cancellations']
    matrix_rows = data['matrix']
    hour_decline_rows = data['hour_decline']
    survey_rows = data['surveys']

    # ── Build priority matrix lookup FIRST (needed for primary detection) ──
    zone_chains = defaultdict(list)
    for row in matrix_rows:
        pzone = (row.get('ERS_Parent_Service_Territory__r') or {}).get('Name', '')
        gname = (row.get('ERS_Spotted_Territory__r') or {}).get('Name', '')
        rank = row.get('ERS_Priority__c', 99)
        pid = row.get('ERS_Parent_Service_Territory__c', '')
        gid = row.get('ERS_Spotted_Territory__c', '')
        if pzone and gname:
            zone_chains[pzone].append({
                'rank': rank, 'garage_name': gname, 'garage_id': gid, 'zone_id': pid,
            })
    for chain in zone_chains.values():
        chain.sort(key=lambda x: x['rank'])

    def _is_placeholder(name):
        return any(name.startswith(p) for p in _PLACEHOLDER_PREFIXES)

    # For each zone, find the primary garage (first non-placeholder) and its rank
    zone_primary = {}  # zone -> {'garage': name, 'rank': float}
    for zname, chain in zone_chains.items():
        for entry in chain:
            if not _is_placeholder(entry['garage_name']):
                zone_primary[zname] = {'garage': entry['garage_name'], 'rank': entry['rank']}
                break

    # Build garage→primary_rank mapping (the min rank at which this garage is primary)
    garage_primary_ranks = defaultdict(set)
    for zname, info in zone_primary.items():
        garage_primary_ranks[info['garage']].add(info['rank'])

    # ── Build garage metrics ──
    garage_stats = defaultdict(lambda: {
        'total': 0, 'completed': 0, 'declined': 0,
        'primary_offered': 0, 'primary_accepted': 0,
        'cascaded_in': 0, 'cnw': 0, 'cnw_cascaded': 0,
        'dispatch_method': None, 'pta_sum': 0, 'pta_count': 0,
        'primary_pta_sum': 0, 'primary_pta_count': 0,
        'cascade_pta_sum': 0, 'cascade_pta_count': 0,
        'spot_dist': defaultdict(int),
    })

    for sa in sa_list:
        tname = (sa.get('ServiceTerritory') or {}).get('Name', '')
        if not tname or _is_placeholder(tname):
            continue
        g = garage_stats[tname]
        g['total'] += 1
        status_cat = sa.get('StatusCategory', '')
        if status_cat == 'Completed':
            g['completed'] += 1

        dm = sa.get('ERS_Dispatch_Method__c', '')
        if dm and not g['dispatch_method']:
            g['dispatch_method'] = dm

        pta = sa.get('ERS_PTA__c')
        if pta and isinstance(pta, (int, float)) and pta > 0:
            g['pta_sum'] += pta
            g['pta_count'] += 1

        # Spotting number = rank of accepting garage in the zone chain
        spot = sa.get('ERS_Spotting_Number__c')
        primary_ranks = garage_primary_ranks.get(tname, set())

        if spot and isinstance(spot, (int, float)) and spot > 0:
            g['spot_dist'][int(spot)] += 1

            if primary_ranks and spot in primary_ranks:
                # This garage was the primary for the zone and accepted
                g['primary_accepted'] += 1
                if pta and isinstance(pta, (int, float)) and pta > 0:
                    g['primary_pta_sum'] += pta
                    g['primary_pta_count'] += 1
            elif primary_ranks and spot > min(primary_ranks):
                # This garage received a cascaded call (accepted at a rank higher
                # than its primary position → it was a backup receiver)
                g['cascaded_in'] += 1
                if pta and isinstance(pta, (int, float)) and pta > 0:
                    g['cascade_pta_sum'] += pta
                    g['cascade_pta_count'] += 1
            elif not primary_ranks:
                # Garage isn't primary anywhere — all its calls are cascade receives
                g['cascaded_in'] += 1
                if pta and isinstance(pta, (int, float)) and pta > 0:
                    g['cascade_pta_sum'] += pta
                    g['cascade_pta_count'] += 1

        # "Could Not Wait" tracking
        cancel_reason = sa.get('ERS_Cancellation_Reason__c', '') or ''
        if 'could not wait' in cancel_reason.lower():
            g['cnw'] += 1

    # Helper to extract territory name from aggregate row
    def _agg_tname(row):
        st = row.get('ServiceTerritory')
        if st and isinstance(st, dict):
            return st.get('Name', '')
        return row.get('Name') or ''

    # Decline reasons by garage
    decline_by_garage = defaultdict(list)
    for row in decline_rows:
        tname = _agg_tname(row)
        reason = row.get('ERS_Facility_Decline_Reason__c') or ''
        cnt = row.get('cnt') or row.get('expr0') or 0
        if tname and reason:
            decline_by_garage[tname].append({'reason': reason, 'count': cnt})
            garage_stats[tname]['declined'] += cnt

    # Estimate primary_offered = primary_accepted + declines (when garage is primary)
    for gname, gs in garage_stats.items():
        gs['primary_offered'] = gs['primary_accepted'] + gs['declined']

    # Cancellation reasons by garage
    cancel_by_garage = defaultdict(list)
    for row in cancel_rows:
        tname = _agg_tname(row)
        reason = row.get('ERS_Cancellation_Reason__c') or ''
        cnt = row.get('cnt') or row.get('expr0') or 0
        if tname and reason:
            cancel_by_garage[tname].append({'reason': reason, 'count': cnt})

    # Hourly decline pattern
    hour_decline_by_garage = defaultdict(lambda: defaultdict(int))
    for row in hour_decline_rows:
        tname = _agg_tname(row)
        hr = row.get('hr') or row.get('expr0') or 0
        cnt = row.get('cnt') or row.get('expr1') or 0
        if tname:
            hour_decline_by_garage[tname][int(hr)] += cnt

    # Survey satisfaction by garage
    # KPI = "% Totally Satisfied" (accreditation metric)
    survey_by_garage = defaultdict(lambda: {'total': 0, 'satisfied': 0})
    for row in survey_rows:
        st = row.get('ServiceTerritory')
        if not st:
            # Aggregate query returns nested under WorkOrder relationship
            st = (row.get('ERS_Work_Order__r') or {}).get('ServiceTerritory')
        tname = (st or {}).get('Name', '') if isinstance(st, dict) else ''
        if not tname:
            tname = row.get('Name', '')
        sat = row.get('ERS_Overall_Satisfaction__c', '')
        cnt = row.get('cnt') or row.get('expr0') or 0
        if tname:
            survey_by_garage[tname]['total'] += cnt
            if sat == 'Totally satisfied':
                survey_by_garage[tname]['satisfied'] += cnt

    # ── Build zone health ──
    # NOTE: We can't map individual SAs to zones (no zone field on SA).
    # Zone metrics use the primary garage's performance as a proxy.
    zone_health = []
    for zname, chain in zone_chains.items():
        primary_info = zone_primary.get(zname)
        if not primary_info:
            continue
        p_name = primary_info['garage']
        p_rank = primary_info['rank']
        ps = garage_stats.get(p_name, {})

        # Primary accept rate = primary_accepted / primary_offered
        p_offered = ps.get('primary_offered', 0)
        p_accepted = ps.get('primary_accepted', 0)
        accept_pct = round(100 * p_accepted / p_offered, 1) if p_offered > 0 else None

        # Use primary garage's volume as zone proxy (not sum of all chain garages)
        p_total = ps.get('total', 0)
        p_declined = ps.get('declined', 0)
        p_cnw = ps.get('cnw', 0)

        # Cascade estimate: primary's decline count represents calls that cascaded
        cascade_pct = round(100 * p_declined / p_total, 1) if p_total > 0 else 0

        # Cascade delay estimate: ~8 min per cascade step (industry empirical)
        # Each decline → redispatch cycle takes roughly 8 min
        _CASCADE_STEP_DELAY = 8

        # Build chain detail (skip placeholders)
        chain_detail = []
        for e in chain:
            if _is_placeholder(e['garage_name']):
                continue
            egs = garage_stats.get(e['garage_name'], {})
            e_offered = egs.get('primary_offered', 0)
            e_accepted = egs.get('primary_accepted', 0)
            chain_detail.append({
                'rank': e['rank'],
                'garage': e['garage_name'],
                'accept_pct': round(100 * e_accepted / e_offered, 1) if e_offered > 0 else None,
                'total': egs.get('total', 0),
                'declined': egs.get('declined', 0),
            })
            if len(chain_detail) >= 5:
                break

        zone_health.append({
            'zone': zname,
            'zone_id': chain[0].get('zone_id', ''),
            'primary_garage': p_name,
            'primary_rank': int(p_rank),
            'primary_accept_pct': accept_pct,
            'primary_volume': p_total,
            'primary_declined': p_declined,
            'cascade_pct': cascade_pct,
            'cascade_delay_min': _CASCADE_STEP_DELAY,
            'cnw': p_cnw,
            'satisfaction_pct': round(100 * survey_by_garage[p_name]['satisfied'] / survey_by_garage[p_name]['total'], 1) if survey_by_garage[p_name]['total'] >= 5 else None,
            'chain': chain_detail,
        })

    zone_health.sort(key=lambda z: z.get('cascade_pct', 0), reverse=True)

    # ── Build garage list ──
    garages_out = []
    for gname, gs in sorted(garage_stats.items(), key=lambda x: -x[1]['total']):
        if gs['total'] < 5 or _is_placeholder(gname):
            continue
        offered = gs['primary_offered']
        accepted = gs['primary_accepted']
        accept_pct = round(100 * accepted / offered, 1) if offered > 0 else None
        completion_pct = round(100 * gs['completed'] / gs['total'], 1) if gs['total'] > 0 else 0
        avg_pta = round(gs['pta_sum'] / gs['pta_count']) if gs['pta_count'] else None
        cnw_pct = round(100 * gs['cnw'] / gs['total'], 1) if gs['total'] > 0 else 0
        decline_pct = round(100 * gs['declined'] / gs['total'], 1) if gs['total'] > 0 else 0

        top_declines = sorted(decline_by_garage.get(gname, []), key=lambda x: -x['count'])[:3]
        top_cancels = sorted(cancel_by_garage.get(gname, []), key=lambda x: -x['count'])[:3]

        hr_map = hour_decline_by_garage.get(gname, {})
        hour_declines = [hr_map.get(h, 0) for h in range(24)]

        garages_out.append({
            'name': gname,
            'dispatch_method': gs['dispatch_method'],
            'total': gs['total'],
            'completed': gs['completed'],
            'completion_pct': completion_pct,
            'declined': gs['declined'],
            'decline_pct': decline_pct,
            'accept_pct': accept_pct,
            'avg_pta': avg_pta,
            'cnw': gs['cnw'],
            'cnw_pct': cnw_pct,
            'cascaded_in': gs['cascaded_in'],
            'top_decline_reasons': top_declines,
            'top_cancel_reasons': top_cancels,
            'hourly_declines': hour_declines,
            'satisfaction_pct': round(100 * survey_by_garage[gname]['satisfied'] / survey_by_garage[gname]['total'], 1) if survey_by_garage[gname]['total'] >= 5 else None,
            'survey_count': survey_by_garage[gname]['total'],
        })

    # ── Build recommendations ──
    recommendations = []
    for zh in zone_health:
        if not zh['primary_accept_pct'] or zh['primary_accept_pct'] >= 75:
            continue
        if zh['primary_volume'] < 20:
            continue
        # Find a better alternative in the chain
        best_alt = None
        for ce in zh['chain'][1:]:
            if ce['accept_pct'] and ce['accept_pct'] > zh['primary_accept_pct'] + 10 and ce['total'] >= 10:
                best_alt = ce
                break
        if not best_alt:
            continue

        calls_per_month = zh['primary_volume']
        current_decline_rate = 100 - zh['primary_accept_pct']
        projected_decline_rate = max(100 - best_alt['accept_pct'], 5)
        cascade_reduction = round(calls_per_month * (current_decline_rate - projected_decline_rate) / 100)
        delay_per_cascade = zh['cascade_delay_min']
        time_saved = cascade_reduction * delay_per_cascade

        # CNW avoided: proportion of CNW among declines
        cnw_rate = zh['cnw'] / max(zh['primary_volume'], 1)
        cnw_avoided = round(cascade_reduction * cnw_rate)

        # Include satisfaction for both current and suggested
        cur_survey = survey_by_garage.get(zh['primary_garage'], {'total': 0, 'satisfied': 0})
        alt_survey = survey_by_garage.get(best_alt['garage'], {'total': 0, 'satisfied': 0})

        recommendations.append({
            'zone': zh['zone'],
            'type': 'swap_primary',
            'current_primary': zh['primary_garage'],
            'current_accept_pct': zh['primary_accept_pct'],
            'current_satisfaction': round(100 * cur_survey['satisfied'] / cur_survey['total'], 1) if cur_survey['total'] >= 5 else None,
            'suggested_primary': best_alt['garage'],
            'suggested_accept_pct': best_alt['accept_pct'],
            'suggested_satisfaction': round(100 * alt_survey['satisfied'] / alt_survey['total'], 1) if alt_survey['total'] >= 5 else None,
            'impact': {
                'cascades_avoided': cascade_reduction,
                'minutes_saved': time_saved,
                'cnw_avoided': cnw_avoided,
                'primary_volume': calls_per_month,
            },
            'confidence': 'high' if calls_per_month >= 100 else 'medium',
        })

    recommendations.sort(key=lambda r: -r['impact']['minutes_saved'])

    # ── Cascade depth distribution (overall) ──
    spot_histogram = defaultdict(int)
    for gs in garage_stats.values():
        for spot_val, cnt in gs.get('spot_dist', {}).items():
            spot_histogram[spot_val] += cnt
    cascade_depth = [{'rank': k, 'count': v} for k, v in sorted(spot_histogram.items())]

    # ── Summary ──
    total_calls = sum(g['total'] for g in garage_stats.values())
    total_cascaded = sum(g['cascaded_in'] for g in garage_stats.values())
    total_cnw = sum(g['cnw'] for g in garage_stats.values())
    total_declined = sum(g['declined'] for g in garage_stats.values())

    return {
        'period': {'start': start_iso, 'end': end_iso},
        'summary': {
            'total_calls': total_calls,
            'total_cascaded': total_cascaded,
            'cascade_pct': round(100 * total_cascaded / max(total_calls, 1), 1),
            'total_cnw': total_cnw,
            'total_declined': total_declined,
            'zones_analyzed': len(zone_health),
            'garages_analyzed': len(garages_out),
            'recommendations_count': len(recommendations),
        },
        'zones': zone_health[:100],
        'garages': garages_out[:100],
        'recommendations': recommendations[:20],
        'cascade_depth': cascade_depth,
        'computed_at': datetime.now(_ET).isoformat(),
    }


@app.get("/api/matrix/health")
def matrix_health(period: str = Query('last_month')):
    """Priority Matrix cascade health analysis."""
    start_iso, end_iso, ttl = _matrix_period_bounds(period)
    cache_key = f"matrix_health:{period}"

    def _fetch():
        return _compute_matrix(start_iso, end_iso)

    return cache.cached_query(cache_key, _fetch, ttl=ttl)


_start_time = time.time()


# ── Cache warmup on startup ──────────────────────────────────────────────────
# Pre-populate cache so the first user doesn't wait for cold SF queries.
# Uses FastAPI startup event (runs after gunicorn worker is ready).
import threading

def _warmup_cache():
    """Pre-fetch ALL key endpoints so first users never wait for cold SF queries."""
    import logging
    log = logging.getLogger('warmup')
    try:
        log.info("Cache warmup starting (full)...")

        # Phase 1: Core endpoints (sequential to avoid SF overload)
        warmup_fns = [
            ("garages_list", lambda: list_garages()),
            ("ops_garages", lambda: __import__('ops').get_ops_garages()),
            ("ops_territories", lambda: __import__('ops').get_ops_territories()),
            ("command_center", lambda: command_center()),
            ("ops_brief", lambda: ops_brief()),
            ("map_grids", lambda: get_map_grids()),
            ("map_drivers", lambda: get_map_drivers()),
            ("pta_advisor", lambda: pta_advisor()),
        ]

        for name, fn in warmup_fns:
            try:
                fn()
                log.info(f"  {name}: cached")
            except Exception as e:
                log.warning(f"  {name} warmup failed: {e}")

        log.info("Cache warmup complete.")
    except Exception as e:
        log.warning(f"Cache warmup error: {e}")

@app.on_event("startup")
async def startup_warmup():
    if os.environ.get("WEBSITE_SITE_NAME"):  # Only on Azure
        # Each worker warms its own in-memory cache.
        # 3 workers × 7 endpoints = 21 SF calls — well within 300/min rate limit.
        # Stagger by worker PID to reduce simultaneous SF queries.
        import random
        delay = random.uniform(0, 5)  # 0-5s random delay
        def _delayed_warmup():
            time.sleep(delay)
            _warmup_cache()
        threading.Thread(target=_delayed_warmup, daemon=True).start()


# ── Serve React SPA ──────────────────────────────────────────────────────────
_static_dir = Path(__file__).resolve().parent / "static"

if _static_dir.is_dir():
    _assets_dir = _static_dir / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve React SPA — any non-API route returns index.html."""
        file_path = _static_dir / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_static_dir / "index.html")
