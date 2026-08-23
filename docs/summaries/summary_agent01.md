Executive Summary
The AWS implementation is incomplete and is not currently capable of executing the documented end-to-end WRF → CROCO → WW3 → validation → Athena chain successfully.
The primary blockers are:
- CROCO cannot locate the WRF files produced by the preceding stage.
- CROCO’s fallback CMEMS workflow requires credentials that are not passed into its container and attempts to write into a read-only mount.
- Post-simulation briefing still retrieves WRF data from GCS, not S3.
- WW3 output validation can mistake its input wind.nc for generated output.
- AWS tests cover only isolated scaffolding, not the daily pipeline.
No AWS state was inspected, so deployment status remains unknown.
System Actually Implemented
The repository contains these AWS components:
1. An ECS daily orchestrator in [scripts/aws_daily_orchestrator.py (line 52)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_daily_orchestrator.py:52).
2. ECMWF and CMEMS download subprocesses executed sequentially at [scripts/aws_daily_orchestrator.py (line 61)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_daily_orchestrator.py:61).
3. One c6i.32xlarge Spot worker with a 300 GB encrypted gp3 volume, 3,000 IOPS and 500 MB/s at [scripts/aws_orchestrator.py (line 129)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_orchestrator.py:129).
4. WRF with 128 MPI ranks, configured as 16×8, at [scripts/aws_orchestrator.py (line 69)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_orchestrator.py:69).
5. WRF-to-WW3 preprocessing at [scripts/aws_orchestrator.py (line 81)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_orchestrator.py:81).
6. Five sequential CROCO runs using 16 ranks each at [scripts/aws_orchestrator.py (line 89)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_orchestrator.py:89).
7. Five sequential WW3 runs using 24 ranks each at [scripts/aws_orchestrator.py (line 101)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_orchestrator.py:101).
8. S3 status publication and EC2 self-termination at [scripts/aws_orchestrator.py (line 46)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_orchestrator.py:46).
9. Parquet export through write_evidence_rows() at [scripts/aws/warehouse.py (line 14)](/Users/charles.santana/PredSea/predsea-system/scripts/aws/warehouse.py:14).
10. Athena-backed API queries in [humanintheloop/api/athena_store.py (line 16)](/Users/charles.santana/PredSea/predsea-system/humanintheloop/api/athena_store.py:16).
11. Terraform for S3, ECR, IAM, Secrets Manager, Athena, App Runner, ECS and EventBridge in [infra/aws/main.tf (line 1)](/Users/charles.santana/PredSea/predsea-system/infra/aws/main.tf:1). The schedule defaults to DISABLED at [infra/aws/variables.tf (line 17)](/Users/charles.santana/PredSea/predsea-system/infra/aws/variables.tf:17).
Documentation vs Implementation
The architecture document accurately describes:
- The EC2 instance type and disk configuration.
- The WRF/CROCO/WW3 sequence and MPI allocations.
- Sequential regional execution.
- S3, ECR, ECS, App Runner and Athena resources.
- EC2 termination trapping.
- EventBridge’s disabled default.
It does not accurately describe a working integration between:
- WRF output and CROCO input.
- Daily CMEMS ETL and CROCO’s required 3-D regional forcing.
- S3 simulation output and briefing generation.
- WW3 completion validation.
- Validation artifacts and confirmed Athena availability.
The implementation appearing most active is the AWS entry point in scripts/aws_daily_orchestrator.py, but substantial GCP-specific behavior remains in scripts called by that entry point.
Findings
F-01 — CRITICAL: CROCO cannot see the WRF output
- Location: build_user_data(), [scripts/aws_orchestrator.py (line 77)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_orchestrator.py:77), [scripts/aws_orchestrator.py (line 94)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_orchestrator.py:94)
- Consumer: run_croco_simulation(), [scripts/run_marine_simulation.py (line 391)](/Users/charles.santana/PredSea/predsea-system/scripts/run_marine_simulation.py:391)
WRF writes under /workspace/outputs/wrf. CROCO receives /workspace/outputs, but its runner searches its configured WRF input directory for at least 73 wrfout_d02_* files.
PREDSEA_WRF_S3_URI is passed into the CROCO container, but run_marine_simulation.py does not consume that variable.
The documented WRF → CROCO connection therefore does not exist operationally.
F-02 — CRITICAL: CMEMS fallback cannot operate inside the CROCO container
- Daily download: [scripts/fetch_cmems_forcing.py (line 221)](/Users/charles.santana/PredSea/predsea-system/scripts/fetch_cmems_forcing.py:221)
- Required CROCO variables/dimensions: [scripts/run_marine_simulation.py (line 190)](/Users/charles.santana/PredSea/predsea-system/scripts/run_marine_simulation.py:190)
- Fallback download: [scripts/run_marine_simulation.py (line 351)](/Users/charles.santana/PredSea/predsea-system/scripts/run_marine_simulation.py:351)
- Read-only mount: [scripts/aws_orchestrator.py (line 96)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_orchestrator.py:96)
The daily ETL downloads a single default CMEMS physical product. CROCO requires uo, vo, thetao, so, zos plus time, depth, latitude and longitude dimensions.
If the shared file is rejected, CROCO invokes fetch_native_marine_forcing.py. However:
- Copernicus credentials are not passed into the CROCO container.
- /workspace/inputs is mounted read-only.
- The fallback attempts to cache downloaded products into that read-only directory at [scripts/run_marine_simulation.py (line 368)](/Users/charles.santana/PredSea/predsea-system/scripts/run_marine_simulation.py:368).
This makes the documented CMEMS → CROCO path non-viable.
F-03 — HIGH: Briefing generation still retrieves WRF from GCS
- Daily invocation: [scripts/aws_daily_orchestrator.py (line 65)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_daily_orchestrator.py:65)
- WRF lookup: _fetch_wrf_wind_context(), [scripts/generate_daily_briefing.py (line 975)](/Users/charles.santana/PredSea/predsea-system/scripts/generate_daily_briefing.py:975)
- GCS client: [scripts/generate_daily_briefing.py (line 1006)](/Users/charles.santana/PredSea/predsea-system/scripts/generate_daily_briefing.py:1006)
The AWS worker uploads WRF output to S3, but briefing generation only consults PREDSEA_GCS_BUCKET and imports google.cloud.storage.
Consequently, the briefing and validation archive are not demonstrably derived from the AWS simulation.
F-04 — HIGH: WW3 completion test accepts an input file as output
- Location: main(), [scripts/aws_ww3_runner.py (line 36)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_ww3_runner.py:36), [scripts/aws_ww3_runner.py (line 43)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_ww3_runner.py:43)
wind.nc is a required input. After ww3_ounf, the runner checks only whether any *.nc file exists. Since wind.nc already exists, this test can pass without a generated WW3 forecast NetCDF.
A WW3_SUCCESS marker can therefore be published without confirmed model output.
F-05 — HIGH: Validation export can silently succeed with no evidence
- Location: main(), [scripts/export_validation_to_athena.py (line 47)](/Users/charles.santana/PredSea/predsea-system/scripts/export_validation_to_athena.py:47)
If none of the three validation JSONL files exist, the exporter prints “Athena export skipped” and returns exit code zero at lines 51–53. The daily orchestrator then publishes overall SUCCEEDED.
This contradicts the documented requirement for Parquet evidence to be visible through Athena.
F-06 — MEDIUM: AWS orchestration retains substantial GCP dependencies
Examples include:
- GCS-only briefing WRF lookup at [scripts/generate_daily_briefing.py (line 1009)](/Users/charles.santana/PredSea/predsea-system/scripts/generate_daily_briefing.py:1009).
- GCS fallback in [scripts/fetch_cmems_forcing.py (line 42)](/Users/charles.santana/PredSea/predsea-system/scripts/fetch_cmems_forcing.py:42).
- GCS/BigQuery implementation in scripts/wrf_forecast_ingestor.py.
- BigQuery warning paths in humanintheloop/api/warnings_service.py.
The API has AWS branches, but the repository-wide GCP-to-AWS refactor is not complete.
F-07 — MEDIUM: EC2 console streaming lacks corresponding IAM permission
- Code: [scripts/aws_orchestrator.py (line 164)](/Users/charles.santana/PredSea/predsea-system/scripts/aws_orchestrator.py:164)
- IAM policy: [infra/aws/main.tf (line 166)](/Users/charles.santana/PredSea/predsea-system/infra/aws/main.tf:166)
The orchestrator invokes ec2:GetConsoleOutput, but the task policy does not grant that action. The exception is swallowed, so simulation execution may continue while the documented log streaming silently fails.
F-08 — MEDIUM: Mutable deployment identifiers reduce reproducibility
- ECR mutability: [infra/aws/main.tf (line 43)](/Users/charles.santana/PredSea/predsea-system/infra/aws/main.tf:43)
- Default image tags: [infra/aws/variables.tf (line 45)](/Users/charles.santana/PredSea/predsea-system/infra/aws/variables.tf:45)
- Build tagging: [buildspec.aws.yml (line 10)](/Users/charles.santana/PredSea/predsea-system/buildspec.aws.yml:10)
Repositories permit mutable tags, and Terraform defaults services to latest. A deployment cannot be reproduced reliably from configuration alone.
F-09 — HIGH: Credential-named files exist in the repository tree
- /Users/charles.santana/PredSea/predsea-system/aws_credentials.txt
- /Users/charles.santana/PredSea/predsea-system/credentials.sh
Their contents were deliberately not displayed. Because this copy has no .git metadata, commit history and exposure status cannot be assessed. These files require a separate security review.
F-10 — INFO: CROCO canonical-grid safety is implemented locally
- Grid validation: [scripts/run_marine_simulation.py (line 300)](/Users/charles.santana/PredSea/predsea-system/scripts/run_marine_simulation.py:300)
- Supported promotion tool: scripts/promote_croco_grid.py
The runner validates a downloaded grid against the requested region before simulation. No grid was copied, promoted or modified during this audit.
Missing Tests
- No test of scripts/aws_daily_orchestrator.py.
- No end-to-end mocked AWS pipeline test.
- No test proving WRF output is visible to CROCO.
- No AWS test of CMEMS staging/fallback credentials and filesystem permissions.
- No test of scripts/aws_ww3_runner.py.
- No test distinguishing WW3 input NetCDF from generated output.
- No test for scripts/export_validation_to_athena.py.
- No test proving the Glue schema can query generated Parquet.
- No test proving briefing generation reads AWS S3 WRF output.
- No Terraform policy test covering runtime API calls.
- Existing AWS tests only cover Spot request structure, storage command construction, and basic S3 evidence access under [tests/aws](/Users/charles.santana/PredSea/predsea-system/tests/aws).
Dangerous Assumptions
- A common mounted filesystem automatically connects WRF output to CROCO input.
- The generic daily CMEMS file satisfies CROCO’s complete 3-D forcing contract.
- Secrets loaded by ECS are automatically available inside EC2 Docker containers.
- Any NetCDF after WW3 indicates a WW3 result.
- An empty validation export is an acceptable successful run.
- A process exit code and marker establish scientific validity.
- Mutable latest images represent a reproducible model version.
- AWS migration is complete because storage and API branches exist.
Scientific Questions
SCIENTIFIC DECISION REQUIRED:
- What exact temporal, vertical and spatial coverage constitutes acceptable CROCO CMEMS forcing?
- What numerical thresholds define acceptable CROCO and WW3 fields?
- Is 16-rank CROCO decomposition scientifically and numerically approved for every compiled regional grid?
- Is 24-rank WW3 execution validated for all five grids?
- Which output variables, timestamps and finite-value percentages are mandatory before publication?
- Is the documented 72-hour chain scientifically validated, or only structurally configured?
- What constitutes acceptable agreement against CMEMS, buoys and coastal observations?
Unknowns
- Whether any Terraform resources have been deployed.
- Whether EventBridge is actually disabled in AWS.
- Whether ECR images exist and match the local source.
- Whether immutable CROCO and WW3 grids exist in S3.
- Whether secret values are populated.
- Whether a 72-hour AWS run has ever completed.
- Whether generated Parquet has ever been queried successfully.
- Which code revision this directory represents because .git metadata is absent.
- Whether the credential-named files contain active secrets.
- Scientific validity of all model outputs.
Recommended Next Steps
Without fixing anything yet, the next authorized task should define a no-cost, fully mocked integration test covering:
1. WRF output discovery by CROCO.
2. Complete regional CMEMS staging.
3. WW3 generated-output identification.
4. S3 briefing input.
5. Required validation evidence.
6. Athena schema compatibility.
STATUS:
FAIL
FINDINGS:
10 findings: 2 CRITICAL, 4 HIGH, 3 MEDIUM, 1 INFO.
RISKS:
The configured AWS chain is likely to fail at CROCO; if bypassed, it can publish misleading WW3 or validation success markers.
UNKNOWN:
Live AWS state, deployed image versions, S3 assets, secret population, historical run success, and scientific acceptance remain unverified.
RECOMMENDED NEXT STEP:
Authorize a separate no-cost mocked integration-test task focused on the five broken handoffs identified above.


1:05 PM
