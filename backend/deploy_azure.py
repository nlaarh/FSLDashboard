#!/usr/bin/env python3
"""
Azure deployment script using ARM REST API (bypasses Azure CLI timeouts)
"""
import subprocess
import requests
import time
import sys
import json

# Configuration
APP_NAME = "fslapp-nyaaa"
RG_NAME = "rg-nlaaroubi-sbx-eus2-001"
SUB_ID = "e287db16-b6ae-415e-bd52-41c8ec5a8f08"

BASE_URL = f"https://management.azure.com/subscriptions/{SUB_ID}/resourceGroups/{RG_NAME}/providers/Microsoft.Web/sites/{APP_NAME}"

def get_token():
    """Get Azure access token"""
    result = subprocess.run(
        ['az', 'account', 'get-access-token', '--query', 'accessToken', '-o', 'tsv'],
        capture_output=True, text=True, timeout=10
    )
    return result.stdout.strip()

def deploy_zip(token, zip_path):
    """Deploy via OneDeploy extension"""
    url = f"{BASE_URL}/extensions/onedeploy?type=zip&api-version=2022-03-01"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/octet-stream'
    }

    print(f"📦 Deploying {zip_path}...")
    with open(zip_path, 'rb') as f:
        r = requests.put(url, data=f, headers=headers, timeout=300)

    if r.status_code in (200, 202):
        print("✓ Deployment accepted")
        return True
    else:
        print(f"✗ Deployment failed: HTTP {r.status_code}")
        print(r.text[:500])
        return False

def set_config(token, startup_command):
    """Set app configuration"""
    url = f"{BASE_URL}/config/web?api-version=2022-03-01"
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

    config = {
        "properties": {
            "appCommandLine": startup_command
        }
    }

    print(f"⚙️ Setting startup command...")
    r = requests.put(url, json=config, headers=headers, timeout=120)

    if r.status_code == 200:
        print("✓ Config updated")
        return True
    else:
        print(f"✗ Config failed: HTTP {r.status_code}")
        return False

def restart_app(token):
    """Restart app"""
    url = f"{BASE_URL}/restart?api-version=2022-03-01"
    headers = {'Authorization': f'Bearer {token}'}

    print("🔄 Restarting app...")
    r = requests.post(url, headers=headers, timeout=60)

    if r.status_code == 200:
        print("✓ App restarted")
        return True
    else:
        print(f"✗ Restart failed: HTTP {r.status_code}")
        return False

def test_app():
    """Test if app responds"""
    url = f"https://{APP_NAME}.azurewebsites.net/api/health"

    print("\n🧪 Testing app...")
    print("Waiting 60 seconds for warmup...")
    time.sleep(60)

    for i in range(1, 6):
        print(f"\nTest {i}/5...")
        try:
            r = requests.get(url, timeout=15)
            print(f"HTTP {r.status_code}")

            if r.status_code == 200:
                print(f"✓ SUCCESS! App is working!")
                print(f"Response: {r.json()}")
                return True
            else:
                print(f"Response: {r.text[:200]}")
        except requests.exceptions.Timeout:
            print("✗ Timeout")
        except Exception as e:
            print(f"✗ Error: {str(e)[:100]}")

        if i < 5:
            time.sleep(10)

    print("\n✗ App is not responding after 5 attempts")
    return False

def main():
    print("=== Azure Deployment via ARM REST API ===\n")

    # Get token
    print("1️⃣ Getting Azure token...")
    try:
        token = get_token()
        if not token:
            print("✗ Failed to get token")
            sys.exit(1)
        print("✓ Token obtained")
    except Exception as e:
        print(f"✗ Token error: {e}")
        sys.exit(1)

    # Deploy
    print("\n2️⃣ Deploying app...")
    if not deploy_zip(token, 'deploy.zip'):
        print("✗ Deployment failed")
        sys.exit(1)

    print("\nWaiting 90 seconds for build...")
    time.sleep(90)

    # Set config
    print("\n3️⃣ Configuring startup...")
    startup_cmd = "gunicorn app:app -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --access-logfile - --error-logfile -"
    if not set_config(token, startup_cmd):
        print("⚠️ Config failed but continuing...")

    # Restart
    print("\n4️⃣ Restarting...")
    restart_app(token)

    # Test
    print("\n5️⃣ Testing...")
    if test_app():
        print("\n🎉 DEPLOYMENT SUCCESSFUL!")
        sys.exit(0)
    else:
        print("\n❌ DEPLOYMENT FAILED - App not responding")
        print("\nCheck logs: az webapp log tail --name fslapp-nyaaa --resource-group rg-nlaaroubi-sbx-eus2-001")
        sys.exit(1)

if __name__ == '__main__':
    main()
