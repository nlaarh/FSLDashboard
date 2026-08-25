-- OPTIONAL upgrade path: a true SELECT-only (non-admin) AAD role for the
-- backup identity, instead of the AAD-admin registration currently used.
--
-- CURRENT STATE (as actually deployed): the backup identity
-- ("fslapp-pg-backup-identity") was registered as a Postgres Microsoft
-- Entra ADMIN via:
--   az postgres flexible-server microsoft-entra-admin create \
--     -g rg-nlaaroubi-sbx-eus2-001 -s fslapp-pg \
--     -i <principalId> -u fslapp-pg-backup-identity -t ServicePrincipal
-- This was chosen because creating a real SELECT-only role requires the
-- `pgaadauth` extension, which is not in fslapp-pg's azure.extensions
-- allowlist (infra/postgres/main.bicep) and enabling it requires a brief
-- primary-server restart -- which was explicitly declined. As a result,
-- the "never touches primary data" guarantee is enforced at the
-- application-code level (run_backup.py only ever calls pg_dump, a
-- read-only tool), NOT at the database-privilege level. See
-- .claude/skills/fslapp-pg-backup/SKILL.md for the full writeup.
--
-- If tighter, privilege-level isolation is wanted later (accepting one
-- brief restart of fslapp-pg):
--   1. Add PGAADAUTH to the azure.extensions parameter in main.bicep and
--      redeploy (this restarts fslapp-pg).
--   2. Run this script once, as the AAD admin, to create the read-only role:
--        PGPASSWORD=$(az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv) \
--        psql "host=fslapp-pg.postgres.database.azure.com dbname=fslapp user=<admin-upn> sslmode=require" \
--          -v ON_ERROR_STOP=1 -f backup-role.sql
--   3. Remove the microsoft-entra-admin registration for
--      fslapp-pg-backup-identity (it becomes redundant/overly broad once
--      this role exists) and set FSLAPP_PG_BACKUP_ROLE to this role name
--      (already the default) in backup-job.bicep.
--
-- This role, once created, can SELECT everything and nothing else: no
-- INSERT/UPDATE/DELETE/DROP/TRUNCATE grant on any object.

SELECT * FROM pgaadauth_create_principal('fslapp-pg-backup-identity', false, false);

-- Grant read-only access to the fslapp database, across every schema
-- (public, accounting, core, ops, optimizer, sales).
GRANT CONNECT ON DATABASE fslapp TO "fslapp-pg-backup-identity";

GRANT USAGE ON SCHEMA public, accounting, core, ops, optimizer, sales TO "fslapp-pg-backup-identity";
GRANT SELECT ON ALL TABLES IN SCHEMA public, accounting, core, ops, optimizer, sales TO "fslapp-pg-backup-identity";

-- Ensure future tables are covered automatically without re-running this script.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO "fslapp-pg-backup-identity";
ALTER DEFAULT PRIVILEGES IN SCHEMA accounting GRANT SELECT ON TABLES TO "fslapp-pg-backup-identity";
ALTER DEFAULT PRIVILEGES IN SCHEMA core GRANT SELECT ON TABLES TO "fslapp-pg-backup-identity";
ALTER DEFAULT PRIVILEGES IN SCHEMA ops GRANT SELECT ON TABLES TO "fslapp-pg-backup-identity";
ALTER DEFAULT PRIVILEGES IN SCHEMA optimizer GRANT SELECT ON TABLES TO "fslapp-pg-backup-identity";
ALTER DEFAULT PRIVILEGES IN SCHEMA sales GRANT SELECT ON TABLES TO "fslapp-pg-backup-identity";
