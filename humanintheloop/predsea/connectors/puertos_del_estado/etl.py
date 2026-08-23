from __future__ import annotations

from importlib import import_module

from . import client, normalizer, station_catalog


def _network_parser(network):
    if network == "redmar":
        from .redmar_parser import parse_station_dataset

        return parse_station_dataset
    if network == "redcos":
        from .redcos_parser import parse_station_dataset

        return parse_station_dataset
    if network == "hfradar":
        from .hfradar_connector import parse_station_dataset

        return parse_station_dataset
    from .redext_parser import parse_station_dataset

    return parse_station_dataset


def fetch_network_observations(
    network,
    *,
    dry_run=False,
    timeout=60,
    max_retries=3,
    backoff_seconds=2,
    cache_dir=None,
    session=None,
    parser_fn=None,
):
    parser_fn = parser_fn or _network_parser(network)
    source_label = {
        "redext": "REDEXT",
        "redcos": "REDCOS",
        "redmar": "REDMAR",
        "hfradar": "HF_RADAR",
    }.get(network, network.upper())
    if dry_run:
        return {
            "observations": {},
            "measurements": {},
            "lineage": {
                "source": "puertos_del_estado",
                "status": "unavailable",
                "stations_matched": 0,
                "station_ids": [],
                "source_labels": [],
                "network": network,
            },
            "errors": {},
            "source": "puertos_del_estado",
            "network": network,
            "catalog_count": 0,
            "catalog_stations": [],
            "cache_paths": [],
        }

    discovered = station_catalog.discover_observation_stations(
        networks=[network],
        session=session,
        timeout=timeout,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        cache_dir=cache_dir,
    )
    observations = {}
    station_measurements = {}
    errors = {}
    matched_station_ids = []
    source_labels = set()
    cache_paths = []

    for station in discovered:
        station_key = station["station_key"]
        try:
            dataset = client.open_dataset(
                station["latest_dataset_url"],
                timeout=timeout,
                max_retries=max_retries,
                backoff_seconds=backoff_seconds,
            )
            try:
                measurements = parser_fn(
                    dataset,
                    station,
                    dataset_url=station["latest_dataset_url"],
                )
            finally:
                dataset.close()

            if not measurements:
                errors[station_key] = "no supported measurements found"
                continue

            record = normalizer.measurements_to_observation_record(station, measurements)
            observations[station_key] = record
            station_measurements[station_key] = measurements
            matched_station_ids.append(station["station_id"])
            source_labels.add(station.get("source_label") or source_label)
        except Exception as error:  # pragma: no cover - network path
            errors[station_key] = str(error)

    lineage = {
        "source": "puertos_del_estado",
        "status": "matched_successfully" if observations else "unavailable",
        "stations_matched": len(matched_station_ids),
        "station_ids": matched_station_ids,
        "source_labels": sorted(source_labels),
        "network": network,
    }
    return {
        "observations": observations,
        "measurements": station_measurements,
        "lineage": lineage,
        "errors": errors,
        "source": "puertos_del_estado",
        "network": network,
        "catalog_count": len(discovered),
        "catalog_stations": discovered,
        "cache_paths": [path for path in cache_paths if path],
    }


def fetch_puertos_observations(
    *,
    dry_run=False,
    timeout=60,
    max_retries=3,
    backoff_seconds=2,
    cache_dir=None,
    session=None,
):
    if dry_run:
        return {
            "observations": {},
            "measurements": {},
            "lineage": {
                "source": "puertos_del_estado",
                "status": "unavailable",
                "stations_matched": 0,
                "station_ids": [],
                "source_labels": [],
            },
            "errors": {},
            "source": "puertos_del_estado",
            "catalog_count": 0,
            "catalog_stations": [],
            "cache_paths": [],
        }

    connector_specs = (
        ("redext", "fetch_redext_observations"),
        ("redcos", "fetch_redcos_observations"),
        ("hfradar", "fetch_hfradar_observations"),
        ("redmar", "fetch_redmar_observations"),
    )

    all_observations = {}
    all_measurements = {}
    all_errors = {}
    all_station_ids = []
    all_source_labels = set()
    all_catalog_stations = []
    all_cache_paths = []

    for network, function_name in connector_specs:
        try:
            module = import_module(f"predsea.connectors.puertos_del_estado.{network}_connector")
            result = getattr(module, function_name)(
                dry_run=dry_run,
                timeout=timeout,
                max_retries=max_retries,
                backoff_seconds=backoff_seconds,
                cache_dir=cache_dir,
                session=session,
            )
        except Exception as error:  # pragma: no cover - connector path
            all_errors[network] = str(error)
            continue

        network_observations = result.get("observations", {})
        network_measurements = result.get("measurements", {})
        for key, value in network_observations.items():
            all_observations[key] = value
        for key, value in network_measurements.items():
            all_measurements[key] = value
        network_lineage = result.get("lineage") or {}
        all_station_ids.extend(network_lineage.get("station_ids") or [])
        all_source_labels.update(network_lineage.get("source_labels") or [])
        all_catalog_stations.extend(result.get("catalog_stations") or [])
        all_cache_paths.extend(result.get("cache_paths") or [])
        if result.get("errors"):
            all_errors[network] = result["errors"]

    lineage = {
        "source": "puertos_del_estado",
        "status": "matched_successfully" if all_observations else "unavailable",
        "stations_matched": len(all_station_ids),
        "station_ids": all_station_ids,
        "source_labels": sorted(all_source_labels),
    }
    return {
        "observations": all_observations,
        "measurements": all_measurements,
        "lineage": lineage,
        "errors": all_errors,
        "source": "puertos_del_estado",
        "catalog_count": len(all_catalog_stations),
        "catalog_stations": all_catalog_stations,
        "cache_paths": [path for path in all_cache_paths if path],
    }
