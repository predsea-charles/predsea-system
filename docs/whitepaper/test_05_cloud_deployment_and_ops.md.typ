
#set page(paper: "a4", margin: 2.5cm)
#set text(font: "Avenir Next", size: 10.5pt)
#show raw.where(block: true): it => rect(fill: rgb("#f8fafc"), inset: 8pt, width: 100%)[#it]

= 05. Cloud Deployment & Serverless Operations
<cloud-deployment-serverless-operations>
This document describes the cloud-native, serverless execution framework
developed for #strong[PredSea] using #strong[Google Cloud Platform (GCP)
Batch], #strong[Spot VM instances], and automated cost-protection
mechanisms.

#divider()

== 1. Containerized HPC Engine (`predsea-croco-staging`)
<containerized-hpc-engine-predsea-croco-staging>
Rather than maintaining dedicated, static HPC server hardware, the
entire numerical modeling environment---including compiled Fortran 90
binaries for CROCO 2.1.3 and SWAN 41.45, OpenMPI execution runtimes,
NetCDF C/Fortran libraries, and Python spatial post-processors---is
encapsulated in an immutable Docker container image.

```
+-----------------------------------------------------------------------------------+
|               PredSea Unified HPC Container Architecture                          |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  | Base OS: Ubuntu 22.04 LTS + OpenMPI 4.1 + gfortran / gcc                      |  |
|  +-----------------------------------------------------------------------------+  |
|  | Compiled Binaries:                                                          |  |
|  |  - croco_balearic.exe (CROCO 2.1.3 MPI binary)                             |  |
|  |  - swan_balearic.exe  (SWAN 41.45 MPI binary)                              |  |
|  +-----------------------------------------------------------------------------+  |
|  | Python Environment: Python 3.11 + NetCDF4 + xarray + SciPy + NumPy           |  |
|  +-----------------------------------------------------------------------------+  |
|  | Automation Scripts:                                                         |  |
|  |  - run_marine_simulation.py  (Master entrypoint)                            |  |
|  |  - prepare_croco_forcing.py   (Parallel GIL-bypass pre-processor)            |  |
|  |  - validate_marine_output.py  (Fail-closed physical range validator)         |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
```

Image digests are pinned in GCP Artifact Registry:
`europe-west1-docker.pkg.dev/predsea-api/predsea-croco-staging/croco:latest`

#divider()

== 2. Dynamic Resource-Aware Compute Sizing
<dynamic-resource-aware-compute-sizing>
To prevent Out-Of-Memory (OOM) failures while minimizing compute
expenditure, the submission orchestrator
#link("file:///Users/charles.santana/Kultrip/predsea-system/scripts/submit_gcp_batch_simulation.py")[`scripts/submit_gcp_batch_simulation.py`]
dynamically parses regional geographic bounds and computes total spatial
grid points:

$ upright("Grid Points") = (frac(\(upright("Lat")_(upright("max")) - upright("Lat")_(upright("min"))\)times 111\,000, H_(upright("res")))) times (frac(\(upright("Lon")_(upright("max")) - upright("Lon")_(upright("min"))\)times 111\,000 times cos\(upright("Lat")_(upright("mid"))\), H_(upright("res")))) $

Based on the calculated density, the job launcher selects the optimal
Compute Engine Spot VM template and MPI rank layout:

```
                  [Geographic Region Config JSON]
                               |
                   (Compute Sizing Formula)
                               |
         +---------------------+---------------------+
         | < 500k Points       | 500k - 2M Points    | > 2M Points
         v                     v                     v
   [c2d-highcpu-4]       [c2d-highcpu-8]       [c2d-highcpu-16]
   (2 MPI Ranks)         (4 MPI Ranks)         (16 MPI Ranks)
```

=== Region Provisioning Matrix
<region-provisioning-matrix>
#figure(
  align(center)[#table(
    columns: (13.79%, 17.24%, 17.24%, 17.24%, 17.24%, 17.24%),
    align: (left,center,center,center,center,center,),
    table.header([Region ID], [Grid Points], [Machine Type], [Spot
      Hourly Rate], [MPI Ranks], [Compute Cost / 24h Forecast],),
    table.hline(),
    [#strong[Balearic
    1km]], [$200\,901$], [`c2d-highcpu-16`], [#strong[\$0.180 /
    hr]], [16], [#strong[\$0.063] (21 min run)],
    [#strong[Alboran
    1km]], [$125\,751$], [`c2d-highcpu-4`], [#strong[\$0.045 /
    hr]], [2], [#strong[\$0.015] (20 min run)],
    [#strong[Gulf of Lion
    1km]], [$135\,951$], [`c2d-highcpu-4`], [#strong[\$0.045 /
    hr]], [2], [#strong[\$0.015] (20 min run)],
    [#strong[Tyrrhenian
    1km]], [$423\,801$], [`c2d-highcpu-8`], [#strong[\$0.090 /
    hr]], [4], [#strong[\$0.036] (24 min run)],
    [#strong[Algerian
    1km]], [$286\,251$], [`c2d-highcpu-8`], [#strong[\$0.090 /
    hr]], [4], [#strong[\$0.030] (20 min run)],
    [#strong[Total Med Suite]], [#strong[\~1.17 Million]], [#strong[5x
    Spot VMs]], [--], [#strong[28 Ranks]], [#strong[\$0.172 / daily
    run]],
  )]
  , kind: table
  )

#divider()

== 3. Spot VM Preemptibility & Cost Safety Traps
<spot-vm-preemptibility-cost-safety-traps>
Compute costs are reduced by #strong[70%--90%] by leveraging GCP
#strong[Spot Instances]. To ensure fault tolerance and prevent runaway
cloud billing:

```mermaid
flowchart TD
    Submit["submit_gcp_batch_simulation.py"] --> Launch["GCP Batch Provisions Spot VM"]
    Launch --> TrapSet["Set Bash Exit Traps & Timers"]
    
    TrapSet --> RunSim["Execute CROCO MPI Run"]
    
    RunSim -- "SUCCESS" --> Valid["validate_marine_output.py"]
    RunSim -- "SPOT Preemption / Crash" --> FailureHandler["Capture Failure Diagnostics"]
    
    Valid -- "PASS" --> Upload["Sync NetCDF to GCS Staging"]
    Valid -- "FAIL (Physical Range)" --> FailureHandler
    
    Upload --> WriteSuccessMarker["Write SUCCESS Token"]
    FailureHandler --> WriteFailMarker["Write FAILURE Marker"]
    
    WriteSuccessMarker --> SelfDestruct["Auto Self-Deletion Trap"]
    WriteFailMarker --> SelfDestruct
```

+ #strong[Automated Self-Deletion Traps (`vm_startup.sh`)]: The
  container launcher registers a shell `trap` command
  (`trap 'gcloud compute instances delete ... --quiet' EXIT INT TERM`).
  Regardless of whether the simulation finishes successfully or
  encounters a script crash, the compute node automatically
  self-destructs, eliminating idle billing risks.
+ #strong[Run-Scoped Immutability]: Outputs are saved under immutable
  run paths:
  `gs://predsea-daily-outputs-test/predictions/YYYY-MM-DD/runs/[RUN_ID]/`
+ #strong[Fail-Closed Diagnostics]: If a Spot node is preempted by GCP,
  the master orchestrator detects missing output hashes, marks the run
  as `FAILED`, preserves intermediate log files, and triggers a clean
  retry with a new unique run ID.

#divider()

== 4. Output Consolidation & Cloud Storage Pipeline
<output-consolidation-cloud-storage-pipeline>
Once numerical solver integration completes, raw model outputs undergo
post-processing:

+ #strong[Canonicalization]: Intermediate output files are consolidated
  into standard single-file NetCDF4 products
  (`balearic_1km_croco_forecast.nc`).
+ #strong[ETL BigQuery Ingestion]:
  `scripts/ingest_predictions_to_bigquery.py` extracts time series
  across #strong[3,046 canonical harbors] and #strong[127 shipping
  routes], inserting records into BigQuery tables for sub-millisecond
  API lookups.
+ #strong[FastAPI Cloud Run Serving]: The web API fetches predictions
  from BigQuery and GCS, generating real-time Vector Tile overlays for
  Deck.gl map visualization.
