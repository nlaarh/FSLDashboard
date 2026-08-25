#!/usr/bin/env python3
"""Daily fslapp-pg backup: pg_dump -> blob storage. Read-only against primary.

Safety properties (see .claude/skills/fslapp-pg-backup/SKILL.md and
backup-role.sql for the full writeup):
  - Connects to Postgres as "fslapp-pg-backup-identity". NOTE: this identity
    is currently registered as a Postgres Microsoft Entra ADMIN (not a
    SELECT-only role -- enabling that requires the pgaadauth extension,
    which needs a primary-server restart that was explicitly declined).
    The "never touches primary data" guarantee is therefore enforced HERE,
    at the application-code level: this script only ever invokes pg_dump
    (a read-only tool) against the primary connection -- it never runs
    pg_restore, DELETE, DROP, or TRUNCATE against fslapp-pg. If a real
    SELECT-only role is adopted later, this comment (and the actual risk
    profile) improves automatically -- no code change needed here.
  - Never restores, never connects to fslapp-pg-dr, never overwrites an
    existing day's backup (upload uses overwrite=False and fails loudly
    on collision instead of overwriting -- verified in production).
  - The only delete this script performs is pruning backup blobs older
    than RETENTION_DAYS in the postgres-backups container -- it holds no
    database credentials capable of deleting anything in Postgres.
"""
import datetime
import os
import subprocess
import sys

from azure.core.exceptions import ResourceExistsError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings

PG_HOST = os.environ["FSLAPP_PG_HOST"]  # fslapp-pg.postgres.database.azure.com
PG_DATABASE = os.environ.get("FSLAPP_PG_DATABASE", "fslapp")
PG_BACKUP_ROLE = os.environ.get("FSLAPP_PG_BACKUP_ROLE", "fslapp-pg-backup-identity")
STORAGE_ACCOUNT = os.environ["BACKUP_STORAGE_ACCOUNT"]  # fslappopt
BACKUP_CONTAINER = os.environ.get("BACKUP_CONTAINER", "postgres-backups")
RETENTION_DAYS = int(os.environ.get("BACKUP_RETENTION_DAYS", "30"))
CLIENT_ID = os.environ.get("AZURE_CLIENT_ID")  # user-assigned managed identity


def get_pg_token(credential: DefaultAzureCredential) -> str:
    return credential.get_token("https://ossrdbms-aad.database.windows.net/.default").token


def run_pg_dump(token: str, dump_path: str) -> None:
    env = dict(os.environ)
    env["PGPASSWORD"] = token
    cmd = [
        "pg_dump",
        f"host={PG_HOST} dbname={PG_DATABASE} user={PG_BACKUP_ROLE} sslmode=require",
        "-Fc",  # custom format: compressed, supports selective/parallel restore
        "-f", dump_path,
    ]
    subprocess.run(cmd, env=env, check=True)


def upload_backup(blob_service: BlobServiceClient, dump_path: str, blob_name: str) -> None:
    container = blob_service.get_container_client(BACKUP_CONTAINER)
    with open(dump_path, "rb") as f:
        try:
            container.upload_blob(
                name=blob_name,
                data=f,
                overwrite=False,  # -> If-None-Match: * under the hood; never overwrite a day's backup
                content_settings=ContentSettings(content_type="application/octet-stream"),
            )
        except ResourceExistsError:
            print(f"ERROR: {blob_name} already exists in {BACKUP_CONTAINER} -- refusing to overwrite.",
                  file=sys.stderr)
            raise


def prune_old_backups(blob_service: BlobServiceClient) -> None:
    container = blob_service.get_container_client(BACKUP_CONTAINER)
    cutoff = datetime.date.today() - datetime.timedelta(days=RETENTION_DAYS)
    for blob in container.list_blobs(name_starts_with="fslapp-pg-"):
        try:
            date_str = blob.name.removeprefix("fslapp-pg-").removesuffix(".dump")
            blob_date = datetime.date.fromisoformat(date_str)
        except ValueError:
            continue  # not a dated backup blob; leave it alone
        if blob_date < cutoff:
            print(f"Pruning {blob.name} (older than {RETENTION_DAYS} days)")
            container.delete_blob(blob.name)


def main() -> None:
    today = datetime.date.today().isoformat()
    dump_path = f"/tmp/fslapp-pg-{today}.dump"
    blob_name = f"fslapp-pg-{today}.dump"

    credential = DefaultAzureCredential(managed_identity_client_id=CLIENT_ID)

    print(f"Dumping {PG_DATABASE}@{PG_HOST} as read-only role {PG_BACKUP_ROLE} ...")
    run_pg_dump(get_pg_token(credential), dump_path)

    blob_service = BlobServiceClient(
        account_url=f"https://{STORAGE_ACCOUNT}.blob.core.windows.net",
        credential=credential,
    )
    print(f"Uploading to {BACKUP_CONTAINER}/{blob_name} ...")
    upload_backup(blob_service, dump_path, blob_name)
    os.remove(dump_path)

    print(f"Pruning backups older than {RETENTION_DAYS} days ...")
    prune_old_backups(blob_service)

    print("Backup complete.")


if __name__ == "__main__":
    main()
