import io

from api.evidence_store import S3EvidenceStore


class Paginator:
    def paginate(self, **kwargs):
        return [{"Contents": [{"Key": "predictions/2026-08-23/latest_run.json"}], "CommonPrefixes": [{"Prefix": "predictions/2026-08-23/"}]}]


class S3:
    def get_paginator(self, name): return Paginator()
    def get_object(self, **kwargs): return {"Body": io.BytesIO(b'{"run_id":"run-1"}')}
    def head_object(self, **kwargs): return {}
    def generate_presigned_url(self, *args, **kwargs): return "https://signed.example"


def test_s3_store_lists_dates_and_reads_latest_run():
    store = S3EvidenceStore("bucket", client=S3())
    assert store.available_dates() == ["2026-08-23"]
    assert store.latest_run("2026-08-23") == "run-1"
