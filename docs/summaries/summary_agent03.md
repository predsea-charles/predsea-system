Executive Summary
The ETL/data-contract audit fails. The pipeline has strong validation in several isolated adapters, but the full AWS chain can still accept stale, incomplete, or cross-run data.
Most significant issues:
- The pre-compute CMEMS download is a 2-D product that cannot satisfy CROCO’s required 3-D contract.
- WW3 forcing is scoped only by date and region, not run ID.
- WW3 output completion checks can mistake the input wind.nc for model output.
- WW3 forcing does not validate timestamp count, continuity, forecast window, variables, units, or spatial coverage.
- Athena exports are append-only and omit run_id, preventing reliable run-level lineage.
- A run can publish SUCCEEDED even when Athena export produces no rows.
Data Flow
Actual AWS flow traced:
ECMWF GRIB2
  → WPS: split by valid time → ungrib → geogrid → metgrid
  → WRF hourly wrfout_d01/d02 files
  ├─→ WRF-to-CROCO bulk forcing
  │    → croco_blk.nc + croco_frc.nc
  ├─→ WRF-to-WW3 interpolation
  │    → per-region wind.nc + WW3 namelists
  └─→ CROCO

Generic CMEMS 2-D file
  → rejected by CROCO staging
  → region-specific 3-D CMEMS products downloaded during EC2 execution
  → croco_ini.nc + croco_clm.nc + croco_bry.nc
  → CROCO history output
  → regional S3 output

WW3 grid + date-scoped wind.nc
  → ww3_prnc → ww3_shel → ww3_ounf
  → regional S3 output

Briefing/validation JSONL
  → normalized Parquet
  → S3 warehouse
  → Glue/Athena
  → API
No implemented CMEMS wave-boundary input was found in the AWS WW3 path.
Data Contracts
Product	Producer → Consumer	Contract actually enforced
ECMWF forcing	ECMWF → WPS	GRIB2; pressure z,t,r,u,v; surface/wind/soil fields; 3-hour steps; cycle and valid-time validation
WRF output	WRF → CROCO/WW3	NetCDF wrfout_d02_*; CROCO requires 73 files and exact hourly timestamps; WW3 does not
Generic CMEMS	CMEMS ETL → CROCO	Default 2-D hourly product; only non-empty file checked
Native CMEMS	CMEMS → CROCO adapter	uo,vo,thetao,so,zos; hourly start/end/count; region bbox; SHA-256 manifest
CROCO forcing	adapters → CROCO	NetCDF initial, boundary, climatology, bulk and SST forcing; finite-value checks
CROCO output	CROCO → S3	Required variables, count, interval, bbox, finite fraction and configured ranges
WW3 wind	WRF adapter → WW3	NetCDF U,V(time,latitude,longitude); manifest generated but not consumed
WW3 output	WW3 → S3	Only existence of any *.nc
Athena evidence	validation JSONL → Athena/API	Parquet normalized to fixed columns, partition-like path by date; no run identifier


Time Handling
Positive controls:
- ECMWF cycle metadata and valid times are checked at [fetch_ecmwf_forcing.py (line 58)](/Users/charles.santana/PredSea/predsea-system/scripts/fetch_ecmwf_forcing.py:58).
- WPS checks every required three-hour intermediate timestamp at [run_pipeline.sh (line 110)](/Users/charles.santana/PredSea/predsea-system/simulation/run_pipeline.sh:110).
- WRF-to-CROCO requires an exact hourly sequence from 00Z through +72h at [prepare_croco_bulk_forcing.py (line 145)](/Users/charles.santana/PredSea/predsea-system/scripts/prepare_croco_bulk_forcing.py:145).
- Region-specific native CMEMS uses UTC-aware request bounds and checks exact first/last timestamps at [fetch_native_marine_forcing.py (line 167)](/Users/charles.santana/PredSea/predsea-system/scripts/fetch_native_marine_forcing.py:167).
Gaps:
- WW3 accepts filenames sorted lexically without verifying 73 timestamps, duplicates, monotonicity, hourly intervals, or requested start/end.
- ECMWF fallback provenance is recorded, but consumers do not read forcing_metadata.json.
- Generic CMEMS uses naive datetime objects and validates no timestamps.
Spatial Handling
- The five region profiles define distinct bounding boxes and compiled CROCO shapes.
- CROCO verifies the canonical grid’s region identity and compiled dimensions.
- Native CMEMS requests each regional bbox with a 0.5° buffer.
- WW3 wind interpolation generates a bbox-based regular grid, but does not verify that the WRF domain covers it. Nearest-neighbour extrapolation can therefore produce plausible values outside true WRF coverage.
- WW3 does not validate that mod_def.ww3, wind.nc, and the region profile describe the same grid.
Units and Variables
Known implemented units:
- CROCO bulk wind: m s-1
- Air/SST: Celsius
- Relative humidity: percent
- Precipitation: m s-1
- Radiation: W m-2
- WW3 wind values originate from WRF U10/V10, but output variables lack explicit unit attributes.
CROCO output range thresholds come from region profiles. Their scientific acceptance remains outside this code audit.
Freshness and Staleness Risks
- Date-scoped WW3 forcing is overwritten/merged across retries and concurrent runs.
- S3 synchronization does not remove old objects.
- Athena creates a new Parquet file on every export, accumulating rerun rows.
- Generic CMEMS --skip-if-exists accepts any non-empty local file without validating date, variables, region, or dataset version.
- latest_run.json is updated by briefing generation, but Athena rows cannot be tied to that run.
Completeness Checks
Strong:
- ECMWF message decoding, cycle, lead and valid-time checks.
- CROCO grid/region/dimension checks.
- Exact WRF hourly timeline for CROCO.
- Native CMEMS variable/count/start/end checks and checksums.
- CROCO output variable, count, interval and bbox checks.
Missing or inadequate:
- Prelaunch CMEMS 3-D validation.
- WW3 input manifest validation.
- WW3 output content validation.
- WW3 success-marker metadata.
- Athena row/schema completeness and run identity.
- Required evidence-row count before publication success.
- Checksums/version IDs for WW3 grids and wind inputs.
Findings
ETL-001 — HIGH: Pre-compute CMEMS product cannot satisfy CROCO
- Producer: fetch_cmems_forcing.py
- Consumer: CROCO staging
- Evidence: Default dataset is 2-D and variables are unrestricted at [fetch_cmems_forcing.py (line 23)](/Users/charles.santana/PredSea/predsea-system/scripts/fetch_cmems_forcing.py:23); validation checks only non-zero size at line 114. CROCO requires uo, vo, thetao, so, zos plus time, depth, latitude, longitude at [run_marine_simulation.py (line 198)](/Users/charles.santana/PredSea/predsea-system/scripts/run_marine_simulation.py:198).
- Current behavior: The expensive worker must reject or replace the predownloaded product.
- Expected contract: All required region-specific 3-D products validated before EC2 launch.
- Risk: Paid compute launches before usable ocean forcing is proven available.
- Next step: Align the preflight producer with fetch_native_marine_forcing.py and verify all five manifests before launch.
ETL-002 — HIGH: WW3 forcing is not run-scoped
- Producer: WRF adapter
- Consumer: WW3 runner
- Evidence: Upload and download use forcing/ww3/<run-date>/<region> without run-id at [aws_orchestrator.py (line 87)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_orchestrator.py:87) and [aws_ww3_runner.py (line 32)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_ww3_runner.py:32).
- Current behavior: Retries or concurrent runs for one date share the same objects.
- Expected contract: Immutable <run-date>/<run-id>/<region> forcing.
- Risk: A run can consume another run’s wind or namelist.
- Next step: Make forcing run-scoped and include source WRF run identity in the consumed manifest.
ETL-003 — CRITICAL: WW3 completion can accept its input as output
- Producer: WW3
- Consumer: publication/S3
- Evidence: After ww3_ounf, the runner considers any *.nc sufficient at [aws_ww3_runner.py (line 43)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_ww3_runner.py:43). wind.nc already exists in that directory.
- Current behavior: WW3_SUCCESS can be created without proving WW3 produced a forecast NetCDF.
- Expected contract: Explicit output filename plus variable, time, spatial and finite-value validation.
- Risk: Empty or absent wave forecasts may be published as successful.
- Next step: Require and validate the canonical ww3_ounf product before creating the marker.
ETL-004 — HIGH: WW3 forcing manifest is generated but ignored
- Producer: prepare_ww3_wind_from_wrf.py
- Consumer: aws_ww3_runner.py
- Evidence: Manifest records region and time summary at [prepare_ww3_wind_from_wrf.py (line 242)](/Users/charles.santana/PredSea/predsea-system/scripts/prepare_ww3_wind_from_wrf.py:242), but the runner checks only four filenames and non-zero sizes at [aws_ww3_runner.py (line 36)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_ww3_runner.py:36).
- Current behavior: Wrong period, duplicate timestamps, partial horizon, wrong region, NaNs, or wrong units can pass staging.
- Expected contract: 73 unique hourly timestamps from run-date 00Z through +72h, finite U/V, correct bbox and region ID.
- Risk: Scientifically wrong forecast period can appear operationally successful.
- Next step: Add a fail-closed WW3 input validator and require its signed/checksummed manifest.
ETL-005 — HIGH: AWS WW3 path has no CMEMS wave-boundary contract
- Producer: CMEMS
- Consumer: WW3
- Evidence: AWS WW3 runner consumes only grid files, wind.nc, and namelists at [aws_ww3_runner.py (line 31)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_ww3_runner.py:31). The generic CMEMS downloader defaults to a physical 2-D dataset, not the declared wave dataset.
- Current behavior: The documented CMEMS wave-boundary flow is absent from the AWS WW3 execution path.
- Expected contract: Explicitly declare whether WW3 is boundary-forced or closed/nested, with validated boundary artifacts.
- Risk: Documentation and actual wave physics differ.
- Next step: Confirm intended WW3 boundary configuration.
ETL-006 — HIGH: Athena evidence lacks run identity and is non-idempotent
- Producer: validation exporter
- Consumer: Athena API
- Evidence: Normalization omits run_id at [export_validation_to_athena.py (line 19)](/Users/charles.santana/PredSea/predsea-system/scripts/export_validation_to_athena.py:19). Each export writes a new UUID object at [warehouse.py (line 35)](/Users/charles.santana/PredSea/predsea-system/scripts/aws/warehouse.py:35). Glue schema also has no run_id.
- Current behavior: Reruns append indistinguishable rows for the same date.
- Expected contract: Run-scoped lineage and idempotent publication.
- Risk: API ranking can mix forecasts from different runs; newest ingestion may not represent latest_run.json.
- Next step: Add run_id lineage and query only the published run.
ETL-007 — MEDIUM: Empty Athena export still permits overall success
- Producer: validation export
- Consumer: publication status
- Evidence: No rows returns exit code zero at [export_validation_to_athena.py (line 51)](/Users/charles.santana/PredSea/predsea-system/scripts/export_validation_to_athena.py:51); the orchestrator then publishes SUCCEEDED at [aws_daily_orchestrator.py (line 71)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_daily_orchestrator.py:71).
- Current behavior: A successful daily status does not guarantee Athena evidence exists.
- Expected contract: Required evidence counts and query visibility before success.
- Risk: API returns stale or absent evidence for a nominally successful run.
- Next step: Make evidence completeness part of publication completion.
ETL-008 — MEDIUM: WW3 wind lacks units and coverage safeguards
- Producer: WRF wind adapter
- Consumer: WW3
- Evidence: U and V are written without unit attributes at [prepare_ww3_wind_from_wrf.py (line 91)](/Users/charles.santana/PredSea/predsea-system/scripts/prepare_ww3_wind_from_wrf.py:91). KD-tree interpolation has no maximum-distance/domain-containment check at lines 182–220.
- Current behavior: Extrapolated values outside WRF coverage can appear valid.
- Expected contract: Explicit m s-1, source-grid coverage check, interpolation-distance limits and finite-value validation.
- Risk: Plausible but spatially invalid forcing.
- Next step: Formalize and validate the wind-grid contract.
Unknowns
- Actual deployed container image revisions and whether they match this checkout.
- Actual S3 object contents, checksums and current freshness.
- Whether WW3 grid assets embed boundary forcing not visible in the runner.
- Exact ww3_ounf canonical output filename.
- Live Athena partition/query behavior was not inspected.
- No runtime datasets were opened or modified.
Scientific Decisions Required
- Intended WW3 boundary-condition strategy.
- Acceptance limits for WRF-to-WW3 extrapolation distance.
- Scientific approval of configured CROCO and wave physical ranges.
- Whether padded terminal CROCO forcing is acceptable for the final interpolation step.
- Whether the constant dQdSST = -40 W m-2 K-1 is approved across all regions.
Recommended Next Steps
Before any paid AWS run:
1. Fix the WW3 output completion contract.
2. Prevalidate region-specific 3-D CMEMS forcing for all regions.
3. Scope WW3 forcing by run ID.
4. Validate WW3 forcing manifests and output contents.
5. Add run identity and idempotency to Athena publication.
6. Require non-empty, queryable evidence before SUCCEEDED.
STATUS:
FAIL
FINDINGS:
1 critical, 5 high, 2 medium.
EVIDENCE:
Read-only source and configuration tracing with exact references above.
RISKS:
False WW3 success, wrong-run forcing, paid compute without usable CMEMS inputs, and mixed/stale Athena evidence.
UNKNOWN:
Deployed-image parity, live S3/Athena state, and approved WW3 boundary physics.
CHANGES MADE:
None.
TESTS RUN:
The narrow unit-test command could not start because the system Python lacks pytest. No dependencies were installed.
AWS / COST IMPACT:
None. No AWS calls, deployments, downloads, or simulations were run.
RECOMMENDED NEXT STEP:
Treat ETL-003 as the immediate release blocker, then resolve ETL-001, ETL-002, ETL-004, and ETL-006 before authorizing a paid forecast.


1:10 PM
