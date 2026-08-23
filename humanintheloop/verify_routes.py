#!/usr/bin/env python3
import json
from pathlib import Path
import math

def haversine_nm(lat1, lon1, lat2, lon2):
    radius_nm = 3440.065
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * radius_nm * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

def main():
    routes_path = Path("humanintheloop/routes.json")
    if not routes_path.exists():
        print("routes.json not found")
        return

    with open(routes_path, "r") as f:
        routes = json.load(f)

    print(f"Verifying {len(routes)} routes...")
    
    issues = []
    for rid, r in routes.items():
        o = r.get("origin", {})
        d = r.get("destination", {})
        
        if not all(k in o for k in ["latitude", "longitude"]) or not all(k in d for k in ["latitude", "longitude"]):
            print(f"Skipping {rid}: missing coordinates")
            continue
            
        dist = haversine_nm(o["latitude"], o["longitude"], d["latitude"], d["longitude"])
        
        # Check if the route has any strange data
        if dist > 1000:
            issues.append(f"Route {rid} is very long: {dist:.1f} nm")
            
    if not issues:
        print("No obvious issues found in route distances.")
    else:
        for issue in issues:
            print(f"ISSUE: {issue}")

if __name__ == "__main__":
    main()
