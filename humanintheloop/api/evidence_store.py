import json
import os
from pathlib import Path
from datetime import timedelta, datetime, timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

def current_local_date(timezone_name: str = "Europe/Madrid") -> str:
    try:
        if ZoneInfo:
            return datetime.now(ZoneInfo(timezone_name)).date().isoformat()
    except Exception:
        pass
    return datetime.now(timezone.utc).date().isoformat()

import evidence_package


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PREDICTIONS_ROOT = Path(os.environ.get("PREDSEA_PREDICTIONS_ROOT", PROJECT_ROOT / "predictions"))
DEFAULT_GCS_PREFIX = os.environ.get("PREDSEA_GCS_PREFIX", "predictions")


class EvidenceNotFoundError(FileNotFoundError):
    pass


class EvidenceStore:
    def __init__(self, predictions_root=DEFAULT_PREDICTIONS_ROOT):
        self.predictions_root = Path(predictions_root)
        self.storage_backend = "local"

    def available_dates(self):
        if not self.predictions_root.exists():
            return []
        return sorted(
            path.name
            for path in self.predictions_root.iterdir()
            if path.is_dir() and path.name[:4].isdigit()
        )

    def latest_date(self):
        dates = [d for d in self.available_dates() if d <= current_local_date()]
        if not dates:
            raise EvidenceNotFoundError(f"No prediction dates found in {self.predictions_root}")
        return dates[-1]

    def resolve_date(self, run_date=None):
        return run_date or self.latest_date()

    def latest_run(self, run_date=None):
        date_text = self.resolve_date(run_date)
        day_dir = self.predictions_root / date_text
        latest_path = day_dir / "latest_run.json"
        if latest_path.exists():
            latest = json.loads(latest_path.read_text(encoding="utf-8"))
            return latest.get("run_id")
        runs_dir = day_dir / "runs"
        if runs_dir.exists():
            runs = sorted(path.name for path in runs_dir.iterdir() if path.is_dir())
            if runs:
                return runs[-1]
        return None

    def resolve_run(self, run_date=None, run_id=None):
        if run_id and run_id != "latest":
            return run_id
        return self.latest_run(run_date)

    def _base_dir(self, run_date=None, run_id=None):
        date_text = self.resolve_date(run_date)
        resolved_run = self.resolve_run(date_text, run_id)
        if resolved_run:
            return self.predictions_root / date_text / "runs" / resolved_run
        return self.predictions_root / date_text

    def route_ids(self, run_date=None, run_id=None):
        date_text = self.resolve_date(run_date)
        day_dir = self._base_dir(date_text, run_id)
        if not day_dir.exists():
            raise EvidenceNotFoundError(f"No predictions found for {date_text}")
        return sorted(
            path.name
            for path in day_dir.iterdir()
            if path.is_dir() and (path / "daily_snapshot.json").exists()
        )

    def load_snapshot(self, route_id, run_date=None, run_id=None):
        date_text = self.resolve_date(run_date)
        base_dir = self._base_dir(date_text, run_id)
        evidence_path = base_dir / route_id / "evidence.json"
        if evidence_path.exists():
            package = json.loads(evidence_path.read_text(encoding="utf-8"))
            return evidence_package.snapshot_from_evidence(package)
        snapshot_path = base_dir / route_id / "daily_snapshot.json"
        if not snapshot_path.exists():
            raise EvidenceNotFoundError(f"No evidence for route '{route_id}' on {date_text}")
        return json.loads(snapshot_path.read_text(encoding="utf-8"))

    def load_text_artifact(self, route_id, artifact_name, run_date=None, run_id=None):
        date_text = self.resolve_date(run_date)
        artifact_path = self._base_dir(date_text, run_id) / route_id / artifact_name
        if not artifact_path.exists():
            raise EvidenceNotFoundError(f"No artifact '{artifact_name}' for route '{route_id}' on {date_text}")
        return artifact_path.read_text(encoding="utf-8")

    def load_binary_artifact(self, route_id, artifact_name, run_date=None, run_id=None):
        date_text = self.resolve_date(run_date)
        artifact_path = self._base_dir(date_text, run_id) / route_id / artifact_name
        if not artifact_path.exists():
            raise EvidenceNotFoundError(f"No artifact '{artifact_name}' for route '{route_id}' on {date_text}")
        return artifact_path.read_bytes()

    def load_map_index(self, variable, run_date=None, run_id=None):
        date_text = self.resolve_date(run_date)
        index_path = self._base_dir(date_text, run_id) / "maps" / variable / "index.json"
        if not index_path.exists():
            raise EvidenceNotFoundError(f"No map overlay index for '{variable}' on {date_text}")
        return json.loads(index_path.read_text(encoding="utf-8"))

    def load_map_overlay(self, variable, filename, run_date=None, run_id=None):
        date_text = self.resolve_date(run_date)
        overlay_path = self._base_dir(date_text, run_id) / "maps" / variable / filename
        if not overlay_path.exists():
            raise EvidenceNotFoundError(f"No map overlay '{filename}' for '{variable}' on {date_text}")
        return overlay_path.read_bytes()

    def load_map_grid(self, variable, filename, run_date=None, run_id=None):
        date_text = self.resolve_date(run_date)
        grid_path = self._base_dir(date_text, run_id) / "maps" / variable / filename
        if not grid_path.exists():
            raise EvidenceNotFoundError(f"No map grid '{filename}' for '{variable}' on {date_text}")
        return json.loads(grid_path.read_text(encoding="utf-8"))

    def load_regional_evidence(self, run_date=None, run_id=None):
        date_text = self.resolve_date(run_date)
        regional_path = self._base_dir(date_text, run_id) / "regional_evidence.json"
        if not regional_path.exists():
            raise EvidenceNotFoundError(f"No regional evidence package on {date_text}")
        return json.loads(regional_path.read_text(encoding="utf-8"))

    def load_place_weather(self, place_id, run_date=None, run_id=None):
        date_text = self.resolve_date(run_date)
        weather_path = self._base_dir(date_text, run_id) / "places" / place_id / "weather.json"
        if not weather_path.exists():
            raise EvidenceNotFoundError(f"No place weather package for '{place_id}' on {date_text}")
        return json.loads(weather_path.read_text(encoding="utf-8"))

    def load_publication_status(self, run_date=None, run_id=None):
        date_text = self.resolve_date(run_date)
        resolved_run = self.resolve_run(date_text, run_id)
        candidates = []
        if resolved_run:
            candidates.append(
                self.predictions_root
                / date_text
                / "runs"
                / resolved_run
                / "publication_status.json"
            )
        candidates.append(self.predictions_root / date_text / "latest_status.json")
        for status_path in candidates:
            if status_path.exists():
                payload = json.loads(status_path.read_text(encoding="utf-8"))
                if not resolved_run or payload.get("run_id") == resolved_run:
                    return payload
        raise EvidenceNotFoundError(f"No publication status found for {date_text}")

    def signed_artifact_url(self, route_id, artifact_name, run_date=None, run_id=None, expires_minutes=30):
        return None


class GcsEvidenceStore:
    def __init__(self, bucket_name, prefix=DEFAULT_GCS_PREFIX, client=None, fallback_store=None):
        self.bucket_name = bucket_name
        self.prefix = prefix.strip("/")
        self.fallback_store = fallback_store
        self.storage_backend = "gcs"
        if client is None:
            from google.cloud import storage

            client = storage.Client()
        self.client = client

    def _object_name(self, *parts):
        clean_parts = [str(part).strip("/") for part in parts if str(part).strip("/")]
        if self.prefix:
            return "/".join([self.prefix, *clean_parts])
        return "/".join(clean_parts)

    def _list_blobs(self, prefix, delimiter=None):
        return self.client.list_blobs(self.bucket_name, prefix=prefix, delimiter=delimiter)

    def _download_text(self, object_name):
        bucket = self.client.bucket(self.bucket_name)
        blob = bucket.blob(object_name)
        if not blob.exists():
            raise EvidenceNotFoundError(f"No GCS object found at gs://{self.bucket_name}/{object_name}")
        return blob.download_as_text(encoding="utf-8")

    def _download_bytes(self, object_name):
        bucket = self.client.bucket(self.bucket_name)
        blob = bucket.blob(object_name)
        if not blob.exists():
            raise EvidenceNotFoundError(f"No GCS object found at gs://{self.bucket_name}/{object_name}")
        return blob.download_as_bytes()

    def available_dates(self):
        root_prefix = f"{self.prefix}/" if self.prefix else ""
        try:
            iterator = self._list_blobs(root_prefix, delimiter="/")
            for _ in iterator:
                pass
            dates = []
            for prefix in iterator.prefixes:
                date_text = prefix.rstrip("/").split("/")[-1]
                if date_text[:4].isdigit():
                    dates.append(date_text)
            if dates:
                return sorted(dates)
        except Exception as error:
            if self.fallback_store is None:
                raise EvidenceNotFoundError(f"Unable to list GCS prediction dates: {error}") from error

        if self.fallback_store is not None:
            return self.fallback_store.available_dates()
        return []

    def latest_date(self):
        dates = [d for d in self.available_dates() if d <= current_local_date()]
        if not dates:
            raise EvidenceNotFoundError(f"No prediction dates found in gs://{self.bucket_name}/{self.prefix}")
        return dates[-1]

    def resolve_date(self, run_date=None):
        return run_date or self.latest_date()

    def latest_run(self, run_date=None):
        date_text = self.resolve_date(run_date)
        latest_object_name = self._object_name(date_text, "latest_run.json")
        try:
            latest = json.loads(self._download_text(latest_object_name))
            return latest.get("run_id")
        except EvidenceNotFoundError:
            pass

        runs_prefix = self._object_name(date_text, "runs")
        if runs_prefix:
            runs_prefix = f"{runs_prefix}/"
        try:
            iterator = self._list_blobs(runs_prefix, delimiter="/")
            for _ in iterator:
                pass
            runs = sorted(prefix.rstrip("/").split("/")[-1] for prefix in iterator.prefixes)
            if runs:
                return runs[-1]
        except Exception as error:
            if self.fallback_store is None:
                raise EvidenceNotFoundError(f"Unable to list GCS runs for {date_text}: {error}") from error

        if self.fallback_store is not None:
            return self.fallback_store.latest_run(date_text)
        return None

    def resolve_run(self, run_date=None, run_id=None):
        if run_id and run_id != "latest":
            return run_id
        return self.latest_run(run_date)

    def _base_prefix(self, run_date=None, run_id=None):
        date_text = self.resolve_date(run_date)
        resolved_run = self.resolve_run(date_text, run_id)
        if resolved_run:
            return self._object_name(date_text, "runs", resolved_run)
        return self._object_name(date_text)

    def route_ids(self, run_date=None, run_id=None):
        date_text = self.resolve_date(run_date)
        prefix = self._base_prefix(date_text, run_id)
        if prefix:
            prefix = f"{prefix}/"
        route_ids = set()
        try:
            for blob in self._list_blobs(prefix):
                relative_name = blob.name[len(prefix) :]
                parts = relative_name.split("/")
                if len(parts) == 2 and parts[1] == "daily_snapshot.json":
                    route_ids.add(parts[0])
        except Exception as error:
            if self.fallback_store is None:
                raise EvidenceNotFoundError(f"Unable to list GCS routes for {date_text}: {error}") from error

        if route_ids:
            return sorted(route_ids)
        if self.fallback_store is not None:
            return self.fallback_store.route_ids(date_text, run_id)
        raise EvidenceNotFoundError(f"No predictions found for {date_text}")

    def load_snapshot(self, route_id, run_date=None, run_id=None):
        date_text = self.resolve_date(run_date)
        base_prefix = self._base_prefix(date_text, run_id)
        evidence_object_name = f"{base_prefix}/{route_id}/evidence.json"
        try:
            return evidence_package.snapshot_from_evidence(json.loads(self._download_text(evidence_object_name)))
        except EvidenceNotFoundError:
            pass

        object_name = f"{base_prefix}/{route_id}/daily_snapshot.json"
        try:
            return json.loads(self._download_text(object_name))
        except EvidenceNotFoundError:
            if self.fallback_store is not None:
                return self.fallback_store.load_snapshot(route_id, date_text, run_id)
            raise

    def load_text_artifact(self, route_id, artifact_name, run_date=None, run_id=None):
        date_text = self.resolve_date(run_date)
        object_name = f"{self._base_prefix(date_text, run_id)}/{route_id}/{artifact_name}"
        try:
            return self._download_text(object_name)
        except EvidenceNotFoundError:
            if self.fallback_store is not None:
                return self.fallback_store.load_text_artifact(route_id, artifact_name, date_text, run_id)
            raise

    def load_binary_artifact(self, route_id, artifact_name, run_date=None, run_id=None):
        date_text = self.resolve_date(run_date)
        object_name = f"{self._base_prefix(date_text, run_id)}/{route_id}/{artifact_name}"
        try:
            return self._download_bytes(object_name)
        except EvidenceNotFoundError:
            if self.fallback_store is not None:
                return self.fallback_store.load_binary_artifact(route_id, artifact_name, date_text, run_id)
            raise

    def load_map_index(self, variable, run_date=None, run_id=None):
        date_text = self.resolve_date(run_date)
        object_name = f"{self._base_prefix(date_text, run_id)}/maps/{variable}/index.json"
        try:
            return json.loads(self._download_text(object_name))
        except EvidenceNotFoundError:
            if self.fallback_store is not None:
                return self.fallback_store.load_map_index(variable, date_text, run_id)
            raise

    def load_map_overlay(self, variable, filename, run_date=None, run_id=None):
        date_text = self.resolve_date(run_date)
        object_name = f"{self._base_prefix(date_text, run_id)}/maps/{variable}/{filename}"
        try:
            return self._download_bytes(object_name)
        except EvidenceNotFoundError:
            if self.fallback_store is not None:
                return self.fallback_store.load_map_overlay(variable, filename, date_text, run_id)
            raise

    def load_map_grid(self, variable, filename, run_date=None, run_id=None):
        date_text = self.resolve_date(run_date)
        object_name = f"{self._base_prefix(date_text, run_id)}/maps/{variable}/{filename}"
        try:
            return json.loads(self._download_text(object_name))
        except EvidenceNotFoundError:
            if self.fallback_store is not None:
                return self.fallback_store.load_map_grid(variable, filename, date_text, run_id)
            raise

    def load_regional_evidence(self, run_date=None, run_id=None):
        date_text = self.resolve_date(run_date)
        object_name = f"{self._base_prefix(date_text, run_id)}/regional_evidence.json"
        try:
            return json.loads(self._download_text(object_name))
        except EvidenceNotFoundError:
            if self.fallback_store is not None:
                return self.fallback_store.load_regional_evidence(date_text, run_id)
            raise

    def load_place_weather(self, place_id, run_date=None, run_id=None):
        date_text = self.resolve_date(run_date)
        object_name = f"{self._base_prefix(date_text, run_id)}/places/{place_id}/weather.json"
        try:
            return json.loads(self._download_text(object_name))
        except EvidenceNotFoundError:
            if self.fallback_store is not None:
                return self.fallback_store.load_place_weather(place_id, date_text, run_id)
            raise

    def load_publication_status(self, run_date=None, run_id=None):
        date_text = self.resolve_date(run_date)
        resolved_run = self.resolve_run(date_text, run_id)
        candidates = []
        if resolved_run:
            candidates.append(
                self._object_name(
                    date_text,
                    "runs",
                    resolved_run,
                    "publication_status.json",
                )
            )
        candidates.append(self._object_name(date_text, "latest_status.json"))
        for object_name in candidates:
            try:
                payload = json.loads(self._download_text(object_name))
                if not resolved_run or payload.get("run_id") == resolved_run:
                    return payload
            except EvidenceNotFoundError:
                continue
        if self.fallback_store is not None:
            return self.fallback_store.load_publication_status(date_text, resolved_run)
        raise EvidenceNotFoundError(f"No publication status found for {date_text}")

    def signed_artifact_url(self, route_id, artifact_name, run_date=None, run_id=None, expires_minutes=30):
        date_text = self.resolve_date(run_date)
        object_name = f"{self._base_prefix(date_text, run_id)}/{route_id}/{artifact_name}"
        bucket = self.client.bucket(self.bucket_name)
        blob = bucket.blob(object_name)
        if not blob.exists():
            if self.fallback_store is not None:
                return self.fallback_store.signed_artifact_url(
                    route_id,
                    artifact_name,
                    date_text,
                    run_id,
                    expires_minutes=expires_minutes,
                )
            raise EvidenceNotFoundError(f"No GCS object found at gs://{self.bucket_name}/{object_name}")
        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=expires_minutes),
            method="GET",
        )


class _S3Object:
    def __init__(self, client, bucket_name, name):
        self._client, self._bucket, self.name = client, bucket_name, name

    def exists(self):
        try:
            self._client.head_object(Bucket=self._bucket, Key=self.name)
            return True
        except Exception as error:
            code = getattr(error, "response", {}).get("Error", {}).get("Code")
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def download_as_text(self, encoding="utf-8"):
        return self._client.get_object(Bucket=self._bucket, Key=self.name)["Body"].read().decode(encoding)

    def download_as_bytes(self):
        return self._client.get_object(Bucket=self._bucket, Key=self.name)["Body"].read()

    def download_to_filename(self, filename):
        self._client.download_file(self._bucket, self.name, filename)

    def generate_signed_url(self, version=None, expiration=None, method="GET"):
        seconds = int(expiration.total_seconds()) if expiration else 1800
        return self._client.generate_presigned_url("get_object", Params={"Bucket": self._bucket, "Key": self.name}, ExpiresIn=seconds)


class _S3Bucket:
    def __init__(self, client, name): self._client, self.name = client, name
    def blob(self, name): return _S3Object(self._client, self.name, name)


class _S3Iterator(list):
    def __init__(self, values, prefixes=()): super().__init__(values); self.prefixes = set(prefixes)


class _S3ClientAdapter:
    """Minimal google-storage-shaped adapter used by the shared evidence logic."""
    def __init__(self, client): self._client = client
    def bucket(self, name): return _S3Bucket(self._client, name)
    def list_blobs(self, bucket, prefix="", delimiter=None):
        paginator = self._client.get_paginator("list_objects_v2")
        kwargs = {"Bucket": bucket, "Prefix": prefix}
        if delimiter: kwargs["Delimiter"] = delimiter
        objects, prefixes = [], []
        for page in paginator.paginate(**kwargs):
            objects.extend(_S3Object(self._client, bucket, item["Key"]) for item in page.get("Contents", []))
            prefixes.extend(item["Prefix"] for item in page.get("CommonPrefixes", []))
        return _S3Iterator(objects, prefixes)


class S3EvidenceStore(GcsEvidenceStore):
    def __init__(self, bucket_name, prefix=DEFAULT_GCS_PREFIX, client=None, fallback_store=None):
        if client is None:
            import boto3
            client = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "eu-west-1"))
        super().__init__(bucket_name, prefix, _S3ClientAdapter(client), fallback_store)
        self.storage_backend = "s3"


def create_evidence_store_from_env():
    from api.config import PREDSEA_GCS_BUCKET, PREDSEA_S3_BUCKET, PREDSEA_STORAGE_BACKEND
    local_store = EvidenceStore()
    if PREDSEA_STORAGE_BACKEND == "local":
        return local_store
    if PREDSEA_STORAGE_BACKEND == "s3":
        if not PREDSEA_S3_BUCKET:
            raise RuntimeError("PREDSEA_S3_BUCKET is required when PREDSEA_STORAGE_BACKEND=s3")
        return S3EvidenceStore(
            bucket_name=PREDSEA_S3_BUCKET,
            prefix=os.environ.get("PREDSEA_S3_PREFIX", DEFAULT_GCS_PREFIX),
            fallback_store=local_store,
        )
    bucket_name = os.environ.get("PREDSEA_GCS_BUCKET") or PREDSEA_GCS_BUCKET
    if not bucket_name:
        return local_store
    return GcsEvidenceStore(
        bucket_name=bucket_name,
        prefix=os.environ.get("PREDSEA_GCS_PREFIX", DEFAULT_GCS_PREFIX),
        fallback_store=local_store,
    )
