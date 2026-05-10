# Gunicorn configuration file for Azure App Service

import os

# CRITICAL: Azure sets PORT environment variable - must bind to it!
port = os.environ.get('PORT', '8000')
bind = f"0.0.0.0:{port}"

# Worker configuration — capped to stay within Azure Postgres connection limit.
# Each worker owns its own pg_pool (reader_max=10, writer_max=4).
# Formula: (10 + 4) × 5 workers = 70 connections + background threads ≈ 75 total.
# Azure Postgres Flexible Server limit is 96 — this leaves a 20-connection safety buffer.
import multiprocessing
workers = min(2 * multiprocessing.cpu_count() + 1, 5)
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 120

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Working directory
chdir = "/home/site/wwwroot"

# Preload app to catch import errors early
preload_app = True

# Detailed error logging
capture_output = True
enable_stdio_inheritance = True

print(f"=== Gunicorn Config: Binding to {bind} ===")
print(f"PORT env var: {os.environ.get('PORT', 'NOT SET')}")
