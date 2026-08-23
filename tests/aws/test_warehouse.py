from pathlib import Path

import pandas as pd
import pytest

from scripts.aws.warehouse import write_evidence_rows


class FakeS3:
    def __init__(self):
        self.upload = None

    def upload_file(self, path, bucket, key, ExtraArgs):
        self.upload = (Path(path).name, bucket, key, ExtraArgs)


def test_writer_uses_deterministic_run_scoped_key(monkeypatch):
    monkeypatch.setattr(pd.DataFrame, "to_parquet", lambda self, path, **kwargs: Path(path).touch())
    s3 = FakeS3()

    uri = write_evidence_rows(
        [{"run_date": "2026-08-23", "run_id": "2026-08-23T0300Z", "value": 1.0}],
        bucket="bucket",
        s3_client=s3,
    )

    expected_key = "warehouse/evidence_rows/run_date=2026-08-23/run_id=2026-08-23T0300Z/evidence.parquet"
    assert uri == f"s3://bucket/{expected_key}"
    assert s3.upload[2] == expected_key


def test_writer_rejects_missing_run_id():
    with pytest.raises(ValueError, match="run_id"):
        write_evidence_rows([{"run_date": "2026-08-23"}], bucket="bucket", s3_client=FakeS3())
