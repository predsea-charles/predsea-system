# Runbook: getting a real WRF/CROCO/NEMO/SWAN run validated (not simulated)

This is the part of the July 2 fix that can't be done from a sandboxed environment
without your GCP credentials — it has to run on your machine (or CI) with real
`gcloud`/`GOOGLE_APPLICATION_CREDENTIALS` access and will spend real credit.

As of the second correction pass (also July 2), `scripts/daily_orchestrator.py` —
the script actually wired to the `0 5 * * *` (05:00 Europe/Madrid) Cloud Scheduler
job created by `infra/deploy.sh` — automatically runs the whole chain: boundary
fetch, Spot VM launch, ingestion for **WRF, CROCO, NEMO, and SWAN** (not ROMS —
`roms_forecast_ingestor.py` exists but isn't called by the scheduled job), the
daily briefing, the climatology anomaly check, and now a real model-comparison
step. So most of this runbook describes what happens automatically and how to
check it worked — not manual steps you need to run every day.

The simulation launcher tries Spot capacity across `europe-west1-b/c/d` using
`c2d-standard-56`, `c2d-standard-32`, `c2d-standard-16`, and
`c2-standard-16`. If every Spot candidate is unavailable, its final candidate
is a regular on-demand `c2-standard-16` VM. A confirmed Compute Engine Spot
preemption retries the whole VM workload twice by default. Replacement VMs use
the same run ID and reuse the ECMWF/CMEMS forcing and runtime configuration
already archived in GCS; WRF computation itself restarts from the beginning.
Override the retry count with `--preemption-retries`.
The deployment scripts give the Cloud Run job a 14-hour task envelope so the
default three-attempt policy can complete while retaining the four-hour limit
for each individual VM attempt.

`hpc_cost_summary.py` is deliberately **not** wired into the automatic run (your
call) — run it manually per Section 5 if/when you want a cost report.

## 0. Before you spend anything

- Confirm your project/billing account: `gcloud config get-value project` should show your real project (per `humanintheloop/docs/bigquery-evidence-rows.md`, the account used for backfills is `hello@predsea.com` — make sure you're not accidentally pointed at a different ADC identity).
- Confirm the WRF/WPS compile artifact from your June 23 Cloud Build run still exists (check whatever image/tag `scripts/vm_startup.sh` expects — `--image-tag latest` by default). If it's gone, you'll compile again before you can run.
- Confirm CROCO and NEMO are actually wired into `vm_startup.sh` and the production Dockerfile — `simulation/Dockerfile` only builds WRF/WPS as of this writing, so double check the image `--image-tag latest` actually points to before assuming CROCO/NEMO output will be there.

## 1. Trigger a real run

To exercise the exact path the 5am scheduler uses (boundaries → Spot VM → all four
ingestors → briefing → anomaly check → model comparison):

```bash
python scripts/daily_orchestrator.py \
  --project <your-project-id> \
  --run-date 2026-07-0X \
  --zone europe-west1-b \
  --machine-type c2d-standard-32 \
  --gcs-bucket predsea-daily-outputs
```

Or, to launch just the Spot VM and drive the rest yourself step by step (useful for
debugging a specific stage):

```bash
python scripts/gcp_orchestrator.py \
  --project <your-project-id> \
  --zone europe-west1-b \
  --machine-type c2d-standard-32 \
  --gcs-bucket predsea-daily-outputs \
  --run-date 2026-07-0X \
  --execution-mode container
```

Either way, write down the instance name and run-id printed — you'll need the
run-id if you re-run any single step manually later.

Monitor the VM (this is the exact command the script itself prints):

```bash
gcloud compute instances get-serial-port-output <instance-name> --zone=europe-west1-b --project=<your-project-id>
```

Watch the serial log for early exits, not just the final "instance deleted"
state. The orchestrator distinguishes a preemption from an application exit by
querying the `compute.instances.preempted` audit event: only a confirmed
preemption is retried automatically. An application failure without `SUCCESS`
still fails immediately so deterministic model errors are not repeated.

## 2. Confirm real output landed in GCS

```bash
gsutil ls -r gs://predsea-daily-outputs/predictions/<run-date>/runs/<run-id>/
```

You're looking for `.nc`/`.nc4` files whose names contain `d03` or `wrfout` (WRF),
`croco`/`his`/`avg` (CROCO), `nemo` (NEMO), or `swan`/`wave` (SWAN) — those are the
exact patterns `scripts/*_forecast_ingestor.py` search for. If nothing matches, the
ingestors won't find anything even if the run technically succeeded — check the
actual filenames the model containers wrote and adjust the ingestor's
`download_*_file_from_gcs()` match patterns if they've drifted, rather than renaming
files by hand every time.

## 3. Confirm ingestion actually happened

If you ran `daily_orchestrator.py`, this already happened automatically (step "3b").
Confirm it in BigQuery:

```sql
SELECT provider, COUNT(*), MIN(target_time_utc), MAX(target_time_utc)
FROM `predsea_validation.evidence_rows`
WHERE record_type = 'forecast' AND run_date = '<run-date>'
GROUP BY provider
```

You should see rows for `predsea_wrf`, `predsea_croco`, `predsea_nemo`, and
`predsea_swan`. If you need to re-run a single ingestor by hand (e.g. after fixing a
filename-matching issue):

```bash
export PREDSEA_ENV=prod
export GOOGLE_CLOUD_PROJECT=<your-project-id>
export PREDSEA_BIGQUERY_DATASET=predsea_validation

python scripts/wrf_forecast_ingestor.py   --run-date <run-date> --run-id <run-id> --gcs-bucket predsea-daily-outputs
python scripts/croco_forecast_ingestor.py --run-date <run-date> --run-id <run-id> --gcs-bucket predsea-daily-outputs
python scripts/nemo_forecast_ingestor.py  --run-date <run-date> --run-id <run-id> --gcs-bucket predsea-daily-outputs
python scripts/swan_forecast_ingestor.py  --run-date <run-date> --run-id <run-id> --gcs-bucket predsea-daily-outputs
```

Add `--dry-run` first to sanity-check the parsed rows (including the
`latitude`/`longitude` fields added 2026-07-02) before writing to BigQuery.

## 4. The real comparison (also automatic now, step 6 of the orchestrator)

If you ran `daily_orchestrator.py`, `humanintheloop/scripts/model_comparison.py`
already ran as step 6 and uploaded `accuracy_comparison.json` to
`gs://predsea-hpc-outputs/reports/<run-date>/`. To re-run it manually (e.g. to
backfill an earlier date, or with different matching tolerances):

```bash
cd humanintheloop
python scripts/model_comparison.py --date <run-date> --project <your-project-id> --dataset predsea_validation
```

Expect one of a few honest outcomes, not automatically a win:
- `no_forecast_data` — step 3 didn't actually write rows for that date; check the BigQuery query above.
- `no_nearby_stations` — your forecast sampling points aren't within 25nm of a station in `station_metadata`; widen `--max-station-distance-nm` or check that table has real recent rows.
- A real report where `variables.<name>.<provider>` shows `"status": "compared"` with real RMSE/bias/correlation for some (variable, model) pairs, and `"insufficient_sample_size"` for others if you don't have 5+ matched pairs yet. Note **CROCO and NEMO are reported separately** even for the same physical variable (e.g. `current_speed`) — they're two different models the orchestrator runs in parallel, not two names for the same run. This is normal for a first run — one day of hourly data gives at most ~24 points per (variable, model, station), and buoy coverage is uneven.

## 5. Cost reporting (optional, manual, not wired into the automatic run)

By your own call, `hpc_cost_summary.py` is not part of the automatic daily run. If
you want a real cost number for a given day, run it manually:

```bash
python humanintheloop/scripts/hpc_cost_summary.py --date <run-date>
```

If you didn't separately log `reports/<run-date>/{wrf,croco,nemo,swan}_cost.json` or
`_runtime.json` to GCS during the run, this correctly says `no_real_cost_recorded`
rather than guessing — to get a real cost, capture the VM's actual runtime
(start/end timestamps from the serial log in step 1) and drop a small
`{"vm_type": "...", "wallclock_minutes": ...}` JSON at
`gs://predsea-hpc-outputs/reports/<run-date>/wrf_runtime.json` (etc.) before
rerunning — it'll turn that into a labeled estimate automatically.

## 6. What "done" looks like

Not "12/12 wins" — a report you could hand to Google's engineer or your own team
that says, for however many (variable, model) pairs had enough real data: real
sample size, real RMSE, real bias, which real station it was checked against. If
`daily_orchestrator.py` runs clean tonight, you'll have this automatically every
morning without touching anything.
