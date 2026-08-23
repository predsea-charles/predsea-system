import argparse
import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HUMANINTHELOOP_DIR = PROJECT_ROOT / "humanintheloop"
if str(HUMANINTHELOOP_DIR) not in sys.path:
    sys.path.insert(0, str(HUMANINTHELOOP_DIR))

import validation_archive
import route_analysis
import bigquery_export


DEFAULT_BUCKET = "predsea-daily-outputs"
DEFAULT_PREFIX = "predictions"


class GcsValidationBackfill:
    def __init__(self, bucket_name=DEFAULT_BUCKET, prefix=DEFAULT_PREFIX, client=None, auth_mode="adc"):
        from google.cloud import storage

        self.client = client or storage.Client(credentials=gcloud_credentials() if auth_mode == "gcloud" else None)
        self.bucket = self.client.bucket(bucket_name)
        self.bucket_name = bucket_name
        self.prefix = prefix.strip("/")

    def object_name(self, *parts):
        clean = [str(part).strip("/") for part in parts if str(part).strip("/")]
        if self.prefix:
            return "/".join([self.prefix, *clean])
        return "/".join(clean)

    def list_dates(self):
        root_prefix = f"{self.prefix}/" if self.prefix else ""
        iterator = self.client.list_blobs(self.bucket, prefix=root_prefix, delimiter="/")
        for _ in iterator:
            pass
        dates = []
        for prefix in iterator.prefixes:
            date_text = prefix.rstrip("/").split("/")[-1]
            if looks_like_date(date_text):
                dates.append(date_text)
        return sorted(dates)

    def list_runs(self, run_date):
        runs_prefix = self.object_name(run_date, "runs")
        if runs_prefix:
            runs_prefix = f"{runs_prefix}/"
        iterator = self.client.list_blobs(self.bucket, prefix=runs_prefix, delimiter="/")
        for _ in iterator:
            pass
        return sorted(prefix.rstrip("/").split("/")[-1] for prefix in iterator.prefixes)

    def list_route_ids(self, run_date, run_id):
        prefix = self.object_name(run_date, "runs", run_id)
        if prefix:
            prefix = f"{prefix}/"
        route_ids = set()
        for blob in self.client.list_blobs(self.bucket, prefix=prefix):
            relative = blob.name[len(prefix):]
            parts = relative.split("/")
            if len(parts) == 2 and parts[1] == "daily_snapshot.json":
                route_ids.add(parts[0])
        return sorted(route_ids)

    def download_json(self, *parts):
        object_name = self.object_name(*parts)
        blob = self.bucket.blob(object_name)
        if not blob.exists():
            return None
        return json.loads(blob.download_as_text(encoding="utf-8"))

    def download_text(self, *parts):
        object_name = self.object_name(*parts)
        blob = self.bucket.blob(object_name)
        if not blob.exists():
            return None
        return blob.download_as_text(encoding="utf-8")

    def upload_text(self, text, *parts):
        object_name = self.object_name(*parts)
        blob = self.bucket.blob(object_name)
        blob.upload_from_string(text, content_type=content_type_for(object_name))
        return object_name

    def upload_json(self, payload, *parts):
        return self.upload_text(json.dumps(payload, indent=2), *parts)

    def load_snapshot(self, run_date, run_id, route_id):
        evidence = self.download_json(run_date, "runs", run_id, route_id, "evidence.json")
        if evidence:
            return evidence.get("decision_context", evidence)
        return self.download_json(run_date, "runs", run_id, route_id, "daily_snapshot.json")

    def validation_exists(self, run_date, run_id):
        blob = self.bucket.blob(self.object_name(run_date, "runs", run_id, "validation", "validation_summary.json"))
        return blob.exists()

    def latest_run_id(self, run_date):
        latest = self.download_json(run_date, "latest_run.json")
        if latest:
            return latest.get("run_id")
        runs = self.list_runs(run_date)
        return runs[-1] if runs else None


def content_type_for(object_name):
    if object_name.endswith(".json"):
        return "application/json"
    if object_name.endswith(".jsonl"):
        return "application/x-ndjson"
    return "text/plain"


def gcloud_credentials():
    from google.oauth2.credentials import Credentials

    token = subprocess.check_output(
        ["gcloud", "auth", "print-access-token"],
        text=True,
    ).strip()
    return Credentials(token)


def looks_like_date(value):
    return len(value) == 10 and value[4] == "-" and value[7] == "-" and value[:4].isdigit()


def parse_date_filter(value):
    if not value:
        return None
    return value


def route_snapshots_from_gcs(store, run_date, run_id, route_ids):
    snapshots = {}
    for route_id in route_ids:
        snapshot = store.load_snapshot(run_date, run_id, route_id)
        if snapshot:
            snapshots[route_id] = snapshot
    return snapshots


def observations_from_snapshots(snapshots):
    for snapshot in snapshots.values():
        observations = snapshot.get("observations")
        if observations:
            return observations
    return {}


def jsonl_text(rows):
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def build_run_archive(run_date, run_id, routes, snapshots, observations, historical_forecast_rows):
    observation_rows = validation_archive.build_observation_rows(observations, run_date, run_id)
    forecast_rows = validation_archive.build_forecast_rows(snapshots, routes, run_date, run_id)
    matched_rows = validation_archive.match_observations_to_forecasts(
        observation_rows,
        historical_forecast_rows + forecast_rows,
    )
    summary = validation_archive.build_validation_summary(
        run_date,
        run_id,
        observation_rows,
        forecast_rows,
        matched_rows,
    )
    return {
        "observation_rows": observation_rows,
        "forecast_rows": forecast_rows,
        "matched_rows": matched_rows,
        "summary": summary,
    }


def validation_manifest_entry(summary):
    return {
        "path": "validation/validation_summary.json",
        "observation_samples_path": "validation/observation_samples.jsonl",
        "forecast_index_path": "validation/forecast_index.jsonl",
        "matched_validation_path": "validation/matched_validation.jsonl",
        "observation_rows": summary.get("observation_rows", 0),
        "forecast_rows": summary.get("forecast_rows", 0),
        "matched_rows": summary.get("matched_rows", 0),
        "matched_variables": summary.get("matched_variables", {}),
    }


def update_manifest_payload(payload, validation_entry):
    if not payload:
        return None
    updated = dict(payload)
    updated["validation"] = validation_entry
    return updated


def upload_run_archive(store, run_date, run_id, archive, latest_run_id):
    validation_entry = validation_manifest_entry(archive["summary"])
    uploaded = []
    uploaded.append(
        store.upload_text(
            jsonl_text(archive["observation_rows"]),
            run_date,
            "runs",
            run_id,
            "validation",
            "observation_samples.jsonl",
        )
    )
    uploaded.append(
        store.upload_text(
            jsonl_text(archive["forecast_rows"]),
            run_date,
            "runs",
            run_id,
            "validation",
            "forecast_index.jsonl",
        )
    )
    uploaded.append(
        store.upload_text(
            jsonl_text(archive["matched_rows"]),
            run_date,
            "runs",
            run_id,
            "validation",
            "matched_validation.jsonl",
        )
    )
    uploaded.append(
        store.upload_json(
            archive["summary"],
            run_date,
            "runs",
            run_id,
            "validation",
            "validation_summary.json",
        )
    )

    run_manifest = store.download_json(run_date, "runs", run_id, "run_manifest.json")
    updated_manifest = update_manifest_payload(run_manifest, validation_entry)
    if updated_manifest:
        uploaded.append(store.upload_json(updated_manifest, run_date, "runs", run_id, "run_manifest.json"))

    if latest_run_id == run_id:
        latest = store.download_json(run_date, "latest_run.json")
        updated_latest = update_manifest_payload(latest, validation_entry)
        if updated_latest:
            uploaded.append(store.upload_json(updated_latest, run_date, "latest_run.json"))

    return uploaded


def iter_target_runs(store, date_from=None, date_to=None, run_id=None):
    for run_date in store.list_dates():
        if date_from and run_date < date_from:
            continue
        if date_to and run_date > date_to:
            continue
        runs = store.list_runs(run_date)
        for candidate_run_id in runs:
            if run_id and candidate_run_id != run_id:
                continue
            yield run_date, candidate_run_id


def backfill_validation_archives(
    bucket_name=DEFAULT_BUCKET,
    prefix=DEFAULT_PREFIX,
    auth_mode="adc",
    date_from=None,
    date_to=None,
    run_id=None,
    apply=False,
    overwrite=False,
    limit=None,
    bigquery_project=None,
    bigquery_dataset=None,
    bigquery_table=None,
    bigquery_location=None,
):
    store = GcsValidationBackfill(bucket_name=bucket_name, prefix=prefix, auth_mode=auth_mode)
    routes = route_analysis.load_routes()
    historical_forecast_rows = []
    results = []

    for run_date, candidate_run_id in iter_target_runs(store, date_from=date_from, date_to=date_to, run_id=run_id):
        if limit is not None and len(results) >= limit:
            break
        already_backfilled = store.validation_exists(run_date, candidate_run_id)
        if already_backfilled and not overwrite:
            results.append(
                {
                    "run_date": run_date,
                    "run_id": candidate_run_id,
                    "status": "skipped_existing",
                }
            )
            existing_forecast = store.download_text(
                run_date,
                "runs",
                candidate_run_id,
                "validation",
                "forecast_index.jsonl",
            )
            if existing_forecast:
                historical_forecast_rows.extend(parse_jsonl(existing_forecast))
            continue

        route_ids = store.list_route_ids(run_date, candidate_run_id)
        snapshots = route_snapshots_from_gcs(store, run_date, candidate_run_id, route_ids)
        if not snapshots:
            results.append({"run_date": run_date, "run_id": candidate_run_id, "status": "no_snapshots"})
            continue

        observations = observations_from_snapshots(snapshots)
        archive = build_run_archive(run_date, candidate_run_id, routes, snapshots, observations, historical_forecast_rows)
        latest_run_id = store.latest_run_id(run_date)
        result = {
            "run_date": run_date,
            "run_id": candidate_run_id,
            "status": "written" if apply else "dry_run",
            "route_count": len(snapshots),
            "observation_rows": archive["summary"]["observation_rows"],
            "forecast_rows": archive["summary"]["forecast_rows"],
            "matched_rows": archive["summary"]["matched_rows"],
            "matched_variables": archive["summary"]["matched_variables"],
        }
        if apply:
            result["uploaded"] = upload_run_archive(store, run_date, candidate_run_id, archive, latest_run_id)
            result["bigquery"] = bigquery_export.export_validation_rows_to_bigquery(
                archive["observation_rows"],
                archive["forecast_rows"],
                project_id=bigquery_project,
                dataset_id=bigquery_dataset,
                table_id=bigquery_table,
                location=bigquery_location,
                run_date=run_date,
                run_id=candidate_run_id,
                dry_run=False,
            )
        results.append(result)
        historical_forecast_rows.extend(archive["forecast_rows"])

    return results


def print_results(results):
    print(json.dumps({"runs": results, "run_count": len(results)}, indent=2))


def parse_jsonl(text):
    rows = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def parse_args():
    parser = argparse.ArgumentParser(description="Backfill PredSea validation archives directly in GCS.")
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    parser.add_argument("--auth", default="adc", choices=["adc", "gcloud"], help="Use ADC or the active gcloud account token.")
    parser.add_argument("--date-from")
    parser.add_argument("--date-to")
    parser.add_argument("--run-id")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--overwrite", action="store_true", help="Rewrite validation files if they already exist.")
    parser.add_argument("--apply", action="store_true", help="Write validation files to GCS. Without this, runs dry.")
    parser.add_argument("--bigquery-project")
    parser.add_argument("--bigquery-dataset")
    parser.add_argument("--bigquery-table")
    parser.add_argument("--bigquery-location")
    return parser.parse_args()


def main():
    args = parse_args()
    results = backfill_validation_archives(
        bucket_name=args.bucket,
        prefix=args.prefix,
        auth_mode=args.auth,
        date_from=parse_date_filter(args.date_from),
        date_to=parse_date_filter(args.date_to),
        run_id=args.run_id,
        apply=args.apply,
        overwrite=args.overwrite,
        limit=args.limit,
        bigquery_project=args.bigquery_project,
        bigquery_dataset=args.bigquery_dataset,
        bigquery_table=args.bigquery_table,
        bigquery_location=args.bigquery_location,
    )
    print_results(results)


if __name__ == "__main__":
    main()
