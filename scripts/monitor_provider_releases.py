import argparse
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


COPERNICUS_DATASETS = {
    "copernicus_currents": "cmems_mod_med_phy-cur_anfc_4.2km-2D_PT1H-m",
    "copernicus_waves": "cmems_mod_med_wav_anfc_4.2km_PT1H-i",
}
SOCIB_RUN_CATALOGS = {
    "socib_sapo_waves": (
        "https://thredds.socib.es/thredds/catalog/"
        "operational_models/oceanographical/wave/model_run_aggregation/"
        "sapo_ib/runs/catalog.xml"
    ),
    "socib_wmop_currents": (
        "https://thredds.socib.es/thredds/catalog/"
        "operational_models/oceanographical/hydrodynamics/model_run_aggregation/"
        "wmop_surface/runs/catalog.xml"
    ),
}


def parse_args():
    parser = argparse.ArgumentParser(description="Probe forecast provider release/update metadata.")
    parser.add_argument("--output-dir", default="outputs/provider-monitor")
    parser.add_argument("--timeout", type=int, default=30)
    return parser.parse_args()


def utc_now():
    return datetime.now(timezone.utc)


def format_probe_time(value):
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_probe_id(value):
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H%MZ")


def fetch_url_text(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def parse_socib_runs_catalog(xml_text, limit=7):
    matches = re.findall(r'_RUN_(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)', xml_text)
    unique_runs = sorted(set(matches), reverse=True)
    return unique_runs[:limit]


def extract_copernicus_update_metadata(catalog_dump):
    parts = []
    for product in catalog_dump.get("products", []):
        for dataset in product.get("datasets", []):
            for version in dataset.get("versions", []):
                parts.extend(version.get("parts", []))
    if not parts:
        return {}
    part = parts[0]
    return {
        "released_date": part.get("released_date"),
        "arco_updating_start_date": part.get("arco_updating_start_date"),
        "arco_updated_date": part.get("arco_updated_date"),
    }


def probe_copernicus_dataset(label, dataset_id):
    import copernicusmarine

    catalog = copernicusmarine.describe(
        dataset_id=dataset_id,
        disable_progress_bar=True,
        raise_on_error=False,
    )
    catalog_dump = catalog.model_dump(mode="json") if hasattr(catalog, "model_dump") else catalog.dict()
    metadata = extract_copernicus_update_metadata(catalog_dump)
    return {
        "provider": "copernicus",
        "dataset": label,
        "dataset_id": dataset_id,
        "available": bool(metadata),
        "latest_model_run": None,
        "provider_updated_at": metadata.get("arco_updated_date"),
        "provider_update_started_at": metadata.get("arco_updating_start_date"),
        "dataset_released_at": metadata.get("released_date"),
    }


def probe_socib_catalog(label, url, timeout=30):
    xml_text = fetch_url_text(url, timeout=timeout)
    runs = parse_socib_runs_catalog(xml_text)
    return {
        "provider": "socib",
        "dataset": label,
        "dataset_id": url,
        "available": bool(runs),
        "latest_model_run": runs[0] if runs else None,
        "recent_model_runs": runs,
        "provider_updated_at": None,
    }


def unavailable_record(provider, dataset, dataset_id, error):
    return {
        "provider": provider,
        "dataset": dataset,
        "dataset_id": dataset_id,
        "available": False,
        "latest_model_run": None,
        "provider_updated_at": None,
        "error": str(error),
    }


def collect_provider_records(timeout=30):
    records = []
    for label, dataset_id in COPERNICUS_DATASETS.items():
        try:
            records.append(probe_copernicus_dataset(label, dataset_id))
        except Exception as error:
            records.append(unavailable_record("copernicus", label, dataset_id, error))

    for label, url in SOCIB_RUN_CATALOGS.items():
        try:
            records.append(probe_socib_catalog(label, url, timeout=timeout))
        except Exception as error:
            records.append(unavailable_record("socib", label, url, error))
    return records


def write_probe_outputs(output_dir, records, probe_time=None):
    probe_time = probe_time or utc_now()
    day_dir = Path(output_dir) / probe_time.astimezone(timezone.utc).date().isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "probe_time_utc": format_probe_time(probe_time),
        "records": records,
    }
    output_path = day_dir / f"provider_release_probe_{format_probe_id(probe_time)}.json"
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    jsonl_path = day_dir / "provider_release_probes.jsonl"
    with jsonl_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, separators=(",", ":")) + "\n")
    return output_path


def main():
    args = parse_args()
    probe_time = utc_now()
    records = collect_provider_records(timeout=args.timeout)
    output_path = write_probe_outputs(args.output_dir, records, probe_time=probe_time)
    print(f"Wrote provider release probe to {output_path}")
    print(json.dumps({"probe_time_utc": format_probe_time(probe_time), "records": records}, indent=2))


if __name__ == "__main__":
    main()
