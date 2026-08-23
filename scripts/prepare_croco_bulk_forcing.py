#!/usr/bin/env python3
"""Build CROCO bulk surface forcing from real PredSea WRF output."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import xarray as xr
from scipy.interpolate import griddata


REQUIRED_WRF_VARIABLES = (
    "XLAT",
    "XLONG",
    "U10",
    "V10",
    "T2",
    "Q2",
    "PSFC",
    "SWDOWN",
    "GLW",
)


def _surface(values: xr.DataArray) -> np.ndarray:
    array = np.asarray(values.values)
    while array.ndim > 2:
        array = array[0]
    return array.astype(np.float64)


def _wrf_timestamp(raw: np.ndarray) -> str:
    """Decode WRF ``Times`` values across NetCDF string representations."""
    values = np.asarray(raw)
    first = values[0]
    if values.ndim == 2:
        parts = np.asarray(first).tolist()
        if parts and isinstance(parts[0], bytes):
            stamp = b"".join(parts).decode("ascii")
        else:
            stamp = "".join(str(part) for part in parts)
    elif isinstance(first, bytes):
        stamp = first.decode("ascii")
    else:
        stamp = str(first)
    return stamp.replace("_", "T")


def _relative_humidity_percent(t_kelvin: np.ndarray, q: np.ndarray, p_pa: np.ndarray) -> np.ndarray:
    """Convert WRF specific humidity to relative humidity in percent."""
    vapor_pressure = q * p_pa / np.maximum(0.622 + 0.378 * q, 1.0e-8)
    t_celsius = t_kelvin - 273.15
    saturation = 611.2 * np.exp(17.67 * t_celsius / (t_celsius + 243.5))
    return np.clip(100.0 * vapor_pressure / saturation, 0.0, 100.0)


def _interpolate(source_lon: np.ndarray, source_lat: np.ndarray, values: np.ndarray,
                 target_lon: np.ndarray, target_lat: np.ndarray) -> np.ndarray:
    points = np.column_stack((source_lon.ravel(), source_lat.ravel()))
    result = griddata(points, values.ravel(), (target_lon, target_lat), method="linear")
    if np.isnan(result).any():
        nearest = griddata(points, values.ravel(), (target_lon, target_lat), method="nearest")
        result = np.where(np.isnan(result), nearest, result)
    return result.astype(np.float32)


def build_bulk_forcing(
    wrf_files: list[Path],
    grid_path: Path,
    output_path: Path,
    *,
    start_time: np.datetime64 | None = None,
    forecast_hours: int | None = None,
) -> xr.Dataset:
    if not wrf_files:
        raise ValueError("at least one WRF output file is required")
    with xr.open_dataset(grid_path) as grid:
        lon_rho = np.asarray(grid["lon_rho"].values)
        lat_rho = np.asarray(grid["lat_rho"].values)

    fields: dict[str, list[np.ndarray]] = {
        name: [] for name in ("uwnd", "vwnd", "tair", "rhum", "prate", "radlw_in", "radsw", "sst")
    }
    times: list[np.datetime64] = []
    previous_rain: np.ndarray | None = None
    previous_time: np.datetime64 | None = None

    for path in sorted(wrf_files):
        with xr.open_dataset(path) as wrf:
            missing = [name for name in REQUIRED_WRF_VARIABLES if name not in wrf]
            if missing:
                raise ValueError(f"{path} is not WRF output; missing {', '.join(missing)}")
            source_lat = _surface(wrf["XLAT"])
            source_lon = _surface(wrf["XLONG"])
            if "Times" in wrf:
                valid_time = np.datetime64(_wrf_timestamp(wrf["Times"].values))
            elif "XTIME" in wrf and "START_DATE" in wrf.attrs:
                valid_time = np.datetime64(wrf.attrs["START_DATE"].replace("_", "T")) + np.timedelta64(
                    int(round(float(np.asarray(wrf["XTIME"].values).ravel()[0]))), "m"
                )
            else:
                raise ValueError(f"{path} has no resolvable WRF valid time")

            t2 = _surface(wrf["T2"])
            q2 = _surface(wrf["Q2"])
            psfc = _surface(wrf["PSFC"])
            if "SST" in wrf:
                sst_k = _surface(wrf["SST"])
            elif "TSK" in wrf:
                sst_k = _surface(wrf["TSK"])
            else:
                sst_k = t2

            cumulative_rain = sum(
                (_surface(wrf[name]) for name in ("RAINC", "RAINNC") if name in wrf),
                np.zeros_like(t2),
            )
            if previous_rain is None or previous_time is None:
                rain_rate = np.zeros_like(cumulative_rain)
            else:
                seconds = float((valid_time - previous_time) / np.timedelta64(1, "s"))
                if seconds <= 0:
                    raise ValueError("WRF valid times must be strictly increasing")
                rain_rate = np.maximum(cumulative_rain - previous_rain, 0.0) / 1000.0 / seconds
            previous_rain = cumulative_rain
            previous_time = valid_time

            source = {
                "uwnd": _surface(wrf["U10"]),
                "vwnd": _surface(wrf["V10"]),
                "tair": t2 - 273.15,
                "rhum": np.clip(_relative_humidity_percent(t2, q2, psfc), 10.0, 100.0),
                "prate": rain_rate,
                # With incoming-longwave radiation enabled (BULK_LW), CROCO
                # uses radlw_in for the bulk flux solver.
                "radlw_in": np.maximum(_surface(wrf["GLW"]), 0.0),
                "radsw": np.minimum(np.maximum(_surface(wrf["SWDOWN"]), 0.0), 1000.0),
                "sst": sst_k - 273.15,
            }
            for name, values in source.items():
                fields[name].append(_interpolate(source_lon, source_lat, values, lon_rho, lat_rho))
            times.append(valid_time)

    if len(set(times)) != len(times):
        raise ValueError("WRF valid times contain duplicates")
    if start_time is not None or forecast_hours is not None:
        if start_time is None or forecast_hours is None:
            raise ValueError("start_time and forecast_hours must be provided together")
        expected = [start_time + np.timedelta64(hour, "h") for hour in range(forecast_hours + 1)]
        if times != expected:
            raise ValueError(
                "WRF forcing does not provide the exact requested hourly timeline: "
                f"expected {expected[0]} through {expected[-1]} ({len(expected)} timestamps), "
                f"got {times[0]} through {times[-1]} ({len(times)} timestamps)"
            )
    if len(times) > 1:
        time_step = times[1] - times[0]
    else:
        time_step = np.timedelta64(1, "h")
    padded_times = times + [times[-1] + time_step]
    origin = times[0].astype("datetime64[s]")
    bulk_time = np.array([(time - origin) / np.timedelta64(1, "D") for time in padded_times], dtype=np.float64)
    dataset = xr.Dataset(
        {name: (("bulk_time", "eta_rho", "xi_rho"), np.pad(np.stack(values), ((0, 1), (0, 0), (0, 0)), mode="edge")) for name, values in fields.items()},
        coords={
            "bulk_time": ("bulk_time", bulk_time),
            "lon_rho": (("eta_rho", "xi_rho"), lon_rho),
            "lat_rho": (("eta_rho", "xi_rho"), lat_rho),
        },
        attrs={"source": "PredSea WRF", "forcing_type": "real_atmospheric_surface_forcing"},
    )
    dataset["bulk_time"].attrs.update(
        units=f"days since {np.datetime_as_string(origin, unit='s').replace('T', ' ')}",
        calendar="gregorian",
    )
    dataset["tair"].attrs["units"] = "Celsius"
    dataset["sst"].attrs["units"] = "Celsius"
    dataset["rhum"].attrs["units"] = "percent"
    dataset["prate"].attrs["units"] = "m s-1"
    dataset["uwnd"].attrs["units"] = dataset["vwnd"].attrs["units"] = "m s-1"
    dataset["radlw_in"].attrs["units"] = dataset["radsw"].attrs["units"] = "W m-2"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_netcdf(output_path, encoding={name: {"zlib": True, "complevel": 1} for name in fields})

    # Generate croco_frc.nc containing SST, sst, and sst_time for QCORRECTION
    frc_dataset = dataset[["sst"]].copy()
    frc_dataset = frc_dataset.rename({"bulk_time": "sst_time"})
    frc_dataset["sst_time"].attrs.update(dataset["bulk_time"].attrs)

    # Provide both uppercase SST (required by CROCO get_sst.F) and lowercase sst
    frc_dataset["SST"] = frc_dataset["sst"].copy()
    frc_dataset["SST"].attrs.update({
        "long_name": "sea surface temperature",
        "units": "Celsius",
    })
    frc_dataset["sst"].attrs.update({
        "long_name": "sea surface temperature",
        "units": "Celsius",
    })

    # Define dQdSST matching SST shape, filled with constant -40.0 W/m2/K (SOCIB operational standard)
    dqdsst_data = np.full_like(frc_dataset["sst"].values, -40.0, dtype=np.float32)
    frc_dataset["dQdSST"] = (("sst_time", "eta_rho", "xi_rho"), dqdsst_data)
    frc_dataset["dQdSST"].attrs.update({
        "long_name": "surface heat flux sensitivity to SST",
        "units": "Watts meter-2 Kelvin-1",
    })

    frc_path = output_path.parent / "croco_frc.nc"
    frc_dataset.to_netcdf(
        frc_path,
        encoding={
            "SST": {"zlib": True, "complevel": 1},
            "sst": {"zlib": True, "complevel": 1},
            "dQdSST": {"zlib": True, "complevel": 1},
        },
    )
    return dataset


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wrf", type=Path, nargs="+", required=True)
    parser.add_argument("--grid", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-time", required=True)
    parser.add_argument("--forecast-hours", type=int, required=True)
    args = parser.parse_args()
    if args.forecast_hours <= 0 or args.forecast_hours > 120:
        parser.error("--forecast-hours must be between 1 and 120")
    dataset = build_bulk_forcing(
        args.wrf,
        args.grid,
        args.output,
        start_time=np.datetime64(args.start_time),
        forecast_hours=args.forecast_hours,
    )
    print(f"CROCO bulk forcing created: {args.output} ({dataset.sizes['bulk_time']} timestamps)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
