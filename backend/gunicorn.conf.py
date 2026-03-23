# Gunicorn configuration file for Azure App Service

import os

# CRITICAL: Azure sets PORT environment variable - must bind to it!
port = os.environ.get('PORT', '8000')
bind = f"0.0.0.0:{port}"

# Worker configuration — auto-scale based on CPU cores
# Each UvicornWorker runs an async event loop + threadpool (40 threads default)
# B1 (1 core): 3 workers = 120 concurrent slots
# P2v2 (2 cores): 5 workers = 200 concurrent slots
# P3v2 (4 cores): 9 workers = 360 concurrent slots
import multiprocessing
workers = min(2 * multiprocessing.cpu_count() + 1, 9)
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
