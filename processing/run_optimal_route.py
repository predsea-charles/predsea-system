from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processing.mariner_interpreter import get_optimal_route


if __name__ == "__main__":
    print(
        get_optimal_route(
            start_lat=39.3,
            start_lon=3.0,
            end_lat=39.8,
            end_lon=3.6,
            time=None,
            cost_field="wind",
        )
    )
