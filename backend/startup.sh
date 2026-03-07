#!/bin/bash
# Azure App Service startup script - with import testing

set -e
cd /home/site/wwwroot

echo "=== FSL App Startup ==="
echo "Working directory: $(pwd)"
echo "Python: $(which python)"

# Test imports
echo "Testing Python imports..."
python << 'PYEOF'
import sys
sys.path.insert(0, '/home/site/wwwroot')
try:
    print("Importing main...")
    import main
    print("✓ main.py imported successfully")
    print(f"✓ FastAPI app: {main.app}")
except Exception as e:
    print(f"✗ Import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
PYEOF

if [ $? -eq 0 ]; then
    echo "✓ Starting gunicorn..."
    exec gunicorn main:app \
        --config gunicorn.conf.py
else
    echo "✗ Import test failed"
    exit 1
fi
