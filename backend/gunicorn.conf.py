# Gunicorn configuration file for Azure App Service

import os

# CRITICAL: Azure sets PORT environment variable - must bind to it!
port = os.environ.get('PORT', '8000')
bind = f"0.0.0.0:{port}"

# Worker configuration
workers = 2
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 600  # Azure default

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "debug"

# Working directory
chdir = "/home/site/wwwroot"

# Preload app to catch import errors early
preload_app = True

# Detailed error logging
capture_output = True
enable_stdio_inheritance = True

print(f"=== Gunicorn Config: Binding to {bind} ===")
print(f"PORT env var: {os.environ.get('PORT', 'NOT SET')}")
