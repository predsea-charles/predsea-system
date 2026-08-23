from __future__ import annotations

from datetime import datetime, timezone
from math import atan2, cos, radians, sin, sqrt
import json
from pathlib import Path
import logging


DEFAULT_TRAVEL_SPEED_KN = 15.0
GRAPH_FALLBACK_SPEED_KN = 15.0

logger = logging.getLogger(__name__)

PLACE_SEED_PATH = Path(__file__).with_name("places_seed_balearics.json")
PLACE_ALIASES_PATH = Path(__file__).with_name("aliases_balearics.json")
OSM_PLACES_PATH = Path(__file__).with_name("osm_maritime_destinations.json")


def _normalize_query_text(text):
    normalized = str(text or "").strip().lower().replace("_", " ").replace("-", " ")
    return " ".join(normalized.split())


def _load_json_file(path):
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def _normalize_catalog_record(place_id, record):
    kind = record.get("kind") or record.get("type") or "place"
    return {
        "name": record["name"],
        "latitude": float(record["latitude"]),
        "longitude": float(record["longitude"]),
        "kind": kind,
        "type": record.get("type", kind),
        "parent_place_id": record.get("parent_place_id"),
        "children": tuple(record.get("children") or ()),
        "aliases": tuple(record.get("aliases") or ()),
        "observation_candidates": tuple(record.get("observation_candidates") or ()),
    }


def _load_place_catalog_from_file():
    catalog = {}
    
    # 1. Load primary seeds
    raw_catalog = _load_json_file(PLACE_SEED_PATH)
    if raw_catalog:
        if isinstance(raw_catalog, dict):
            raw_records = []
            for place_id, record in raw_catalog.items():
                normalized_record = dict(record)
                normalized_record.setdefault("id", place_id)
                raw_records.append(normalized_record)
        else:
            raw_records = list(raw_catalog)
            
        for record in raw_records:
            place_id = record.get("id")
            if not place_id:
                continue
            catalog[place_id] = _normalize_catalog_record(place_id, record)
            
    # 2. Load OSM destinations
    osm_data = _load_json_file(OSM_PLACES_PATH)
    if osm_data and isinstance(osm_data, dict):
        osm_places = osm_data.get("places") or []
        for p in osm_places:
            pid = p.get("place_id")
            if pid and pid not in catalog:
                catalog[pid] = {
                    "name": p["name"],
                    "latitude": float(p["latitude"]),
                    "longitude": float(p["longitude"]),
                    "kind": p.get("category") or "maritime_destination",
                    "type": p.get("category") or "maritime_destination",
                    "parent_place_id": None,
                    "children": (),
                    "aliases": (),
                    "observation_candidates": (),
                    "source": "openstreetmap"
                }
                
    return catalog if catalog else None


def _load_place_aliases_from_file(catalog):
    raw_aliases = _load_json_file(PLACE_ALIASES_PATH)
    if raw_aliases:
        aliases = {
            _normalize_query_text(alias): place_id
            for alias, place_id in raw_aliases.items()
            if _normalize_query_text(alias)
        }
        return aliases

    aliases = {}
    for place_id, place in catalog.items():
        aliases[_normalize_query_text(place_id)] = place_id
        aliases[_normalize_query_text(place["name"])] = place_id
        for alias in place.get("aliases") or ():
            aliases[_normalize_query_text(alias)] = place_id
    return aliases


def _build_name_index(catalog):
    return {_normalize_query_text(place["name"]): place_id for place_id, place in catalog.items()}


def _resolve_catalog():
    loaded = _load_place_catalog_from_file()
    if loaded is not None:
        return loaded
    return PLACE_CATALOG


def _resolve_aliases(catalog):
    loaded = _load_place_aliases_from_file(catalog)
    if loaded:
        return loaded
    return DEFAULT_PLACE_BY_QUERY


def _haversine_nm(lat1, lon1, lat2, lon2):
    radius_nm = 3440.065
    phi1 = radians(lat1)
    phi2 = radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2.0) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2.0) ** 2
    return 2.0 * radius_nm * atan2(sqrt(a), sqrt(1.0 - a))


def _normalize_route_waypoints(route, simplify=True):
    def iter_points(node):
        if node is None:
            return
        if isinstance(node, dict):
            latitude = node.get("lat")
            if latitude is None:
                latitude = node.get("latitude")
            longitude = node.get("lng")
            if longitude is None:
                longitude = node.get("lon")
            if longitude is None:
                longitude = node.get("longitude")
            if latitude is not None and longitude is not None:
                yield {"lat": float(latitude), "lng": float(longitude)}
            return
        if isinstance(node, (list, tuple)):
            if len(node) >= 2 and all(isinstance(value, (int, float)) for value in node[:2]):
                yield {"lat": float(node[1]), "lng": float(node[0])}
                return
            for child in node:
                yield from iter_points(child)

    candidates = []
    if isinstance(route, dict):
        geometry = route.get("geometry")
        if isinstance(geometry, dict):
            candidates.append(geometry.get("coordinates"))
        candidates.append(route.get("coordinates"))
        candidates.append(route.get("path"))
        candidates.append(route.get("waypoints"))
    else:
        geometry = getattr(route, "geometry", None)
        if geometry is not None:
            candidates.append(getattr(geometry, "coordinates", None))
        candidates.append(getattr(route, "coordinates", None))
        candidates.append(getattr(route, "path", None))
        candidates.append(getattr(route, "waypoints", None))

    waypoints = []
    for candidate in candidates:
        if candidate is None:
            continue
        waypoints.extend(list(iter_points(candidate)))
        if waypoints:
            break

    # Apply Douglas-Peucker simplification to smooth out intermediate open-ocean grid jogs
    if simplify and len(waypoints) > 2:
        waypoints = _simplify_waypoints(waypoints, epsilon=0.015)

    return waypoints


def _simplify_waypoints(points: list[dict], epsilon: float = 0.015) -> list[dict]:
    """
    Simplifies a 2D line of lat/lng points using the Douglas-Peucker algorithm.
    epsilon: Tolerance in degrees (default 0.015 degrees is approx. 0.9 nautical miles).
    """
    if len(points) < 3:
        return points

    import math

    def perpendicular_distance(p, p1, p2):
        x, y = p["lng"], p["lat"]
        x1, y1 = p1["lng"], p1["lat"]
        x2, y2 = p2["lng"], p2["lat"]
        
        dx = x2 - x1
        dy = y2 - y1
        if dx == 0.0 and dy == 0.0:
            return math.sqrt((x - x1)**2 + (y - y1)**2)
            
        numerator = abs(dy * x - dx * y + x2 * y1 - y2 * x1)
        denominator = math.sqrt(dx**2 + dy**2)
        return numerator / denominator

    dmax = 0.0
    index = 0
    end = len(points) - 1

    for i in range(1, end):
        d = perpendicular_distance(points[i], points[0], points[end])
        if d > dmax:
            index = i
            dmax = d

    if dmax > epsilon:
        results1 = _simplify_waypoints(points[:index+1], epsilon)
        results2 = _simplify_waypoints(points[index:], epsilon)
        return results1[:-1] + results2
    else:
        return [points[0], points[end]]


def _searoute_metrics(
    origin_longitude,
    origin_latitude,
    destination_longitude,
    destination_latitude,
    *,
    speed_kn,
    simplify=True,
):
    try:
        import searoute as sr
    except Exception as error:  # pragma: no cover - dependency/runtime failure
        raise ValueError("Sea route geometry requires the searoute package") from error

    route = sr.searoute(
        [float(origin_longitude), float(origin_latitude)],
        [float(destination_longitude), float(destination_latitude)],
        units="naut",
        speed_knot=float(speed_kn or DEFAULT_TRAVEL_SPEED_KN),
    )
    properties = route.get("properties") if isinstance(route, dict) else getattr(route, "properties", None)
    if not isinstance(properties, dict):
        properties = properties or {}
    waypoints = _normalize_route_waypoints(route, simplify=simplify)
    length_nm = properties.get("length")
    duration_hours = properties.get("duration_hours")
    if length_nm is None and duration_hours is None:
        raise ValueError("Sea route geometry returned no usable route")
    if not waypoints:
        raise ValueError("Sea route geometry returned no waypoints")
    speed_kn = float(speed_kn or DEFAULT_TRAVEL_SPEED_KN)
    if length_nm is None and duration_hours is not None:
        length_nm = float(duration_hours) * speed_kn
    if duration_hours is None and length_nm is not None:
        duration_hours = float(length_nm) / speed_kn
    return {
        "distance_nm": float(length_nm),
        "estimated_time_h": float(duration_hours),
        "waypoints": waypoints,
        "source_tag": "graph_sea_route_v1",
    }


PLACE_CATALOG = {
    "ibiza": {
        "name": "Ibiza",
        "latitude": 38.92,
        "longitude": 1.49,
        "kind": "main_place",
        "parent_place_id": None,
        "children": (),
        "aliases": ("ibiza", "ibiza island"),
        "observation_candidates": ("canal_de_ibiza", "puertos_ibiza", "ibiza"),
    },
    "palma": {
        "name": "Palma",
        "latitude": 39.52,
        "longitude": 2.58,
        "kind": "main_port",
        "parent_place_id": None,
        "children": ("port_de_palma", "port_adriano", "can_pastilla"),
        "aliases": ("palma", "palma de mallorca"),
        "observation_candidates": ("bahia_de_palma", "puertos_mallorca", "mallorca", "palma"),
    },
    "port_de_palma": {
        "name": "Port de Palma",
        "latitude": 39.55,
        "longitude": 2.63,
        "kind": "sub_port",
        "parent_place_id": "palma",
        "children": (),
        "aliases": ("port de palma", "port of palma"),
        "observation_candidates": ("bahia_de_palma", "puertos_mallorca", "mallorca", "palma"),
    },
    "port_adriano": {
        "name": "Port Adriano",
        "latitude": 39.50,
        "longitude": 2.48,
        "kind": "sub_port",
        "parent_place_id": "palma",
        "children": (),
        "aliases": ("port adriano",),
        "observation_candidates": ("bahia_de_palma", "puertos_mallorca", "mallorca", "palma"),
    },
    "can_pastilla": {
        "name": "Can Pastilla",
        "latitude": 39.53,
        "longitude": 2.71,
        "kind": "sub_port",
        "parent_place_id": "palma",
        "children": (),
        "aliases": ("can pastilla", "can pastilla palma"),
        "observation_candidates": ("bahia_de_palma", "puertos_mallorca", "mallorca", "palma"),
    },
    "formentera": {
        "name": "Formentera",
        "latitude": 38.68,
        "longitude": 1.49,
        "kind": "main_place",
        "parent_place_id": None,
        "children": (),
        "aliases": ("formentera",),
        "observation_candidates": ("formentera", "puertos_formentera", "canal_de_ibiza"),
    },
    "menorca": {
        "name": "Menorca",
        "latitude": 40.02,
        "longitude": 4.12,
        "kind": "main_place",
        "parent_place_id": None,
        "children": ("ciutadella",),
        "aliases": ("menorca",),
        "observation_candidates": ("mahon", "puertos_mahon"),
    },
    "cabrera": {
        "name": "Cabrera",
        "latitude": 39.14,
        "longitude": 2.92,
        "kind": "main_place",
        "parent_place_id": None,
        "children": (),
        "aliases": ("cabrera",),
        "observation_candidates": ("canal_de_ibiza", "puertos_mallorca", "mallorca"),
    },
    "ciutadella": {
        "name": "Ciutadella",
        "latitude": 40.02,
        "longitude": 3.82,
        "kind": "main_port",
        "parent_place_id": "menorca",
        "children": (),
        "aliases": ("ciutadella", "ciutadella de menorca"),
        "observation_candidates": ("mahon", "puertos_mahon", "menorca"),
    },
    "alcudia": {
        "name": "Alcudia",
        "latitude": 39.84,
        "longitude": 3.14,
        "kind": "main_port",
        "parent_place_id": "palma",
        "children": (),
        "aliases": ("alcudia", "alcudia de mallorca"),
        "observation_candidates": ("alcudia", "puertos_alcudia", "mallorca", "puertos_mallorca"),
    },
    "soller": {
        "name": "Soller",
        "latitude": 39.81,
        "longitude": 2.74,
        "kind": "main_port",
        "parent_place_id": "palma",
        "children": (),
        "aliases": ("soller", "port de soller"),
        "observation_candidates": ("bahia_de_palma", "puertos_mallorca", "mallorca", "palma"),
    },
    "barcelona": {
        "name": "Barcelona",
        "latitude": 41.32,
        "longitude": 2.22,
        "kind": "main_place",
        "parent_place_id": None,
        "children": (),
        "aliases": ("barcelona",),
        "observation_candidates": ("barcelona", "puertos_barcelona"),
    },
    "valencia": {
        "name": "Valencia",
        "latitude": 39.38,
        "longitude": -0.28,
        "kind": "main_place",
        "parent_place_id": None,
        "children": (),
        "aliases": ("valencia",),
        "observation_candidates": ("valencia", "puertos_valencia"),
    },
    "portocolom": {
        "name": "Portocolom",
        "latitude": 39.41,
        "longitude": 3.27,
        "kind": "main_port",
        "parent_place_id": "palma",
        "children": (),
        "aliases": ("portocolom", "porto colom", "port de portocolom"),
        "observation_candidates": ("porto_colom", "puertos_mallorca", "mallorca", "puertos_alcudia", "alcudia"),
    },
}


DEFAULT_PLACE_BY_QUERY = {
    "palma": "palma",
    "palma de mallorca": "palma",
    "port de palma": "port_de_palma",
    "port of palma": "port_de_palma",
    "port adriano": "port_adriano",
    "can pastilla": "can_pastilla",
    "ibiza": "ibiza",
    "ibiza island": "ibiza",
    "formentera": "formentera",
    "menorca": "menorca",
    "cabrera": "cabrera",
    "ciutadella": "ciutadella",
    "ciutadella de menorca": "ciutadella",
    "alcudia": "alcudia",
    "alcudia de mallorca": "alcudia",
    "soller": "soller",
    "port de soller": "soller",
    "barcelona": "barcelona",
    "valencia": "valencia",
    "portocolom": "portocolom",
    "porto colom": "portocolom",
    "port de portocolom": "portocolom",
}


PLACE_CATALOG = _resolve_catalog()
DEFAULT_PLACE_BY_QUERY = _resolve_aliases(PLACE_CATALOG)
PLACE_NAME_INDEX = _build_name_index(PLACE_CATALOG)

PAIR_METRICS = {}
STATIC_METRICS_COMPUTED_AT_UTC = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
FIXED_DISTANCE_TABLE = {
    ("palma", "ibiza"): 100.0,
    ("ibiza", "palma"): 100.0,
    ("ibiza", "formentera"): 15.0,
    ("formentera", "ibiza"): 15.0,
    ("palma", "portocolom"): 35.0,
    ("portocolom", "palma"): 35.0,
    ("palma", "alcudia"): 26.0,
    ("alcudia", "palma"): 26.0,
    ("alcudia", "ciutadella"): 30.0,
    ("ciutadella", "alcudia"): 30.0,
    ("palma", "port_de_palma"): 3.0,
    ("port_de_palma", "palma"): 3.0,
    ("palma", "port_adriano"): 15.0,
    ("port_adriano", "palma"): 15.0,
    ("palma", "can_pastilla"): 6.0,
    ("can_pastilla", "palma"): 6.0,
    ("palma", "soller"): 18.0,
    ("soller", "palma"): 18.0,
}


class PlaceDistanceResolver:
    def __init__(
        self,
    ):
        self._graph_metrics_cache = {}

    def resolve(self, origin_place_id: str, destination_place_id: str) -> dict:
        key = (origin_place_id, destination_place_id)
        fixed = FIXED_DISTANCE_TABLE.get(key)
        if fixed is not None:
            return self._fixed_metrics(origin_place_id, destination_place_id, fixed)
        if key not in self._graph_metrics_cache:
            self._graph_metrics_cache[key] = self._graph_metrics(origin_place_id, destination_place_id)
        return dict(self._graph_metrics_cache[key])

    def _fixed_metrics(self, origin_place_id: str, destination_place_id: str, distance_nm: float) -> dict:
        origin = place_definition(origin_place_id)
        destination = place_definition(destination_place_id)
        typical_travel_time_minutes = int(round((float(distance_nm) / DEFAULT_TRAVEL_SPEED_KN) * 60.0))
        return {
            "origin_place_id": origin_place_id,
            "origin_place_name": origin["name"],
            "destination_place_id": destination_place_id,
            "destination_place_name": destination["name"],
            "distance_nm": float(distance_nm),
            "typical_speed_kn": DEFAULT_TRAVEL_SPEED_KN,
            "typical_travel_time_minutes": typical_travel_time_minutes,
            "computed_at_utc": STATIC_METRICS_COMPUTED_AT_UTC,
            "source_tag": "place_distance_table_v1",
        }

    def _graph_metrics(self, origin_place_id: str, destination_place_id: str) -> dict:
        origin = place_definition(origin_place_id)
        destination = place_definition(destination_place_id)
        try:
            import searoute as sr
        except Exception as error:  # pragma: no cover - dependency/runtime failure
            raise ValueError("Graph fallback requires the searoute package") from error

        route = sr.searoute(
            [float(origin["longitude"]), float(origin["latitude"])],
            [float(destination["longitude"]), float(destination["latitude"])],
            units="naut",
            speed_knot=GRAPH_FALLBACK_SPEED_KN,
        )
        properties = route.get("properties") or {}
        length_nm = properties.get("length")
        duration_hours = properties.get("duration_hours")
        if length_nm is None and duration_hours is None:
            raise ValueError(
                f"Graph fallback returned no usable route for '{origin_place_id}' -> '{destination_place_id}'"
            )
        if length_nm is None and duration_hours is not None:
            length_nm = float(duration_hours) * GRAPH_FALLBACK_SPEED_KN
        if duration_hours is None and length_nm is not None:
            duration_hours = float(length_nm) / GRAPH_FALLBACK_SPEED_KN
        return {
            "origin_place_id": origin_place_id,
            "origin_place_name": origin["name"],
            "destination_place_id": destination_place_id,
            "destination_place_name": destination["name"],
            "distance_nm": float(length_nm),
            "typical_speed_kn": GRAPH_FALLBACK_SPEED_KN,
            "typical_travel_time_minutes": int(round(float(duration_hours) * 60.0)),
            "computed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "source_tag": "graph_sea_route_v1",
        }


PLACE_DISTANCE_RESOLVER = PlaceDistanceResolver()

def available_place_ids():
    return sorted(PLACE_CATALOG)


def _catalog_place_id_for_query(query):
    """Resolve a catalog ID without building a place response.

    Keeping this lookup independent from ``place_definition`` prevents the
    public resolver and catalog accessor from recursively calling each other.
    """
    normalized = _normalize_query_text(query)
    if not normalized:
        return None
    return (
        DEFAULT_PLACE_BY_QUERY.get(normalized)
        or PLACE_NAME_INDEX.get(normalized)
        or (normalized if normalized in PLACE_CATALOG else None)
    )


def place_definition(place_id, latitude=None, longitude=None):
    if place_id == "current_position":
        lat = float(latitude) if latitude is not None else 0.0
        lon = float(longitude) if longitude is not None else 0.0
        return {
            "id": "current_position",
            "name": f"Coordinate ({lat}, {lon})",
            "latitude": lat,
            "longitude": lon,
            "kind": "coordinate",
            "observation_candidates": (),
        }
    canonical_place_id = _catalog_place_id_for_query(place_id) or place_id
    try:
        return PLACE_CATALOG[canonical_place_id]
    except KeyError as error:
        available = ", ".join(available_place_ids())
        raise ValueError(f"Unknown place '{place_id}'. Available places: {available}") from error


def resolve_place_query(query):
    normalized = _normalize_query_text(query)
    if not normalized:
        return {
            "query": query,
            "matched": False,
            "place_id": None,
            "place_name": None,
            "type": None,
            "latitude": None,
            "longitude": None,
            "confidence": "low",
            "resolved_via": None,
        }

    place_id = _catalog_place_id_for_query(query)
    resolved_via = None
    if place_id is None and normalized in PLACE_CATALOG:
        place_id = normalized
        resolved_via = "canonical_id"
    elif place_id is not None:
        resolved_via = "alias" if normalized != _normalize_query_text(place_id) else "name"

    if place_id is None:
        return {
            "query": query,
            "matched": False,
            "place_id": None,
            "place_name": None,
            "type": None,
            "latitude": None,
            "longitude": None,
            "confidence": "low",
            "resolved_via": None,
        }

    place = PLACE_CATALOG[place_id]
    return {
        "query": query,
        "matched": True,
        "place_id": place_id,
        "place_name": place["name"],
        "type": place.get("kind") or place.get("type"),
        "latitude": float(place["latitude"]),
        "longitude": float(place["longitude"]),
        "confidence": "high",
        "resolved_via": resolved_via or "alias",
    }



def default_place_id_for_query(query):
    return resolve_place_query(query)["place_id"] if query is not None else None


def station_candidates_for_place(place_id, latitude=None, longitude=None):
    if place_id == "current_position":
        return ()
    try:
        place = place_definition(place_id, latitude=latitude, longitude=longitude)
        return tuple(place.get("observation_candidates") or ())
    except Exception:
        return ()


def place_pair_metrics(origin_place_id, destination_place_id):
    key = (origin_place_id, destination_place_id)
    if key not in PAIR_METRICS:
        PAIR_METRICS[key] = PLACE_DISTANCE_RESOLVER.resolve(origin_place_id, destination_place_id)
    return dict(PAIR_METRICS[key])


def coordinates_connection_metrics(
    *,
    origin_place_id,
    origin_place_name,
    origin_latitude,
    origin_longitude,
    destination_place_id,
    destination_place_name,
    destination_latitude,
    destination_longitude,
    typical_speed_kn=DEFAULT_TRAVEL_SPEED_KN,
):
    metrics = _searoute_metrics(
        origin_longitude,
        origin_latitude,
        destination_longitude,
        destination_latitude,
        speed_kn=typical_speed_kn,
    )
    typical_speed_kn = float(typical_speed_kn or DEFAULT_TRAVEL_SPEED_KN)
    return {
        "origin_place_id": origin_place_id,
        "origin_place_name": origin_place_name,
        "destination_place_id": destination_place_id,
        "destination_place_name": destination_place_name,
        "distance_nm": float(metrics["distance_nm"]),
        "typical_speed_kn": typical_speed_kn,
        "typical_travel_time_minutes": int(round(float(metrics["estimated_time_h"]) * 60.0)),
        "computed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "source_tag": metrics["source_tag"],
    }


def coordinates_route_geometry_metrics(
    *,
    origin_place_id,
    origin_place_name,
    origin_latitude,
    origin_longitude,
    destination_place_id,
    destination_place_name,
    destination_latitude,
    destination_longitude,
    typical_speed_kn=DEFAULT_TRAVEL_SPEED_KN,
    simplify=True,
):
    metrics = _searoute_metrics(
        origin_longitude,
        origin_latitude,
        destination_longitude,
        destination_latitude,
        speed_kn=typical_speed_kn,
        simplify=simplify,
    )
    typical_speed_kn = float(typical_speed_kn or DEFAULT_TRAVEL_SPEED_KN)
    return {
        "origin_place_id": origin_place_id,
        "origin_place_name": origin_place_name,
        "origin_latitude": float(origin_latitude),
        "origin_longitude": float(origin_longitude),
        "destination_place_id": destination_place_id,
        "destination_place_name": destination_place_name,
        "destination_latitude": float(destination_latitude),
        "destination_longitude": float(destination_longitude),
        "distance_nm": float(metrics["distance_nm"]),
        "estimated_time_h": round(float(metrics["estimated_time_h"]), 2),
        "typical_speed_kn": typical_speed_kn,
        "waypoints": metrics["waypoints"],
        "computed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "source_tag": metrics["source_tag"],
    }


def place_family(place_id):
    place = place_definition(place_id)
    parent_place_id = place.get("parent_place_id")
    if parent_place_id is None:
        return {
            "place_id": place_id,
            "place_name": place["name"],
            "parent_place_id": None,
            "children": list(place.get("children") or ()),
        }
    parent = place_definition(parent_place_id)
    return {
        "place_id": place_id,
        "place_name": place["name"],
        "parent_place_id": parent_place_id,
        "parent_place_name": parent["name"],
        "children": list(place.get("children") or ()),
    }
