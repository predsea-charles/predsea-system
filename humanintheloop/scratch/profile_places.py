import time
import json
from pathlib import Path
import sys

# Add humanintheloop to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from api.app import create_app, place_observation_sources
from api.evidence_store import EvidenceStore
import place_registry

def profile_places_endpoint():
    print("--- Profiling /places Endpoint Logic ---")
    
    start_total = time.time()
    
    # 1. Startup / Registry Loading
    t0 = time.time()
    place_ids = place_registry.available_place_ids()
    t1 = time.time()
    print(f"available_place_ids() count: {len(place_ids)}")
    print(f"available_place_ids() took: {t1 - t0:.4f}s")
    
    # 2. Loop iteration & Data loading
    store = EvidenceStore()
    summaries = []
    
    load_definitions_time = 0
    observation_sources_time = 0
    build_summary_time = 0
    
    # Limit to 100 for a sample if it's too slow, but let's try all to see the full impact
    # Actually, let's do 100 first to estimate
    sample_size = min(len(place_ids), 3050)
    print(f"Processing {sample_size} places...")
    
    for i, place_id in enumerate(place_ids[:sample_size]):
        t_loop_start = time.time()
        
        td0 = time.time()
        place = place_registry.place_definition(place_id)
        load_definitions_time += time.time() - td0
        
        to0 = time.time()
        # This is the suspected bottleneck
        obs_sources = place_observation_sources(store, place_id)
        observation_sources_time += time.time() - to0
        
        ts0 = time.time()
        summaries.append(
            {
                "place_id": place_id,
                "place_name": place["name"],
                "type": place.get("type") or place.get("kind"),
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "parent_place_id": place.get("parent_place_id"),
                "children": list(place.get("children") or ()),
                "aliases": list(place.get("aliases") or ()),
                "observation_candidates": list(place.get("observation_candidates") or ()),
                "observation_sources": obs_sources,
            }
        )
        build_summary_time += time.time() - ts0
        
        if (i + 1) % 500 == 0:
            print(f"  Processed {i+1} places...")

    t_loop_end = time.time()
    print(f"\nLoop for {sample_size} places took: {t_loop_end - t1:.4f}s")
    print(f"  - place_definition: {load_definitions_time:.4f}s")
    print(f"  - place_observation_sources: {observation_sources_time:.4f}s")
    print(f"  - dict building: {build_summary_time:.4f}s")
    
    # 3. Serialization
    print("\n--- Serialization ---")
    t2 = time.time()
    json_data = json.dumps({"places": summaries})
    t3 = time.time()
    print(f"json.dumps() took: {t3 - t2:.4f}s")
    print(f"Total JSON size: {len(json_data) / 1024 / 1024:.2f} MB")
    
    total_time = time.time() - start_total
    print(f"\nTotal profiling time: {total_time:.4f}s")

if __name__ == "__main__":
    profile_places_endpoint()
