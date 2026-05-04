"""Optimizer store dispatcher — DuckDB by default, Postgres when OPT_DB_BACKEND=postgres.

This is the SINGLE import point for any code that touches the optimizer DB.
Caller code stays the same — `import optimizer_db` then call functions.

Routing logic:
- `OPT_DB_BACKEND=duckdb` (default): import everything from `optimizer_db_duck`
- `OPT_DB_BACKEND=postgres`:           import everything from `optimizer_db_pg`

Both modules expose the same public API. See either for docs on individual
functions. Switch backend by setting the env var; no code changes needed.

Public API (must be in sync between both backends):
    init_db, get_conn, _rows, list_runs, get_run_detail, get_sa_decision,
    get_driver_analysis, get_unscheduled_analysis, get_exclusion_patterns,
    query_optimizer_sql, upsert_resource_names, get_resource_name,
    purge_old_runs
"""

import os
import logging

log = logging.getLogger('optimizer_db')

_BACKEND = os.environ.get('OPT_DB_BACKEND', 'duckdb').lower()

if _BACKEND == 'postgres':
    log.info("optimizer_db: routing to Postgres backend (optimizer_db_pg)")
    from optimizer_db_pg import (    # noqa: F401  re-export
        init_db,
        get_conn,
        _rows,
        list_runs,
        get_run_detail,
        get_sa_decision,
        get_driver_analysis,
        get_unscheduled_analysis,
        get_exclusion_patterns,
        query_optimizer_sql,
        upsert_resource_names,
        get_resource_name,
        purge_old_runs,
        upsert_run,
        bulk_upsert_decisions,
        bulk_upsert_verdicts,
    )
elif _BACKEND == 'duckdb':
    log.info("optimizer_db: routing to DuckDB backend (optimizer_db_duck)")
    from optimizer_db_duck import (  # noqa: F401  re-export
        init_db,
        get_conn,
        _rows,
        list_runs,
        get_run_detail,
        get_sa_decision,
        get_driver_analysis,
        get_unscheduled_analysis,
        get_exclusion_patterns,
        query_optimizer_sql,
        upsert_resource_names,
        get_resource_name,
        purge_old_runs,
        upsert_run,
        bulk_upsert_decisions,
        bulk_upsert_verdicts,
        DB_PATH,        # DuckDB-specific: file path used by the ETL script
    )
else:
    raise RuntimeError(
        f"Unknown OPT_DB_BACKEND={_BACKEND!r}. Expected 'duckdb' or 'postgres'."
    )
