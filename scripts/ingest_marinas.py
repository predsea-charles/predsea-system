#!/usr/bin/env python
"""
ingest_marinas.py — Monthly Harvester for Western Mediterranean Marinas

Queries the OpenStreetMap Overpass API for harbours and marinas,
extracts VHF, phone, website details, and merges them with our
curated seed dataset to produce the production-ready marinas.json database.
"""

import os
import json
import logging
import requests
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("ingest_marinas")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# Bounding box covering Western Med: South: 35.0, West: -1.0, North: 45.0, East: 15.0
BBOX = "35.0,-1.0,45.0,15.0"

OVERPASS_QUERY = f"""[out:json][timeout:30];
(
  node["harbour"="yes"]({BBOX});
  node["marina"="yes"]({BBOX});
  way["harbour"="yes"]({BBOX});
  way["marina"="yes"]({BBOX});
);
out center;"""


def fetch_osm_marinas() -> list:
    logger.info("Querying Overpass API for harbours and marinas...")
    headers = {
        "User-Agent": "PredSea-Navigation-App/1.0 (contact: support@predsea.com)",
        "Accept": "application/json"
    }
    try:
        # Send raw query in POST body directly
        response = requests.post(OVERPASS_URL, data=OVERPASS_QUERY, headers=headers, timeout=45)
        response.raise_for_status()
        data = response.json()
        elements = data.get("elements", [])
        logger.info("Successfully fetched %d raw elements from OSM.", len(elements))
        return elements
    except Exception as e:
        logger.error("Failed to fetch from Overpass API: %s", e)
        return []


def parse_osm_marina(el: dict) -> dict:
    tags = el.get("tags", {})
    
    # Extract coordinates (ways have 'center', nodes have 'lat'/'lon')
    lat = el.get("lat") or el.get("center", {}).get("lat")
    lon = el.get("lon") or el.get("center", {}).get("lon")
    
    if lat is None or lon is None:
        return {}

    name = tags.get("name") or tags.get("name:en") or f"Unnamed Marina ({el.get('id')})"
    
    # Contact metadata
    phone = tags.get("contact:phone") or tags.get("phone") or tags.get("telephone")
    vhf = tags.get("contact:vhf") or tags.get("vhf") or tags.get("communication:vhf") or tags.get("communication:vhf_channel")
    website = tags.get("contact:website") or tags.get("website")
    
    # Amenities/Constraints fallback estimates based on tags
    fuel = tags.get("fuel") == "yes" or tags.get("amenity") == "fuel" or "fuel" in tags
    max_length = tags.get("max_length") or tags.get("mooring:max_length")
    max_draft = tags.get("max_draft") or tags.get("mooring:max_draft")
    
    try:
        max_length_m = float(max_length) if max_length else 30.0
    except ValueError:
        max_length_m = 30.0
        
    try:
        max_draft_m = float(max_draft) if max_draft else 4.0
    except ValueError:
        max_draft_m = 4.0

    return {
        "port_id": f"osm_{el.get('id')}",
        "name": name,
        "country": tags.get("addr:country") or "Unknown",
        "location": {"latitude": float(lat), "longitude": float(lon)},
        "comms": {
            "vhf_channel": str(vhf) if vhf else "09",
            "phone": str(phone) if phone else None
        },
        "amenities": {
            "max_length_m": max_length_m,
            "max_draft_m": max_draft_m,
            "fuel_available": bool(fuel)
        }
    }


def main():
    base_dir = Path(__file__).resolve().parent.parent
    seed_path = base_dir / "humanintheloop" / "data/places" / "marinas_seed.json"
    output_path = base_dir / "humanintheloop" / "data/places" / "marinas.json"

    # 1. Load curated seed data
    seed_marinas = []
    if seed_path.exists():
        logger.info("Loading seed marinas from %s", seed_path)
        try:
            with open(seed_path, "r", encoding="utf-8") as f:
                seed_marinas = json.load(f)
        except Exception as e:
            logger.error("Failed to load seed marinas: %s", e)
    else:
        logger.warning("Seed marinas file not found at %s", seed_path)

    # Dictionary keyed by location (rounded to 3 decimal places to match close geographical entries)
    merged_marinas = {}
    
    def geo_key(lat, lon):
        return (round(lat, 3), round(lon, 3))

    # Add seed marinas first to guarantee maximum priority / clean metadata
    for m in seed_marinas:
        key = geo_key(m["location"]["latitude"], m["location"]["longitude"])
        merged_marinas[key] = m

    # 2. Fetch and merge OSM marinas
    osm_elements = fetch_osm_marinas()
    new_count = 0
    for el in osm_elements:
        parsed = parse_osm_marina(el)
        if not parsed:
            continue
            
        key = geo_key(parsed["location"]["latitude"], parsed["location"]["longitude"])
        
        # Merge criteria: If near an existing seed port, enrich vhf/phone if missing, but do not overwrite
        if key in merged_marinas:
            existing = merged_marinas[key]
            # Enrich contact details from OSM if seed was missing them
            if not existing.get("comms", {}).get("phone") and parsed.get("comms", {}).get("phone"):
                existing["comms"]["phone"] = parsed["comms"]["phone"]
            if existing.get("comms", {}).get("vhf_channel") == "09" and parsed.get("comms", {}).get("vhf_channel") != "09":
                existing["comms"]["vhf_channel"] = parsed["comms"]["vhf_channel"]
        else:
            merged_marinas[key] = parsed
            new_count += 1

    # 3. Write final unified database
    final_list = list(merged_marinas.values())
    logger.info("Merged registry has %d ports (Added %d new from OSM).", len(final_list), new_count)
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(final_list, f, indent=2, ensure_ascii=False)
        logger.info("Successfully wrote unified marinas registry to %s", output_path)
    except Exception as e:
        logger.error("Failed to write unified marinas to file: %s", e)


if __name__ == "__main__":
    main()
