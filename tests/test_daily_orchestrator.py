from pathlib import Path

from scripts import daily_orchestrator as orchestrator


def test_ecmwf_opendata_is_the_default_atmospheric_source():
    assert orchestrator.DEFAULT_ATMOSPHERIC_SOURCE == "ecmwf-opendata"


def test_ecmwf_opendata_command_uses_dedicated_fetcher():
    command = orchestrator.atmospheric_forcing_command(
        "ecmwf-opendata",
        python_bin="python3",
        run_date="2026-08-23",
        forecast_hours=72,
        gcs_bucket="predsea-daily-outputs",
    )
    assert command[1].endswith("scripts/fetch_ecmwf_forcing.py")
    assert "--lead-hours=72" in command


def test_terminated_diagnostic_vm_is_not_treated_as_running(monkeypatch):
    class Result:
        stdout = "TERMINATED\n"
        stderr = ""

    monkeypatch.setattr(orchestrator.subprocess, "run", lambda *args, **kwargs: Result())

    assert not orchestrator.check_gce_instance_exists(
        "predsea-sim-failed", "europe-west1-b", "predsea-api"
    )


def test_running_vm_is_still_active(monkeypatch):
    class Result:
        stdout = "RUNNING\n"
        stderr = ""

    monkeypatch.setattr(orchestrator.subprocess, "run", lambda *args, **kwargs: Result())

    assert orchestrator.check_gce_instance_exists(
        "predsea-sim-running", "europe-west1-b", "predsea-api"
    )


def test_ordered_unique_keeps_primary_and_removes_duplicates():
    assert orchestrator.ordered_unique(
        "europe-west1-c",
        "europe-west1-b,europe-west1-c,europe-west1-d",
        orchestrator.DEFAULT_FALLBACK_ZONES,
    ) == ["europe-west1-c", "europe-west1-b", "europe-west1-d"]


def test_regular_vm_fallback_checks_zones_before_smaller_machine(monkeypatch):
    commands = []

    def fake_run(command, dry_run=False):
        commands.append(command)
        return 0 if "--zone=europe-west1-d" in command else 1

    monkeypatch.setattr(orchestrator, "run_subprocess", fake_run)

    selected = orchestrator.launch_vm_with_fallback(
        ["python", "gcp_orchestrator.py"],
        ["europe-west1-b", "europe-west1-c", "europe-west1-d"],
        ["n2-standard-64", "n2-standard-32"],
    )

    assert selected == ("europe-west1-d", "n2-standard-64", "STANDARD")
    assert len(commands) == 3
    assert all("--machine-type=n2-standard-64" in command for command in commands)
    assert all("--provisioning-model=STANDARD" in command for command in commands)


def test_regular_vm_fallback_uses_smaller_machine_after_all_zones(monkeypatch):
    commands = []

    def fake_run(command, dry_run=False):
        commands.append(command)
        return 0 if "--machine-type=n2-standard-32" in command else 1

    monkeypatch.setattr(orchestrator, "run_subprocess", fake_run)

    selected = orchestrator.launch_vm_with_fallback(
        ["python", "gcp_orchestrator.py"],
        ["europe-west1-b", "europe-west1-c"],
        ["n2-standard-64", "n2-standard-32"],
    )

    assert selected == ("europe-west1-b", "n2-standard-32", "STANDARD")
    assert len(commands) == 3


def test_all_default_vm_candidates_are_regular_capacity(monkeypatch):
    commands = []

    def fake_run(command, dry_run=False):
        commands.append(command)
        return 0

    monkeypatch.setattr(orchestrator, "run_subprocess", fake_run)

    selected = orchestrator.launch_vm_with_fallback(
        ["python", "gcp_orchestrator.py"],
        ["europe-west1-b", "europe-west1-c"],
        ["n2-standard-64", "n2-standard-32"],
    )

    assert selected == ("europe-west1-b", "n2-standard-64", "STANDARD")
    assert len(commands) == 1
    assert "--provisioning-model=STANDARD" in commands[0]


def test_default_machine_fallbacks_use_high_quota_n2_capacity():
    assert orchestrator.DEFAULT_FALLBACK_MACHINE_TYPES == (
        "n2-standard-64",
        "n2-standard-32",
        "n2-standard-16",
    )


def test_forecast_resource_defaults_scale_for_five_days():
    timeout_hours, boot_disk_size = orchestrator.forecast_resource_defaults(120)

    assert timeout_hours == 20.0
    assert boot_disk_size == "500GB"


def test_forecast_resource_defaults_preserve_operational_day_floor():
    timeout_hours, boot_disk_size = orchestrator.forecast_resource_defaults(24)

    assert timeout_hours == 6.0
    assert boot_disk_size == "200GB"


def test_forecast_horizon_is_forwarded_to_forcing_and_vm(monkeypatch, tmp_path):
    source = Path(orchestrator.__file__).read_text()

    assert 'f"--lead-hours={args.forecast_hours}"' in source
    assert 'f"--forecast-hours={args.forecast_hours}"' in source


def test_was_instance_preempted_reads_compute_audit_event(monkeypatch):
    class Result:
        stdout = "Instance was preempted.\n"
        stderr = ""

    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return Result()

    monkeypatch.setattr(orchestrator.subprocess, "run", fake_run)

    assert orchestrator.was_instance_preempted(
        "predsea-sim-test",
        "europe-west1-c",
        "predsea-api",
    )
    assert commands[0][:3] == ["gcloud", "logging", "read"]


def test_publish_run_status_dry_run_describes_preliminary_release():
    payload = orchestrator.publish_run_status(
        "predsea-daily-outputs",
        "2026-07-14",
        "2026-07-14T1400Z",
        "preliminary",
        "running",
        "Forecast online",
        dry_run=True,
    )

    assert payload["publication_phase"] == "preliminary"
    assert payload["wrf_status"] == "running"
    assert payload["message"] == "Forecast online"
