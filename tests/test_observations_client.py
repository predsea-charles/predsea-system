from pathlib import Path

import numpy as np
import xarray as xr

from ingestion.observations_client import (
    Observation,
    extract_copernicus_mooring_observation,
    load_observations_csv,
)


def test_load_observations_csv_normalizes_common_station_columns(tmp_path):
    csv_path = tmp_path / "observations.csv"
    csv_path.write_text(
        "\n".join(
            [
                "station_id,time,lat,lon,wind_knots,wind_direction_deg,pressure_hpa",
                "socib-01,2026-04-29T18:00:00Z,39.30,3.00,8.5,90,1012.4",
                "socib-02,2026-04-29T18:00:00Z,39.50,3.20,6.0,85,1011.8",
            ]
        )
    )

    observations = load_observations_csv(csv_path)

    assert observations == [
        Observation(
            source_id="socib-01",
            time="2026-04-29T18:00:00Z",
            lat=39.30,
            lon=3.00,
            wind_knots=8.5,
            wind_direction_deg=90.0,
            pressure_hpa=1012.4,
        ),
        Observation(
            source_id="socib-02",
            time="2026-04-29T18:00:00Z",
            lat=39.50,
            lon=3.20,
            wind_knots=6.0,
            wind_direction_deg=85.0,
            pressure_hpa=1011.8,
        ),
    ]


def test_extract_copernicus_mooring_observation_reads_nearest_time_and_depth(tmp_path):
    nc_path = tmp_path / "IR_TS_MO_6100430.nc"
    dataset = xr.Dataset(
        data_vars={
            "WSPD": (("TIME", "DEPTH"), np.array([[3.0], [4.0]])),
            "WDIR": (("TIME", "DEPTH"), np.array([[90.0], [100.0]])),
            "ATMS": (("TIME", "DEPTH"), np.array([[1012.0], [1011.5]])),
        },
        coords={
            "TIME": np.array(["2026-04-29T17:00:00", "2026-04-29T18:00:00"], dtype="datetime64[ns]"),
            "DEPTH": np.array([0.0]),
            "LATITUDE": np.float32(39.5644),
            "LONGITUDE": np.float32(2.0972),
            "STATION": np.bytes_("6100430"),
        },
    )
    dataset.to_netcdf(nc_path)

    observation = extract_copernicus_mooring_observation(nc_path, "2026-04-29T18:00:00Z")

    assert observation == Observation(
        source_id="6100430",
        time="2026-04-29T18:00:00Z",
        lat=39.56439971923828,
        lon=2.0971999168395996,
        wind_knots=7.775,
        wind_direction_deg=100.0,
        pressure_hpa=1011.5,
    )
