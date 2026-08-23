from pathlib import Path
from pprint import pprint
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processing.mariner_interpreter import compare_optimal_routes


if __name__ == "__main__":
    pprint(
        compare_optimal_routes(
            start_lat=39.3,
            start_lon=3.0,
            end_lat=39.8,
            end_lon=3.6,
            time=None,
            wrfout_paths=[
                Path("processing/fixtures/wrfout_d01_sample.nc"),
                Path("processing/fixtures/wrfout_d02_sample.nc"),
                Path("processing/fixtures/wrfout_d03_sample.nc"),
            ],
            cost_field="wind",
        )
    )
