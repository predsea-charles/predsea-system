import json
from pathlib import Path

import pytest
from scripts.run_marine_simulation import (
    CROCO_MPI_RANKS,
    croco_ocean_source,
    croco_mpi_command,
    require_one,
    require_wrf_forcing,
    resolve_swan_tools,
    stage_croco_ocean_inputs,
    run_subprocess,
    upload_croco_failure_diagnostics,
    validate_croco_mpi_ranks,
)


def test_croco_docker_build_matches_unified_grid_profile():
    dockerfile = Path("simulation/marine/croco/Dockerfile.batch").read_text()
    profile = json.loads(
        Path("simulation/marine/regions/western_mediterranean_1km.json").read_text()
    )
    shape = profile["models"]["croco"]["compiled_grid_shape"]

    assert f"ARG PREDSEA_CROCO_LM={shape['xi_rho'] - 2}" in dockerfile
    assert f"ARG PREDSEA_CROCO_MM={shape['eta_rho'] - 2}" in dockerfile
    assert "ARG PREDSEA_CROCO_N=32" in dockerfile
    assert "sed -i 's/-mcmodel=medium//g'" not in dockerfile


def test_croco_mpi_rank_contract_covers_unified_binary():
    assert CROCO_MPI_RANKS == {"western_mediterranean_1km": 192}
    for region_id, mpi_ranks in CROCO_MPI_RANKS.items():
        validate_croco_mpi_ranks(region_id, mpi_ranks)


def test_croco_mpi_rank_contract_rejects_region_mismatch():
    with pytest.raises(ValueError, match="compiled decomposition requires 192"):
        validate_croco_mpi_ranks("western_mediterranean_1km", 96)


def test_require_wrf_forcing_rejects_missing_and_empty_placeholders(tmp_path: Path):
    with pytest.raises(RuntimeError, match="expected at least 7 hourly files, found 0"):
        require_wrf_forcing(tmp_path, domain="d02", forecast_hours=6)

    for hour in range(7):
        (tmp_path / f"wrfout_d02_2026-09-09_{hour:02d}:00:00").touch()
    with pytest.raises(RuntimeError, match="empty placeholder files"):
        require_wrf_forcing(tmp_path, domain="d02", forecast_hours=6)


def test_require_wrf_forcing_returns_six_hour_window(tmp_path: Path):
    expected = []
    for hour in range(8):
        path = tmp_path / f"wrfout_d02_2026-09-09_{hour:02d}:00:00"
        path.write_bytes(b"netcdf")
        expected.append(path)

    assert require_wrf_forcing(tmp_path, domain="d02", forecast_hours=6) == expected[:7]


def test_alboran_defaults_to_staged_ocean_inputs(monkeypatch):
    monkeypatch.delenv("PREDSEA_CROCO_OCEAN_SOURCE", raising=False)
    assert croco_ocean_source("alboran_1km") == "staged"
    assert croco_ocean_source("alboran_1km", "cmems") == "cmems"


def test_stage_croco_ocean_inputs_requires_compiled_contract(tmp_path: Path):
    source = tmp_path / "inputs" / "croco" / "alboran_1km"
    work = tmp_path / "work"
    source.mkdir(parents=True)
    work.mkdir()
    for name in ("croco_ini.nc", "croco_bry.nc", "croco_clm.nc"):
        (source / name).write_bytes(b"netcdf")

    staged = stage_croco_ocean_inputs(tmp_path / "inputs", work, "alboran_1km")

    assert [path.name for path in staged] == [
        "croco_ini.nc", "croco_bry.nc", "croco_clm.nc"
    ]


def test_stage_croco_ocean_inputs_fails_closed_when_boundary_missing(tmp_path: Path):
    source = tmp_path / "inputs" / "alboran_1km"
    work = tmp_path / "work"
    source.mkdir(parents=True)
    work.mkdir()
    (source / "croco_ini.nc").write_bytes(b"netcdf")
    (source / "croco_clm.nc").write_bytes(b"netcdf")

    with pytest.raises(FileNotFoundError, match="croco_bry.nc"):
        stage_croco_ocean_inputs(tmp_path / "inputs", work, "alboran_1km")
from scripts.submit_gcp_batch_simulation import (
    build_batch_job_json,
    default_timeout_seconds,
)


def test_require_one_rejects_missing_and_ambiguous_products(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="Missing SWAN boundary"):
        require_one(tmp_path, ("cmems_swan_boundary.nc",), "SWAN boundary")

    (tmp_path / "one.nc").write_text("one")
    (tmp_path / "two.nc").write_text("two")
    with pytest.raises(RuntimeError, match="Ambiguous SWAN boundary"):
        require_one(tmp_path, ("*.nc",), "SWAN boundary")


def test_require_one_returns_the_exact_product(tmp_path: Path):
    expected = tmp_path / "cmems_swan_boundary.nc"
    expected.write_text("boundary")
    assert require_one(
        tmp_path, ("cmems_swan_boundary.nc",), "SWAN boundary"
    ) == expected.resolve()


def test_resolve_swan_tools_handles_minimal_batch_path(tmp_path: Path, monkeypatch):
    for name in ("swan.exe", "swanrun"):
        executable = tmp_path / name
        executable.write_text("#!/bin/sh\n")
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", "")
    swan_exe, swanrun = resolve_swan_tools(tmp_path)
    assert swan_exe == str(tmp_path / "swan.exe")
    assert swanrun == str(tmp_path / "swanrun")


def test_croco_mpi_uses_allocated_hardware_threads():
    command = croco_mpi_command(16, Path("/usr/local/bin/croco"), Path("/work/croco.in"))

    assert command[:5] == [
        "mpirun", "--allow-run-as-root", "--use-hwthread-cpus", "-np", "16"
    ]


def test_run_subprocess_streams_output_to_durable_log(tmp_path: Path):
    log_path = tmp_path / "croco.stdout.log"

    result = run_subprocess(
        ["python3", "-c", "print('CROCO STEP 42')"], log_path=log_path
    )

    assert result == 0
    assert log_path.read_text(encoding="utf-8") == "CROCO STEP 42\n"


def test_croco_failure_diagnostics_are_run_scoped(tmp_path: Path, monkeypatch):
    captured = {}

    def fake_run_subprocess(command, cwd=None, log_path=None):
        captured["command"] = command
        return 0

    monkeypatch.setattr(
        "scripts.run_marine_simulation.run_subprocess", fake_run_subprocess
    )

    result = upload_croco_failure_diagnostics(
        outputs_dir=tmp_path,
        region_id="balearic_1km",
        run_date="2026-07-16",
        run_id="croco-diagnostic-v8",
        gcs_bucket="predsea-daily-outputs-test",
        error=RuntimeError("parallel CROCO execution failed with exit code 1"),
    )

    failure = tmp_path / "croco_balearic_1km" / "FAILURE.txt"
    assert result == 0
    assert "status=FAILED" in failure.read_text(encoding="utf-8")
    assert "RuntimeError" in failure.read_text(encoding="utf-8")
    assert captured["command"][-1].endswith(
        "/2026-07-16/runs/croco-diagnostic-v8/balearic_1km/failure-diagnostics/"
    )


def test_long_horizon_timeout_is_not_the_old_four_hour_constant():
    assert default_timeout_seconds(24) == 4 * 3600
    assert default_timeout_seconds(120) == 8 * 3600


def test_batch_manifest_carries_immutable_run_identity_and_timeout():
    image = "europe-west1-docker.pkg.dev/p/model/swan@sha256:" + "a" * 64
    manifest = build_batch_job_json(
        project_id="predsea-api",
        region_id="balearic_1km",
        model_type="swan",
        forecast_hours=120,
        gcs_bucket="predsea-daily-outputs-test",
        machine_type="c2d-highcpu-8",
        cpu_milli=8000,
        memory_mib=16384,
        mpi_ranks=4,
        image_uri=image,
        run_date="2026-07-20",
        run_id="run-123",
        timeout_seconds=28800,
    )
    task = manifest["taskGroups"][0]["taskSpec"]
    runnable = task["runnables"][0]
    assert task["maxRunDuration"] == "28800s"
    assert runnable["container"]["imageUri"] == image
    assert runnable["environment"]["variables"]["PREDSEA_RUN_ID"] == "run-123"
    assert (
        runnable["environment"]["variables"]["CLOUDSDK_PYTHON"]
        == "/usr/local/bin/python3"
    )


def test_batch_manifest_exposes_copernicus_service_environment_names():
    manifest = build_batch_job_json(
        project_id="predsea-api",
        region_id="balearic_1km",
        model_type="swan",
        forecast_hours=24,
        gcs_bucket="predsea-daily-outputs-test",
        machine_type="c2d-highcpu-4",
        cpu_milli=4000,
        memory_mib=8192,
        mpi_ranks=2,
        image_uri="example.invalid/swan@sha256:" + "a" * 64,
        run_date="2026-07-20",
        run_id="run-credentials",
        timeout_seconds=14400,
        copernicus_username="user",
        copernicus_password="password",
    )
    variables = manifest["taskGroups"][0]["taskSpec"]["runnables"][0][
        "environment"
    ]["variables"]
    assert variables["COPERNICUSMARINE_SERVICE_USERNAME"] == "user"
    assert variables["COPERNICUSMARINE_SERVICE_PASSWORD"] == "password"


def test_batch_manifest_supports_deadline_critical_standard_vm():
    manifest = build_batch_job_json(
        project_id="predsea-api",
        region_id="balearic_1km",
        model_type="swan",
        forecast_hours=24,
        gcs_bucket="predsea-daily-outputs-test",
        machine_type="c2d-highcpu-16",
        cpu_milli=16000,
        memory_mib=32768,
        mpi_ranks=8,
        image_uri="example.invalid/swan@sha256:" + "a" * 64,
        run_date="2026-07-20",
        run_id="run-standard-16",
        timeout_seconds=14400,
        provisioning_model="STANDARD",
    )

    policy = manifest["allocationPolicy"]["instances"][0]["policy"]
    task = manifest["taskGroups"][0]["taskSpec"]
    command = task["runnables"][0]["container"]["commands"][1]
    assert policy == {
        "machineType": "c2d-highcpu-16",
        "provisioningModel": "STANDARD",
    }
    assert task["computeResource"] == {"cpuMilli": "16000", "memoryMib": "32768"}
    assert "--mpi-ranks 8" in command


def test_croco_manifest_requires_and_carries_explicit_staging_inputs():
    with pytest.raises(ValueError, match="explicit WRF"):
        build_batch_job_json(
            project_id="predsea-api", region_id="balearic_1km", model_type="croco",
            forecast_hours=6, gcs_bucket="predsea-daily-outputs-test",
            machine_type="c2d-highcpu-16", cpu_milli=16000, memory_mib=32768,
            mpi_ranks=16, image_uri="example.invalid/croco@sha256:" + "a" * 64,
            run_date="2026-07-20", run_id="croco-gate", timeout_seconds=7200,
        )

    with pytest.raises(ValueError, match="region mismatch"):
        build_batch_job_json(
            project_id="predsea-api", region_id="alboran_1km", model_type="croco",
            forecast_hours=6, gcs_bucket="predsea-daily-outputs-test",
            machine_type="c2d-highcpu-16", cpu_milli=16000, memory_mib=32768,
            mpi_ranks=16, image_uri="example.invalid/croco@sha256:" + "a" * 64,
            run_date="2026-07-20", run_id="croco-gate", timeout_seconds=7200,
            croco_grid_gcs_uri=(
                "gs://predsea-daily-outputs-test/static/native-marine/"
                "balearic_1km/croco-grid/20260722-v3/croco_grid.nc"
            ),
            wrf_gcs_uri="gs://predsea-daily-outputs-test/runs/wrf/*",
        )

    manifest = build_batch_job_json(
        project_id="predsea-api", region_id="balearic_1km", model_type="croco",
        forecast_hours=6, gcs_bucket="predsea-daily-outputs-test",
        machine_type="c2d-highcpu-16", cpu_milli=16000, memory_mib=32768,
        mpi_ranks=16, image_uri="example.invalid/croco@sha256:" + "a" * 64,
        run_date="2026-07-20", run_id="croco-gate", timeout_seconds=7200,
        croco_grid_gcs_uri=(
            "gs://predsea-daily-outputs-test/static/native-marine/"
            "balearic_1km/croco-grid/20260722-v3/croco_grid.nc"
        ),
        wrf_gcs_uri="gs://predsea-daily-outputs-test/runs/wrf/*",
    )
    variables = manifest["taskGroups"][0]["taskSpec"]["runnables"][0]["environment"]["variables"]
    assert variables["PREDSEA_CROCO_GRID_GCS_URI"].startswith("gs://predsea-daily-outputs-test/")
    assert variables["PREDSEA_WRF_GCS_URI"].startswith("gs://predsea-daily-outputs-test/")
