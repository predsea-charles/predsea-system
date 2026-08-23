#!/usr/bin/env bash
# PredSea GCP Environment Infrastructure Provisioning Script
# Idempotently creates GCS buckets, BigQuery datasets, Service Accounts,
# and assigns strict isolated IAM roles for "test" and "prod" environments.

set -euo pipefail

# Text coloring utilities
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}👉 [INFO] $1${NC}"
}

log_warn() {
    echo -e "${YELLOW}⚠️ [WARN] $1${NC}"
}

log_err() {
    echo -e "${RED}❌ [ERROR] $1${NC}"
}

# 1. Identify and verify active GCP Project
log_info "Identifying active Google Cloud Project..."
PROJECT_ID=$(gcloud config get-value project 2>/dev/null || true)

if [ -z "${PROJECT_ID}" ] || [ "${PROJECT_ID}" != "predsea-api" ]; then
    log_err "Active GCP Project ID is not 'predsea-api' (found: '${PROJECT_ID:-None}')."
    log_err "Please set the active project to 'predsea-api':"
    echo "  gcloud config set project predsea-api"
    exit 1
fi

log_info "Verified GCP Project: ${PROJECT_ID}"

# Resolve project number dynamically for default compute service account
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)" 2>/dev/null || echo "193957983101")
DEFAULT_COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
log_info "Resolved Default Compute Service Account: ${DEFAULT_COMPUTE_SA}"

REGION="europe-west1"
BQ_LOCATION="EU"
BASE_BUCKET="predsea-daily-outputs"
BASE_DATASET="predsea_validation"

ENVIRONMENTS=("test" "prod")

# 2. Provision GCS Buckets & Sync Static Data
for ENV in "${ENVIRONMENTS[@]}"; do
    BUCKET_NAME="${BASE_BUCKET}-${ENV}"
    log_info "Checking GCS Bucket: gs://${BUCKET_NAME}..."
    
    # Check if bucket exists
    if ! gcloud storage buckets describe "gs://${BUCKET_NAME}" >/dev/null 2>&1; then
        log_info "Creating bucket gs://${BUCKET_NAME} in ${REGION} with uniform bucket-level access..."
        gcloud storage buckets create "gs://${BUCKET_NAME}" \
            --project="${PROJECT_ID}" \
            --location="${REGION}" \
            --uniform-bucket-level-access
    else
        log_info "GCS Bucket gs://${BUCKET_NAME} already exists."
    fi

    # Update labels
    log_info "Updating GCS bucket labels for gs://${BUCKET_NAME}..."
    gcloud storage buckets update "gs://${BUCKET_NAME}" --update-labels="env=${ENV}"
    
    # Sync static data from original bucket if it exists and target doesn't have it
    for DIR in "static" "routes"; do
        log_info "Checking static directory '/${DIR}/' in gs://${BUCKET_NAME}..."
        # If target directory is empty, sync from original bucket
        if ! gcloud storage ls "gs://${BUCKET_NAME}/${DIR}/" >/dev/null 2>&1; then
            log_info "Syncing gs://${BASE_BUCKET}/${DIR}/ to gs://${BUCKET_NAME}/${DIR}/..."
            gcloud storage cp -r "gs://${BASE_BUCKET}/${DIR}" "gs://${BUCKET_NAME}/" || log_warn "Could not sync gs://${BASE_BUCKET}/${DIR} (maybe not present or permission issue)."
        else
            log_info "Static directory '/${DIR}/' already exists in gs://${BUCKET_NAME}."
        fi
    done
done

# 3. Provision BigQuery Datasets & Copy Tables
for ENV in "${ENVIRONMENTS[@]}"; do
    DATASET_NAME="${BASE_DATASET}_${ENV}"
    log_info "Checking BigQuery Dataset: ${DATASET_NAME}..."
    
    # Check if dataset exists
    if ! bq show --project_id="${PROJECT_ID}" "${DATASET_NAME}" >/dev/null 2>&1; then
        log_info "Creating BigQuery Dataset ${DATASET_NAME} in location ${BQ_LOCATION}..."
        bq mk --dataset \
              --project_id="${PROJECT_ID}" \
              --location="${BQ_LOCATION}" \
              --description="PredSea ${ENV} environment validation dataset" \
              --label="env:${ENV}" \
              "${DATASET_NAME}"
    else
        log_info "BigQuery Dataset ${DATASET_NAME} already exists."
    fi

    # Copy/bootstrap tables and schemas from base dataset
    TABLES=("climatology_baseline" "evidence_rows" "model_bias" "station_metadata" "universal_telemetry_baseline")
    for TABLE in "${TABLES[@]}"; do
        SRC_TABLE="${PROJECT_ID}:${BASE_DATASET}.${TABLE}"
        DEST_TABLE="${PROJECT_ID}:${DATASET_NAME}.${TABLE}"
        
        log_info "Checking table ${DEST_TABLE}..."
        if ! bq show "${DEST_TABLE}" >/dev/null 2>&1; then
            log_info "Bootstrapping table ${DEST_TABLE} by copying from ${SRC_TABLE}..."
            bq cp -f "${SRC_TABLE}" "${DEST_TABLE}"
        else
            log_info "Table ${DEST_TABLE} already exists. Skipping copy."
        fi
    done
done

# 4. Provision Service Accounts
for ENV in "${ENVIRONMENTS[@]}"; do
    API_SA_NAME="predsea-api-${ENV}"
    API_SA_EMAIL="${API_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
    
    log_info "Checking API Service Account: ${API_SA_EMAIL}..."
    if ! gcloud iam service-accounts describe "${API_SA_EMAIL}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
        log_info "Creating API Service Account: ${API_SA_NAME}..."
        gcloud iam service-accounts create "${API_SA_NAME}" \
            --project="${PROJECT_ID}" \
            --display-name="PredSea API Service Account - ${ENV}"
    else
        log_info "API Service Account ${API_SA_EMAIL} already exists."
    fi

    ETL_SA_NAME="predsea-etl-${ENV}"
    ETL_SA_EMAIL="${ETL_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
    
    log_info "Checking ETL Service Account: ${ETL_SA_EMAIL}..."
    if ! gcloud iam service-accounts describe "${ETL_SA_EMAIL}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
        log_info "Creating ETL Service Account: ${ETL_SA_NAME}..."
        gcloud iam service-accounts create "${ETL_SA_NAME}" \
            --project="${PROJECT_ID}" \
            --display-name="PredSea ETL Service Account - ${ENV}"
    else
        log_info "ETL Service Account ${ETL_SA_EMAIL} already exists."
    fi
done

# 5. Apply Strict IAM Permissions and Isolation Constraints
for ENV in "${ENVIRONMENTS[@]}"; do
    API_SA_EMAIL="predsea-api-${ENV}@${PROJECT_ID}.iam.gserviceaccount.com"
    ETL_SA_EMAIL="predsea-etl-${ENV}@${PROJECT_ID}.iam.gserviceaccount.com"
    ENV_BUCKET="gs://${BASE_BUCKET}-${ENV}"
    ENV_DATASET="${BASE_DATASET}_${ENV}"

    log_info "========================================================="
    log_info "Applying Isolated IAM Permissions for [${ENV}] Environment"
    log_info "========================================================="

    # --- API Service Account Permissions ---
    log_info "Granting Project-level roles to API Service Account: ${API_SA_EMAIL}..."
    # API SA needs bigquery.jobUser on the project to run queries
    gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
        --member="serviceAccount:${API_SA_EMAIL}" \
        --role="roles/bigquery.jobUser" \
        --quiet >/dev/null

    log_info "Granting Bucket-level roles to API Service Account on ${ENV_BUCKET}..."
    # API SA needs storage.objectViewer on its environment bucket
    gcloud storage buckets add-iam-policy-binding "${ENV_BUCKET}" \
        --member="serviceAccount:${API_SA_EMAIL}" \
        --role="roles/storage.objectViewer" \
        --quiet >/dev/null

    log_info "Granting Dataset-level roles to API Service Account on BigQuery dataset: ${ENV_DATASET}..."
    # API SA needs bigquery.dataViewer on its environment dataset
    .venv311/bin/python infra/update_bq_access.py "${ENV_DATASET}" "${API_SA_EMAIL}" READER

    # --- ETL Service Account Permissions ---
    log_info "Granting Project-level roles to ETL Service Account: ${ETL_SA_EMAIL}..."
    # ETL SA needs bigquery.jobUser on the project to run queries
    gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
        --member="serviceAccount:${ETL_SA_EMAIL}" \
        --role="roles/bigquery.jobUser" \
        --quiet >/dev/null

    # ETL SA needs compute.instanceAdmin to spin up/tear down simulation VMs
    gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
        --member="serviceAccount:${ETL_SA_EMAIL}" \
        --role="roles/compute.instanceAdmin" \
        --quiet >/dev/null

    # ETL SA needs iam.serviceAccountUser on default compute SA to run VM tasks as default compute service account
    gcloud iam service-accounts add-iam-policy-binding "${DEFAULT_COMPUTE_SA}" \
        --project="${PROJECT_ID}" \
        --member="serviceAccount:${ETL_SA_EMAIL}" \
        --role="roles/iam.serviceAccountUser" \
        --quiet >/dev/null

    log_info "Granting Bucket-level roles to ETL Service Account on ${ENV_BUCKET}..."
    # ETL SA needs storage.objectAdmin on its environment bucket
    gcloud storage buckets add-iam-policy-binding "${ENV_BUCKET}" \
        --member="serviceAccount:${ETL_SA_EMAIL}" \
        --role="roles/storage.objectAdmin" \
        --quiet >/dev/null

    log_info "Granting Dataset-level roles to ETL Service Account on BigQuery dataset: ${ENV_DATASET}..."
    # ETL SA needs bigquery.dataEditor on its environment dataset
    .venv311/bin/python infra/update_bq_access.py "${ENV_DATASET}" "${ETL_SA_EMAIL}" WRITER
done

log_info "Environment Infrastructure successfully provisioned! 🎉"
