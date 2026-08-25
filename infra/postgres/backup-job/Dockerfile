FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir azure-identity azure-storage-blob

COPY run_backup.py /app/run_backup.py

ENTRYPOINT ["python", "/app/run_backup.py"]
