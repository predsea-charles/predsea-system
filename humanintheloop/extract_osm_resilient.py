#!/usr/bin/env python3
"""
Hybrid Resilient OSM Extractor.
Features:
- Uses larger tiles (2.0 degrees) by default for speed.
- Automatically splits a tile into four smaller tiles (1.0 degree) if it fails/timeouts.
- Progress saving and resume capability.
- Multiple Overpass servers.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import requests


OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
]

# Western Mediterranean:
# south, west, north, east
WESTERN_MEDITERRANEAN_BBOX = (
    35.0,
    -6.5,
    45.5,
    16.8,
)

DEFAULT_TILE_SIZE = 1.0

REQUEST_TIMEOUT_SECONDS = 180
REQUEST_DELAY_SECONDS = 2.0
MAX_RETRIES = 3

INCLUDE_ANCHORAGES = True
INCLUDE_UNNAMED_LOCATIONS = False

OUTPUT_JSON = Path("osm_maritime_destinations.json")
OUTPUT_CSV = Path("osm_maritime_destinations.csv")
PROGRESS_FILE = Path("extraction_progress.json")


def build_overpass_query(bbox: tuple[float, float, float, float]) -> str:
    south, west, north, east = bbox
    bbox_string = f"{south},{west},{north},{east}"
    filters = [
        f'nwr["leisure"="marina"]({bbox_string});',
        f'nwr["harbour"="yes"]({bbox_string});',
        f'nwr["seamark:type"="harbour"]({bbox_string});',
        f'nwr["industrial"="port"]({bbox_string});',
        f'nwr["landuse"="port"]({bbox_string});',
        f'nwr["seaway"="port"]({bbox_string});',
        f'nwr["amenity"="ferry_terminal"]({bbox_string});',
    ]
    if INCLUDE_ANCHORAGES:
        filters.extend([
            f'nwr["seamark:type"="anchorage"]({bbox_string});',
            f'nwr["seamark:anchorage:category"]({bbox_string});',
        ])
    joined_filters = "\n".join(filters)
    return f"[out:json][timeout:180];\n(\n{joined_filters}\n);\nout center tags;"


def query_overpass(query: str, label: str) -> list[dict[str, Any]]:
    last_error = None
    for attempt in range(len(OVERPASS_URLS) * 2):
        endpoint = OVERPASS_URLS[attempt % len(OVERPASS_URLS)]
        try:
            print(f"Querying {label} via {endpoint} (Attempt {attempt + 1})...")
            response = requests.post(
                endpoint, data={"data": query}, timeout=REQUEST_TIMEOUT_SECONDS,
                headers={"User-Agent": "PredSea-Importer/1.0 (info@predsea.com)"}
            )
            if response.status_code in {429, 502, 503, 504}:
                raise RuntimeError(f"HTTP {response.status_code}")
            response.raise_for_status()
            return response.json().get("elements", [])
        except Exception as e:
            last_error = e
            delay = 5 * (attempt + 1)
            print(f"Error {label}: {e}. Retrying in {delay}s...")
            time.sleep(delay)
    raise RuntimeError(f"Failed {label} after all retries: {last_error}")


def generate_tiles(bbox: tuple[float, float, float, float], size: float) -> list[tuple[float, float, float, float]]:
    south, west, north, east = bbox
    tiles = []
    lat = south
    while lat < north:
        t_north = min(lat + size, north)
        lon = west
        while lon < east:
            t_east = min(lon + size, east)
            tiles.append((lat, lon, t_north, t_east))
            lon = t_east
        lat = t_north
    return tiles


def process_tile(tile: tuple[float, float, float, float], label: str, depth: int = 0) -> list[dict[str, Any]]:
    query = build_overpass_query(tile)
    try:
        elements = query_overpass(query, label)
        return elements
    except Exception as e:
        if depth < 1:  # Only split once
            print(f"Tile {label} failed. Splitting into smaller tiles...")
            sub_tiles = generate_tiles(tile, 1.0)
            all_elements = []
            for j, sub_tile in enumerate(sub_tiles):
                all_elements.extend(process_tile(sub_tile, f"{label}.{j+1}", depth + 1))
            return all_elements
        else:
            print(f"Sub-tile {label} failed persistently. Skipping.")
            return []


def get_coordinates(element: dict[str, Any]) -> tuple[float, float] | None:
    if "lat" in element and "lon" in element: return float(element["lat"]), float(element["lon"])
    c = element.get("center")
    if c: return float(c["lat"]), float(c["lon"])
    return None

def get_name(tags: dict[str, str]) -> str | None:
    for k in ["name", "seamark:name", "name:en", "official_name"]:
        v = tags.get(k)
        if v and v.strip(): return v.strip()
    return None

def classify(tags: dict[str, str]) -> str:
    if tags.get("leisure") == "marina": return "marina"
    if "anchorage" in tags.get("seamark:type", ""): return "anchorage"
    if tags.get("amenity") == "ferry_terminal": return "ferry_terminal"
    return "maritime_destination"

def slugify(v: str) -> str:
    n = unicodedata.normalize("NFKD", v).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "_", n).strip("_")

def main():
    tiles = generate_tiles(WESTERN_MEDITERRANEAN_BBOX, DEFAULT_TILE_SIZE)
    print(f"Processing {len(tiles)} main tiles...")
    
    all_elements = []
    start_index = 0
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, "r") as f:
            p = json.load(f)
            all_elements = p.get("elements", [])
            start_index = p.get("next_tile_index", 0)
            print(f"Resuming from tile {start_index + 1} (already have {len(all_elements)} elements)")

    for i in range(start_index, len(tiles)):
        els = process_tile(tiles[i], f"Tile {i+1}/{len(tiles)}")
        all_elements.extend(els)
        with open(PROGRESS_FILE, "w") as f:
            json.dump({"next_tile_index": i + 1, "elements": all_elements}, f)
        time.sleep(REQUEST_DELAY_SECONDS)

    # Dedup and parse
    seen = set()
    places = []
    for el in all_elements:
        key = (el["type"], el["id"])
        if key in seen: continue
        seen.add(key)
        tags = el.get("tags", {})
        coords = get_coordinates(el)
        name = get_name(tags)
        if coords and name:
            lat, lon = coords
            places.append({
                "place_id": f"{slugify(name)}_{hashlib.sha1(f'{lat:.5f},{lon:.5f}'.encode()).hexdigest()[:7]}",
                "name": name,
                "category": classify(tags),
                "latitude": round(lat, 7),
                "longitude": round(lon, 7),
                "osm_url": f"https://www.openstreetmap.org/{el['type']}/{el['id']}",
                "source": "openstreetmap"
            })

    with open(OUTPUT_JSON, "w") as f:
        json.dump({"count": len(places), "places": places}, f, indent=2)
    
    if places:
        with open(OUTPUT_CSV, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(places[0].keys()))
            writer.writeheader()
            writer.writerows(places)

    print(f"Done! {len(places)} destinations saved.")
    if PROGRESS_FILE.exists(): PROGRESS_FILE.unlink()

if __name__ == "__main__":
    main()
