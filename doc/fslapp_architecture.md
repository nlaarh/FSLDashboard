# FSLAPP Technical Architecture

## Stack
- **Frontend**: React 18 + Vite, Tailwind CSS, Leaflet maps, Lucide icons, Axios
- **Backend**: FastAPI (Python 3.13), uvicorn, live Salesforce queries via `sf_client.py`
- **Auth**: Phase 1 = local users (JSON file), Phase 2 = Microsoft SSO (Azure AD Easy Auth)
- **Caching**: Custom in-memory cache with TTLs, stale-while-revalidate, circuit breaker for SF

## Directory Layout
```
FSLAPP/
├── frontend/src/
│   ├── api.js                 — All API client functions (axios)
│   ├── mapStyles.js           — 8 map tile styles, localStorage persistence
│   ├── index.css              — Global styles, Tailwind
│   ├── pages/
│   │   ├── Admin.jsx          — PIN-gated admin: users, sessions, cache, map style, TTL ref
│   │   ├── CommandCenter.jsx  — Main ops dashboard with map (6 layers)
│   │   ├── PtaAdvisor.jsx     — PTA projections for all garages (4 types)
│   │   ├── MapPage.jsx        — Standalone map (grid, drivers, SAs, weather)
│   │   └── ...
│   └── components/
│       ├── GarageDashboard.jsx — Garage performance metrics, charts
│       ├── MapView.jsx         — Reusable map for dispatch analysis
│       └── ...
├── backend/
│   ├── main.py          — FastAPI app, all endpoints, auth middleware
│   ├── ops.py           — Daily operations queries (territories, garages)
│   ├── sf_client.py     — Salesforce REST client (parallel queries, rate limiter, circuit breaker)
│   ├── cache.py         — In-memory cache with TTL + stale-while-revalidate
│   ├── users.py         — User store (JSON file), session management
│   ├── scorer.py        — Garage composite scoring
│   ├── scheduler.py     — Schedule generation
│   ├── simulator.py     — Day simulation + haversine
│   └── dispatch.py      — Live queue, driver recommendations, cascade, forecast
```

## Auth System (as of Mar 2026)

### Login Flow
1. Server renders `/login` HTML page with SSO button + username/password form
2. SSO: redirects to `/.auth/login/aad` (Azure Easy Auth) — sets `x-ms-client-principal` header
3. Local: `POST /api/auth/login` → `users.authenticate()` → creates session → sets signed cookie
4. Cookie format: `{username}:{role}:{session_token}.{hmac_signature}`
5. Middleware checks: Azure header → signed cookie → local dev bypass

### User Management
- Store: `~/.fslapp/users.json` — passwords hashed SHA-256 + random salt
- Default admin: `admin` / `admin2026!@` (auto-created if no users exist)
- Roles: `admin`, `supervisor`, `viewer`
- Sessions: in-memory dict, 24h expiry, track login_time + last_seen
- Admin API endpoints (PIN-protected): CRUD `/api/admin/users`, `/api/admin/sessions`
- PIN: env `ADMIN_PIN` or default `121838`

### Phase 2 Plan
- Add Microsoft SSO via Azure AD Easy Auth (already supported in middleware)
- Local users remain as fallback / service accounts

## Map System

### 8 Map Styles (saved in localStorage)
- apple_dark, dark_matter, voyager_dark, voyager, apple_light, positron, satellite, topo
- Some use CSS filter inversion to create dark mode from light tiles
- `mapStyles.js` exports `getMapConfig()`, fires `mapStyleChanged` window event for cross-component sync
- Style switcher in Admin page with preview tiles (actual map tiles at Buffalo coordinates)

### Map Layers (CommandCenter.jsx)
1. **Active SAs** — CircleMarker, color-coded by status
2. **Fleet Drivers** — Truck SVG icons (purple=service, amber=tow), tooltip shows truck + capabilities
3. **Fleet Garages** — Green square icons with wrench
4. **Towbook Garages** — Orange circle icons with wrench (static locations from ServiceTerritory coords)
5. **Grid Boundaries** — GeoJSON polygons, style adapts for dark/light maps
6. **Weather** — Station markers with temp, emoji, conditions

### Key Map Patterns
- GeoJSON must re-render on style change → use dynamic `key` prop: `key={`grids-${isDark ? 'dark' : 'light'}`}`
- CSS filter on tiles: inject `<style>` tag inside MapContainer
- `noSubdomains` flag for ESRI satellite tiles (no `{s}` in URL)
- Grid colors: dark maps use `#818cf8` (indigo-400), light maps use `#4f46e5` (indigo-600) with thicker lines

## Driver Identification (Vehicle Login)

### The Correct Way to Find "On-Shift" Drivers
```sql
SELECT ERS_Driver__c, Name, ERS_Truck_Capabilities__c, ERS_LegacyTruckID__c
FROM Asset
WHERE RecordType.Name = 'ERS Truck'
  AND ERS_Driver__c != null
```
- ~115 drivers logged into vehicles at any time
- `ERS_Driver__c` links to ServiceResource.Id
- **Replaces** old GPS freshness check (2-hour cutoff was unreliable)
- Applied to: `/api/ops/brief`, `/api/map/drivers`, `/api/sa/{number}`

### Fleet vs Towbook
- **Fleet drivers**: Real GPS from ServiceResource.LastKnownLatitude/Longitude, vehicle login from Asset
- **Towbook "drivers"**: 73 placeholder ServiceResources (one per garage), NO individual GPS
- **Towbook garage locations**: From ServiceTerritory lat/lon (the garage's physical address)
- `ERS_Facility_Account__r.Dispatch_Method__c` on ServiceTerritory distinguishes Fleet vs Towbook

### Closest Driver Calculations
- Only apply to Fleet drivers logged into vehicles
- Towbook = external contractors, can't redirect them
- Uses haversine distance from driver GPS to SA coordinates

## Cache Architecture

### TTL Tiers
- **Live** (30-120s): command_center, queue_live, map_drivers, sa_lookup, simulate, recommend, cascade
- **Historical** (300-3600s): scorer, scorecard, perf, decomp, forecast
- **Static** (600-3600s): garages_list, map_grids, map_weather, skills, ops_garages, ops_territories

### Flush Controls (Admin page, PIN-protected)
- Flush Live / Historical / Static / Everything
- Each flush category clears specific key prefixes
- Cards use `flex flex-col` + `mt-auto` on button for aligned flush buttons

## Garage Dashboard Metrics

### 1st Call Acceptance (first_call_pct)
- **Primary metric**: When garage is primary in priority matrix (`ERS_Spotting_Number__c = 1`), did they accept?
- **PITFALL**: `ERS_Spotting_Number__c` is a FORMULA field — can't GROUP BY in SOQL, and SF may return int `1` or float `1.0` → must check `in (1, 1.0)`
- **PITFALL**: Many garages (especially Towbook) have NO spotting data → `first_call_pct` was `None`
- **Fix**: Fallback to overall acceptance rate (accepted / total) when no spotting data; label changes to "Call Acceptance" with `first_call_source` field indicating 'spotting' vs 'acceptance'

### Response Times
- Exclude Tow Drop-Off SAs (member response = Pick-Up only)
- Exclude Towbook SAs (ActualStartTime is bulk-updated at midnight, not real arrival)
- Only Field Services SAs have reliable ATA (CreatedDate → ActualStartTime)

### Completion Rate
- completed / total dispatched (all statuses)

### Performance Endpoint
- `GET /api/garages/{id}/performance?period_start=YYYY-MM-DD&period_end=YYYY-MM-DD`
- Parallel SF queries: individual SAs + WO IDs for surveys + trend aggregate
- Returns: dispatch_analysis, completion, first_call, response_times, survey, definitions

## PTA Advisor (`/api/pta-advisor`)
- **Page**: `PtaAdvisor.jsx` — route `/pta`
- **4 call types**: Tow, Winch, Battery, Light (everything else)
- **Cycle times**: Tow=115, Winch=40, Battery=38, Light=33 min
- **Dispatch+travel buffer**: Tow=30, Winch=25, Battery=25, Light=25 min
- **5 parallel SF queries**: today's SAs (with Off_Platform_Driver__r.Name), assigned resources, logged-in drivers (Asset), territory members, PTA settings (ERS_Service_Appointment_PTA__c)
- **Fleet drivers**: from Asset WHERE ERS_Driver__c != null → capability-based tier (tow/light/battery)
- **Towbook drivers**: from SA.Off_Platform_Driver__r.Name (real names), NOT from AssignedResource (generic "Towbook-XXX")
  - `Off_Platform_Driver__r.Name` = individual driver name
  - `Off_Platform_Truck_Id__c` = truck ID
  - `ERS_OffPlatformDriverLocation__c` = GPS
  - AssignedResource.ServiceResource.Name = generic "Towbook-076DO" (useless for individual drivers)
- **Projection algorithm**: heap-based FIFO simulation
  - Idle drivers → use PTA setting scaled by type (tow=1.0, winch=0.75, battery=0.65, light=0.7)
  - Busy drivers → simulate queue drain + travel buffer
  - Only UNASSIGNED SAs go in queue (assigned SAs counted in driver's remaining time)
- **Towbook garages**: no idle driver visibility, use PTA setting as projection
- **Fleet garages**: if no capable drivers for a type → "no_coverage" (NOT PTA setting fallback)
- **Driver tier classification** (`_driver_tier`):
  - _TOW_CAPS = {'tow', 'flat bed', 'wheel lift'}
  - _BATTERY_CAPS = {'battery', 'battery service', 'jumpstart'}
  - Check tow caps first → if match → 'tow'
  - Check battery caps → if match AND has light caps (tire/lockout/etc) → 'light'
  - Check battery caps → if match alone → 'battery'
  - Default → 'light'
- **Cache**: TTL = configurable via `~/.fslapp/settings.json` (default 900s/15min)
- **Refresh**: PIN-protected manual refresh, auto-refresh via setInterval
- **Settings**: `GET/PUT /api/admin/settings` — pta_refresh_interval

## Cross-Territory Dispatch (VERIFIED Mar 9, 2026)
- **Fleet drivers are DE FACTO territory-locked**
  - 7-day analysis (Mar 2-9): 95 Fleet drivers, 924 dispatch records
  - Only 2 drivers (2%) were dispatched to >1 territory (both edge cases: WM zones)
  - 93 drivers (98%) served ONLY their home territory
  - Despite some drivers having multi-territory STM assignments (admin only), Mulesoft dispatches within home territory
- **Fleet = only ~20-26% of total volume** (~924 AR records / week for Field Services)
- **Contractor (Towbook) = ~74-80% of total volume** — dispatchers have NO driver-level control
- **Dispatch model**: Mulesoft assigns call → garage (via Priority Matrix) → garage assigns their own driver
  - Fleet: Mulesoft picks driver within the territory
  - Towbook: Mulesoft sends to garage, garage dispatcher assigns
- **Conclusion**: Cross-territory Fleet rebalancing has low practical value. The real optimization opportunity is in **contractor garage selection** (Priority Matrix) and **cascade efficiency**
- Grid boundaries (FSL__Polygon__c/KML) define zones for the Priority Matrix, not driver movement

## Known SF Field Pitfalls
- `ERS_Spotting_Number__c` — formula field, can't GROUP BY, returns int or float
- `SA.Description` — can't filter in WHERE clause
- `ERS_Auto_Assign__c` — UNRELIABLE for dispatch analysis (use AssignedResource.CreatedBy instead)
- `ERS_Facility_Dispatch_Method__c` on WorkOrder — formula field, NOT groupable
- Formula fields generally: check with `sf_describe` before using in GROUP BY or WHERE
- Towbook `ActualStartTime` — bulk-updated at midnight, NOT real arrival time

## Frontend Patterns
- Dark theme throughout (slate-900 bg, glass cards)
- `glass` CSS class for card backgrounds
- Brand color: indigo (`brand-400`, `brand-500`, `brand-600`)
- PIN gate pattern: admin features behind PIN verification, then periodic refresh
- Axios interceptor base: `/api` prefix, 60s timeout
- Map style changes: localStorage + `window.dispatchEvent(new Event('mapStyleChanged'))`
