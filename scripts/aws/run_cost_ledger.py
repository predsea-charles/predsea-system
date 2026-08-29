"""Run-scoped AWS cost evidence with explicit estimate provenance."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _provisional_component(service: str, estimate: str | None) -> dict:
    component = {
        "service": service,
        "cost_classification": "provisional_estimate",
        "amount_usd": None,
        "currency": "USD",
    }
    if estimate in (None, ""):
        component["pricing_status"] = "unpriced"
        component["note"] = "No reviewed provisional estimate was configured."
        return component
    try:
        amount = Decimal(str(estimate))
    except InvalidOperation as error:
        raise ValueError(f"Invalid provisional {service} cost: {estimate!r}") from error
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"Provisional {service} cost must be finite and non-negative")
    component["amount_usd"] = float(amount)
    component["pricing_status"] = "priced"
    component["note"] = "Operator-supplied estimate; replace with attributed billing data."
    return component


def _pending_component(service: str) -> dict:
    return {
        "service": service,
        "cost_classification": "actual_attribution_pending",
        "pricing_status": "unpriced",
        "amount_usd": None,
        "currency": "USD",
        "note": "Populate from run-tagged billing or usage records after settlement.",
    }


@dataclass
class RunCostLedger:
    bucket: str
    run_date: str
    run_id: str
    s3: object
    provisional_s3_cost_usd: str | None = None
    provisional_cloudwatch_cost_usd: str | None = None
    status: str = "STARTED"
    started_at_utc: str = field(default_factory=_utc_now)
    completed_at_utc: str | None = None
    message: str = "AWS daily run started"

    @property
    def key(self) -> str:
        return f"predictions/{self.run_date}/runs/{self.run_id}/run_cost_ledger.json"

    def payload(self) -> dict:
        components = [
            _pending_component("ec2_spot"),
            _pending_component("ebs"),
            _provisional_component("s3", self.provisional_s3_cost_usd),
            _provisional_component("cloudwatch", self.provisional_cloudwatch_cost_usd),
            _pending_component("data_transfer"),
            _pending_component("fargate_orchestrator"),
            _pending_component("athena"),
        ]
        priced = [Decimal(str(item["amount_usd"])) for item in components if item["amount_usd"] is not None]
        return {
            "schema_version": "predsea.run_cost_ledger.v1",
            "run_date": self.run_date,
            "run_id": self.run_id,
            "status": self.status,
            "started_at_utc": self.started_at_utc,
            "completed_at_utc": self.completed_at_utc,
            "message": self.message,
            "components": components,
            "provisional_priced_subtotal_usd": float(sum(priced, Decimal("0"))),
            "total_cost_usd": None,
            "total_cost_status": "awaiting_attributed_billing_data",
        }

    def publish(self) -> None:
        self.s3.put_object(
            Bucket=self.bucket,
            Key=self.key,
            Body=json.dumps(self.payload(), indent=2).encode(),
            ContentType="application/json",
            ServerSideEncryption="AES256",
        )

    def finish(self, status: str, message: str) -> None:
        self.status = status
        self.message = message
        self.completed_at_utc = _utc_now()
        self.publish()
