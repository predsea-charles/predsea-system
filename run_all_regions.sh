#!/usr/bin/env bash
set -euo pipefail

echo "========================================================================="
echo "🚀 Launching All 5 Western Mediterranean CROCO Shards (v20)"
echo "========================================================================="

.venv/bin/python3 scripts/submit_gcp_batch_simulation.py \
  --region balearic_1km --model croco --forecast-hours 72 \
  --image-uri europe-west1-docker.pkg.dev/predsea-api/predsea-simulations/croco-batch@sha256:f8313ce5d43624d055321ba769f7a7da315c6aad5c7e16c30ab10ba063953ba8 \
  --wrf-gcs-uri gs://predsea-daily-outputs-test/predictions/2026-07-16/runs/2026-07-16T0733Z \
  --run-date 2026-07-16 --project predsea-api --location europe-west1 \
  --run-id 2026-07-27-croco-balearic-72h-dt30-ndtfast45 \
  --croco-timestep-seconds 30 --croco-ndtfast 45 \
  --machine-type c2d-highcpu-16 --cpu-milli 16000 --memory-mib 32768 --mpi-ranks 16 --provisioning-model STANDARD

.venv/bin/python3 scripts/submit_gcp_batch_simulation.py \
  --region algerian_1km --model croco --forecast-hours 72 \
  --image-uri europe-west1-docker.pkg.dev/predsea-api/predsea-simulations/croco-batch@sha256:f8313ce5d43624d055321ba769f7a7da315c6aad5c7e16c30ab10ba063953ba8 \
  --wrf-gcs-uri gs://predsea-daily-outputs-test/predictions/2026-07-16/runs/2026-07-16T0733Z \
  --run-date 2026-07-16 --project predsea-api --location europe-west1 \
  --run-id 2026-07-27-croco-algerian-72h-dt30-ndtfast45 \
  --croco-timestep-seconds 30 --croco-ndtfast 45 \
  --machine-type c2d-highcpu-16 --cpu-milli 16000 --memory-mib 32768 --mpi-ranks 16 --provisioning-model STANDARD

.venv/bin/python3 scripts/submit_gcp_batch_simulation.py \
  --region tyrrhenian_1km --model croco --forecast-hours 72 \
  --image-uri europe-west1-docker.pkg.dev/predsea-api/predsea-simulations/croco-batch@sha256:f8313ce5d43624d055321ba769f7a7da315c6aad5c7e16c30ab10ba063953ba8 \
  --wrf-gcs-uri gs://predsea-daily-outputs-test/predictions/2026-07-16/runs/2026-07-16T0733Z \
  --run-date 2026-07-16 --project predsea-api --location europe-west1 \
  --run-id 2026-07-27-croco-tyrrhenian-72h-dt30-ndtfast45 \
  --croco-timestep-seconds 30 --croco-ndtfast 45 \
  --machine-type c2d-highcpu-16 --cpu-milli 16000 --memory-mib 32768 --mpi-ranks 16 --provisioning-model STANDARD

.venv/bin/python3 scripts/submit_gcp_batch_simulation.py \
  --region alboran_1km --model croco --forecast-hours 72 \
  --image-uri europe-west1-docker.pkg.dev/predsea-api/predsea-simulations/croco-batch@sha256:f8313ce5d43624d055321ba769f7a7da315c6aad5c7e16c30ab10ba063953ba8 \
  --wrf-gcs-uri gs://predsea-daily-outputs-test/predictions/2026-07-16/runs/2026-07-16T0733Z \
  --run-date 2026-07-16 --project predsea-api --location europe-west1 \
  --run-id 2026-07-27-croco-alboran-72h-dt30-ndtfast45 \
  --croco-timestep-seconds 30 --croco-ndtfast 45 \
  --machine-type c2d-highcpu-16 --cpu-milli 16000 --memory-mib 32768 --mpi-ranks 16 --provisioning-model STANDARD

.venv/bin/python3 scripts/submit_gcp_batch_simulation.py \
  --region gulf_of_lion_1km --model croco --forecast-hours 72 \
  --image-uri europe-west1-docker.pkg.dev/predsea-api/predsea-simulations/croco-batch@sha256:f8313ce5d43624d055321ba769f7a7da315c6aad5c7e16c30ab10ba063953ba8 \
  --wrf-gcs-uri gs://predsea-daily-outputs-test/predictions/2026-07-16/runs/2026-07-16T0733Z \
  --run-date 2026-07-16 --project predsea-api --location europe-west1 \
  --run-id 2026-07-27-croco-gulf_of_lion-72h-dt30-ndtfast45 \
  --croco-timestep-seconds 30 --croco-ndtfast 45 \
  --machine-type c2d-highcpu-16 --cpu-milli 16000 --memory-mib 32768 --mpi-ranks 16 --provisioning-model STANDARD

wait
echo "========================================================================="
echo "✅ All 5 Western Mediterranean regional jobs successfully submitted to GCP Batch!"
echo "========================================================================="
