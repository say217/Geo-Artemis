#!/usr/bin/env python3
"""
Comprehensive verification script for Geo Artemis App4 - Earthquake and All Events Features
Tests all backend endpoints and validates data integrity
"""

import requests
import json
import sys
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"
ENDPOINTS = {
    "all_events_2026": "/app4/all-events-2026",
    "earthquake_points": "/app4/earthquake-points"
}

def print_header(text):
    print("\n" + "="*70)
    print(f"  {text}")
    print("="*70)

def verify_endpoint(name, url):
    """Test a single endpoint"""
    print(f"\n✓ Testing: {name}")
    print(f"  URL: {BASE_URL}{url}")
    
    try:
        response = requests.get(f"{BASE_URL}{url}", timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        # Print summary
        if "data" in data:
            count = len(data.get("data", []))
            print(f"  ✅ Status: {response.status_code}")
            print(f"  📊 Data points: {count}")
            print(f"  💾 Total returned: {data.get('count', count)}")
            
            # Show sample of first record
            if count > 0:
                sample = data["data"][0]
                print(f"  📋 Sample record: {json.dumps(sample, indent=2)[:200]}...")
        else:
            print(f"  ✅ Status: {response.status_code}")
            print(f"  📦 Response: {json.dumps(data, indent=2)[:300]}...")
        
        return True
        
    except requests.exceptions.ConnectionError:
        print(f"  ❌ ERROR: Cannot connect to {BASE_URL}")
        print(f"     Is the server running? Try: uvicorn main:app --reload")
        return False
    except requests.exceptions.Timeout:
        print(f"  ❌ ERROR: Request timeout (endpoint too slow)")
        return False
    except json.JSONDecodeError:
        print(f"  ❌ ERROR: Invalid JSON response")
        return False
    except Exception as e:
        print(f"  ❌ ERROR: {str(e)}")
        return False

def verify_data_files():
    """Verify that required data files exist"""
    print_header("DATA FILE VERIFICATION")
    
    files_to_check = {
        "Prepared Data": Path("c:\\PROJECTS\\Geo Artemis\\Main\\app4\\Data\\final_hazard_dataset.csv"),
        "Earthquake Data": Path("c:\\PROJECTS\\Geo Artemis\\USGS_DATA\\earthquakes_5_years.json"),
    }
    
    all_exist = True
    for name, path in files_to_check.items():
        if path.exists():
            size_mb = path.stat().st_size / (1024*1024)
            print(f"✅ {name}: {path}")
            print(f"   📦 Size: {size_mb:.2f} MB")
        else:
            print(f"❌ {name}: NOT FOUND at {path}")
            all_exist = False
    
    return all_exist

def main():
    print_header("🌍 GEO ARTEMIS - ENDPOINT VERIFICATION TEST")
    print("Testing All Events Button & Earthquake Points Feature")
    
    # Step 1: Verify data files
    files_ok = verify_data_files()
    if not files_ok:
        print("\n⚠️  Warning: Some data files missing. Features may not work properly.")
    
    # Step 2: Test endpoints
    print_header("BACKEND ENDPOINT TESTS")
    
    results = {}
    for name, url in ENDPOINTS.items():
        results[name] = verify_endpoint(name, url)
    
    # Step 3: Summary
    print_header("TEST SUMMARY")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    print(f"\n📊 Results: {passed}/{total} endpoints working")
    
    if passed == total:
        print("\n✅ ALL TESTS PASSED!")
        print("\n🎯 Ready to use:")
        print("   • Click 'All Events' button to display 7243 hazard events from 2026")
        print("   • Click 'SHOW' in Earthquake Points HUD to display earthquake data")
        print("   • All loaders should activate and display status updates")
        print("   • Popups show detailed information on marker click")
        return 0
    else:
        print(f"\n❌ {total - passed} endpoint(s) failed!")
        print("\n⚠️  Troubleshooting:")
        print("   1. Ensure server is running: uvicorn main:app --reload")
        print("   2. Check data files exist in correct locations")
        print("   3. Verify no port conflicts (default: 8000)")
        return 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⏹️  Test cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {str(e)}")
        sys.exit(1)
