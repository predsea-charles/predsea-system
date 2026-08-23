from scripts import run_marine_simulation as runner


def test_s3_copy_and_sync_commands(monkeypatch):
    monkeypatch.setenv("PREDSEA_STORAGE_BACKEND", "s3")
    assert runner.cloud_uri("bucket", "path/file.nc") == "s3://bucket/path/file.nc"
    assert runner.cloud_copy("local.nc", "s3://bucket/object") == [
        "aws", "s3", "cp", "local.nc", "s3://bucket/object", "--only-show-errors"
    ]
    assert runner.cloud_sync("s3://bucket/prefix/", "/workspace/input") == [
        "aws", "s3", "sync", "s3://bucket/prefix/", "/workspace/input", "--only-show-errors"
    ]


def test_gcs_rollback_commands_remain_available(monkeypatch):
    monkeypatch.setenv("PREDSEA_STORAGE_BACKEND", "gcs")
    assert runner.cloud_uri("bucket", "path") == "gs://bucket/path"
