import json
import sys
from pathlib import Path

# Add workspace to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import map_generator

def main():
    scratch_dir = Path(__file__).resolve().parent / "2026-07-07"
    
    # Paths to local files
    waves_path = scratch_dir / "waves_latest.nc"
    currents_path = scratch_dir / "currents_latest.nc"
    snapshot_path = scratch_dir / "marseille_palma" / "daily_snapshot.json"
    evidence_path = scratch_dir / "marseille_palma" / "evidence.json"
    
    with open(snapshot_path, "r") as f:
        snapshot = json.load(f)
        
    with open(evidence_path, "r") as f:
        evidence = json.load(f)
        
    route = evidence["subject"]
    
    # Target time or peak time
    target_time = snapshot.get("forecast", {}).get("wave_peak_time")
    print(f"Target peak wave time: {target_time}")
    
    output_path = scratch_dir / "marseille_palma" / "route_decision_map_test.png"
    
    print("Generating route decision map...")
    map_generator.generate_route_decision_map(
        waves_path=str(waves_path),
        currents_path=str(currents_path),
        route=route,
        snapshot=snapshot,
        output_path=str(output_path),
        target_time=target_time
    )
    print(f"Done! Saved map to {output_path}")

if __name__ == "__main__":
    main()
