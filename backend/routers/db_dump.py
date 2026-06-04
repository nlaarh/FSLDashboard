"""SQL dump & restore endpoints for the admin System Health panel.

GET  /api/admin/system/health/db/dump   — stream a SQL data dump (PIN required)
POST /api/admin/system/health/db/restore — restore from uploaded SQL (PIN + RESTORE)

Dump strategy:
  1. Try pg_dump binary (available locally, not on Azure App Service).
  2. Fall back to a pure-Python INSERT-based export (always works on Azure).

Restore strategy:
  1. Try psql binary.
  2. Fall back to executing statements via psycopg in a single transaction.

Both endpoints use the shared Entra token for DB auth (no stored passwords).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from routers.admin import _check_pin

router = APIRouter()

_VALID_SCHEMAS = {"core", "optimizer", "sales", "core+optimizer", "all"}
_SCHEMA_MAP: dict[str, list[str]] = {
    "core":           ["core"],
    "optimizer":      ["optimizer"],
    "sales":          ["sales"],
    "core+optimizer": ["core", "optimizer"],
    "all":            ["core", "optimizer", "sales"],
}


def _config_value(key: str) -> str:
    value = os.environ.get(key)
    if value:
        return value
    from dotenv import dotenv_values
    from pathlib import Path
    for path in [
        Path(__file__).resolve().parents[2] / ".env",
        Path(__file__).resolve().parents[1] / ".env",
    ]:
        if path.exists():
            v = dotenv_values(path).get(key)
            if v:
                return str(v)
    return ""


def _entra_token() -> str:
    from azure.identity import DefaultAzureCredential
    return DefaultAzureCredential().get_token(
        "https://ossrdbms-aad.database.windows.net/.default"
    ).token


def _sql_val(v: object) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''").replace("\\", "\\\\") + "'"


def _python_dump(schemas: list[str]) -> bytes:
    """Generate INSERT-based SQL dump using psycopg — no pg_dump binary needed."""
    import pg_pool

    lines: list[str] = [
        "-- FSLAPP SQL Data Dump\n",
        f"-- Generated: {datetime.now(timezone.utc).isoformat()}\n",
        f"-- Schemas: {', '.join(schemas)}\n",
        f"-- Host: {pg_pool.PG_HOST}  DB: {pg_pool.PG_DATABASE}\n",
        "-- Format: INSERT-based data dump (DDL not included)\n",
        "-- Restore: psql -h HOST -U USER -d fslapp -f this_file.sql\n\n",
        "BEGIN;\n\n",
    ]

    with pg_pool.reader() as conn:
        for schema in schemas:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename",
                    (schema,),
                )
                tables = [r[0] for r in cur.fetchall()]

            lines.append(f"-- ═══ Schema: {schema} ═══\n")
            lines.append(f"SET search_path = {schema}, public;\n\n")

            for table in tables:
                try:
                    with conn.cursor() as cur:
                        cur.execute(f'SELECT * FROM "{schema}"."{table}"')
                        cols = [d[0] for d in cur.description]
                        rows = cur.fetchall()
                    col_list = ", ".join(f'"{c}"' for c in cols)
                    lines.append(f"-- Table: {schema}.{table}  ({len(rows)} rows)\n")
                    lines.append(f'DELETE FROM "{schema}"."{table}";\n')
                    for row in rows:
                        vals = ", ".join(_sql_val(v) for v in row)
                        lines.append(
                            f'INSERT INTO "{schema}"."{table}" ({col_list}) VALUES ({vals});\n'
                        )
                    lines.append("\n")
                except Exception as exc:
                    lines.append(f"-- WARNING: skipped {schema}.{table}: {exc}\n\n")

    lines.append("COMMIT;\n")
    return "".join(lines).encode("utf-8")


@router.get("/api/admin/system/health/db/dump")
def db_dump(request: Request, schema: str = "core+optimizer"):
    """Stream a SQL data dump for the requested schema(s). PIN required."""
    _check_pin(request)
    if schema not in _VALID_SCHEMAS:
        raise HTTPException(400, f"schema must be one of: {', '.join(sorted(_VALID_SCHEMAS))}")

    schemas = _SCHEMA_MAP[schema]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"fslapp_dump_{schema.replace('+', '_')}_{stamp}.sql"

    pg_dump_bin = shutil.which("pg_dump")
    if pg_dump_bin:
        import pg_pool
        try:
            token = _entra_token()
            env = {**os.environ, "PGPASSWORD": token}
            args = [
                pg_dump_bin,
                f"--host={pg_pool.PG_HOST}",
                f"--username={pg_pool.PG_USER}",
                f"--dbname={pg_pool.PG_DATABASE}",
                "--no-password", "--format=plain", "--encoding=UTF8",
            ]
            for s in schemas:
                args += ["--schema", s]

            def _stream_pgdump():
                with subprocess.Popen(
                    args, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
                ) as proc:
                    while chunk := proc.stdout.read(65536):
                        yield chunk

            return StreamingResponse(
                _stream_pgdump(),
                media_type="application/octet-stream",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except Exception:
            pass  # fall through to Python dump

    sql_bytes = _python_dump(schemas)

    return StreamingResponse(
        iter([sql_bytes]),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/admin/system/health/db/restore")
async def db_restore(
    request: Request,
    confirm: str = Form(...),
    pin_confirm: str = Form(...),
    sql_file: UploadFile = File(...),
):
    """Restore database from an uploaded SQL dump. Requires PIN header + form PIN + 'RESTORE'."""
    _check_pin(request)

    if confirm != "RESTORE":
        raise HTTPException(400, "Confirmation text must be exactly: RESTORE")

    admin_pin = _config_value("ADMIN_PIN")
    if not admin_pin or pin_confirm.strip() != admin_pin.strip():
        raise HTTPException(403, "PIN confirmation failed — re-enter the admin PIN")

    sql_bytes = await sql_file.read()
    if not sql_bytes:
        raise HTTPException(400, "Uploaded file is empty")
    if len(sql_bytes) > 500 * 1024 * 1024:
        raise HTTPException(413, "File too large — max 500 MB")

    psql_bin = shutil.which("psql")
    if psql_bin:
        import pg_pool
        try:
            token = _entra_token()
            env = {**os.environ, "PGPASSWORD": token}
            result = subprocess.run(
                [
                    psql_bin,
                    f"--host={pg_pool.PG_HOST}",
                    f"--username={pg_pool.PG_USER}",
                    f"--dbname={pg_pool.PG_DATABASE}",
                    "--no-password", "--set=ON_ERROR_STOP=on",
                ],
                input=sql_bytes, env=env,
                capture_output=True, timeout=300,
            )
            if result.returncode != 0:
                err = result.stderr.decode(errors="replace")[:600]
                raise HTTPException(500, f"psql restore failed: {err}")
            return {
                "ok": True, "method": "psql",
                "size_bytes": len(sql_bytes),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "Restore timed out (>5 min)")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"psql error: {exc}")

    # Python fallback via psycopg
    import pg_pool

    sql_text = sql_bytes.decode("utf-8", errors="replace")
    statements: list[str] = []
    for raw in sql_text.split(";"):
        stmt = "\n".join(
            ln for ln in raw.splitlines()
            if ln.strip() and not ln.strip().startswith("--")
        ).strip()
        if stmt and stmt.upper() not in {"BEGIN", "COMMIT"}:
            statements.append(stmt)

    executed = 0
    try:
        with pg_pool.writer() as conn:
            with conn.transaction():
                for stmt in statements:
                    conn.execute(stmt)
                    executed += 1
    except Exception as exc:
        raise HTTPException(500, f"Restore failed after {executed} statements: {exc}")

    return {
        "ok": True, "method": "psycopg",
        "statements_executed": executed,
        "size_bytes": len(sql_bytes),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
