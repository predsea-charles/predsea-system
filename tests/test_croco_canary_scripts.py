import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "scripts" / "stage_wrf_for_canary.sh"
SUBMIT = ROOT / "scripts" / "submit_croco_canary.sh"
DATE = "2026-09-13"
RUN_ID = f"{DATE}T0000Z-canary-dt90"


def expected_objects(
    prefix: str, *, zero_hour: int | None = None, forecast_hours: int = 3
) -> dict[str, int]:
    start = datetime.strptime(DATE, "%Y-%m-%d")
    return {
        f"{prefix}/wrfout_d02_{start + timedelta(hours=hour):%Y-%m-%d_%H:00:00}":
            0 if hour == zero_hour else 958118624
        for hour in range(forecast_hours + 1)
    }


def fake_aws(tmp_path: Path, objects: dict[str, int]) -> dict[str, str]:
    binary = tmp_path / "aws"
    binary.write_text(
        """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
objects = json.loads(os.environ.get('FAKE_OBJECTS', '{}'))
with open(os.environ['FAKE_LOG'], 'a') as stream:
    stream.write(json.dumps(args) + '\\n')
if args[:2] == ['s3api', 'head-object']:
    key = args[args.index('--key') + 1]
    if key not in objects:
        raise SystemExit(255)
    print(objects[key])
elif args[:2] == ['s3api', 'list-objects-v2']:
    prefix = args[args.index('--prefix') + 1]
    print(sum(key.startswith(prefix) for key in objects))
elif args[:2] == ['s3', 'cp']:
    print('copy')
elif args[:2] == ['batch', 'submit-job']:
    print(json.dumps({'jobId': 'should-not-run-in-tests'}))
else:
    raise SystemExit(2)
"""
    )
    binary.chmod(0o755)
    log = tmp_path / "aws.log"
    return {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "FAKE_OBJECTS": json.dumps(objects),
        "FAKE_LOG": str(log),
    }


def run(script: Path, args: list[str], env: dict[str, str], *, input_text: str = ""):
    return subprocess.run(
        ["bash", str(script), *args], text=True, input=input_text,
        capture_output=True, env=env, check=False,
    )


def stage_args() -> list[str]:
    return [
        "--s3-bucket", "bucket", "--source-run-date", DATE,
        "--source-run-id", "source-72h", "--canary-run-date", DATE,
        "--canary-run-id", RUN_ID, "--forecast-hours", "3", "--dry-run",
    ]


def submit_args() -> list[str]:
    return [
        "--timestep-seconds", "90", "--ndtfast", "30",
        "--run-id-prefix", "canary-dt90", "--s3-bucket", "bucket",
        "--forecast-hours", "3", "--run-date", DATE,
    ]


def test_stage_selects_exactly_four_d02_files_and_ignores_unrelated(tmp_path):
    source = f"predictions/{DATE}/runs/source-72h/wrf"
    objects = expected_objects(source)
    objects[f"{source}/wrfout_d01_{DATE}_00:00:00"] = 123
    objects[f"{source}/unrelated.bin"] = 456
    env = fake_aws(tmp_path, objects)
    result = run(STAGE, stage_args(), env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("[DRY RUN] ->") == 4
    assert "d01" not in result.stdout and "unrelated.bin" not in result.stdout
    calls = (tmp_path / "aws.log").read_text()
    assert "s3\", \"cp" not in calls


def test_stage_rejects_missing_wrf_file(tmp_path):
    source = f"predictions/{DATE}/runs/source-72h/wrf"
    objects = expected_objects(source)
    objects.pop(f"{source}/wrfout_d02_{DATE}_02:00:00")
    result = run(STAGE, stage_args(), fake_aws(tmp_path, objects))
    assert result.returncode != 0
    assert "required WRF file is missing" in result.stderr


def test_stage_rejects_zero_byte_wrf_file(tmp_path):
    source = f"predictions/{DATE}/runs/source-72h/wrf"
    result = run(STAGE, stage_args(), fake_aws(tmp_path, expected_objects(source, zero_hour=1)))
    assert result.returncode != 0
    assert "required WRF file is empty" in result.stderr


def test_stage_72h_rolls_dates_and_selects_73_files(tmp_path):
    source = f"predictions/{DATE}/runs/source-72h/wrf"
    args = [value if value != "3" else "72" for value in stage_args()]
    result = run(
        STAGE, args, fake_aws(tmp_path, expected_objects(source, forecast_hours=72))
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("[DRY RUN] ->") == 73
    assert "wrfout_d02_2026-09-16_00:00:00" in result.stdout
    assert "_24:00:00" not in result.stdout


def test_submit_run_id_suffix_occurs_exactly_once(tmp_path):
    prefix = f"predictions/{DATE}/runs/{RUN_ID}/wrf"
    result = run(SUBMIT, [*submit_args(), "--dry-run"], fake_aws(tmp_path, expected_objects(prefix)))
    assert result.returncode == 0, result.stderr
    assert f"run_id={RUN_ID}" in result.stdout
    assert "dt90-dt90" not in result.stdout


def test_submit_requires_exactly_four_nonempty_d02_files(tmp_path):
    prefix = f"predictions/{DATE}/runs/{RUN_ID}/wrf"
    missing = expected_objects(prefix)
    missing.pop(f"{prefix}/wrfout_d02_{DATE}_03:00:00")
    result = run(SUBMIT, [*submit_args(), "--dry-run"], fake_aws(tmp_path, missing))
    assert result.returncode != 0
    assert "expected exactly 4" in result.stderr


def test_submit_rejects_zero_byte_wrf_file(tmp_path):
    prefix = f"predictions/{DATE}/runs/{RUN_ID}/wrf"
    result = run(
        SUBMIT,
        [*submit_args(), "--dry-run"],
        fake_aws(tmp_path, expected_objects(prefix, zero_hour=2)),
    )
    assert result.returncode != 0
    assert "empty staged WRF file" in result.stderr


def test_canary_queue_is_mandatory_and_production_queue_rejected(tmp_path):
    env = fake_aws(tmp_path, {})
    result = run(SUBMIT, [*submit_args(), "--job-queue", "predsea-models"], env)
    assert result.returncode != 0
    assert "overrides are forbidden" in result.stderr


def test_scientific_approval_gate_blocks_submission(tmp_path):
    prefix = f"predictions/{DATE}/runs/{RUN_ID}/wrf"
    env = fake_aws(tmp_path, expected_objects(prefix))
    result = run(SUBMIT, submit_args(), env)
    assert result.returncode != 0
    assert "scientific approval is required" in result.stderr
    calls = (tmp_path / "aws.log").read_text()
    assert "submit-job" not in calls
