-- FSLAPP Postgres schema initialization
--
-- Run after `az deployment group create` succeeds. Idempotent — safe to re-run.
--
-- Architecture:
--   Single `fslapp` database hosts ALL FSLAPP features as separate schemas.
--   Phase 1 creates `optimizer.*` (replaces DuckDB). Future phases add core,
--   accounting, ops without touching this file — they own their own migrations.
--
-- Auth model:
--   AAD admin (the user running this) has full DDL rights via azure_pg_admin role.
--   App Service managed identity (`fslapp-nyaaa`) is a regular role granted
--   per-schema USAGE + DML at the bottom of this file.

\echo '── Enabling extensions ──'
CREATE EXTENSION IF NOT EXISTS vector;          -- pgvector for Phase 3 (RAG)
CREATE EXTENSION IF NOT EXISTS pg_trgm;         -- trigram similarity for ILIKE
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS btree_gin;

\echo '── Creating schemas ──'
-- Phase 1 (now): optimizer
CREATE SCHEMA IF NOT EXISTS optimizer;
COMMENT ON SCHEMA optimizer IS 'FSL optimizer feature — replaces DuckDB. Owned by Phase 1 migration.';

-- Reserved for future phases (created empty so future migrations can ALTER cleanly)
CREATE SCHEMA IF NOT EXISTS core;
COMMENT ON SCHEMA core IS 'Shared FSLAPP data: users, sessions, activity log. Migrated from ~/.fslapp/users.json + sqlite.';

CREATE SCHEMA IF NOT EXISTS accounting;
COMMENT ON SCHEMA accounting IS 'Accounting feature data — to be populated when accounting migrates from current local store.';

CREATE SCHEMA IF NOT EXISTS ops;
COMMENT ON SCHEMA ops IS 'Daily ops / dispatch insights — populated when those features migrate from cache layer.';

-- App-wide migration tracking (single table, not per-schema, so we can reason about state)
CREATE TABLE IF NOT EXISTS public.schema_migrations (
  id          SERIAL PRIMARY KEY,
  schema_name TEXT NOT NULL,
  version     TEXT NOT NULL,
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  description TEXT,
  UNIQUE (schema_name, version)
);
COMMENT ON TABLE public.schema_migrations IS 'Single source of truth for which migrations have been applied to which schema. Append-only.';

-- ─── Phase 1: optimizer schema ────────────────────────────────────────────
\echo '── Creating optimizer.* tables ──'

SET search_path = optimizer, public;

CREATE TABLE IF NOT EXISTS opt_runs (
  id                          TEXT PRIMARY KEY,
  name                        TEXT,
  territory_id                TEXT,
  territory_name              TEXT,
  policy_id                   TEXT,
  policy_name                 TEXT,
  run_at                      TIMESTAMPTZ NOT NULL,
  horizon_start               TIMESTAMPTZ,
  horizon_end                 TIMESTAMPTZ,
  resources_count             INT,
  services_count              INT,
  pre_scheduled               INT,
  post_scheduled              INT,
  unscheduled_count           INT,
  pre_travel_time_s           DOUBLE PRECISION,
  post_travel_time_s          DOUBLE PRECISION,
  pre_response_avg_s          DOUBLE PRECISION,
  post_response_avg_s         DOUBLE PRECISION,
  batch_id                    TEXT,
  chunk_num                   INT,
  fsl_type                    TEXT,
  fsl_status                  TEXT,
  objectives_count            INT,
  work_rules_count            INT,
  skills_count                INT,
  daily_optimization          BOOLEAN,
  commit_mode                 TEXT,
  post_response_appt_s        DOUBLE PRECISION,
  post_extraneous_time_s      DOUBLE PRECISION,
  post_start_commute_dist     DOUBLE PRECISION,
  post_end_commute_dist       DOUBLE PRECISION,
  post_resources_unscheduled  INT
);

CREATE INDEX IF NOT EXISTS idx_opt_runs_run_at      ON opt_runs USING BRIN (run_at);
CREATE INDEX IF NOT EXISTS idx_opt_runs_batch       ON opt_runs (batch_id) WHERE batch_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_opt_runs_territory   ON opt_runs (territory_name, run_at DESC);

CREATE TABLE IF NOT EXISTS opt_sa_decisions (
  id                       TEXT PRIMARY KEY,
  run_id                   TEXT NOT NULL,
  sa_id                    TEXT NOT NULL,
  sa_number                TEXT,
  sa_work_type             TEXT,
  action                   TEXT,
  unscheduled_reason       TEXT,
  winner_driver_id         TEXT,
  winner_driver_name       TEXT,
  winner_travel_time_min   DOUBLE PRECISION,
  winner_travel_dist_mi    DOUBLE PRECISION,
  run_at                   TIMESTAMPTZ NOT NULL,
  priority                 DOUBLE PRECISION,
  duration_min             DOUBLE PRECISION,
  sa_status                TEXT,
  sa_lat                   DOUBLE PRECISION,
  sa_lon                   DOUBLE PRECISION,
  earliest_start           TIMESTAMPTZ,
  due_date                 TIMESTAMPTZ,
  sched_start              TIMESTAMPTZ,
  sched_end                TIMESTAMPTZ,
  required_skills          TEXT,
  is_pinned                BOOLEAN,
  seats_required           DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_decisions_run         ON opt_sa_decisions (run_id);
CREATE INDEX IF NOT EXISTS idx_decisions_sa_number   ON opt_sa_decisions (sa_number);
CREATE INDEX IF NOT EXISTS idx_decisions_run_at      ON opt_sa_decisions USING BRIN (run_at);
CREATE INDEX IF NOT EXISTS idx_decisions_action_run  ON opt_sa_decisions (run_id, action);
CREATE INDEX IF NOT EXISTS idx_decisions_winner      ON opt_sa_decisions (winner_driver_id, run_id) WHERE winner_driver_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS opt_driver_verdicts (
  id                TEXT PRIMARY KEY,
  run_id            TEXT NOT NULL,
  sa_id             TEXT NOT NULL,
  driver_id         TEXT NOT NULL,
  driver_name       TEXT,
  status            TEXT NOT NULL,           -- winner | eligible | excluded
  exclusion_reason  TEXT,
  travel_time_min   DOUBLE PRECISION,
  travel_dist_mi    DOUBLE PRECISION,
  driver_skills     TEXT,
  driver_territory  TEXT,
  run_at            TIMESTAMPTZ NOT NULL
);

-- Composite (run_id, sa_id) is the join key for the decision modal — most important index here.
CREATE INDEX IF NOT EXISTS idx_verdicts_run_sa       ON opt_driver_verdicts (run_id, sa_id);
CREATE INDEX IF NOT EXISTS idx_verdicts_run_status   ON opt_driver_verdicts (run_id, status);
CREATE INDEX IF NOT EXISTS idx_verdicts_driver       ON opt_driver_verdicts (driver_id, run_id);
CREATE INDEX IF NOT EXISTS idx_verdicts_run_at_brin  ON opt_driver_verdicts USING BRIN (run_at);
CREATE INDEX IF NOT EXISTS idx_verdicts_excl_reason  ON opt_driver_verdicts (exclusion_reason) WHERE exclusion_reason IS NOT NULL;

CREATE TABLE IF NOT EXISTS opt_resources (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS opt_blob_audit (
  run_id          TEXT PRIMARY KEY,
  blob_prefix     TEXT NOT NULL,
  blob_modified   TIMESTAMPTZ,
  processed_at    TIMESTAMPTZ DEFAULT now(),
  parser_version  TEXT,
  status          TEXT,
  error_message   TEXT
);
CREATE INDEX IF NOT EXISTS idx_blob_audit_status ON opt_blob_audit (status, processed_at DESC);

CREATE TABLE IF NOT EXISTS opt_sync_errors (
  run_id      TEXT,
  run_name    TEXT,
  error       TEXT,
  failed_at   TIMESTAMPTZ DEFAULT now(),
  retried     BOOLEAN DEFAULT FALSE,
  attempts    INT DEFAULT 0,
  run_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_sync_errors_unretried ON opt_sync_errors (retried) WHERE retried = FALSE;

CREATE TABLE IF NOT EXISTS opt_sync_cursor (
  cursor_name  TEXT PRIMARY KEY,
  cursor_value TEXT,
  updated_at   TIMESTAMPTZ DEFAULT now()
);

-- ─── Reserved for Phase 3 (pgvector RAG) — empty until then ──────────────
\echo '── Reserving optimizer.opt_narratives for Phase 3 ──'
CREATE TABLE IF NOT EXISTS opt_narratives (
  id           TEXT PRIMARY KEY,            -- run_id || ':' || sa_id
  run_id       TEXT NOT NULL,
  sa_id        TEXT NOT NULL,
  sa_number    TEXT,
  territory    TEXT,
  run_at       TIMESTAMPTZ NOT NULL,
  narrative    TEXT NOT NULL,
  embedding    vector(1536),                -- text-embedding-3-small
  created_at   TIMESTAMPTZ DEFAULT now()
);
-- HNSW index added in Phase 3 only when populated (empty index is wasted maintenance).

-- ─── Grant App Service managed identity DML on optimizer schema ─────────
\echo '── Granting role permissions to fslapp-nyaaa managed identity ──'
-- The role name MUST match the App Service name (Azure pattern for AAD service principals).
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fslapp-nyaaa') THEN
    GRANT USAGE ON SCHEMA optimizer  TO "fslapp-nyaaa";
    GRANT USAGE ON SCHEMA core       TO "fslapp-nyaaa";
    GRANT USAGE ON SCHEMA accounting TO "fslapp-nyaaa";
    GRANT USAGE ON SCHEMA ops        TO "fslapp-nyaaa";
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA optimizer TO "fslapp-nyaaa";
    ALTER DEFAULT PRIVILEGES IN SCHEMA optimizer  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "fslapp-nyaaa";
    ALTER DEFAULT PRIVILEGES IN SCHEMA core       GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "fslapp-nyaaa";
    ALTER DEFAULT PRIVILEGES IN SCHEMA accounting GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "fslapp-nyaaa";
    ALTER DEFAULT PRIVILEGES IN SCHEMA ops        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "fslapp-nyaaa";
    RAISE NOTICE 'Granted DML on optimizer.* + USAGE on all schemas to fslapp-nyaaa';
  ELSE
    RAISE NOTICE 'Role fslapp-nyaaa does not exist yet. Run after `az postgres flexible-server ad-admin create -i <managed-identity-id> -t ServicePrincipal -u fslapp-nyaaa`.';
  END IF;
END $$;

-- ─── Mark this migration applied ─────────────────────────────────────────
INSERT INTO public.schema_migrations (schema_name, version, description)
VALUES
  ('optimizer',  '001-init', 'Initial Phase-1 schema — optimizer tables migrated from DuckDB'),
  ('core',       '000-empty', 'Schema reserved, no tables yet'),
  ('accounting', '000-empty', 'Schema reserved, no tables yet'),
  ('ops',        '000-empty', 'Schema reserved, no tables yet')
ON CONFLICT DO NOTHING;

\echo '── Done ──'
\echo 'Schemas:'
SELECT schema_name FROM information_schema.schemata WHERE schema_name IN ('optimizer','core','accounting','ops','public') ORDER BY 1;
\echo
\echo 'Optimizer tables:'
SELECT tablename FROM pg_tables WHERE schemaname = 'optimizer' ORDER BY 1;
