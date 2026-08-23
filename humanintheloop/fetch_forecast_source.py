import argparse
import json
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Fetch one PredSea forecast source.")
    parser.add_argument("--source", required=True, choices=["copernicus", "socib"])
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--forecast-run-date")
    return parser.parse_args()


def fetch_copernicus(output_dir, dry_run=False, forecast_run_date=None):
    import fetch_data

    fetch_data.OUTPUT_DIR = str(output_dir)
    Path(fetch_data.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    result = fetch_data.get_balearic_forecast(
        dry_run=dry_run,
        forecast_run_date=forecast_run_date,
    ) or {}
    return {
        "id": "copernicus",
        "label": "Copernicus Marine Mediterranean forecast",
        "available": True,
        "forecast_source_status": result.get("forecast_source_status", "live"),
        "forecast_run_date": result.get("forecast_run_date"),
        "waves_path": str(Path(result.get("waves_path") or output_dir / "balearic_waves.nc")),
        "currents_path": str(Path(result.get("currents_path") or output_dir / "balearic_currents.nc")),
        "metadata": {
            "wave_model": fetch_data.WAV_ID,
            "current_model": fetch_data.PHY_ID,
        },
    }


def fetch_socib(output_dir, dry_run=False):
    import socib_thredds

    result = socib_thredds.get_balearic_forecast(output_dir=output_dir, dry_run=dry_run)
    return {
        "id": "socib",
        "label": "SOCIB WMOP/SAPO forecast",
        "available": True,
        "waves_path": str(result["waves_path"]),
        "currents_path": str(result["currents_path"]),
        "metadata": result.get("metadata", {}),
    }


def main():
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.source == "copernicus":
        metadata = fetch_copernicus(output_dir, dry_run=args.dry_run, forecast_run_date=args.forecast_run_date)
    else:
        metadata = fetch_socib(output_dir, dry_run=args.dry_run)

    (output_dir / "forecast_source.json").write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )
    print(f"Fetched forecast source {args.source} into {output_dir}", flush=True)


if __name__ == "__main__":
    main()
