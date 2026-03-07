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
    return (dt - timedelta(hours=5)) if dt else None


from sf_client import sf_query_all, sf_parallel
from scheduler import generate_schedule
from simulator import simulate_day, haversine
from scorer import compute_score
from ops import get_ops_territories, get_ops_territory_detail, get_ops_garages
import cache

app = FastAPI(title="FSL App", version="1.0.0")

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
.sso-btn{width:100%;padding:.8rem;background:#0078d4;color:#fff;border:none;border-radius:6px;font-size:1rem;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:.6rem}
.sso-btn:hover{background:#106ebe}
.sso-btn svg{width:20px;height:20px}
.divider{display:flex;align-items:center;margin:1.5rem 0;color:#999;font-size:.85rem}
.divider::before,.divider::after{content:'';flex:1;border-bottom:1px solid #ddd}
.divider::before{margin-right:.8rem}
.divider::after{margin-left:.8rem}
.pwd-toggle{text-align:center;margin-bottom:1rem}
.pwd-toggle a{color:#0066cc;cursor:pointer;font-size:.9rem;text-decoration:none}
.pwd-toggle a:hover{text-decoration:underline}
.pwd-form{display:none}
.pwd-form.show{display:block}
input{width:100%;padding:.6rem;margin:.3rem 0 .8rem;border:1px solid #ddd;border-radius:4px;box-sizing:border-box;font-size:.95rem}
.login-btn{width:100%;padding:.7rem;background:#333;color:#fff;border:none;border-radius:6px;font-size:.95rem;cursor:pointer}
.login-btn:hover{background:#555}
.err{color:#cc0000;text-align:center;margin-bottom:.8rem;font-size:.9rem}
</style></head>
<body><div class="card">
<h2>FSLAPP</h2>
<div class="subtitle">Field Service Lightning Analytics</div>
<button class="sso-btn" onclick="window.location.href='/.auth/login/aad'">
<svg viewBox="0 0 21 21" fill="none"><rect x="1" y="1" width="9" height="9" fill="#f25022"/>
<rect x="11" y="1" width="9" height="9" fill="#7fba00"/><rect x="1" y="11" width="9" height="9" fill="#00a4ef"/>
<rect x="11" y="11" width="9" height="9" fill="#ffb900"/></svg>
Sign in with Microsoft
</button>
<div class="divider">or</div>
<div class="pwd-toggle"><a onclick="document.getElementById('pwdForm').classList.toggle('show')">Use Username and Password</a></div>
<div class="pwd-form" id="pwdForm">
<div class="err" id="err"></div>
<form onsubmit="return doLogin(event)">
<input name="username" placeholder="Username" required>
<input name="password" type="password" placeholder="Password" required>
<button type="submit" class="login-btn">Sign In</button>
</form>
</div>
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
    if creds.get("username") == _ADMIN_USER and creds.get("password") == _ADMIN_PASS:
        payload = f"{_ADMIN_USER}:{int(time.time())}"
        response.set_cookie("fslapp_auth", _sign_cookie(payload), httponly=True, samesite="lax", max_age=86400)
        return {"ok": True, "user": _ADMIN_USER}
    raise HTTPException(status_code=401, detail="Invalid credentials")


@app.get("/api/auth/me")
def auth_me(request: Request):
    # Azure Easy Auth
    principal = request.headers.get("x-ms-client-principal-name")
    if principal:
        return {"user": principal, "method": "sso"}
    # Admin cookie
    cookie = request.cookies.get("fslapp_auth")
    payload = _verify_cookie(cookie) if cookie else None
    if payload:
        return {"user": payload.split(":")[0], "method": "admin"}
    return {"user": "dev", "method": "local"}


@app.post("/api/auth/logout")
def auth_logout(response: Response):
    response.delete_cookie("fslapp_auth")
    return {"ok": True}


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "db_seeded": True, "sync_in_progress": False}


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
    cache_key = f"schedule_{territory_id}_{start_date or 'none'}_{end_date or 'none'}_{weeks}"
    result = cache.cached_query(
        cache_key,
        lambda: generate_schedule(territory_id, weeks, start_date=start_date, end_date=end_date),
        ttl=600,
    )
    if 'error' in result and not result.get('schedule'):
        raise HTTPException(status_code=404, detail=result['error'])
    return result


# ── Scorecard — Goal-Based Performance ───────────────────────────────────────

@app.get("/api/garages/{territory_id}/scorecard")
def get_scorecard(territory_id: str, weeks: int = Query(4, ge=1, le=12)):
    """Performance scorecard: SLA compliance, fleet capacity, and gap analysis."""
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
                SELECT CreatedDate, ActualStartTime, ERS_PTA__c
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                  AND Status = 'Completed'
                  AND ActualStartTime != null
                  AND WorkType.Name != 'Tow Drop-Off'
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
                if 0 < diff < 1440:
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

    return cache.cached_query(f'scorecard_{territory_id}_{weeks}', _fetch, ttl=300)


# ── Appointments (Day View) ─────────────────────────────────────────────────

@app.get("/api/garages/{territory_id}/appointments")
def get_appointments(territory_id: str, date_str: str = Query(..., alias='date')):
    """Get all SAs for a territory on a specific date."""
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
    results = simulate_day(territory_id, date_str)
    if not results:
        raise HTTPException(status_code=404, detail="No simulatable SAs found")

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


# ── Performance Score ────────────────────────────────────────────────────────

@app.get("/api/garages/{territory_id}/score")
def get_score(territory_id: str, weeks: int = Query(4, ge=1, le=12)):
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
                # Exclude Tow Drop-Off — member response time is on Pick-Up SA only
                wt_name = (s.get('WorkType') or {}).get('Name', '') or ''
                if 'drop' in wt_name.lower():
                    continue
                c = _parse_dt(s.get('CreatedDate'))
                a = _parse_dt(s.get('ActualStartTime'))
                if c and a:
                    diff = (a - c).total_seconds() / 60
                    if 0 < diff < 1440:
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


# ── SA Lookup — Zoom-to with Driver Positions ────────────────────────────────

@app.get("/api/sa/{sa_number}")
def lookup_sa(sa_number: str):
    """Lookup an SA by AppointmentNumber and return driver positions."""
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
        raise HTTPException(status_code=404, detail=f"SA {sa_number} not found")

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

    # Live driver GPS
    if tid:
        members = sf_query_all(f"""
            SELECT ServiceResourceId, ServiceResource.Name,
                   ServiceResource.LastKnownLatitude,
                   ServiceResource.LastKnownLongitude,
                   ServiceResource.LastKnownLocationDate,
                   TerritoryType
            FROM ServiceTerritoryMember
            WHERE ServiceTerritoryId = '{tid}'
        """)
        members = [m for m in members
                    if not ((m.get('ServiceResource') or {}).get('Name') or '').lower().startswith('towbook')]

        sa_lat = sa.get('Latitude')
        sa_lon = sa.get('Longitude')
        if sa_lat: sa_lat = float(sa_lat)
        if sa_lon: sa_lon = float(sa_lon)

        for m in members:
            sr = m.get('ServiceResource') or {}
            d_lat = sr.get('LastKnownLatitude')
            d_lon = sr.get('LastKnownLongitude')
            if d_lat: d_lat = float(d_lat)
            if d_lon: d_lon = float(d_lon)
            dist = haversine(d_lat, d_lon, sa_lat, sa_lon) if d_lat and d_lon and sa_lat and sa_lon else None

            gps_date = _to_eastern(sr.get('LastKnownLocationDate'))
            result['drivers'].append({
                'id': m['ServiceResourceId'],
                'name': sr.get('Name', '?'),
                'phone': '',
                'lat': d_lat,
                'lon': d_lon,
                'gps_time': gps_date.strftime('%I:%M %p') if gps_date else '?',
                'distance': dist,
                'territory_type': m.get('TerritoryType', '?'),
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
    cache_key = f"perf_{territory_id}_{period_start}_{period_end}"
    return cache.cached_query(cache_key, lambda: _compute_performance(territory_id, period_start, period_end), ttl=300)


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
                   WorkType.Name
            FROM ServiceAppointment
            WHERE ServiceTerritoryId = '{territory_id}'
              AND CreatedDate >= {since}
              AND CreatedDate < {until}
              AND Status IN ('Dispatched','Completed','Canceled','Assigned')
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
    )

    sas = data['sas']
    if not sas:
        raise HTTPException(status_code=404, detail="No SAs found for this period")

    total = len(sas)
    completed = [s for s in sas if s.get('Status') == 'Completed']

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

    # Response times (exclude Tow Drop-Off — member response is on Pick-Up SA)
    response_times = []
    for s in completed:
        wt_name = (s.get('WorkType') or {}).get('Name', '') or ''
        if 'drop' in wt_name.lower():
            continue
        created = _parse_dt(s.get('CreatedDate'))
        started = _parse_dt(s.get('ActualStartTime'))
        if created and started:
            diff = (started - created).total_seconds() / 60
            if 0 < diff < 1440:
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

    # PTS-ATA
    pts_deltas = []
    for s in completed:
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
            # Shift UTC hour to Eastern
            eastern_hr = (hr - 5) % 24
            key = f"{eastern_hr:02d}:00"
        else:
            m = int(r.get('m', 1))
            key = f"2026-{m:02d}-{d:02d}"
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
        'response_time': rt,
        'pts_ata': pts_ata,
        'satisfaction': satisfaction,
        'trend': trend,
        'period': {
            'start': period_start,
            'end': period_end,
            'single_day': is_single_day,
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
    """Active drivers with last known GPS positions (cached 2 minutes)."""
    def _fetch():
        drivers = sf_query_all("""
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
        drivers = [d for d in drivers if not d.get('Name', '').lower().startswith('towbook')]
        result = []
        for d in drivers:
            gps_date = _to_eastern(d.get('LastKnownLocationDate'))
            rr = d.get('RelatedRecord') or {}
            result.append({
                'id': d['Id'],
                'name': d.get('Name', '?'),
                'lat': float(d['LastKnownLatitude']),
                'lon': float(d['LastKnownLongitude']),
                'gps_time': gps_date.strftime('%I:%M %p') if gps_date else '?',
                'driver_type': d.get('ERS_Driver_Type__c', ''),
                'tech_id': d.get('ERS_Tech_ID__c', ''),
                'phone': rr.get('Phone') or None,
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


# ── Serve React SPA ──────────────────────────────────────────────────────────
_static_dir = Path(__file__).resolve().parent / "static"

if _static_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=_static_dir / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve React SPA — any non-API route returns index.html."""
        file_path = _static_dir / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_static_dir / "index.html")
