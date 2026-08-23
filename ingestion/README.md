# Ingestion

Data acquisition scripts live here.

Phase 3 uses `gfs_puller.py`, which discovers the latest available GFS
0.25-degree cycle from the NOAA public S3 bucket.

Dry-run key discovery:

```bash
python ingestion/gfs_puller.py --dry-run --max-files 5
```

Download and spatially filter GRIB2 files:

```bash
conda install -c conda-forge wgrib2
python ingestion/gfs_puller.py --max-files 1
```

The script uses `wgrib2 -small_grib` for the Western Mediterranean bounding box:

```text
lon -6.0 to 10.0, lat 34.0 to 45.5
```

Observation ingestion starts with `observations_client.py`, which normalizes
station-style SOCIB, Puertos del Estado, or yacht telemetry exports into a
shared CSV-backed shape for forecast validation.
