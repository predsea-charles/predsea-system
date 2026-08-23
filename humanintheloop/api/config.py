import os

# PREDSEA_ENV: 'test' (default) or 'prod'
PREDSEA_ENV = os.environ.get("PREDSEA_ENV", "test").strip().lower()
if PREDSEA_ENV not in ("test", "prod"):
    PREDSEA_ENV = "test"

# Main GCS Bucket name resolution
DEFAULT_BASE_BUCKET = "predsea-daily-outputs"
PREDSEA_GCS_BUCKET = os.environ.get("PREDSEA_GCS_BUCKET") or f"{DEFAULT_BASE_BUCKET}-{PREDSEA_ENV}"
PREDSEA_S3_BUCKET = os.environ.get("PREDSEA_S3_BUCKET") or ""
PREDSEA_STORAGE_BACKEND = os.environ.get("PREDSEA_STORAGE_BACKEND", "s3" if PREDSEA_S3_BUCKET else "gcs").lower()

# BigQuery Dataset resolution
DEFAULT_BASE_DATASET = "predsea_validation"
PREDSEA_BIGQUERY_DATASET = os.environ.get("PREDSEA_BIGQUERY_DATASET") or f"{DEFAULT_BASE_DATASET}_{PREDSEA_ENV}"

# Precomputed routes static GCS folder
DEFAULT_ROUTE_GCS_PREFIX = f"gs://{PREDSEA_GCS_BUCKET}/routes"
DEFAULT_ROUTE_S3_PREFIX = f"s3://{PREDSEA_S3_BUCKET}/routes" if PREDSEA_S3_BUCKET else ""
