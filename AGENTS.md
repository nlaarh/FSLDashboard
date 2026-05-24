# Repository Guidelines

## Project Structure
- FastAPI backend at `backend/` with entrypoint `backend/main.py` (not `app.py`)
- Vite/React frontend at `frontend/`, served via backend static files in production
- Routers in `backend/routers/`, shared helpers at backend root (`cache.py`, `utils.py`, etc.)
- Tests in `backend/tests/` (pytest + FastAPI TestClient, named `test_*.py`)
- Infra/PostgreSQL under `infra/postgres/`

## Dev Commands
- `./start.sh` — starts backend on `:8000` and frontend on `:5173` (both sides)
- `./start.sh backend` or `./start.sh frontend` — one side only
- `cd backend && uvicorn main:app --port 8000 --reload` — backend direct
- `cd frontend && npm run dev` — frontend dev (proxies `/api` to backend)
- `cd frontend && npm run build` — production frontend bundle (outputs to `frontend/dist/`)
- `cd backend && pytest` — backend tests

## Deployment
- Build: `npm run build` in `frontend/` → `cp -r frontend/dist backend/static`
- Deploy: `git push origin main` triggers GitHub Actions → Azure App Service
- Health check: `curl https://fslapp-nyaaa.azurewebsites.net/api/health`
- Never delete `output.tar.zst`; never use VFS for Python

## Critical Domain Rules (from `doc/fslapp/coding_rules.md` — READ BEFORE TOUCHING METRICS OR DISPATCH LOGIC)

1. **Tow Drop-Off Exclusion**: Every SOQL query or Python filter counting SAs MUST exclude Tow Drop-Off (`WorkType.Name != 'Tow Drop-Off'` or `if 'drop' in wt_name.lower(): continue`). Every tow generates paired Pick-Up + Drop-Off SAs; counting both inflates volume ~25%. Does NOT apply to map visualizations.

2. **Towbook vs Fleet**: Towbook garages have NO Fleet drivers (`has_fleet_drivers = False`). Towbook drivers ARE visible via `Off_Platform_Driver__r.Name` on SA and `ERS_PTA__c`. `ActualStartTime` is UNRELIABLE for Towbook (midnight bulk update) — never use for ATA. For Towbook PTA, use live `ERS_PTA__c`, NOT simulation.

3. **Work Type Cycle Times differ**: Tow=115m, Battery=38m, Light=33m, Winch=40m. PTA promises differ by type. When filtering live SAs for projected PTA, FILTER BY CALL TYPE FIRST. If projected values come out identical for all 4 types → bug.

4. **DST-Safe Eastern Time**: Never hardcode UTC-5 or UTC-4. Always use `ZoneInfo('America/New_York')`. SOQL `HOUR_IN_DAY()` returns UTC — convert to Eastern before comparing.

5. **Case-Insensitive Salesforce Comparisons**: Always use `.lower()` when comparing satisfaction, status, reason fields. 'Totally Satisfied' vs 'Totally satisfied' → `.lower() == 'totally satisfied'`.

## Coding Style
- Python `snake_case`; React components `PascalCase.jsx`, hooks `useThing.js`, utils `camelCase.js`
- Match existing Tailwind styling and `lucide-react` icons; prefer local shared components before creating new UI
- Keep every source file under 600 lines

## Gold Rules (override all other instructions)
1. **Never delete without backup + preview + permission.** Before any `DELETE`, `DROP`, `TRUNCATE`, `rm -rf`, or destructive `UPDATE`: create a backup, run a preview (`SELECT` same `WHERE`, `find` before `rm`), show user exactly what will be deleted and row count, wait for explicit approval.
2. **No test data in production stores.**
3. **Verify before declaring success.** Count rows before/after, compare samples, confirm backup is readable.

See `.claude/skills/gold-rules/SKILL.md` for full rules.

## Security
Never commit secrets from `.env`, Azure credentials, Salesforce tokens, or deployment credentials.