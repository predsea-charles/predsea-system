#!/usr/bin/env python3
"""
Extract ports, marinas, harbours, ferry terminals and optional anchorages
from OpenStreetMap using the Overpass API.

Output:
    osm_maritime_destinations.json
    osm_maritime_destinations.csv

Example:
    python extract_osm_maritime_destinations.py

Dependencies:
    pip install requests
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
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
]

# Western Mediterranean:
# south, west, north, east
WESTERN_MEDITERRANEAN_BBOX = (
    35.0,
    -6.5,
    45.5,
    16.8,
)

# Small tiles reduce the risk of Overpass timeouts.
TILE_SIZE_DEGREES = 2.0

REQUEST_TIMEOUT_SECONDS = 180
REQUEST_DELAY_SECONDS = 2.0
MAX_RETRIES = 4

INCLUDE_ANCHORAGES = True
INCLUDE_UNNAMED_LOCATIONS = False

OUTPUT_JSON = Path("osm_maritime_destinations.json")
OUTPUT_CSV = Path("osm_maritime_destinations.csv")


@dataclass
class MaritimeDestination:
    place_id: str
    name: str
    category: str
    latitude: float
    longitude: float
    osm_type: str
    osm_id: int
    osm_url: str

    name_local: str | None = None
    name_en: str | None = None

    harbour_category: str | None = None
    operator: str | None = None
    website: str | None = None
    phone: str | None = None
    vhf_channel: str | None = None

    access: str | None = None
    fee: str | None = None
    capacity: str | None = None
    max_draft: str | None = None
    max_length: str | None = None

    source: str = "openstreetmap"
    source_tags: dict[str, str] | None = None


def generate_tiles(
    bbox: tuple[float, float, float, float],
    tile_size: float,
) -> Iterable[tuple[float, float, float, float]]:
    """Split a large bounding box into smaller Overpass query tiles."""

    south, west, north, east = bbox

    latitude = south
    while latitude < north:
        tile_north = min(latitude + tile_size, north)

        longitude = west
        while longitude < east:
            tile_east = min(longitude + tile_size, east)

            yield latitude, longitude, tile_north, tile_east
            longitude = tile_east

        latitude = tile_north


def build_overpass_query(
    bbox: tuple[float, float, float, float],
) -> str:
    """
    Build an Overpass QL query.

    Overpass bbox order:
        south, west, north, east
    """

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
        filters.extend(
            [
                f'nwr["seamark:type"="anchorage"]({bbox_string});',
                f'nwr["seamark:anchorage:category"]({bbox_string});',
            ]
        )

    joined_filters = "\n".join(filters)

    return f"""
[out:json][timeout:150];
(
{joined_filters}
);
out center tags;
"""


def query_overpass(
    query: str,
    tile_number: int,
) -> list[dict[str, Any]]:
    """Call one of the configured Overpass API instances with retries."""

    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        endpoint = OVERPASS_URLS[attempt % len(OVERPASS_URLS)]

        try:
            response = requests.post(
                endpoint,
                data={"data": query},
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers={
                    "User-Agent": (
                        "PredSea-Maritime-Destination-Importer/1.0 "
                        "(contact: info@predsea.com)"
                    )
                },
            )

            if response.status_code in {429, 502, 503, 504}:
                raise RuntimeError(
                    f"Temporary Overpass error: HTTP {response.status_code}"
                )

            response.raise_for_status()
            payload = response.json()

            elements = payload.get("elements", [])

            print(
                f"Tile {tile_number}: received {len(elements)} elements "
                f"from {endpoint}"
            )

            return elements

        except (
            requests.RequestException,
            RuntimeError,
            ValueError,
        ) as exc:
            last_error = exc
            delay = 5 * (attempt + 1)

            print(
                f"Tile {tile_number}: attempt {attempt + 1} failed: "
                f"{exc}. Retrying in {delay} seconds."
            )
            time.sleep(delay)

    raise RuntimeError(
        f"Overpass request failed after {MAX_RETRIES} attempts"
    ) from last_error


def get_coordinates(
    element: dict[str, Any],
) -> tuple[float, float] | None:
    """Get coordinates from a node or from the calculated center of a way/relation."""

    if "lat" in element and "lon" in element:
        return float(element["lat"]), float(element["lon"])

    center = element.get("center")

    if center and "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])

    return None


def get_name(tags: dict[str, str]) -> str | None:
    """Select the best available destination name."""

    name_keys = [
        "name",
        "seamark:name",
        "name:en",
        "official_name",
        "short_name",
        "loc_name",
    ]

    for key in name_keys:
        value = tags.get(key)
        if value and value.strip():
            return value.strip()

    return None


def classify_destination(tags: dict[str, str]) -> str:
    """Assign a single PredSea-friendly destination category."""

    if tags.get("leisure") == "marina":
        return "marina"

    if (
        tags.get("seamark:type") == "anchorage"
        or "seamark:anchorage:category" in tags
    ):
        return "anchorage"

    if tags.get("amenity") == "ferry_terminal":
        return "ferry_terminal"

    if (
        tags.get("industrial") == "port"
        or tags.get("landuse") == "port"
        or tags.get("seaway") == "port"
    ):
        return "commercial_port"

    if (
        tags.get("seamark:type") == "harbour"
        or tags.get("harbour") == "yes"
    ):
        harbour_category = tags.get("seamark:harbour:category", "")

        if "marina" in harbour_category:
            return "marina"

        return "harbour"

    return "maritime_destination"


def slugify(value: str) -> str:
    """Convert a destination name to a stable readable identifier."""

    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_value = ascii_value.lower()
    ascii_value = re.sub(r"[^a-z0-9]+", "_", ascii_value)

    return ascii_value.strip("_")


def make_place_id(
    name: str,
    latitude: float,
    longitude: float,
) -> str:
    """
    Create a stable identifier.

    A coordinate hash avoids collisions when two destinations have the same name.
    """

    coordinate_string = f"{latitude:.5f},{longitude:.5f}"
    short_hash = hashlib.sha1(
        coordinate_string.encode("utf-8")
    ).hexdigest()[:7]

    return f"{slugify(name)}_{short_hash}"


def parse_element(
    element: dict[str, Any],
) -> MaritimeDestination | None:
    """Convert an OSM element into the normalized destination model."""

    tags = element.get("tags", {})
    coordinates = get_coordinates(element)

    if not coordinates:
        return None

    latitude, longitude = coordinates
    name = get_name(tags)

    if not name:
        if not INCLUDE_UNNAMED_LOCATIONS:
            return None

        name = (
            f"Unnamed {classify_destination(tags).replace('_', ' ')} "
            f"{element['type']}/{element['id']}"
        )

    osm_type = str(element["type"])
    osm_id = int(element["id"])

    return MaritimeDestination(
        place_id=make_place_id(name, latitude, longitude),
        name=name,
        name_local=tags.get("name"),
        name_en=tags.get("name:en"),
        category=classify_destination(tags),
        latitude=round(latitude, 7),
        longitude=round(longitude, 7),
        osm_type=osm_type,
        osm_id=osm_id,
        osm_url=f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
        harbour_category=tags.get("seamark:harbour:category"),
        operator=tags.get("operator"),
        website=tags.get("website") or tags.get("contact:website"),
        phone=tags.get("phone") or tags.get("contact:phone"),
        vhf_channel=(
            tags.get("vhf")
            or tags.get("contact:vhf")
            or tags.get("seamark:radio_station:channel")
        ),
        access=tags.get("access"),
        fee=tags.get("fee"),
        capacity=tags.get("capacity"),
        max_draft=(
            tags.get("maxdraft")
            or tags.get("max_draft")
            or tags.get("seamark:harbour:maximum_draught")
        ),
        max_length=tags.get("maxlength") or tags.get("max_length"),
        source_tags=tags,
    )


def haversine_distance_m(
    first: MaritimeDestination,
    second: MaritimeDestination,
) -> float:
    """Calculate distance between two destinations in metres."""

    earth_radius_m = 6_371_000

    lat1 = math.radians(first.latitude)
    lat2 = math.radians(second.latitude)
    delta_lat = math.radians(second.latitude - first.latitude)
    delta_lon = math.radians(second.longitude - first.longitude)

    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    return earth_radius_m * 2 * math.atan2(
        math.sqrt(value),
        math.sqrt(1 - value),
    )


def normalized_name(name: str) -> str:
    """Normalize names for approximate duplicate detection."""

    normalized = unicodedata.normalize("NFKD", name)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower()
    normalized = re.sub(
        r"\b(port|porto|puerto|marina|harbour|harbor|port de|port d)\b",
        " ",
        normalized,
    )
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)

    return " ".join(normalized.split())


def quality_score(destination: MaritimeDestination) -> int:
    """Prefer richer OSM records when several objects represent one place."""

    score = 0

    if destination.name:
        score += 10

    if destination.category == "marina":
        score += 4
    elif destination.category == "harbour":
        score += 3
    elif destination.category == "commercial_port":
        score += 2

    optional_values = [
        destination.website,
        destination.phone,
        destination.operator,
        destination.vhf_channel,
        destination.capacity,
        destination.max_draft,
        destination.max_length,
    ]

    score += sum(bool(value) for value in optional_values)

    # Nodes usually provide the explicit labelled point, but a richer relation
    # or area may still win through the metadata score above.
    if destination.osm_type == "node":
        score += 1

    return score


def merge_destinations(
    primary: MaritimeDestination,
    secondary: MaritimeDestination,
) -> MaritimeDestination:
    """Fill missing values in the preferred record from a duplicate record."""

    merge_fields = [
        "name_local",
        "name_en",
        "harbour_category",
        "operator",
        "website",
        "phone",
        "vhf_channel",
        "access",
        "fee",
        "capacity",
        "max_draft",
        "max_length",
    ]

    for field in merge_fields:
        if not getattr(primary, field) and getattr(secondary, field):
            setattr(primary, field, getattr(secondary, field))

    if primary.source_tags is None:
        primary.source_tags = {}

    if secondary.source_tags:
        for key, value in secondary.source_tags.items():
            primary.source_tags.setdefault(key, value)

    return primary


def deduplicate(
    destinations: list[MaritimeDestination],
    maximum_distance_m: float = 750,
) -> list[MaritimeDestination]:
    """
    Remove duplicate OSM representations.

    A marina can appear as a node, area and seamark harbour. Records with
    similar normalized names and positions within 750 metres are merged.
    """

    # First eliminate exact OSM duplicates caused by overlapping query tiles.
    exact: dict[tuple[str, int], MaritimeDestination] = {}

    for destination in destinations:
        key = destination.osm_type, destination.osm_id
        exact[key] = destination

    candidates = sorted(
        exact.values(),
        key=lambda destination: (
            normalized_name(destination.name),
            destination.latitude,
            destination.longitude,
        ),
    )

    result: list[MaritimeDestination] = []

    for candidate in candidates:
        candidate_name = normalized_name(candidate.name)
        duplicate_index: int | None = None

        for index, existing in enumerate(result):
            if normalized_name(existing.name) != candidate_name:
                continue

            if (
                haversine_distance_m(existing, candidate)
                <= maximum_distance_m
            ):
                duplicate_index = index
                break

        if duplicate_index is None:
            result.append(candidate)
            continue

        existing = result[duplicate_index]

        if quality_score(candidate) > quality_score(existing):
            result[duplicate_index] = merge_destinations(
                candidate,
                existing,
            )
        else:
            result[duplicate_index] = merge_destinations(
                existing,
                candidate,
            )

    return sorted(
        result,
        key=lambda destination: (
            destination.name.casefold(),
            destination.category,
        ),
    )


def export_json(
    destinations: list[MaritimeDestination],
    output_path: Path,
) -> None:
    payload = {
        "source": "OpenStreetMap via Overpass API",
        "bbox": {
            "south": WESTERN_MEDITERRANEAN_BBOX[0],
            "west": WESTERN_MEDITERRANEAN_BBOX[1],
            "north": WESTERN_MEDITERRANEAN_BBOX[2],
            "east": WESTERN_MEDITERRANEAN_BBOX[3],
        },
        "count": len(destinations),
        "places": [asdict(destination) for destination in destinations],
    }

    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def export_csv(
    destinations: list[MaritimeDestination],
    output_path: Path,
) -> None:
    rows = []

    for destination in destinations:
        row = asdict(destination)
        row.pop("source_tags", None)
        rows.append(row)

    if not rows:
        raise RuntimeError("No destinations were returned.")

    with output_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(rows[0].keys()),
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    tiles = list(
        generate_tiles(
            WESTERN_MEDITERRANEAN_BBOX,
            TILE_SIZE_DEGREES,
        )
    )

    print(f"Querying {len(tiles)} geographic tiles...")

    raw_destinations: list[MaritimeDestination] = []

    for tile_number, tile in enumerate(tiles, start=1):
        query = build_overpass_query(tile)
        elements = query_overpass(query, tile_number)

        for element in elements:
            destination = parse_element(element)

            if destination:
                raw_destinations.append(destination)

        if tile_number < len(tiles):
            time.sleep(REQUEST_DELAY_SECONDS)

    destinations = deduplicate(raw_destinations)

    export_json(destinations, OUTPUT_JSON)
    export_csv(destinations, OUTPUT_CSV)

    print()
    print(f"Raw named records: {len(raw_destinations)}")
    print(f"Deduplicated destinations: {len(destinations)}")
    print(f"JSON: {OUTPUT_JSON.resolve()}")
    print(f"CSV:  {OUTPUT_CSV.resolve()}")

    category_counts: dict[str, int] = {}

    for destination in destinations:
        category_counts[destination.category] = (
            category_counts.get(destination.category, 0) + 1
        )

    print("\nDestinations by category:")

    for category, count in sorted(category_counts.items()):
        print(f"  {category}: {count}")


if __name__ == "__main__":
    main()
