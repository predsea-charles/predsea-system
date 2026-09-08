import json
from pathlib import Path

from scripts import aws_daily_orchestrator as daily


class FakeS3:
    def __init__(self):
        self.uploads = []

    def upload_file(self, source, bucket, key, ExtraArgs=None):
        self.uploads.append((Path(source).name, bucket, key, ExtraArgs))


def test_native_marine_staging_uses_validated_region_scoped_products(monkeypatch):
    def fake_run(command, *, dry_run=False):
        assert "fetch_cmems_forcing.py" not in " ".join(command)
        output_dir = Path(command[command.index("--output-dir") + 1])
        region = Path(command[command.index("--region") + 1]).stem
        output_dir.mkdir(parents=True)
        models = command[command.index("--models") + 1 : command.index("--overwrite")]
        filenames = daily.CROCO_FILES if models == ["croco"] else daily.WAVE_FILES
        for filename in filenames:
            (output_dir / filename).write_bytes(b"netcdf")
        (output_dir / "forcing_manifest.json").write_text(json.dumps({
            "status": "succeeded", "region_id": region
        }))

    monkeypatch.setattr(daily, "run", fake_run)
    s3 = FakeS3()
    daily.stage_native_marine_forcing(
        "bucket", "2026-08-23", 72, s3=s3
    )

    assert len(s3.uploads) == (len(daily.CROCO_FILES) + 1) + (
        len(daily.MARINE_REGIONS) * (len(daily.WAVE_FILES) + 1)
    )
    keys = {upload[2] for upload in s3.uploads}
    assert (
        "forcing/cmems/2026-08-23/"
        "cmems_croco_currents_3d_western_mediterranean_1km.nc"
    ) in keys
    assert "forcing/cmems/2026-08-23/cmems_croco_currents_3d_alboran_1km.nc" not in keys
    assert "forcing/cmems/2026-08-23/forcing_manifest_tyrrhenian_1km.json" in keys
