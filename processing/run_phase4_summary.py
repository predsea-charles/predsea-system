from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processing.mariner_interpreter import get_captain_summary


if __name__ == "__main__":
    print(get_captain_summary(lat=39.5, lon=3.2, time=None))
