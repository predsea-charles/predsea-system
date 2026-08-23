from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from urllib.parse import urljoin

from .client import fetch_json, fetch_text
from .common import NETWORK_LABELS, clean_station_name, normalize_text, station_id_from_label, station_key_from_label

import route_analysis


ROOT_CATALOG_URL = "https://opendap.puertos.es/thredds/catalog.xml"
THREDDS_BASE_URL = "https://opendap.puertos.es/thredds"
PORTUSCOPIA_API_BASE = "https://portuscopia.puertos.es/portuscopiasvr/api"

SUPPORTED_NETWORKS = {"redext", "redcos", "redmar", "hfradar"}
RADAR_NETWORK_LABEL = "HF_RADAR"
ROUTE_IDS = (
    "ibiza_palma",
    "barcelona_palma",
    "cabrera_palma",
    "palma_valencia",
    "formentera_ibiza",
    "ibiza_mahon",
    "alcudia_ciutadella",
    "ciutadella_palma",
    "mahon_palma",
)


def _is_hidden_or_temp_ref(value):
    text = normalize_text(str(value or ""))
    if not text:
        return True
    lowered = str(value).lower()
    if lowered in {".ds_store", "__macosx"}:
        return True
    if lowered.startswith("._"):
        return True
    if lowered.endswith("~"):
        return True
    if "/." in lowered:
        return True
    if any(part in lowered for part in ("/__macosx/", "/.ds_store", ".tmp", ".temp")):
        return True
    return False


def _is_valid_thredds_ref(name, href):
    if _is_hidden_or_temp_ref(name) or _is_hidden_or_temp_ref(href):
        return False
    href_text = str(href or "").lower()
    if not href_text:
        return False
    if not re.search(r"\.(?:nc4?|nc)$", href_text, re.IGNORECASE) and "/catalog.xml" not in href_text:
        return False
    return True


def _is_valid_dataset_url_path(url_path):
    if _is_hidden_or_temp_ref(url_path):
        return False
    text = str(url_path or "").lower()
    if not text:
        return False
    if text.endswith("/"):
        return False
    if any(marker in text for marker in (".json", "/catalog", "/out")):
        return False
    if text.endswith((".nc", ".nc4", ".nc5")):
        return True
    if "/dodsc/" in text:
        return True
    return False


def _select_latest_valid_dataset_url(dataset_urls):
    valid_urls = [url for url in dataset_urls if _is_valid_dataset_url_path(url)]
    if valid_urls:
        return valid_urls[-1]
    return None


def _is_valid_catalog_page_url(url):
    if _is_hidden_or_temp_ref(url):
        return False
    text = str(url or "").lower()
    if not text:
        return False
    if text.endswith("/") or any(marker in text for marker in (".json", "/out")):
        return False
    return text.endswith("/catalog.xml") or text.endswith("/catalog.html")


def _absolute_thredds_url(href):
    if not href:
        return None
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return urljoin("https://opendap.puertos.es/", href.lstrip("/"))


def _discover_root_catalog_refs(*, session=None, timeout=60, max_retries=3, backoff_seconds=2, cache_dir=None):
    result = fetch_text(
        ROOT_CATALOG_URL,
        session=session,
        timeout=timeout,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        cache_dir=cache_dir,
        cache_key="puertos_root_catalog",
    )
    xml = result["text"]
    root = ET.fromstring(xml)
    ns = {"t": "http://www.unidata.ucar.edu/namespaces/thredds/InvCatalog/v1.0"}
    refs = []
    for ref in root.findall(".//t:catalogRef", ns):
        name = ref.attrib.get("name")
        href = ref.attrib.get("{http://www.w3.org/1999/xlink}href")
        if not name or not href:
            continue
        if not _is_valid_thredds_ref(name, href):
            continue
        absolute = _absolute_thredds_url(href)
        if absolute:
            refs.append({"name": name, "href": href, "catalog_url": absolute})
    return refs


def _root_ref_index(refs, *, prefix=None):
    grouped = defaultdict(list)
    for ref in refs:
        if _is_hidden_or_temp_ref(ref.get("name")) or _is_hidden_or_temp_ref(ref.get("href")):
            continue
        href_parts = str(ref.get("href") or "").split("/")
        if prefix and (len(href_parts) < 2 or not href_parts[-2].startswith(prefix)):
            continue
        grouped[normalize_text(ref["name"])].append(ref)
    return grouped


def _score_catalog_match(station_name, candidate_name):
    station_key = normalize_text(clean_station_name(station_name))
    candidate_key = normalize_text(clean_station_name(candidate_name))
    if not station_key or not candidate_key:
        return -10
    if station_key == candidate_key:
        return 100
    station_tokens = set(station_key.split("_"))
    candidate_tokens = set(candidate_key.split("_"))
    overlap = len(station_tokens & candidate_tokens)
    score = overlap * 10
    if station_key in candidate_key or candidate_key in station_key:
        score += 30
    score -= abs(len(station_key) - len(candidate_key)) // 4
    return score


def _best_catalog_ref(name, refs, *, prefix=None):
    if not refs:
        return None
    candidates = []
    for ref in refs:
        href = ref.get("href") or ""
        if _is_hidden_or_temp_ref(ref.get("name")) or _is_hidden_or_temp_ref(href):
            continue
        path_parts = href.split("/")
        if prefix is not None:
            if len(path_parts) < 2:
                continue
            if not path_parts[-2].startswith(prefix):
                continue
        candidates.append(ref)
    if not candidates:
        candidates = list(refs)
    best = None
    best_score = None
    for ref in candidates:
        score = _score_catalog_match(name, ref["name"])
        if best is None or score > best_score:
            best = ref
            best_score = score
    return best


def _entry_network(entry):
    categories = entry.get("categories") or {}
    device = normalize_text(categories.get("device"))
    station_name = entry.get("Name") or ""
    if device in {"tide_gaude", "tide_gauge"}:
        return "redmar"
    if device == "radar":
        return "hfradar"
    if device == "buoy":
        if "costera" in normalize_text(station_name):
            return "redcos"
        return "redext"
    return None


def _portuscopia_catalogs_for_device(device, *, session=None, timeout=60, max_retries=3, backoff_seconds=2, cache_dir=None):
    payload = {"dataType": ["measure"], "device": [device], "variable": [], "scale": []}
    result = fetch_json(
        f"{PORTUSCOPIA_API_BASE}/tree/catalogs",
        method="post",
        json_data=payload,
        session=session,
        timeout=timeout,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        cache_dir=cache_dir,
        cache_key=f"puertos_tree_catalogs_{device}",
    )
    return result["json"]


def _merge_catalog_entries(entries):
    merged = {}
    for entry in entries:
        catalog_id = entry.get("catalogRefID") or entry.get("Xlink") or entry.get("Name")
        if not catalog_id:
            continue
        current = merged.setdefault(
            catalog_id,
            {
                **entry,
                "variablesInfo": [],
                "categories": {},
            },
        )
        current["Name"] = entry.get("Name") or current.get("Name")
        current["Xlink"] = entry.get("Xlink") or current.get("Xlink")
        current["portusLink"] = entry.get("portusLink") or current.get("portusLink")
        current["coords"] = entry.get("coords") or current.get("coords")
        current["bounds"] = entry.get("bounds") or current.get("bounds")
        current["dateFrom"] = entry.get("dateFrom") or current.get("dateFrom")
        current["dateTo"] = entry.get("dateTo") or current.get("dateTo")
        current["isPoint"] = entry.get("isPoint") if entry.get("isPoint") is not None else current.get("isPoint")
        current["availableMean"] = entry.get("availableMean") or current.get("availableMean")
        current["hourStep"] = entry.get("hourStep") or current.get("hourStep")
        current["netcdf4"] = entry.get("netcdf4") if entry.get("netcdf4") is not None else current.get("netcdf4")
        current.setdefault("variablesInfo", [])
        current["variablesInfo"].extend(entry.get("variablesInfo") or [])
        current.setdefault("categories", {})
        current["categories"].update(entry.get("categories") or {})
    return list(merged.values())


def _catalog_url_for_station(entry, network, root_refs):
    xlink = entry.get("Xlink")
    if isinstance(xlink, str) and xlink.startswith("/thredds/catalog/"):
        if _is_hidden_or_temp_ref(xlink):
            return None
        return _absolute_thredds_url(xlink)
    if isinstance(xlink, str) and xlink.startswith("https://opendap.puertos.es/thredds/catalog/"):
        if _is_hidden_or_temp_ref(xlink):
            return None
        return xlink
    name = entry.get("Name") or ""
    prefix = {
        "redmar": "tidegauge_",
        "redext": "wave_local_",
        "redcos": "wave_coast_",
        "hfradar": "radar_local_",
    }.get(network)
    ref = _best_catalog_ref(name, root_refs, prefix=prefix)
    if ref:
        return ref["catalog_url"]
    return None


def _route_distance_metadata(latitude, longitude, route_ids=ROUTE_IDS):
    if latitude is None or longitude is None:
        return {"nearest_routes": [], "distance_to_route_nm": None}
    try:
        routes = route_analysis.load_routes()
    except Exception:
        return {"nearest_routes": [], "distance_to_route_nm": None}
    candidates = []
    for route_id in route_ids:
        route = routes.get(route_id)
        if not route:
            continue
        points = route_analysis.route_sample_points(route)
        if not points:
            continue
        distance = min(
            route_analysis.haversine_nm(
                float(latitude),
                float(longitude),
                float(point["latitude"]),
                float(point["longitude"]),
            )
            for point in points
        )
        candidates.append(
            {
                "route_id": route_id,
                "route_name": route.get("name") or route_id,
                "distance_to_route_nm": round(distance, 1),
            }
        )
    candidates.sort(key=lambda item: (item["distance_to_route_nm"], item["route_name"].lower()))
    nearest = candidates[:3]
    return {
        "nearest_routes": [item["route_id"] for item in nearest],
        "distance_to_route_nm": nearest[0]["distance_to_route_nm"] if nearest else None,
    }


def _priority_for_station(station):
    station_id = str(station.get("station_id") or "").lower()
    network = str(station.get("network") or "").lower()
    distance_to_route_nm = station.get("distance_to_route_nm")
    explicit_high = {
        "bahia_de_palma",
        "canal_de_ibiza",
        "ibiza",
        "mallorca",
        "puertos_mallorca",
        "puertos_ibiza",
        "puertos_alcudia",
        "puertos_mahon",
        "puertos_formentera",
        "porto_colom",
        "puertos_delta_del_ebro",
    }
    if station_id in explicit_high or network == "hfradar":
        return "high"
    if network == "redmar":
        return "low"
    if distance_to_route_nm is None:
        return "normal"
    try:
        distance_to_route_nm = float(distance_to_route_nm)
    except Exception:
        return "normal"
    if distance_to_route_nm <= 20:
        return "high"
    if distance_to_route_nm <= 45:
        return "medium"
    return "normal"


def discover_station_catalogs(
    *,
    networks=None,
    session=None,
    timeout=60,
    max_retries=3,
    backoff_seconds=2,
    cache_dir=None,
):
    allowed_networks = {str(network).lower() for network in (networks or SUPPORTED_NETWORKS)}
    refs = _discover_root_catalog_refs(
        session=session,
        timeout=timeout,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        cache_dir=cache_dir,
    )
    entries = []
    for device in ("buoy", "tide_gaude", "radar"):
        try:
            entries.extend(
                _portuscopia_catalogs_for_device(
                    device,
                    session=session,
                    timeout=timeout,
                    max_retries=max_retries,
                    backoff_seconds=backoff_seconds,
                    cache_dir=cache_dir,
                )
            )
        except Exception:
            continue

    merged = _merge_catalog_entries(entries)
    stations = []
    for entry in merged:
        network = _entry_network(entry)
        if network not in allowed_networks:
            continue
        station_name = entry.get("Name") or "Unknown"
        station_id = station_id_from_label(station_name)
        coords = entry.get("coords") or {}
        thredds_catalog_url = _catalog_url_for_station(entry, network, refs)
        if not thredds_catalog_url:
            continue
        route_metadata = _route_distance_metadata(coords.get("lat"), coords.get("lon"))
        variables_available = sorted(
            {
                normalize_text(variable.get("name") or variable.get("desc"))
                for variable in (entry.get("variablesInfo") or [])
                if normalize_text(variable.get("name") or variable.get("desc"))
            }
        )
        station = {
            "source_system": "puertos_del_estado",
            "source_label": NETWORK_LABELS.get(network, RADAR_NETWORK_LABEL if network == "hfradar" else network.upper()),
            "network": network,
            "catalog_id": entry.get("catalogRefID") or entry.get("Xlink") or station_name,
            "catalog_url": thredds_catalog_url,
            "portus_link": entry.get("portusLink"),
            "station_id": station_id,
            "station_name": station_name,
            "station_key": station_key_from_label(station_name),
            "latitude": coords.get("lat"),
            "longitude": coords.get("lon"),
            "variables_info": entry.get("variablesInfo") or [],
            "variables_available": variables_available,
            "station_kind": "radar" if network == "hfradar" else ("tide_gauge" if network == "redmar" else "buoy"),
            "priority": None,
            "nearest_routes": route_metadata["nearest_routes"],
            "distance_to_route_nm": route_metadata["distance_to_route_nm"],
            "is_point": entry.get("isPoint"),
        }
        station["priority"] = _priority_for_station(station)
        stations.append(station)
    return sorted(stations, key=lambda item: (item["network"], item["station_name"].lower()))


def discover_latest_dataset_url(
    station_catalog_url,
    *,
    session=None,
    timeout=60,
    max_retries=3,
    backoff_seconds=2,
    cache_dir=None,
    _visited=None,
):
    if not station_catalog_url:
        return None
        
    # Standardize the string reference by removing trailing junk/queries to ensure the deduplication works perfectly
    normalized_url = station_catalog_url.split('?')[0].rstrip('/')
    
    visited = set(_visited or ())
    if normalized_url in visited:
        return None
    visited.add(normalized_url)

    fetched = fetch_text(
        station_catalog_url,
        session=session,
        timeout=timeout,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        cache_dir=cache_dir,
        cache_key=f"puertos_catalog_{normalize_text(normalized_url)}",
    )
    xml_text = fetched["text"]
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        root = None
        
    if root is not None:
        ns = {"t": "http://www.unidata.ucar.edu/namespaces/thredds/InvCatalog/v1.0"}
        dataset_urls = sorted(
            {
                dataset.attrib.get("urlPath")
                for dataset in root.findall(".//t:dataset", ns)
                if dataset.attrib.get("urlPath")
            }
        )
        if dataset_urls:
            raw_links = [link for link in dataset_urls if "_analysis" not in link.lower() and ".ds_store" not in link.lower()]
            chosen = _select_latest_valid_dataset_url(raw_links)
            if chosen:
                return urljoin(THREDDS_BASE_URL.rstrip("/") + "/dodsC/", chosen)

        child_links = []
        for ref in root.findall(".//t:catalogRef", ns):
            href = ref.attrib.get("{http://www.w3.org/1999/xlink}href") or ref.attrib.get("xlink:href")
            if not href:
                continue
            
            # Defensive guard: skip known cyclic references or dot directories
            if href in ("..", ".", "./") or "catalog.xml" in href and href == station_catalog_url.split('/')[-1]:
                continue
                
            if href.startswith("http://") or href.startswith("https://"):
                child_links.append(href)
            elif href.startswith("/thredds/"):
                child_links.append(_absolute_thredds_url(href))
            else:
                child_links.append(urljoin(station_catalog_url, href))
        child_links = sorted({link for link in child_links if link})
    else:
        html = xml_text
        dataset_links = sorted(
            set(
                match.group("dataset")
                for match in re.finditer(
                    r'href="(?:/thredds/)?catalog\.html\?dataset=(?P<dataset>[^"]+\.(?:nc4?|nc))"',
                    html,
                    re.IGNORECASE,
                )
            )
        )
        if dataset_links:
            raw_links = [link for link in dataset_links if "_analysis" not in link.lower() and ".ds_store" not in link.lower()]
            chosen = _select_latest_valid_dataset_url(raw_links)
            if chosen:
                return urljoin(THREDDS_BASE_URL.rstrip("/") + "/dodsC/", chosen)

        child_links = []
        for match in re.finditer(r'href="(?P<href>[^"]+/catalog\.xml)"', html, re.IGNORECASE):
            href = match.group("href")
            if href.startswith("http://") or href.startswith("https://"):
                child_links.append(href)
            elif href.startswith("/thredds/"):
                child_links.append(_absolute_thredds_url(href))
            else:
                child_links.append(urljoin(station_catalog_url, href))
        child_links = sorted({link for link in child_links if link})

    for child_url in reversed([link for link in child_links if link]):
        # Double check that the child isn't just the parent re-badged
        if child_url.split('?')[0].rstrip('/') in visited:
            continue
        if not _is_valid_catalog_page_url(child_url):
            continue
            
        latest = discover_latest_dataset_url(
            child_url,
            session=session,
            timeout=timeout,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            cache_dir=cache_dir,
            _visited=visited,
        )
        if latest:
            return latest
    return None

def discover_observation_stations(
    *,
    networks=None,
    session=None,
    timeout=60,
    max_retries=3,
    backoff_seconds=2,
    cache_dir=None,
):
    stations = discover_station_catalogs(
        networks=networks,
        session=session,
        timeout=timeout,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        cache_dir=cache_dir,
    )
    discovered = []
    for station in stations:
        try:
            latest_dataset_url = discover_latest_dataset_url(
                station["catalog_url"],
                session=session,
                timeout=timeout,
                max_retries=max_retries,
                backoff_seconds=backoff_seconds,
                cache_dir=cache_dir,
            )
        except Exception:
            latest_dataset_url = None
        if not latest_dataset_url:
            continue
        discovered.append(
            {
                **station,
                "latest_dataset_url": latest_dataset_url,
            }
        )
    return discovered
