from __future__ import annotations

import argparse
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.observations_client import (
    extract_copernicus_mooring_observation,
    write_observations_csv,
)


def convert_copernicus_observations(
    input_dir: Path,
    output_csv: Path,
    target_time: str,
) -> list[Path]:
    nc_paths = sorted(input_dir.rglob("IR_TS_MO_*.nc"))
    observations = [
        extract_copernicus_mooring_observation(path, target_time)
        for path in nc_paths
    ]
    observations = [observation for observation in observations if observation.wind_knots is not None]
    write_observations_csv(observations, output_csv)
    return nc_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert Copernicus mooring NetCDF observations to PredSea CSV.")
    parser.add_argument("--input-dir", type=Path, default=Path("observations"))
    parser.add_argument("--output-csv", type=Path, default=Path("ingestion/fixtures/balearic_observations_real.csv"))
    parser.add_argument("--target-time", default="2026-04-29T18:00:00Z")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = convert_copernicus_observations(
        input_dir=args.input_dir,
        output_csv=args.output_csv,
        target_time=args.target_time,
    )
    print(f"converted_files={len(paths)}")
    print(args.output_csv)


if __name__ == "__main__":
    main()
