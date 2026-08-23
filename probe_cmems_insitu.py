#!/usr/bin/env python3
"""
Diagnostic script — NOT part of the pipeline. Run this locally to figure out
the real structure of the CMEMS Western Mediterranean in-situ NRT product
before we write the actual copernicus_insitu connector.

Round 1: open_dataset() failed -> told us to use read_dataframe() (sqlite-backed
in-situ data isn't lazily loadable as xarray).
Round 2: read_dataframe() over the FULL Western Med bbox (-5 to 20 lon,
34 to 48 lat) was walking hundreds of geo-chunks and would have taken 30-60+
minutes just to answer "what columns does this even have".

Round 3 (this one): shrink the bbox to a tiny box around Barcelona (a handful
of geo-chunks) and a short time window, purely to see the DataFrame schema
fast. Once we know the shape of the data we can decide the real fetch
strategy for the full domain (probably: fetch per sub-region, or restrict to
fewer variables, or run it as a slow nightly job that isn't on any user-facing
critical path).
"""
from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
dotenv_path = BASE_DIR / "humanintheloop" / ".env"
if not dotenv_path.exists():
    dotenv_path = Path("humanintheloop/.env")
load_dotenv(dotenv_path)

username = os.getenv("COPERNICUS_USERNAME")
password = os.getenv("COPERNICUS_PASSWORD")
if username:
    os.environ["COPERNICUSMARINE_SERVICE_USERNAME"] = username
if password:
    os.environ["COPERNICUSMARINE_SERVICE_PASSWORD"] = password

if not os.environ.get("COPERNICUSMARINE_SERVICE_USERNAME"):
    print("WARNING: no Copernicus credentials found in humanintheloop/.env", file=sys.stderr)

import copernicusmarine  # noqa: E402

DATASET_ID = "cmems_obs-ins_med_phybgcwav_mynrt_na_irr"

# Tiny box around Barcelona -- just a few geo-chunks, purely to see the schema fast.
LON_MIN, LON_MAX = 1.5, 3.0
LAT_MIN, LAT_MAX = 40.5, 41.5

# Dataset's own reported max time (from the warning in round 2) was 2026-07-03 06:12 UTC.
# Use a 12h window ending there so we don't ask for data past the end of the archive.
END_TIME = datetime.datetime(2026, 7, 3, 6, 0, tzinfo=datetime.timezone.utc)
START_TIME = END_TIME - datetime.timedelta(hours=12)


def try_read_dataframe():
    print("=" * 60)
    print("Attempt: copernicusmarine.read_dataframe() — small bbox, fast schema check")
    print(f"Bbox: lon [{LON_MIN}, {LON_MAX}] lat [{LAT_MIN}, {LAT_MAX}]")
    print(f"Time window: {START_TIME.isoformat()} to {END_TIME.isoformat()}")
    print("=" * 60)
    try:
        df = copernicusmarine.read_dataframe(
            dataset_id=DATASET_ID,
            minimum_longitude=LON_MIN,
            maximum_longitude=LON_MAX,
            minimum_latitude=LAT_MIN,
            maximum_latitude=LAT_MAX,
            start_datetime=START_TIME,
            end_datetime=END_TIME,
        )
        print("SUCCESS.")
        print(f"Shape: {df.shape}")
        print(f"Columns: {list(df.columns)}")
        print()
        print("First 20 rows:")
        print(df.head(20).to_string())
        print()

        for candidate in ("platform_code", "PLATFORM_CODE", "platform", "station_id", "wmo_platform_code"):
            if candidate in df.columns:
                print(f"Unique values of '{candidate}' ({df[candidate].nunique()} distinct):")
                print(df[candidate].unique()[:30])

        for candidate in ("source", "platform_name", "instrument", "parameter"):
            if candidate in df.columns:
                print(f"\nUnique values of '{candidate}':")
                print(df[candidate].unique()[:30])

        return df
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        return None


if __name__ == "__main__":
    try_read_dataframe()
    print()
    print("Done. Please paste the full output back.")
