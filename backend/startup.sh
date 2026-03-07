#!/bin/bash
# Azure App Service startup script
set -e

cd /home/site/wwwroot

# Add pre-installed packages to Python path
export PYTHONPATH="/home/site/wwwroot/.python_packages/lib/site-packages:${PYTHONPATH:-}"

# Azure sets PORT env var (typically 8000 or 8181)
PORT="${PORT:-8000}"

echo "=== FSL App Startup ==="
echo "Working dir: $(pwd)"
echo "PORT: $PORT"
echo "PYTHONPATH: $PYTHONPATH"
echo "Python: $(python3 --version)"
echo "Files: $(ls *.py 2>/dev/null | tr '\n' ' ')"

# Quick import test
python3 -c "
import sys
sys.path.insert(0, '/home/site/wwwroot/.python_packages/lib/site-packages')
sys.path.insert(0, '/home/site/wwwroot')
print('Testing imports...')
import fastapi; print(f'  fastapi {fastapi.__version__}')
import uvicorn; print(f'  uvicorn OK')
import gunicorn; print(f'  gunicorn OK')
import requests; print(f'  requests OK')
import main; print(f'  main.py OK - app={main.app}')
print('All imports passed.')
" 2>&1

echo "Starting gunicorn on port $PORT..."
exec gunicorn main:app \
    --workers 2 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind "0.0.0.0:$PORT" \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
