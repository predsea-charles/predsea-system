#!/usr/bin/env python3
"""Prepare a reproducible nonstationary SWAN run from real staging inputs."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np
import xarray as xr

try:
    from scripts.validate_marine_region import validate_region
except ModuleNotFoundError:  # Direct execution from the scripts directory.
    from validate_marine_region import validate_region


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _swan_time(value: np.datetime64) -> str:
    timestamp = value.astype("datetime64[s]").astype(dt.datetime)
    return timestamp.strftime("%Y%m%d.%H%M%S")


def _write_grid(path: Path, values: np.ndarray) -> None:
    """Write a lower-left-origin SWAN free-format grid (idla=3)."""
    with path.open("w") as stream:
        for row in values:
            np.savetxt(stream, row[np.newaxis, :], fmt="%.6g")


def _circular_mean_degrees(values: np.ndarray) -> float:
    radians = np.deg2rad(values[np.isfinite(values)])
    if not radians.size:
        raise ValueError("wave direction boundary contains no finite values")
    angle = np.rad2deg(np.arctan2(np.sin(radians).mean(), np.cos(radians).mean()))
    return float(angle % 360.0)


def _computational_timestep_minutes(region: dict) -> int:
    minutes = int(
        region["models"]["swan"].get("computational_timestep_minutes", 5)
    )
    output_interval_minutes = int(region["output_interval_hours"]) * 60
    if minutes <= 0 or output_interval_minutes % minutes != 0:
        raise ValueError(
            "SWAN computational_timestep_minutes must be positive and divide "
            "the configured output interval exactly"
        )
    return minutes


def _side_series(dataset: xr.Dataset, side: str) -> tuple[np.ndarray, ...]:
    """Extract a boundary time series for one edge of the domain.

    A region's rectangular bbox is not guaranteed to end exactly on open
    water -- coastal/bay-shaped regions (e.g. Gulf of Lion) can have an edge
    that sits entirely on land at a given resolution, and this only gets more
    likely as resolution increases and bboxes are drawn tighter to a coast.
    The CMEMS wave product is masked (NaN) over land, so the literal edge row
    or column can be all-NaN even though the region overall is a real,
    correctly-configured marine domain. Rather than treating that as fatal,
    walk inward from the true edge until an open-water row/column is found,
    and use that as the boundary condition -- the nearest real ocean data is
    the physically sound substitute for a boundary that would otherwise have
    no water at all.
    """
    if side == "north":
        dim, start_index, step = "latitude", dataset.sizes["latitude"] - 1, -1
    elif side == "south":
        dim, start_index, step = "latitude", 0, 1
    elif side == "east":
        dim, start_index, step = "longitude", dataset.sizes["longitude"] - 1, -1
    elif side == "west":
        dim, start_index, step = "longitude", 0, 1
    else:
        raise ValueError(side)

    dim_size = dataset.sizes[dim]
    edge = None
    used_index = None
    for offset in range(dim_size):
        candidate_index = start_index + step * offset
        if candidate_index < 0 or candidate_index >= dim_size:
            break
        candidate = dataset.isel({dim: candidate_index})
        has_any_finite = bool(
            (
                np.isfinite(candidate["VHM0"].values)
                & np.isfinite(candidate["VTPK"].values)
                & np.isfinite(candidate["VMDR"].values)
            ).any()
        )
        if has_any_finite:
            edge = candidate
            used_index = candidate_index
            break

    if edge is None:
        raise ValueError(
            f"{side} wave boundary has no finite values anywhere along the "
            f"{dim} axis (checked all {dim_size} rows/columns) -- this "
            "region's domain does not reach open water on this side at all"
        )
    if used_index != start_index:
        offset = abs(used_index - start_index)
        # A small inward walk (a handful of cells) is a reasonable substitute
        # for a boundary that grazes the coast. A large one means most of this
        # side of the bbox sits on land -- that's a sign the region's bounding
        # box is drawn wrong for this side, not something to silently patch
        # over with an unrepresentative, deep-inland "boundary" value.
        if offset > 0.3 * dim_size:
            raise ValueError(
                f"{side} wave boundary: the true edge {dim} index ({start_index}) "
                f"is land/masked, and the nearest open water is {offset} cells "
                f"inward ({offset / dim_size:.0%} of the {dim_size}-cell {dim} "
                "span). That's too deep inland to stand in for this side's "
                "boundary condition -- redraw this region's bbox so this side "
                "actually reaches open water, rather than defaulting to a "
                "value from deep inside the domain."
            )
        print(
            f"⚠️ {side} wave boundary: the true edge {dim} index ({start_index}) "
            f"is entirely land/masked; substituting the nearest open-water "
            f"{dim} index {used_index} ({offset} cells "
            "inward) for this side's boundary condition."
        )

    heights: list[float] = []
    periods: list[float] = []
    directions: list[float] = []
    for index in range(edge.sizes["time"]):
        sample = edge.isel(time=index)
        hs = np.asarray(sample["VHM0"].values)
        tp = np.asarray(sample["VTPK"].values)
        wave_dir = np.asarray(sample["VMDR"].values)
        finite = np.isfinite(hs) & np.isfinite(tp) & np.isfinite(wave_dir)
        if not finite.any():
            raise ValueError(
                f"{side} wave boundary has no finite values at time index {index} "
                f"even after substituting the nearest open-water {dim} index {used_index}"
            )
        heights.append(float(np.nanmedian(hs[finite])))
        periods.append(float(np.nanmedian(tp[finite])))
        directions.append(_circular_mean_degrees(wave_dir[finite]))
    return np.asarray(heights), np.asarray(periods), np.asarray(directions)


def _write_tpar(
    path: Path,
    times: np.ndarray,
    height: np.ndarray,
    period: np.ndarray,
    direction: np.ndarray,
) -> None:
    with path.open("w") as stream:
        stream.write("TPAR\n")
        for time, hs, tp, wave_dir in zip(times, height, period, direction):
            # Last value is directional spreading in degrees.
            stream.write(
                f"{_swan_time(time)} {max(hs, 0.01):.3f} "
                f"{max(tp, 1.0):.3f} {wave_dir:.2f} 25.0\n"
            )


def _open_wind(
    grib_path: Path,
    start: np.datetime64,
    end: np.datetime64,
    bbox: dict,
) -> tuple[xr.DataArray, xr.DataArray]:
    common = {"engine": "cfgrib", "backend_kwargs": {"indexpath": ""}}
    u_dataset = xr.open_dataset(
        grib_path,
        backend_kwargs={"filter_by_keys": {"shortName": "10u"}, "indexpath": ""},
        engine="cfgrib",
    )
    v_dataset = xr.open_dataset(
        grib_path,
        backend_kwargs={"filter_by_keys": {"shortName": "10v"}, "indexpath": ""},
        engine="cfgrib",
    )
    try:
        u = u_dataset["u10"].sel(
            step=(u_dataset.valid_time >= start) & (u_dataset.valid_time <= end),
            latitude=slice(bbox["latitude_max"], bbox["latitude_min"]),
            longitude=slice(bbox["longitude_min"], bbox["longitude_max"]),
        )
        v = v_dataset["v10"].sel(
            step=(v_dataset.valid_time >= start) & (v_dataset.valid_time <= end),
            latitude=slice(bbox["latitude_max"], bbox["latitude_min"]),
            longitude=slice(bbox["longitude_min"], bbox["longitude_max"]),
        )
        u = u.assign_coords(time=("step", u.valid_time.values)).swap_dims(
            {"step": "time"}
        )
        v = v.assign_coords(time=("step", v.valid_time.values)).swap_dims(
            {"step": "time"}
        )
        u = u.sortby("latitude").load()
        v = v.sortby("latitude").load()
    finally:
        u_dataset.close()
        v_dataset.close()
    if u.sizes.get("time", 0) < 2 or not np.array_equal(u.time, v.time):
        raise ValueError("ECMWF wind does not provide an aligned multi-time U/V sequence")
    if u.time.values[0] != start or u.time.values[-1] != end:
        raise ValueError(
            f"ECMWF wind coverage {u.time.values[0]}..{u.time.values[-1]} "
            f"does not match {start}..{end}"
        )
    hourly_times = np.arange(
        start, end + np.timedelta64(1, "h"), np.timedelta64(1, "h")
    )
    u = _linear_time_interpolate(u, hourly_times)
    v = _linear_time_interpolate(v, hourly_times)
    if not np.isfinite(u.values).all() or not np.isfinite(v.values).all():
        raise ValueError("Hourly ECMWF wind interpolation produced non-finite values")
    return u, v


def _linear_time_interpolate(
    values: xr.DataArray, target_times: np.ndarray
) -> xr.DataArray:
    """Linearly interpolate time without xarray's optional SciPy dependency."""
    source_ns = values.time.values.astype("datetime64[ns]").astype(np.int64)
    target_ns = target_times.astype("datetime64[ns]").astype(np.int64)
    frames: list[xr.DataArray] = []
    for target in target_ns:
        right = int(np.searchsorted(source_ns, target, side="left"))
        if right < source_ns.size and source_ns[right] == target:
            frame = values.isel(time=right, drop=True)
        else:
            left = right - 1
            if left < 0 or right >= source_ns.size:
                raise ValueError("Hourly wind target lies outside ECMWF coverage")
            weight = (target - source_ns[left]) / (source_ns[right] - source_ns[left])
            frame = values.isel(time=left, drop=True) * (1.0 - weight) + values.isel(
                time=right, drop=True
            ) * weight
        frames.append(frame)
    return xr.concat(frames, dim=xr.IndexVariable("time", target_times))


def prepare(
    region_path: Path,
    bathymetry_path: Path,
    wind_grib_path: Path,
    boundary_path: Path,
    output_dir: Path,
    start: np.datetime64,
    forecast_hours: int,
) -> dict:
    region_validation = validate_region(region_path)
    if region_validation["status"] != "succeeded":
        raise ValueError(
            "Marine region profile failed preflight: "
            + "; ".join(region_validation["errors"])
        )
    region = json.loads(region_path.read_text())
    bbox = region["bbox"]
    compute_timestep_minutes = _computational_timestep_minutes(region)
    end = start + np.timedelta64(forecast_hours, "h")
    output_dir.mkdir(parents=True, exist_ok=True)

    with xr.open_dataset(bathymetry_path) as bathy_dataset:
        # Slice bathymetry to region's bbox to support multi-region scaling and prevent memory exhaustion
        sliced_bathy = bathy_dataset.sel(
            longitude=slice(bbox["longitude_min"], bbox["longitude_max"]),
            latitude=slice(bbox["latitude_min"], bbox["latitude_max"])
        )
        depth = sliced_bathy["depth"].transpose("latitude", "longitude").load()
        longitude = np.asarray(sliced_bathy["longitude"].values)
        latitude = np.asarray(sliced_bathy["latitude"].values)
    if not np.all(np.diff(longitude) > 0) or not np.all(np.diff(latitude) > 0):
        raise ValueError("bathymetry coordinates must increase west-east and south-north")
    bottom = np.asarray(depth.values, dtype=np.float64)
    bottom[bottom <= 0.0] = -999.0
    _write_grid(output_dir / "bottom.bot", bottom)

    u, v = _open_wind(wind_grib_path, start, end, bbox)
    wind_path = output_dir / "wind.dat"
    with wind_path.open("w") as stream:
        for index in range(u.sizes["time"]):
            for component in (u.isel(time=index).values, v.isel(time=index).values):
                for row in component:
                    np.savetxt(stream, row[np.newaxis, :], fmt="%.5f")

    with xr.open_dataset(boundary_path) as boundary_dataset:
        boundary = boundary_dataset.sel(time=slice(start, end)).sortby("time").load()
    expected_boundary_times = np.arange(
        start, end + np.timedelta64(1, "h"), np.timedelta64(1, "h")
    )
    if not np.array_equal(boundary.time.values.astype("datetime64[h]"), expected_boundary_times):
        raise ValueError("CMEMS boundary does not provide the exact hourly forecast window")
    side_codes = {"north": "N", "south": "S", "east": "E", "west": "W"}
    for side in side_codes:
        hs, tp, direction = _side_series(boundary, side)
        _write_tpar(
            output_dir / f"{side}.tpar",
            boundary.time.values,
            hs,
            tp,
            direction,
        )

    nx = longitude.size
    ny = latitude.size
    mx = nx - 1
    my = ny - 1
    dx = float(np.diff(longitude).mean())
    dy = float(np.diff(latitude).mean())
    wind_lon = np.asarray(u.longitude.values)
    wind_lat = np.asarray(u.latitude.values)
    wind_dx = float(np.diff(wind_lon).mean())
    wind_dy = float(np.diff(wind_lat).mean())
    wind_interval_hours = int(
        (u.time.values[1] - u.time.values[0]) / np.timedelta64(1, "h")
    )
    start_text = _swan_time(start)
    end_text = _swan_time(end)

    project_code = region["region_id"][:4].title()
    commands = [
        f"PROJECT 'PredSea' '{project_code}'",
        "MODE NONSTATIONARY TWODIMENSIONAL",
        "SET NAUTICAL",
        "COORDINATES SPHERICAL CCM",
        (
            f"CGRID REGULAR {longitude[0]:.6f} {latitude[0]:.6f} 0.0 "
            f"{longitude[-1]-longitude[0]:.6f} {latitude[-1]-latitude[0]:.6f} "
            f"{mx} {my} CIRCLE 36 0.04 1.0 32"
        ),
        (
            f"INPGRID BOTTOM REGULAR {longitude[0]:.6f} {latitude[0]:.6f} 0.0 "
            f"{mx} {my} {dx:.8f} {dy:.8f} EXCEPTION -999.0"
        ),
        "READINP BOTTOM 1.0 'bottom.bot' 3 0 FREE",
        (
            f"INPGRID WIND REGULAR {wind_lon[0]:.6f} {wind_lat[0]:.6f} 0.0 "
            f"{wind_lon.size-1} {wind_lat.size-1} {wind_dx:.8f} {wind_dy:.8f} "
            f"NONSTATIONARY {start_text} {wind_interval_hours} HR {end_text}"
        ),
        "READINP WIND 1.0 'wind.dat' 3 0 0 0 FREE",
        "BOUND SHAPESPEC JONSWAP 3.3 PEAK DSPR DEGREES",
    ]
    for side, code in side_codes.items():
        commands.append(
            f"BOUNDSPEC SIDE {code} CCW CONSTANT FILE '{side}.tpar' 1"
        )
    commands.extend(
        [
            # WESTHUYSEN (previous default) is more iteration-heavy per
            # timestep than KOMEN, and on the basin-wide domain (~2.3M grid
            # points, union of all 5 regions) that cost became severe: a 6h
            # forecast at 64 MPI ranks was still stuck on the very first
            # hourly output block after 7h44m of continuous full-CPU
            # computation (implying ~40min+ per 5min internal timestep).
            # KOMEN was already flagged as worth testing for narrow/sheltered
            # regions (see the SWAN paper review); trying it here first since
            # it's a one-line change, before considering shrinking the
            # basin-wide domain itself.
            "GEN3 KOMEN",
            "BREAKING CONSTANT 1.0 0.73",
            "FRICTION JONSWAP 0.038",
            "TRIAD",
            # Default propagation scheme (S&L) loses accuracy/stability across
            # sharp bathymetric or coastline transitions that can't be avoided
            # -- narrow straits (Alboran/Gibraltar), bay-shaped shelves (Gulf
            # of Lion), narrow coastal shelves (Algerian). SWAN's own manual
            # recommends the more diffusive, more robust first-order upwind
            # BSBT scheme for exactly this case:
            # https://swanmodel.sourceforge.io/online_doc/swanuse/node29.html
            "PROP BSBT",
            (
                f"FRAME 'OUTPUT' {longitude[0]:.6f} {latitude[0]:.6f} 0.0 "
                f"{longitude[-1]-longitude[0]:.6f} {latitude[-1]-latitude[0]:.6f} "
                f"{mx} {my}"
            ),
            (
                # SWAN's MPI NetCDF collector is not reliable for this regular
                # grid. Parallel VTK is explicitly designed to remain sharded;
                # the publication stage converts it to the canonical NetCDF.
                "BLOCK 'OUTPUT' NOHEADER 'swan_output.vts' "
                f"HSIGN TPS DIR WIND DEPTH OUTPUT {start_text} 1 HR"
            ),
            (
                f"COMPUTE NONSTATIONARY {start_text} "
                f"{compute_timestep_minutes} MIN {end_text}"
            ),
            "STOP",
        ]
    )
    command_path = output_dir / f"predsea_{region['region_id']}.swn"
    command_path.write_text("\n".join(commands) + "\n")

    inputs = {
        path.name: {"size_bytes": path.stat().st_size, "sha256": _sha256(path)}
        for path in (
            region_path,
            bathymetry_path,
            wind_grib_path,
            boundary_path,
            output_dir / "bottom.bot",
            wind_path,
            command_path,
        )
    }
    manifest = {
        "schema_version": "predsea.swan_run_input.v1",
        "region_id": region["region_id"],
        "start_time": str(start),
        "end_time": str(end),
        "forecast_hours": forecast_hours,
        "computational_timestep_minutes": compute_timestep_minutes,
        "grid": {"nx": nx, "ny": ny, "dx_degrees": dx, "dy_degrees": dy},
        "wind": {
            "source": "ECMWF",
            "timestamps": int(u.sizes["time"]),
            "interval_hours": wind_interval_hours,
        },
        "open_boundary": {
            "source": "Copernicus Marine",
            "formulation": "hourly parametric JONSWAP from VHM0/VTPK/VMDR",
            "timestamps": int(boundary.sizes["time"]),
        },
        "native_output": {
            "format": "parallel_vtk",
            "publication_format": "netcdf",
            "reason": "avoid SWAN MPI NetCDF shard collection failure",
        },
        "inputs": inputs,
    }
    (output_dir / "input_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", type=Path, required=True)
    parser.add_argument("--bathymetry", type=Path, required=True)
    parser.add_argument("--wind-grib", type=Path, required=True)
    parser.add_argument("--wave-boundary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-time", required=True)
    parser.add_argument("--forecast-hours", type=int, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    start = np.datetime64(args.start_time, "s")
    manifest = prepare(
        args.region,
        args.bathymetry,
        args.wind_grib,
        args.wave_boundary,
        args.output_dir,
        start,
        args.forecast_hours,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
