#!/usr/bin/env python3
"""Deploy to Azure App Service using Azure SDK"""
import os
import subprocess
import sys

def main():
    app_name = "fslapp-nyaaa"
    resource_group = "rg-nlaaroubi-sbx-eus2-001"
    
    print("=" * 60)
    print("Azure App Service Deployment")
    print("=" * 60)
    print(f"App: {app_name}")
    print(f"Resource Group: {resource_group}")
    print()
    
    # Method: Use az webapp deploy with restart
    print("[1/3] Deploying application...")
    deploy_cmd = [
        'az', 'webapp', 'deploy',
        '--name', app_name,
        '--resource-group', resource_group,
        '--src-path', 'deploy.zip',
        '--type', 'zip',
        '--restart', 'true',
        '--timeout', '600'
    ]
    
    try:
        result = subprocess.run(deploy_cmd, capture_output=True, text=True, timeout=600)
        if result.returncode == 0:
            print("✓ Deployment package uploaded")
        else:
            print(f"✗ Deployment failed: {result.stderr[:500]}")
            return 1
    except subprocess.TimeoutExpired:
        print("⚠ Deployment command timed out, but deployment may still be processing...")
        print("  Checking app status in 30 seconds...")
    except Exception as e:
        print(f"Error: {e}")
        return 1
    
    # Check app status
    print("\n[2/3] Waiting for app to start...")
    import time
    time.sleep(30)
    
    print("\n[3/3] Checking app health...")
    health_cmd = ['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}', 
                  f'https://{app_name}.azurewebsites.net/']
    try:
        result = subprocess.run(health_cmd, capture_output=True, text=True, timeout=15)
        status = result.stdout.strip()
        print(f"HTTP Status: {status}")
        
        if status == '200':
            print("\n✓ Deployment successful!")
            print(f"\n🌐 App URL: https://{app_name}.azurewebsites.net/")
            return 0
        else:
            print(f"\n⚠ App responded with status {status}")
            print("Check logs: az webapp log tail --name {app_name} --resource-group {resource_group}")
            return 1
    except Exception as e:
        print(f"Error checking health: {e}")
        return 1

if __name__ == '__main__':
    sys.exit(main())
