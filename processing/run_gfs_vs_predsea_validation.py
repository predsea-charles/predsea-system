from pathlib import Path
from pprint import pprint
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.observations_client import load_observations_csv
from processing.forecast_validation import compare_gfs_to_predsea


if __name__ == "__main__":
    observations = load_observations_csv("ingestion/fixtures/balearic_observations_real.csv")
    pprint(
        compare_gfs_to_predsea(
            observations=observations,
            gfs_path=Path("processing/fixtures/gfs_20260429_12_f006_wind_prmsl.nc"),
            wrfout_path=Path("processing/fixtures/wrfout_d03_sample.nc"),
            time="2026-04-29T18:00:00Z",
            variable="wind_knots",
        )
    )
