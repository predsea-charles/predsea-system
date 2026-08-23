#!/usr/bin/env bash
# PredSea GCP Serverless Deployment Script (Option A)
# Automates Cloud Build image generation, Cloud Run Job setup, and Scheduler trigger creation.

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

# 1. Identify GCP Project
log_info "Identifying active Google Cloud Project..."
PROJECT_ID="${PREDSEA_GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"

if [ -z "${PROJECT_ID}" ]; then
    log_err "No active Google Cloud Project found. Please login and configure your project first:"
    echo "  gcloud auth login"
    echo "  gcloud config set project [PROJECT_ID]"
    exit 1
fi

log_info "Active GCP Project ID: ${PROJECT_ID}"

REGION="europe-west1"
IMAGE_NAME="europe-west1-docker.pkg.dev/${PROJECT_ID}/cloud-run-source-deploy/predsea-api:latest"

# 2. Build the unified container image using Cloud Build
log_info "Submitting build to Google Cloud Build (Remote compilation)..."
gcloud builds submit --project="${PROJECT_ID}" --region="${REGION}" --default-buckets-behavior="regional-user-owned-bucket" --tag "${IMAGE_NAME}" .

# 3. Securely Load Environment Variables for API Integrations (CMEMS, AEMET, SOCIB)
# Sensitive credentials are mounted from Secret Manager via --set-secrets (below),
# never as plaintext --set-env-vars, so `gcloud run jobs describe` / `services describe`
# can no longer print their actual values. Prerequisite: the secrets referenced in
# secret_name_for_key() must already exist (gcloud secrets create ...), and the
# service account used here must have roles/secretmanager.secretAccessor on them.
is_sensitive_key() {
    case "$1" in
        AEMET_API_KEY|SOCIB_API_KEY|COPERNICUS_PASSWORD|COPERNICUSMARINE_SERVICE_PASSWORD|GOOGLE_AGENT_PLATFORM_API|GOOGLE_AGENT_PLATFORM_API_2)
            return 0 ;;
        *)
            return 1 ;;
    esac
}

secret_name_for_key() {
    case "$1" in
        AEMET_API_KEY) echo "aemet-api-key" ;;
        SOCIB_API_KEY) echo "socib-api-key" ;;
        COPERNICUS_PASSWORD|COPERNICUSMARINE_SERVICE_PASSWORD) echo "copernicus-password" ;;
        GOOGLE_AGENT_PLATFORM_API) echo "google-agent-platform-api" ;;
        GOOGLE_AGENT_PLATFORM_API_2) echo "google-agent-platform-api-2" ;;
    esac
}

ENV_VARS="GOOGLE_CLOUD_PROJECT=${PROJECT_ID}"
SECRET_VARS=""
if [ -f "humanintheloop/.env" ]; then
    log_info "Loading environment variables from humanintheloop/.env..."
    while IFS= read -r line || [ -n "$line" ]; do
        # Skip comments and empty lines
        if [[ ! "$line" =~ ^# ]] && [[ ! "$line" =~ ^$ ]]; then
            key="${line%%=*}"
            if is_sensitive_key "$key"; then
                # Routed through Secret Manager instead; never carried as plaintext.
                continue
            fi
            # Map COPERNICUS_USERNAME to the SDK's expected variable name too (not sensitive)
            if [[ "$line" =~ ^COPERNICUS_USERNAME= ]]; then
                val="${line#COPERNICUS_USERNAME=}"
                line="COPERNICUS_USERNAME=$val,COPERNICUSMARINE_SERVICE_USERNAME=$val"
            fi

            if [ -z "$ENV_VARS" ]; then
                ENV_VARS="$line"
            else
                ENV_VARS="$ENV_VARS,$line"
            fi
        fi
    done < "humanintheloop/.env"
fi

for key in AEMET_API_KEY SOCIB_API_KEY COPERNICUS_PASSWORD COPERNICUSMARINE_SERVICE_PASSWORD GOOGLE_AGENT_PLATFORM_API GOOGLE_AGENT_PLATFORM_API_2; do
    secret_name="$(secret_name_for_key "$key")"
    if [ -z "$SECRET_VARS" ]; then
        SECRET_VARS="${key}=${secret_name}:latest"
    else
        SECRET_VARS="${SECRET_VARS},${key}=${secret_name}:latest"
    fi
done
log_info "Sensitive credentials will be mounted from Secret Manager: ${SECRET_VARS}"

# Append standard GCS bucket and prefix environment variables if they are not already set
ENV_VARS="$ENV_VARS,PREDSEA_GCS_BUCKET=predsea-daily-outputs,PREDSEA_GCS_PREFIX=predictions,PREDSEA_BIGQUERY_DATASET=predsea_validation,PREDSEA_ENV=prod"

log_info "Deploying the serverless Cloud Run Service: 'predsea-api'..."
gcloud run deploy predsea-api \
    --project "${PROJECT_ID}" \
    --image "${IMAGE_NAME}" \
    --region "${REGION}" \
    --allow-unauthenticated \
    --memory 4Gi \
    --cpu 2 \
    --min-instances=1 \
    ${ENV_VARS:+--set-env-vars="$ENV_VARS"} \
    ${SECRET_VARS:+--set-secrets="$SECRET_VARS"} \
    --quiet

log_info "Cloud Run Service 'predsea-api' is now deployed and active!"

log_info "Deploying the serverless Cloud Run Job: 'daily-orchestrator'..."
gcloud run jobs deploy daily-orchestrator \
    --project "${PROJECT_ID}" \
    --image "${IMAGE_NAME}" \
    --command "python" \
    --args "scripts/daily_orchestrator.py" \
    --region "${REGION}" \
    --max-retries 0 \
    --task-timeout 14h \
    --cpu 2 \
    --memory 8Gi \
    ${ENV_VARS:+--set-env-vars="$ENV_VARS"} \
    ${SECRET_VARS:+--set-secrets="$SECRET_VARS"} \
    --quiet

log_info "Cloud Run Job 'daily-orchestrator' is now deployed and ready!"

# 4. Provide instructions for Cloud Scheduler Trigger
log_info "Deployment Successful! 🎉"
echo "========================================================="
echo -e "To schedule the orchestrator to run automatically every day,"
echo -e "you can create a Cloud Scheduler job with the following command:"
echo "========================================================="
echo ""
echo "gcloud scheduler jobs create http daily-forecaster-trigger \\"
echo "  --schedule=\"0 5 * * *\" \\"
echo "  --time-zone=\"Europe/Madrid\" \\"
echo "  --uri=\"https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/daily-orchestrator:run\" \\"
echo "  --http-method=POST \\"
echo "  --oauth-service-account-email=\"[YOUR_SERVICE_ACCOUNT_EMAIL]\" \\"
echo "  --location=\"${REGION}\""
echo ""
echo "========================================================="
echo -e "To execute a manual run of the deployed job immediately:"
echo "========================================================="
echo "  gcloud run jobs execute daily-orchestrator --region=${REGION}"
echo "========================================================="
