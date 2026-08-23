from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import xarray as xr


MPS_TO_KNOTS = 1.9438444924406


@dataclass(frozen=True)
class Observation:
    source_id: str
    time: str
    lat: float
    lon: float
    wind_knots: float | None = None
    wind_direction_deg: float | None = None
    pressure_hpa: float | None = None


def load_observations_csv(path: str | Path) -> list[Observation]:
    """Load normalized station observations from a CSV export."""

    with Path(path).open(newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        return [_observation_from_row(row) for row in reader]


def write_observations_csv(observations: list[Observation], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=["station_id", "time", "lat", "lon", "wind_knots", "wind_direction_deg", "pressure_hpa"],
        )
        writer.writeheader()
        for observation in observations:
            writer.writerow(
                {
                    "station_id": observation.source_id,
                    "time": observation.time,
                    "lat": observation.lat,
                    "lon": observation.lon,
                    "wind_knots": observation.wind_knots if observation.wind_knots is not None else "",
                    "wind_direction_deg": (
                        observation.wind_direction_deg if observation.wind_direction_deg is not None else ""
                    ),
                    "pressure_hpa": observation.pressure_hpa if observation.pressure_hpa is not None else "",
                }
            )


def extract_copernicus_mooring_observation(
    nc_path: str | Path,
    target_time: str,
) -> Observation:
    with xr.open_dataset(nc_path) as dataset:
        time_index = _nearest_time_index(dataset, target_time)
        depth_index = _surface_depth_index(dataset)
        station = _station_id(dataset, Path(nc_path))
        lat = _coordinate_value(dataset, "PRECISE_LATITUDE", time_index)
        lon = _coordinate_value(dataset, "PRECISE_LONGITUDE", time_index)
        if lat is None:
            lat = _scalar_coordinate_value(dataset, "LATITUDE")
        if lon is None:
            lon = _scalar_coordinate_value(dataset, "LONGITUDE")

        wind_mps = _variable_value(dataset, "WSPD", time_index, depth_index)
        wind_direction = _variable_value(dataset, "WDIR", time_index, depth_index)
        pressure = _variable_value(dataset, "ATMS", time_index, depth_index)

    if lat is None or lon is None:
        raise ValueError(f"Observation file {nc_path} has no usable latitude/longitude.")

    return Observation(
        source_id=station,
        time=target_time,
        lat=lat,
        lon=lon,
        wind_knots=round(wind_mps * MPS_TO_KNOTS, 3) if wind_mps is not None else None,
        wind_direction_deg=round(wind_direction, 3) if wind_direction is not None else None,
        pressure_hpa=round(pressure, 3) if pressure is not None else None,
    )


def _observation_from_row(row: dict[str, str]) -> Observation:
    return Observation(
        source_id=row.get("station_id") or row.get("source_id") or row.get("id") or "unknown",
        time=row["time"],
        lat=float(row["lat"]),
        lon=float(row["lon"]),
        wind_knots=_optional_float(row.get("wind_knots")),
        wind_direction_deg=_optional_float(row.get("wind_direction_deg")),
        pressure_hpa=_optional_float(row.get("pressure_hpa")),
    )


def _optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _nearest_time_index(dataset: xr.Dataset, target_time: str) -> int:
    if "TIME" not in dataset:
        raise ValueError("Copernicus mooring file has no TIME coordinate.")
    target = np.datetime64(target_time.replace("Z", ""))
    times = dataset["TIME"].values
    return int(np.abs(times - target).argmin())


def _surface_depth_index(dataset: xr.Dataset) -> int:
    if "DEPTH" not in dataset:
        return 0
    depths = dataset["DEPTH"].values
    return int(np.nanargmin(np.abs(depths)))


def _station_id(dataset: xr.Dataset, path: Path) -> str:
    if "STATION" in dataset:
        value = np.asarray(dataset["STATION"].values).item()
        if isinstance(value, bytes):
            return value.decode("utf-8").strip()
        if hasattr(value, "decode"):
            return value.decode("utf-8").strip()
        return str(value).replace("b'", "").replace("'", "").strip()
    stem = path.stem
    return stem.rsplit("_", 1)[-1]


def _coordinate_value(dataset: xr.Dataset, name: str, time_index: int) -> float | None:
    if name not in dataset:
        return None
    value = dataset[name]
    if "TIME" in value.dims:
        return _clean_float(value.isel(TIME=time_index).values)
    return _clean_float(value.values)


def _scalar_coordinate_value(dataset: xr.Dataset, name: str) -> float | None:
    if name not in dataset:
        return None
    return _clean_float(dataset[name].values)


def _variable_value(dataset: xr.Dataset, name: str, time_index: int, depth_index: int) -> float | None:
    if name not in dataset:
        return None
    value = dataset[name]
    indexers = {}
    if "TIME" in value.dims:
        indexers["TIME"] = time_index
    if "DEPTH" in value.dims:
        indexers["DEPTH"] = depth_index
    return _clean_float(value.isel(indexers).values if indexers else value.values)


def _clean_float(value) -> float | None:
    result = float(np.asarray(value).item())
    if np.isnan(result):
        return None
    return result
