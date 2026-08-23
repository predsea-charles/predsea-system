from pathlib import Path
from pprint import pprint
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.observations_client import load_observations_csv
from processing.forecast_validation import compare_forecast_distributions


if __name__ == "__main__":
    observations = load_observations_csv("ingestion/fixtures/balearic_observations_sample.csv")
    pprint(
        compare_forecast_distributions(
            observations=observations,
            wrfout_paths=[
                Path("processing/fixtures/wrfout_d01_sample.nc"),
                Path("processing/fixtures/wrfout_d02_sample.nc"),
                Path("processing/fixtures/wrfout_d03_sample.nc"),
            ],
            time="2026-04-29T18:00:00Z",
            variable="wind_knots",
        )
    )
