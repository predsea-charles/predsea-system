#!/usr/bin/env python3
"""
PredSea Marine Simulation Runner.
Orchestrates raw forcing download from GCS, pre-processing (SWAN preparation, CROCO forcing),
executes parallel simulations via MPI/OpenMP, converts outputs to NetCDF,
runs physical validations, and uploads results back to GCS.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import xarray as xr

CROCO_MPI_RANKS = {
    "western_mediterranean_1km": 192,
}

try:
    from scripts.fetch_swan_wind import fetch_wind, validate_wind
    from scripts.grid_validation import validate_grid_matches_region
except ModuleNotFoundError:  # Direct execution from the scripts directory.
    from fetch_swan_wind import fetch_wind, validate_wind
    from grid_validation import validate_grid_matches_region


def log_step(name: str):
    print("\n" + "=" * 60)
    print(f"🌊 [RUNNER] {name}")
    print("=" * 60)


def resolve_swan_tools(
    install_dir: Path = Path("/usr/local/bin"),
) -> tuple[str | None, str | None]:
    """Resolve the native SWAN tools even when Batch supplies a minimal PATH."""
    current_path = os.environ.get("PATH", "")
    entries = current_path.split(os.pathsep) if current_path else []
    if str(install_dir) not in entries:
        os.environ["PATH"] = os.pathsep.join([str(install_dir), *entries])
    return shutil.which("swan.exe"), shutil.which("swanrun")


def run_subprocess(
    cmd: list[str], cwd: Path | None = None, log_path: Path | None = None
) -> int:
    print(f"Running: {' '.join(cmd)}")
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=str(cwd) if cwd else None
    )
    log_file = None
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = log_path.open("w", encoding="utf-8")
    try:
        if process.stdout:
            for line in process.stdout:
                print(line, end="", flush=True)
                if log_file is not None:
                    log_file.write(line)
                    log_file.flush()
    finally:
        if log_file is not None:
            log_file.close()
    return process.wait()


def run_checked(
    cmd: list[str], *, stage: str, cwd: Path | None = None,
    log_path: Path | None = None,
) -> None:
    return_code = run_subprocess(cmd, cwd=cwd, log_path=log_path)
    if return_code != 0:
        raise RuntimeError(f"{stage} failed with exit code {return_code}")


def storage_backend() -> str:
    return os.environ.get("PREDSEA_STORAGE_BACKEND", "gcs").strip().lower()


def cloud_uri(bucket: str, key: str = "") -> str:
    scheme = "s3" if storage_backend() == "s3" else "gs"
    return f"{scheme}://{bucket}/{key.lstrip('/')}"


def cloud_copy(source: str, destination: str, *, recursive: bool = False) -> list[str]:
    if storage_backend() == "s3":
        command = ["aws", "s3", "cp", source, destination, "--only-show-errors"]
        if recursive:
            command.append("--recursive")
        return command
    command = ["gsutil", "-m", "cp"]
    if recursive:
        command.append("-r")
    return [*command, source, destination]


def cloud_sync(source: str, destination: str) -> list[str]:
    if storage_backend() == "s3":
        return ["aws", "s3", "sync", source, destination, "--only-show-errors"]
    return ["gsutil", "-m", "rsync", "-r", source, destination]


def upload_croco_failure_diagnostics(
    *, outputs_dir: Path, region_id: str, run_date: str, run_id: str,
    gcs_bucket: str, error: Exception,
) -> int:
    """Persist a failed CROCO run without turning upload failure into success."""
    failure_dir = outputs_dir / f"croco_{region_id}"
    failure_dir.mkdir(parents=True, exist_ok=True)
    (failure_dir / "FAILURE.txt").write_text(
        f"status=FAILED\nstage=croco\nerror={type(error).__name__}: {error}\n"
        f"timestamp={dt.datetime.now(dt.timezone.utc).isoformat()}\n",
        encoding="utf-8",
    )
    diagnostic_target = cloud_uri(
        gcs_bucket,
        f"predictions/{run_date}/runs/{run_id}/"
        f"{region_id}/failure-diagnostics/"
    )
    return run_subprocess(cloud_copy(str(failure_dir), diagnostic_target, recursive=True))


def croco_mpi_command(mpi_ranks: int, executable: Path, namelist: Path) -> list[str]:
    """Execute serial binary directly when mpi_ranks <= 1, else invoke mpirun."""
    if mpi_ranks <= 1:
        return [str(executable), str(namelist)]
    return [
        "mpirun",
        "--allow-run-as-root",
        "--use-hwthread-cpus",
        "-np",
        str(mpi_ranks),
        str(executable),
        str(namelist),
    ]


def validate_croco_mpi_ranks(region_id: str, mpi_ranks: int) -> None:
    """Require the rank count compiled into the selected regional binary."""
    expected_mpi_ranks = CROCO_MPI_RANKS.get(region_id)
    if expected_mpi_ranks is None:
        raise ValueError(
            f"unsupported CROCO region_id: {region_id}; expected one of "
            + ", ".join(sorted(CROCO_MPI_RANKS))
        )
    if mpi_ranks != expected_mpi_ranks:
        raise ValueError(
            f"CROCO mpi_ranks mismatch for {region_id}: got {mpi_ranks}, "
            f"compiled decomposition requires {expected_mpi_ranks}"
        )


def require_wrf_forcing(
    wrf_dir: Path, *, domain: str, forecast_hours: int
) -> list[Path]:
    """Return the required real hourly WRF files, rejecting placeholders."""
    wrf_files = sorted(wrf_dir.rglob(f"wrfout_{domain}_*"))
    required_count = forecast_hours + 1
    if len(wrf_files) < required_count:
        raise RuntimeError(
            f"WRF forcing is incomplete for {domain}: expected at least "
            f"{required_count} hourly files, found {len(wrf_files)}"
        )
    selected = wrf_files[:required_count]
    empty = [path.name for path in selected if path.stat().st_size == 0]
    if empty:
        raise RuntimeError(
            "WRF forcing contains empty placeholder files: " + ", ".join(empty)
        )
    return selected


def require_one(directory: Path, patterns: tuple[str, ...], label: str) -> Path:
    """Resolve one explicit input product and reject ambiguous discovery."""
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(directory.glob(pattern))
    unique = sorted({path.resolve() for path in matches if path.is_file()})
    if not unique:
        raise FileNotFoundError(
            f"Missing {label} in {directory}; expected one of: {', '.join(patterns)}"
        )
    if len(unique) != 1:
        rendered = ", ".join(path.name for path in unique)
        raise RuntimeError(f"Ambiguous {label} in {directory}: {rendered}")
    return unique[0]


def resolve_project_file(container_path: Path, local_path: Path) -> Path:
    if container_path.exists():
        return container_path
    if local_path.exists():
        return local_path
    raise FileNotFoundError(f"Required project file is missing: {container_path}")


def resolve_swan_bathymetry(project_root: Path, region_id: str) -> Path:
    # Historical note: balearic_1km used to fall back to a mislabeled
    # "balearic_bathymetry_swan.nc" file (missing "_1km", and covering the
    # whole western Med basin rather than balearic's own bbox) because a
    # correctly-named, region-scoped file was never generated. Fixed
    # 2026-08-03 -- balearic_1km now has its own properly-generated
    # assets/static_grids/balearic_1km_bathymetry_swan.nc like every other
    # region, so this function no longer needs a special case.
    path = project_root / "simulation" / "inputs" / f"{region_id}_bathymetry_swan.nc"
    if path.exists():
        return path
    raise FileNotFoundError(
        f"No versioned SWAN bathymetry is installed for {region_id}; "
        "generate and validate the regional grid before submitting compute"
    )


import tempfile

def stage_cmems_forcing(staged_cmems: Path, croco_work: Path, forecast_hours: int) -> Path:
    """Copy a pre-staged CMEMS file only when it is complete 3-D forcing that
    actually covers the requested forecast horizon."""
    if not staged_cmems.is_file():
        raise FileNotFoundError(f"Pre-staged CMEMS forcing is missing: {staged_cmems}")
    source_size = staged_cmems.stat().st_size
    if source_size == 0:
        raise ValueError(f"Pre-staged CMEMS forcing is empty: {staged_cmems}")

    with xr.open_dataset(staged_cmems) as dataset:
        required_variables = {"uo", "vo", "thetao", "so", "zos"}
        missing_variables = required_variables - set(dataset.variables)
        if missing_variables:
            raise ValueError(
                "Pre-staged CMEMS forcing is incomplete; missing variables: "
                f"{', '.join(sorted(missing_variables))}"
            )
        required_dimensions = {"time", "depth", "latitude", "longitude"}
        missing_dimensions = required_dimensions - set(dataset.sizes)
        if missing_dimensions:
            raise ValueError(
                "Pre-staged CMEMS forcing is not three-dimensional; "
                f"missing dimensions: {', '.join(sorted(missing_dimensions))}"
            )
        if any(int(dataset.sizes[name]) <= 0 for name in required_dimensions):
            raise ValueError("Pre-staged CMEMS forcing contains empty dimensions")
        expected_timestamps = forecast_hours + 1
        actual_timestamps = int(dataset.sizes["time"])
        if actual_timestamps < expected_timestamps:
            raise ValueError(
                "Pre-staged CMEMS forcing does not cover the requested forecast "
                f"horizon: needs {expected_timestamps} hourly timestamps for "
                f"{forecast_hours}h, found only {actual_timestamps} — likely a "
                "cache left over from a shorter-horizon run"
            )

    destination = croco_work / "cmems_ocean_forcing.nc"
    shutil.copy2(staged_cmems, destination)
    if not destination.is_file() or destination.stat().st_size != source_size:
        raise OSError(
            "Pre-staged CMEMS forcing copy failed integrity check: "
            f"source={staged_cmems}, destination={destination}"
        )
    return destination


def croco_ocean_source(region_id: str, configured: str | None = None) -> str:
    """Select the ocean-state provider without making CMEMS a CROCO invariant."""
    value = (configured or os.environ.get("PREDSEA_CROCO_OCEAN_SOURCE") or
             ("staged" if region_id == "alboran_1km" else "cmems"))
    value = value.strip().lower()
    if value not in {"staged", "cmems"}:
        raise ValueError("CROCO ocean source must be 'staged' or 'cmems'")
    return value


def stage_croco_ocean_inputs(inputs_dir: Path, croco_work: Path,
                             region_id: str) -> tuple[Path, ...]:
    """Stage the files required by the current REGIONAL/FRC_BRY compile."""
    required = ("croco_ini.nc", "croco_bry.nc", "croco_clm.nc")
    search_dirs = (inputs_dir / "croco" / region_id, inputs_dir / region_id, inputs_dir)
    staged: list[Path] = []
    for name in required:
        matches = [directory / name for directory in search_dirs
                   if (directory / name).is_file()]
        if not matches:
            raise FileNotFoundError(
                f"Missing staged CROCO input {name} for {region_id}; searched: "
                + ", ".join(str(directory) for directory in search_dirs)
            )
        source = matches[0]
        if source.stat().st_size == 0:
            raise ValueError(f"Staged CROCO input is empty: {source}")
        destination = croco_work / name
        shutil.copy2(source, destination)
        staged.append(destination)
    return tuple(staged)


def run_croco_simulation(*, project_root: Path, inputs_dir: Path, outputs_dir: Path,
                         region_id: str, run_date: str, run_id: str,
                         forecast_hours: int, mpi_ranks: int, gcs_bucket: str,
                         ocean_source: str | None = None) -> None:
    """Run the unified CROCO path from explicit real inputs."""
    total_started = time.monotonic()

    validate_croco_mpi_ranks(region_id, mpi_ranks)

    grid_uri = os.environ.get("PREDSEA_CROCO_GRID_S3_URI") or os.environ.get("PREDSEA_CROCO_GRID_GCS_URI")
    expected_scheme_prefix = "s3" if storage_backend() == "s3" else "gs"
    wrf_uri = f"{expected_scheme_prefix}://{gcs_bucket}/predictions/{run_date}/runs/{run_id}/wrf/"

    expected_scheme = "s3://" if storage_backend() == "s3" else "gs://"
    if not grid_uri or not grid_uri.startswith(expected_scheme):
        raise ValueError(f"CROCO grid URI must identify an immutable {expected_scheme} object")
    if not wrf_uri or not wrf_uri.startswith(expected_scheme):
        raise ValueError(f"WRF URI must identify immutable {expected_scheme} output")

    region_profile = project_root / "simulation" / "marine" / "regions" / f"{region_id}.json"
    template = project_root / "simulation" / "marine" / "croco" / "croco.in.balearic"
    croco_exe = Path(f"/usr/local/bin/croco_{region_id}")
    croco_bin_env = os.environ.get("PREDSEA_CROCO_BINARY")
    if croco_bin_env and Path(croco_bin_env) != croco_exe:
        raise ValueError(
            "PREDSEA_CROCO_BINARY must match the binary compiled for this region: "
            f"region_id={region_id}, expected={croco_exe}, configured={croco_bin_env}"
        )

    for required in (region_profile, template, croco_exe):
        if not required.is_file():
            raise FileNotFoundError(
                f"required CROCO runtime asset is missing for region_id={region_id}: "
                f"{required}"
            )

    with open(region_profile, "r", encoding="utf-8") as f:
        region_data = json.load(f)
    croco_spec = region_data.get("models", {}).get("croco", {})
    compiled_shape = croco_spec.get("compiled_grid_shape")
    if not isinstance(compiled_shape, dict):
        raise ValueError(
            f"missing models.croco.compiled_grid_shape for region_id={region_id}"
        )
    try:
        expected_shape = (
            int(compiled_shape["xi_rho"]),
            int(compiled_shape["eta_rho"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"invalid models.croco.compiled_grid_shape for region_id={region_id}: "
            f"{compiled_shape!r}"
        ) from exc

    # Aggressively clean working directories to ensure retries start with a 100% pristine workspace
    croco_work = outputs_dir / f"croco_{region_id}"
    if croco_work.exists():
        log_step(f"0. Cleaning existing CROCO working directory for retry: {croco_work}")
        shutil.rmtree(croco_work, ignore_errors=True)
    croco_work.mkdir(parents=True, exist_ok=True)

    wrf_dir = inputs_dir / "wrf"
    if wrf_dir.exists():
        shutil.rmtree(wrf_dir, ignore_errors=True)
    wrf_dir.mkdir(parents=True, exist_ok=True)

    for tmp_pattern in ("*.interpolated.float32", "croco_*", "cmems_*"):
        for tmp_file in Path(tempfile.gettempdir()).glob(tmp_pattern):
            try:
                if tmp_file.is_file() or tmp_file.is_symlink():
                    tmp_file.unlink()
                elif tmp_file.is_dir():
                    shutil.rmtree(tmp_file, ignore_errors=True)
            except OSError:
                pass

    grid_path = croco_work / "croco_grid.nc"
    wrf_dir = inputs_dir / "wrf"
    wrf_dir.mkdir(parents=True, exist_ok=True)
    run_checked(cloud_copy(grid_uri, str(grid_path)), stage="CROCO grid download")
    validate_grid_matches_region(str(grid_path), region_id)
    with xr.open_dataset(grid_path) as grid:
        actual_shape = (int(grid.sizes["xi_rho"]), int(grid.sizes["eta_rho"]))
    if actual_shape != expected_shape:
        raise ValueError(
            "CROCO grid/binary dimension mismatch: "
            f"region_id={region_id}, binary={croco_exe}, "
            f"grid xi_rho/eta_rho={actual_shape}, "
            f"compiled contract={expected_shape}"
        )
    run_checked(cloud_copy(wrf_uri, str(wrf_dir), recursive=True), stage="WRF forcing download")

    domain = os.environ.get("PREDSEA_WRF_DOMAIN", "d02")
    wrf_files = require_wrf_forcing(
        wrf_dir, domain=domain, forecast_hours=forecast_hours
    )

    vertical_levels = int(croco_spec.get("vertical_levels", 32))

    selected_ocean_source = croco_ocean_source(region_id, ocean_source)

    if selected_ocean_source == "staged":
        inputs_uri = (os.environ.get("PREDSEA_CROCO_INPUTS_S3_URI") or
                      os.environ.get("PREDSEA_CROCO_INPUTS_GCS_URI"))
        if inputs_uri:
            if not inputs_uri.startswith(expected_scheme):
                raise ValueError(
                    f"CROCO inputs URI must use the active {expected_scheme} backend"
                )
            run_checked(
                cloud_sync(inputs_uri, str(inputs_dir / "croco" / region_id)),
                stage="staged CROCO ocean-input download",
            )
        log_step("2. Staging configured CROCO initial, boundary, and climatology files")
        stage_croco_ocean_inputs(inputs_dir, croco_work, region_id)
    else:
        log_step("2. Acquiring validated three-dimensional CMEMS ocean forcing")

    forcing_started = time.monotonic()
    if selected_ocean_source == "cmems":
        staged_cmems = inputs_dir / "cmems_ocean_forcing.nc"
        # Shared run-date caches must use region-scoped filenames.
        croco_product_stems = (
            "cmems_croco_currents_3d",
            "cmems_croco_temperature_3d",
            "cmems_croco_salinity_3d",
            "cmems_croco_sea_level",
        )
        staged_products = tuple(
            inputs_dir / f"{stem}_{region_id}.nc" for stem in croco_product_stems
        )
        use_staged_cmems = False

        if staged_cmems.exists():
            log_step(f"--> Validating pre-staged CMEMS forcing at {staged_cmems}...")
            try:
                stage_cmems_forcing(staged_cmems, croco_work, forecast_hours)
                use_staged_cmems = True
            except ValueError as exc:
                log_step(
                    "--> Rejecting structurally invalid CMEMS cache and "
                    f"reacquiring real 3-D forcing: {exc}"
                )
        elif all(path.is_file() and path.stat().st_size > 0 for path in staged_products):
            expected_timestamps = forecast_hours + 1
            with xr.open_dataset(staged_products[0]) as probe:
                actual_timestamps = int(probe.sizes.get("time", 0))
            if actual_timestamps >= expected_timestamps:
                log_step(f"--> Found validated region-scoped CMEMS product set for {region_id}; staging for interpolation...")
                for source in staged_products:
                    plain_name = source.name[: -len(f"_{region_id}.nc")] + ".nc"
                    shutil.copy2(source, croco_work / plain_name)
                use_staged_cmems = True
            else:
                log_step(
                    f"--> Region-scoped CMEMS cache for {region_id} only covers "
                    f"{actual_timestamps} timestamps (need {expected_timestamps} for "
                    f"{forecast_hours}h); reacquiring real 3-D forcing instead of "
                    "reusing a shorter-horizon cache"
                )

        if not use_staged_cmems:
            run_checked(
                [
                    "python3", "/app/scripts/fetch_native_marine_forcing.py",
                    "--run-date", run_date,
                    "--forecast-hours", str(forecast_hours),
                    "--region", str(region_profile),
                    "--output-dir", str(croco_work),
                    "--models", "croco",
                    "--overwrite",
                ],
                stage="CROCO CMEMS acquisition and validation",
            )
            for stem in croco_product_stems:
                fetched_path = croco_work / f"{stem}.nc"
                if fetched_path.is_file() and fetched_path.stat().st_size > 0:
                    region_scoped_name = f"{stem}_{region_id}.nc"
                    shutil.copy2(fetched_path, inputs_dir / region_scoped_name)
                    run_checked(
                        cloud_copy(
                            str(inputs_dir / region_scoped_name),
                            cloud_uri(gcs_bucket, f"forcing/cmems/{run_date}/{region_scoped_name}"),
                        ),
                        stage=f"validated CROCO CMEMS cache upload ({stem})",
                    )
        run_checked(
            [
                "python3", "/app/scripts/prepare_croco_forcing.py",
                "--grid", str(grid_path),
                "--forcing-dir", str(croco_work),
                "--output-dir", str(croco_work),
                "--vertical-levels", str(vertical_levels),
            ],
            stage="CROCO ocean forcing interpolation",
        )

    bulk_path = croco_work / "croco_blk.nc"
    run_checked(
        [
            "python3", "/app/scripts/prepare_croco_bulk_forcing.py",
            "--wrf", *[str(path) for path in wrf_files],
            "--grid", str(grid_path),
            "--output", str(bulk_path),
            "--start-time", f"{run_date}T00:00:00",
            "--forecast-hours", str(forecast_hours),
        ],
        stage="real WRF-to-CROCO bulk forcing conversion",
    )
    print(f"PERFORMANCE forcing_preparation_seconds={time.monotonic() - forcing_started:.3f}")

    # Ensure both croco_blk.nc and croco_frc.nc are present in croco_work and
    # mirrored to relative template directory tmp/forcing-croco-24h
    rel_forcing_dir = Path("tmp/forcing-croco-24h")
    rel_forcing_dir.mkdir(parents=True, exist_ok=True)
    for fname in ("croco_blk.nc", "croco_frc.nc"):
        src = croco_work / fname
        if src.is_file():
            dst = rel_forcing_dir / fname
            if dst.resolve() != src.resolve():
                shutil.copy2(src, dst)

    namelist = croco_work / "croco.in"
    croco_timestep_seconds = int(
        os.environ.get("PREDSEA_CROCO_TIMESTEP_SECONDS", croco_spec.get("timestep_seconds", 30))
    )
    croco_ndtfast = int(
        os.environ.get("PREDSEA_CROCO_NDTFAST", croco_spec.get("ndtfast", 30))
    )
    run_checked(
        [
            "python3", "/app/simulation/marine/croco/prepare_croco_in.py",
            "--template", str(template),
            "--output", str(namelist),
            "--work-dir", str(croco_work),
            "--start-date", run_date,
            "--forecast-hours", str(forecast_hours),
            "--timestep-seconds", str(croco_timestep_seconds),
            "--ndtfast", str(croco_ndtfast),
        ],
        stage="CROCO namelist rendering",
    )

    log_step("3. Running native CROCO ocean forecast")
    simulation_started = time.monotonic()
    os.environ["OMPI_ALLOW_RUN_AS_ROOT"] = "1"
    os.environ["OMPI_ALLOW_RUN_AS_ROOT_CONFIRM"] = "1"
    run_checked(
        croco_mpi_command(mpi_ranks, croco_exe, namelist),
        stage="parallel CROCO execution",
        cwd=croco_work,
        log_path=croco_work / "croco.stdout.log",
    )
    simulation_finished = time.monotonic()
    print(f"PERFORMANCE croco_simulation_seconds={simulation_finished - simulation_started:.3f}")
    history = croco_work / "croco_his.nc"
    if not history.is_file() or history.stat().st_size == 0:
        raise RuntimeError("CROCO returned without a non-empty croco_his.nc")
    run_checked(
        [
            "python3", "/app/scripts/validate_marine_output.py",
            "--output", str(history),
            "--model=croco",
            "--region", str(region_profile),
            "--forecast-hours", str(forecast_hours),
        ],
        stage="CROCO content validation",
    )

    log_step("4. Uploading validated native CROCO forecast")
    prefix = f"predictions/{run_date}/runs/{run_id}/{region_id}/"
    target = cloud_uri(gcs_bucket, f"{prefix}{region_id}_croco_forecast.nc")
    run_checked(cloud_copy(str(history), target), stage="canonical CROCO upload")
    marker = outputs_dir / "CROCO_SUCCESS"
    marker.write_text(
        f"status=SUCCESS\nmodel=croco\nforcing=predsea_wrf+{selected_ocean_source}\n"
        f"timestamp={dt.datetime.now(dt.timezone.utc).isoformat()}\n"
    )
    run_checked(
        cloud_copy(str(marker), cloud_uri(gcs_bucket, f"{prefix}CROCO_SUCCESS")),
        stage="CROCO success-marker upload",
    )
    print(f"PERFORMANCE total_job_seconds={time.monotonic() - total_started:.3f}")


def main():
    parser = argparse.ArgumentParser(description="Run SWAN/CROCO simulation shard.")
    parser.add_argument("--region", required=True, help="CROCO or wave-model domain ID")
    parser.add_argument("--model", choices=["swan", "croco", "both"], default="both", help="Model to run")
    parser.add_argument("--forecast-hours", type=int, default=24, help="Forecast horizon hours")
    parser.add_argument("--mpi-ranks", type=int, default=4, help="MPI rank count")
    parser.add_argument("--run-date", help="Run date (YYYY-MM-DD); overrides PREDSEA_RUN_DATE")
    parser.add_argument("--run-id", help="Run ID; overrides PREDSEA_RUN_ID")
    parser.add_argument(
        "--croco-ocean-source", choices=["staged", "cmems"],
        help=("CROCO initial/boundary provider. Defaults to staged for "
              "alboran_1km, CMEMS for legacy regional runs; environment: "
              "PREDSEA_CROCO_OCEAN_SOURCE"),
    )
    bucket_group = parser.add_mutually_exclusive_group(required=True)
    bucket_group.add_argument("--gcs-bucket", help="Output GCS bucket")
    bucket_group.add_argument("--s3-bucket", help="Output S3 bucket")
    args = parser.parse_args()

    if args.s3_bucket:
        os.environ["PREDSEA_STORAGE_BACKEND"] = "s3"
    args.gcs_bucket = args.s3_bucket or args.gcs_bucket
    if args.forecast_hours <= 0 or args.forecast_hours > 120:
        parser.error("--forecast-hours must be between 1 and 120")
    if args.mpi_ranks <= 0:
        parser.error("--mpi-ranks must be positive")
    if args.model == "both":
        parser.error(
            "combined execution is intentionally disabled; submit SWAN and CROCO "
            "as separate parallel Batch jobs"
        )
    # Determine dates and run IDs from CLI args, then environment, then fallback to today
    run_date = args.run_date or os.environ.get("PREDSEA_RUN_DATE")
    if not run_date:
        run_date = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")

    run_id = args.run_id or os.environ.get("PREDSEA_RUN_ID")
    if not run_id:
        run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H%MZ")


    log_step(f"Initializing simulation shard: region={args.region}, model={args.model}, hours={args.forecast_hours}")
    print(f"📅 Run Date: {run_date}")
    print(f"🆔 Run ID: {run_id}")
    print(f"🪣 GCS Bucket: {args.gcs_bucket}")
    print(f"🧵 MPI Ranks: {args.mpi_ranks}")

    project_root = Path("/app")
    if not (project_root / "scripts").exists():
        project_root = Path(__file__).resolve().parents[1]

    # Setup standard workspaces
    workspace_dir = Path("/workspace")
    workspace_dir.mkdir(parents=True, exist_ok=True)

    inputs_dir = workspace_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    outputs_dir = workspace_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    # 1. Sync boundary forcing down from GCS
    log_step("1. Syncing boundary forcing files from GCS")

    ecmwf_gcs_src = cloud_uri(args.gcs_bucket, f"forcing/ecmwf/{run_date}/")
    cmems_gcs_src = os.environ.get(
        "PREDSEA_CMEMS_GCS_URI",
        cloud_uri(args.gcs_bucket, f"forcing/cmems/{run_date}/"),
    )

    print(f"📥 Syncing ECMWF forcing from {ecmwf_gcs_src}...")
    ecmwf_sync_rc = run_subprocess(
        cloud_sync(ecmwf_gcs_src, str(inputs_dir))
    )
    if ecmwf_sync_rc != 0:
        print(
            "⚠️ Cached ECMWF forcing is unavailable; the runner will fetch "
            "the minimal SWAN wind product directly."
        )

    selected_croco_source = (
        croco_ocean_source(args.region, args.croco_ocean_source)
        if args.model == "croco" else None
    )
    if args.model != "croco" or selected_croco_source == "cmems":
        print(f"📥 Syncing CMEMS forcing from {cmems_gcs_src}...")
        run_checked(
            cloud_sync(cmems_gcs_src, str(inputs_dir)),
            stage="CMEMS forcing download",
        )

    if args.model == "croco":
        try:
            run_croco_simulation(
                project_root=project_root,
                inputs_dir=inputs_dir,
                outputs_dir=outputs_dir,
                region_id=args.region,
                run_date=run_date,
                run_id=run_id,
                forecast_hours=args.forecast_hours,
                mpi_ranks=args.mpi_ranks,
                gcs_bucket=args.gcs_bucket,
                ocean_source=selected_croco_source,
            )
        except Exception as exc:
            upload_rc = upload_croco_failure_diagnostics(
                outputs_dir=outputs_dir,
                region_id=args.region,
                run_date=run_date,
                run_id=run_id,
                gcs_bucket=args.gcs_bucket,
                error=exc,
            )
            if upload_rc != 0:
                print(
                    "WARNING: failed to upload CROCO failure diagnostics",
                    file=sys.stderr,
                    flush=True,
                )
            raise
        log_step("🏆 CROCO shard execution finished successfully!")
        return

    wind_candidates = sorted(inputs_dir.glob(f"ecmwf_sfc_{run_date}_*Z.grib2"))
    wind_candidates.extend(inputs_dir.glob("ecmwf_sfc.grib2"))
    wind_grib = inputs_dir / f"ecmwf_swan_wind_{run_date}_00Z.grib2"
    wind_error: Exception | None = None
    for candidate in dict.fromkeys(path.resolve() for path in wind_candidates):
        try:
            report = validate_wind(candidate, run_date, args.forecast_hours)
            print(f"✅ Cached ECMWF SWAN wind passed payload/time validation: {report}")
            wind_grib = candidate
            break
        except Exception as exc:
            wind_error = exc
            print(f"⚠️ Rejecting cached ECMWF wind {candidate.name}: {exc}")
    else:
        print(
            "📡 No cached wind passed validation; fetching a clean 10u/10v "
            "forecast directly from ECMWF Open Data in GCP."
        )
        if wind_error:
            print(f"   Last cached-wind validation error: {wind_error}")
        report = fetch_wind(run_date, args.forecast_hours, wind_grib)
        print(f"✅ Fresh ECMWF SWAN wind passed payload/time validation: {report}")
        run_checked(
            cloud_copy(str(wind_grib), f"{ecmwf_gcs_src}{wind_grib.name}"),
            stage="validated ECMWF SWAN wind cache upload",
        )
    # Wave boundary content is region-specific (fetched from CMEMS using this
    # region's own bbox), but the GCS cache directory (cmems_gcs_src) is keyed
    # only by run_date and is shared by every region's job. A generic filename
    # here would let one region's job populate the shared cache first and
    # every other region silently reuse its (wrong-bbox) wave data -- SWAN's
    # finite-value check would catch that as a crash, but only after wasting
    # the whole run. Scope both the local cache file and the GCS object name
    # by region so parallel regions can never collide.
    region_scoped_wave_boundary_name = f"cmems_swan_boundary_{args.region}.nc"
    region_scoped_wave_boundary_path = inputs_dir / region_scoped_wave_boundary_name
    if region_scoped_wave_boundary_path.is_file() and region_scoped_wave_boundary_path.stat().st_size > 0:
        wave_boundary = region_scoped_wave_boundary_path
    else:
        print(
            "📡 No region-scoped CMEMS SWAN boundary cached; fetching the exact "
            "regional hourly product directly in GCP."
        )
        run_checked(
            [
                "python3",
                "/app/scripts/fetch_native_marine_forcing.py",
                "--run-date",
                run_date,
                "--forecast-hours",
                str(args.forecast_hours),
                "--region",
                str(
                    project_root
                    / "simulation"
                    / "marine"
                    / "regions"
                    / f"{args.region}.json"
                ),
                "--output-dir",
                str(inputs_dir),
                "--models",
                "swan",
                "--overwrite",
            ],
            stage="CMEMS SWAN boundary acquisition and validation",
        )
        fetched_wave_boundary = require_one(
            inputs_dir,
            ("cmems_swan_boundary.nc",),
            "fresh CMEMS SWAN boundary NetCDF",
        )
        shutil.copy2(fetched_wave_boundary, region_scoped_wave_boundary_path)
        wave_boundary = region_scoped_wave_boundary_path
        run_checked(
            cloud_copy(str(wave_boundary), f"{cmems_gcs_src}{region_scoped_wave_boundary_name}"),
            stage="validated CMEMS SWAN boundary cache upload",
        )
    print(f"🔍 Resolved forcing: wind={wind_grib.name}, waves={wave_boundary.name}")

    # 2. Run SWAN simulation flow
    if args.model in ("swan", "both"):
        log_step("2. Running SWAN Wave Simulation")

        region_profile = resolve_project_file(
            project_root / "simulation" / "marine" / "regions" / f"{args.region}.json",
            Path(__file__).resolve().parents[1]
            / "simulation"
            / "marine"
            / "regions"
            / f"{args.region}.json",
        )
        bathymetry_path = resolve_swan_bathymetry(project_root, args.region)
        swan_work_dir = outputs_dir / f"swan_{args.region}"
        swan_work_dir.mkdir(parents=True, exist_ok=True)

        # Run prepare_swan_run.py
        prep_cmd = [
            "python3", "/app/scripts/prepare_swan_run.py",
            "--region", str(region_profile),
            "--bathymetry", str(bathymetry_path),
            "--wind-grib", str(wind_grib),
            "--wave-boundary", str(wave_boundary),
            "--output-dir", str(swan_work_dir),
            "--start-time", f"{run_date}T00:00:00",
            "--forecast-hours", str(args.forecast_hours)
        ]

        run_checked(prep_cmd, stage="SWAN input preparation")

        # Execute SWAN parallel run
        # Compile/run steps can be performed using native swan binary
        print(f"🚀 Executing parallel SWAN wave model on {args.mpi_ranks} MPI ranks...")
        # Note: In container, swan.exe or similar execution script is inside PATH or compiled in place
        swan_exe, swanrun = resolve_swan_tools()
        if not swan_exe or not swanrun:
            raise FileNotFoundError(
                "swan.exe/swanrun are not installed in the Batch image; "
                "use the pinned native SWAN Batch image"
            )
        command_files = sorted(swan_work_dir.glob("predsea_*.swn"))
        if len(command_files) != 1:
            raise RuntimeError(
                f"Expected one SWAN command file, found {len(command_files)}"
            )
        input_stem = command_files[0].stem
        swan_run_cmd = [
            swanrun, "-input", input_stem, "-mpi", str(args.mpi_ranks)
        ]

        # We run the command inside the prepared swan workspace directory containing swan.cmd
        # GCP Batch containers run as root. OpenMPI requires both acknowledgements
        # before it will launch ranks in that environment.
        os.environ["OMPI_ALLOW_RUN_AS_ROOT"] = "1"
        os.environ["OMPI_ALLOW_RUN_AS_ROOT_CONFIRM"] = "1"
        run_checked(swan_run_cmd, stage="parallel SWAN execution", cwd=swan_work_dir)
        if not (swan_work_dir / "swan_output.pvd").is_file():
            raise RuntimeError(
                "parallel SWAN execution returned without producing swan_output.pvd"
            )

        # Convert parallel VTK outputs to NetCDF using the corrected vtk_to_netcdf script
        log_step("3. Converting SWAN parallel VTK XML output to NetCDF")
        netcdf_output_file = outputs_dir / f"{args.region}_swan_forecast.nc"

        convert_cmd = [
            "python3", "/app/scripts/vtk_to_netcdf.py",
            "--results-dir", str(swan_work_dir),
            "--output", str(netcdf_output_file),
        ]
        run_checked(convert_cmd, stage="SWAN canonicalization")

        # Run physics validation checks (fail-closed, land-mask aware)
        log_step("4. Validating output products")
        validate_cmd = [
            "python3", "/app/scripts/validate_marine_output.py",
            "--output", str(netcdf_output_file),
            "--model=swan",
            "--region", str(region_profile),
            "--forecast-hours", str(args.forecast_hours)
        ]
        run_checked(validate_cmd, stage="SWAN content validation")

        # Upload NetCDF to GCS
        log_step("5. Uploading output NetCDF and products to GCS")
        gcs_dest_path = f"predictions/{run_date}/runs/{run_id}/{args.region}/"
        netcdf_gcs_target = cloud_uri(args.gcs_bucket, f"{gcs_dest_path}{args.region}_swan_forecast.nc")

        print(f"☁️ Uploading {netcdf_output_file.name} to {netcdf_gcs_target}...")
        run_checked(
            cloud_copy(str(netcdf_output_file), netcdf_gcs_target),
            stage="canonical SWAN upload",
        )

        # Upload SUCCESS completion marker
        success_marker = outputs_dir / "SUCCESS"
        success_marker.write_text(f"status=SUCCESS\ntimestamp={dt.datetime.now(dt.timezone.utc).isoformat()}\n")

        success_gcs_target = cloud_uri(args.gcs_bucket, f"{gcs_dest_path}SUCCESS")
        print(f"☁️ Uploading SUCCESS marker to {success_gcs_target}...")
        run_checked(
            cloud_copy(str(success_marker), success_gcs_target),
            stage="SWAN success-marker upload",
        )

    log_step("🏆 Shard execution finished successfully!")


if __name__ == "__main__":
    main()
