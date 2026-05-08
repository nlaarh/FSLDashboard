# Repository Guidelines

## Project Structure & Module Organization
This repository contains a FastAPI backend and a Vite/React frontend for the FSLAPP dashboard. Backend code lives in `backend/`, with API routers in `backend/routers/`, shared helpers such as `utils.py`, `cache.py`, and database modules at the backend root, and backend tests in `backend/tests/`. Frontend source is in `frontend/src/`, organized by `pages/`, `components/`, `hooks/`, `utils/`, and `contexts/`; public assets live in `frontend/public/`. Deployment and PostgreSQL infrastructure live under `infra/postgres/`. Technical references and design notes are in `doc/` and `docs/superpowers/`.

## Build, Test, and Development Commands
- `./start.sh`: starts backend on `localhost:8000` and frontend on `localhost:5173`.
- `./start.sh backend` or `./start.sh frontend`: run one side only.
- `cd backend && uvicorn main:app --port 8000 --reload`: run the API directly.
- `cd frontend && npm run dev`: run Vite with `/api` proxied to the backend.
- `cd frontend && npm run build`: create the production frontend bundle.
- `cd backend && pytest`: run backend unit and router smoke tests.

## Coding Style & Naming Conventions
Use Python `snake_case` for backend functions, variables, and modules. Keep FastAPI endpoints grouped by domain in `backend/routers/`. Use React component files in `PascalCase.jsx`, hooks as `useThing.js`, and utilities in `camelCase.js`. Match existing Tailwind styling, `lucide-react` icons, and local shared components before creating new UI. Keep every source file under 600 lines; split by feature before adding more code.

## Testing Guidelines
Backend tests use `pytest` and FastAPI `TestClient`; name files `test_*.py` and place them in `backend/tests/`. Add focused tests for shared helpers, router registration, and endpoint behavior. For UI changes, run `npm run build` and verify the rendered page in the browser against the local API.

## Commit & Pull Request Guidelines
Recent history uses concise imperative commits, often Conventional Commit prefixes such as `fix:`, `feat:`, `perf(scope):`, and `refactor(scope):`. Keep PRs focused, describe user-visible impact, list verification steps, and include screenshots for frontend changes. Do not push or deploy without explicit approval.

## Security & Configuration Tips
Do not commit secrets from `.env`, Azure credentials, Salesforce tokens, or generated deployment credentials. Review `doc/fslapp/coding_rules.md` before changing metrics or dispatch logic, especially Tow Drop-Off exclusions, Towbook/Fleet handling, work-type-specific calculations, DST-safe Eastern time, and case-insensitive Salesforce comparisons.
