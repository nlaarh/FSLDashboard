# FSL App — Architecture & Operations Knowledge Base

Everything learned about how this app works, how data flows, and critical gotchas.
Companion to `METRICS_KNOWLEDGE_BASE.md` (which covers formulas and per-page metrics).

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React + Vite, Tailwind CSS, Lucide icons, Leaflet maps, clsx |
| Backend | Python FastAPI, single `main.py` + modules (`ops.py`, `dispatch.py`, `scorer.py`, `cache.py`, `sf_client.py`, `users.py`) |
| Data Source | Salesforce FSL (live SOQL queries, no local database) |
| Caching | In-memory with TTL + stale-while-revalidate (`cache.py`) |
| Auth | Cookie-based sessions with HMAC signing + Azure Easy Auth SSO |
| AI Chatbot | Multi-provider (OpenAI/Anthropic/Google) with primary+fallback model |
| Hosting | Azure App Service (Linux, Python 3.11) |
| Build | `npm run build` → `frontend/dist/` → copied to `backend/static/` → served by FastAPI |

---

## Salesforce Data Model — Key Relationships

### Core Objects
| Object | What It Is | Key Fields |
|--------|-----------|------------|
| **ServiceAppointment** | A roadside call (the central object) | Id, AppointmentNumber, Status, CreatedDate, ActualStartTime, Latitude, Longitude, ERS_PTA__c, ERS_Dispatch_Method__c, ServiceTerritoryId, WorkType |
| **ServiceTerritory** | A garage / territory | Id, Name — each garage IS a territory |
| **ServiceResource** | A driver (fleet or contractor) | Id, Name, LastKnownLatitude, LastKnownLongitude, ERS_Driver_Type__c |
| **ServiceTerritoryMember** | Links drivers to territories | ServiceResourceId, ServiceTerritoryId, TerritoryType (P=Primary, S=Secondary, R=Relocation) |
| **WorkType** | Call type definition | Name (Tow, Battery, Winch Out, Lockout, etc.) |
| **WorkOrder** | Parent of SA, links to surveys | Id, WorkOrderNumber, ServiceTerritoryId |
| **AssignedResource** | Links driver to an SA | ServiceResourceId, ServiceAppointmentId |
| **ServiceResourceSkill** | Driver capabilities | ServiceResourceId, Skill.MasterLabel |
| **Skill** | Skill definition | MasterLabel (Tow, Flat Bed, Battery, Lockout, etc.) |
| **Asset** | Trucks/vehicles | Name, ERS_Driver__c (lookup to ServiceResource), ERS_Truck_Capabilities__c, RecordType.Name='ERS Truck' |
| **Shift** | Driver shift schedules | ServiceResourceId, ServiceTerritoryId, StartTime, EndTime |
| **ResourceAbsence** | Driver time off | ResourceId, Start, End, Type |

### Custom Objects
| Object | What It Is |
|--------|-----------|
| **ERS_Territory_Priority_Matrix__c** | Zone-to-garage mapping with rank (1=primary, 2=cascade, 3=backup) |
| **ERS_Service_Appointment_PTA__c** | PTA settings per territory + work type (what time is promised to members) |
| **Survey_Result__c** | Customer satisfaction surveys linked via ERS_Work_Order_Number__c |
| **SkillRequirement** | What skills a WorkType needs |

### Managed Package Objects (FSL)
| Object | What It Is |
|--------|-----------|
| **FSL__Scheduling_Policy__c** | Optimization rules for the FSL scheduler |
| **FSL__Scheduling_Policy_Goal__c** | Goals within a policy (minimize travel, etc.) |
| **FSL__Service_Goal__c** | Individual optimization goals |
| **FSL__Scheduling_Policy_Work_Rule__c** | Work rules within a policy |
| **FSL__Work_Rule__c** | Constraints (max travel, skill match, etc.) |

---

## Territory & Zone Structure

```
AAA WNYC Region
├── Buffalo West (ServiceTerritory)
│   ├── Zone: Cheektowaga (Rank 1 = primary)
│   ├── Zone: Tonawanda (Rank 1)
│   └── Zone: Hamburg (Rank 2 = cascade backup)
├── Buffalo East (ServiceTerritory)
│   ├── Zone: Williamsville (Rank 1)
│   └── Zone: Cheektowaga (Rank 2 = backup for Buffalo West)
├── Rochester (ServiceTerritory)
│   └── ...
└── ...
```

- **Priority Matrix** (`ERS_Territory_Priority_Matrix__c`) defines which garage handles which zone at what priority
- Rank 1 = primary garage for that zone (gets first call)
- Rank 2+ = cascade / backup (gets call if primary declines)
- **Cascade flow**: Member calls → Zone identified → Rank 1 garage dispatched → If decline → Rank 2 garage → etc.

---

## Fleet vs Towbook (Contractors) — Critical Differences

| Aspect | Fleet (Field Services) | Towbook (Contractor) |
|--------|----------------------|---------------------|
| **Identifier** | `ERS_Dispatch_Method__c = 'Field Services'` | `ERS_Dispatch_Method__c = 'Towbook'` |
| **GPS** | Real-time via `LastKnownLatitude/Longitude` | NOT available (no GPS tracking) |
| **ActualStartTime** | Real arrival time | **FAKE** — set to a future estimate at completion time |
| **Real Arrival** | `ActualStartTime` | `ServiceAppointmentHistory` WHERE `Field='Status'` AND `NewValue='On Location'` → the `CreatedDate` of that history row |
| **Driver Name** | `ServiceResource.Name` via `AssignedResource` | `Off_Platform_Driver__c` → Contact record, OR `Off_Platform_Truck_Id__c` |
| **Data Quality** | High — real GPS, real timestamps | Lower — estimated times, no GPS, some fields missing |
| **Truck Info** | `Asset` table (ERS_Driver__c links to ServiceResource) | `Off_Platform_Truck_Id__c` on SA |

### Getting Towbook ATA (the #1 gotcha)
```
1. Get ServiceAppointment.Id for the Towbook SA
2. Query ServiceAppointmentHistory:
   SELECT CreatedDate FROM ServiceAppointmentHistory
   WHERE ServiceAppointmentId = '{sa_id}'
   AND Field = 'Status' AND NewValue = 'On Location'
   ORDER BY CreatedDate DESC LIMIT 1
3. ATA = (history.CreatedDate - SA.CreatedDate) in minutes
```
**NEVER use ActualStartTime for Towbook** — it's always wrong.

### Getting Towbook Driver Name
- Check `Off_Platform_Driver__c` (lookup to Contact) on the SA
- If null, check `Off_Platform_Truck_Id__c` for truck ID
- For fleet: `AssignedResource` → `ServiceResource.Name`

---

## Skill Hierarchy & Matching

```
Tow Driver (most versatile)
├── Can handle: Tow, Flat Bed, Wheel Lift
├── Can also handle: Light Service (tire, lockout, winch out, fuel, pvs)
└── Can also handle: Battery (battery, jumpstart)

Light Service Driver
├── Can handle: Tire, Lockout, Locksmith, Winch Out, Fuel, PVS
└── Can also handle: Battery, Jumpstart

Battery Driver (least versatile)
└── Can handle: Battery, Jumpstart only
```

- Skills stored in `ServiceResourceSkill` → `Skill.MasterLabel`
- Work type requirements in `SkillRequirement` → `WorkType`
- **Cross-skilling**: A tow driver CAN be sent to a battery call (capable), but it's a "cross-skill" dispatch (scores 75 instead of 100 for skill match)

---

## Caching Architecture

All data is fetched live from Salesforce, cached in-memory with TTLs:

| Category | Endpoints | TTL | Notes |
|----------|----------|-----|-------|
| **Live** | Command Center, Queue, SA Lookup, Driver GPS, Dispatch Map | 30s-120s | Shared across users, auto-refresh |
| **Historical** | Scorecard, Performance, Decomposition, Forecast, Score | 300s-3600s | Per territory + period |
| **Static** | Garage List, Map Grids, Weather, Skills, Priority Matrix | 600s-3600s | Rarely changes |

- **Stale-while-revalidate**: When TTL expires, one thread fetches fresh data while others serve stale cache
- **Circuit breaker**: If Salesforce errors spike, breaker opens → all requests serve stale cache until SF recovers
- **Rate limiting**: Max API calls per minute to Salesforce to stay within org limits
- Admin can flush cache categories independently (Live, Historical, Static, or All)

---

## Driver Recommendation Algorithm

When asked "who should handle SA X?":

1. **Fetch SA details** — location (lat/lon), work type, territory, PTA promise
2. **Fetch all territory members** — drivers assigned to that territory
3. **Fetch driver skills** — from ServiceResourceSkill
4. **Fetch driver workload** — count of active (Dispatched/Assigned) SAs per driver
5. **Filter**: exclude Towbook placeholders, exclude drivers without matching skills, exclude drivers with no GPS
6. **Score each driver** (0-100 composite):
   - **ETA (40%)**: `100 - max(0, (ETA_min - 10)) * 3` — penalizes every minute past 10
   - **Skill Match (25%)**: 100 if exact match, 75 if cross-skill capable
   - **Workload (20%)**: `100 - active_jobs * 30` — fewer jobs = higher score
   - **Shift (15%)**: 100 if idle, 70 if 1 active job, 40 if 2+
7. **Sort by composite score** descending → return top 5

ETA is calculated as: `distance_miles / 25 mph * 60 minutes`
Distance uses Haversine formula from `ServiceResource.LastKnownLatitude/Longitude` to `SA.Latitude/Longitude`

---

## PTA (Promised Time of Arrival) System

- Each territory + work type has a PTA setting in `ERS_Service_Appointment_PTA__c`
- Defaults if no config: Tow=60min, Winch=50min, Battery=45min, Light=45min
- When a call comes in, Mulesoft reads the PTA setting and quotes it to the member
- **PTA Accuracy** = % of completed SAs where actual response time ≤ promised PTA
- The PTA Advisor page projects whether current PTAs are achievable based on today's driver positions and queue depth

---

## Garage Scoring System

8 dimensions → composite score 0-100 → letter grade:

| Dimension | Weight | Target | Direction |
|-----------|--------|--------|-----------|
| 45-Min SLA Hit Rate | 30% | 100% | Higher = better |
| Completion Rate | 15% | 95% | Higher = better |
| Customer Satisfaction | 15% | 82% | Higher = better |
| Median Response Time | 10% | ≤ 45 min | Lower = better |
| PTA Accuracy | 10% | 90% | Higher = better |
| "Could Not Wait" Rate | 10% | < 3% | Lower = better |
| Dispatch Speed | 5% | ≤ 5 min | Lower = better |
| Facility Decline Rate | 5% | < 2% | Lower = better |

Grade scale: A ≥ 90, B ≥ 80, C ≥ 70, D ≥ 60, F < 60

Satisfaction is measured from `Survey_Result__c` where `ERS_Overall_Satisfaction__c = 'Totally Satisfied'`, matched to SAs via `ERS_Work_Order_Number__c`.

---

## Security Model

### Authentication
- Cookie-based: `fslapp_auth` cookie with HMAC-signed payload `username:role:session_token`
- Azure Easy Auth: `x-ms-client-principal-name` header for SSO
- PIN-protected admin endpoints: `X-Admin-Pin` header

### Chatbot Security (7 layers)
1. **Rate limit**: 10 questions/minute per session
2. **Prompt injection detection**: regex patterns for "ignore instructions", "jailbreak", etc. → CRITICAL: logout + email alert
3. **Keyword blocklist**: export, dump, SQL, backend, socket, password → MEDIUM: block + email alert
4. **Email detection**: no email addresses allowed in questions → MEDIUM
5. **Historical data guard**: refuses "last month", date ranges → LOW: friendly redirect
6. **Off-topic guard**: must contain FSL-related terms → LOW: friendly redirect
7. **Response sanitization**: strips emails, API keys, file paths from LLM output

Critical threats → force logout + email alert to nlaaroubi@nyaaa.com

### AI Chatbot Architecture
- Multi-provider: OpenAI, Anthropic, Google (configured in Admin)
- Primary model + fallback model (auto-retry on failure)
- System prompt contains: security rules + operations knowledge base + data dictionary + live data snapshot
- Live data injection: server-side keyword classification → fetches relevant internal data → injects into prompt (PII stripped, capped volume, today only)

---

## Key Files Reference

| File | What It Does |
|------|-------------|
| `backend/main.py` | FastAPI app — all API endpoints, auth, chatbot, admin, issue management |
| `backend/ops.py` | Territory operations — daily ops dashboard, garage operations table |
| `backend/dispatch.py` | Queue board, driver recommendations, cascade status, forecast |
| `backend/scorer.py` | 8-dimension garage scoring engine |
| `backend/cache.py` | In-memory cache with TTL, stale-while-revalidate, circuit breaker |
| `backend/sf_client.py` | Salesforce client — SOQL queries, parallel execution, rate limiting |
| `backend/users.py` | User management — auth, sessions, roles |
| `frontend/src/pages/Help.jsx` | Help Center — 8 sections, floating chatbot, data dictionary viewer |
| `frontend/src/pages/Admin.jsx` | Admin panel — users, cache, AI config, map style |
| `frontend/src/pages/CommandCenter.jsx` | Real-time multi-territory ops dashboard |
| `frontend/src/pages/Dashboard.jsx` | Per-garage dashboard (schedule, scorecard, map) |
| `frontend/src/pages/PtaAdvisor.jsx` | PTA projection and recommendation tool |
| `frontend/src/pages/MatrixAdvisor.jsx` | Territory priority matrix analysis |
| `frontend/src/components/GarageDashboard.jsx` | Garage detail view with tabs |
| `frontend/src/components/Layout.jsx` | App shell — nav bar, routing |
| `frontend/src/api.js` | All API client functions |
| `frontend/public/data/fsl-dictionary.json` | Master data dictionary (24 entities, 119 fields, 27 relationships) |

---

## Deployment

- **Azure App Service**: `fslapp-nyaaa.azurewebsites.net`
- **Build process**: `cd frontend && npm run build` → `cp -r dist/* ../backend/static/`
- **Start command**: `gunicorn -k uvicorn.workers.UvicornWorker main:app`
- **Environment variables**: `SF_USERNAME`, `SF_PASSWORD`, `SF_SECURITY_TOKEN`, `SF_DOMAIN`, `COOKIE_SECRET`, `GITHUB_TOKEN`, `AGENTMAIL_API_KEY`
- See `MANUAL_DEPLOY.md` for step-by-step Azure deployment instructions

---

## Common Gotchas & Lessons Learned

1. **Towbook ActualStartTime is ALWAYS wrong** — use ServiceAppointmentHistory "On Location" instead
2. **Tow Drop-Off** work type is excluded from ALL metrics — it's the second leg of a tow, not a new call
3. **Response times > 480 min** are treated as data errors in PTA calculations
4. **PTA = 0 or 999** are sentinel values meaning "not set" — excluded from accuracy calculations
5. **ServiceAppointmentHistory** queries are expensive — batch SA IDs, never query one-by-one
6. **Satisfaction surveys** live in a separate custom object (`Survey_Result__c`), matched by WorkOrderNumber, NOT by SA Id
7. **DST transitions** can cause time calculation errors — always use timezone-aware datetimes with `America/New_York`
8. **Circuit breaker** protects Salesforce — if it trips, the app serves stale cached data until SF recovers
9. **Fleet vs Towbook detection**: check `ERS_Dispatch_Method__c`, NOT driver type. A territory can have both.
10. **Driver GPS freshness**: `LastKnownLocationDate` tells you when the GPS was last updated — stale positions (>30min) are unreliable
