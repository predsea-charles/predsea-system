from types import SimpleNamespace

from scripts import gcp_orchestrator


def _args(provisioning_model):
    return SimpleNamespace(
        project="predsea-api",
        zone="europe-west1-b",
        machine_type="c2-standard-16",
        gcs_bucket="predsea-daily-outputs",
        image_tag="latest",
        run_date="2026-07-14",
        run_id="2026-07-14T1200Z",
        instance_name="predsea-sim-test",
        execution_mode="container",
        boot_disk_size="200GB",
        provisioning_model=provisioning_model,
    )


def test_standard_vm_omits_spot_termination_action(monkeypatch):
    commands = []
    monkeypatch.setattr(
        gcp_orchestrator,
        "run_command",
        lambda command: commands.append(command) or "created",
    )

    gcp_orchestrator.launch_vm(_args("STANDARD"))

    assert "--provisioning-model=STANDARD" in commands[0]
    assert "--instance-termination-action=DELETE" not in commands[0]


def test_spot_vm_keeps_delete_termination_action(monkeypatch):
    commands = []
    monkeypatch.setattr(
        gcp_orchestrator,
        "run_command",
        lambda command: commands.append(command) or "created",
    )

    gcp_orchestrator.launch_vm(_args("SPOT"))

    assert "--provisioning-model=SPOT" in commands[0]
    assert "--instance-termination-action=DELETE" in commands[0]
