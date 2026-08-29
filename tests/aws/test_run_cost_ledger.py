import json

import pytest

from scripts.aws.run_cost_ledger import RunCostLedger


class FakeS3:
    def __init__(self): self.objects = []
    def put_object(self, **kwargs): self.objects.append(kwargs)


def test_ledger_labels_storage_and_logs_as_provisional_estimates():
    s3 = FakeS3()
    ledger = RunCostLedger(
        "bucket", "2026-08-25", "run", s3,
        provisional_s3_cost_usd="0.12",
        provisional_cloudwatch_cost_usd="0.03",
    )
    ledger.publish()
    body = json.loads(s3.objects[-1]["Body"])
    assert s3.objects[-1]["Key"].endswith("/run_cost_ledger.json")
    by_service = {item["service"]: item for item in body["components"]}
    assert by_service["s3"]["cost_classification"] == "provisional_estimate"
    assert by_service["cloudwatch"]["cost_classification"] == "provisional_estimate"
    assert by_service["ec2_spot"]["cost_classification"] == "actual_attribution_pending"
    assert body["provisional_priced_subtotal_usd"] == 0.15
    assert body["total_cost_usd"] is None


def test_ledger_does_not_turn_missing_prices_into_zero_cost():
    ledger = RunCostLedger("bucket", "2026-08-25", "run", FakeS3())
    components = {item["service"]: item for item in ledger.payload()["components"]}
    assert components["s3"]["amount_usd"] is None
    assert components["cloudwatch"]["amount_usd"] is None
    assert components["s3"]["pricing_status"] == "unpriced"


def test_ledger_rejects_invalid_provisional_cost():
    ledger = RunCostLedger("bucket", "2026-08-25", "run", FakeS3(), provisional_s3_cost_usd="-1")
    with pytest.raises(ValueError, match="non-negative"):
        ledger.payload()
