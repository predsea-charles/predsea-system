
#set page(paper: "a4", margin: 2.5cm)
#set text(font: "Avenir Next", size: 10.5pt)
#show raw.where(block: true): it => rect(fill: rgb("#f8fafc"), inset: 8pt, width: 100%)[#it]

= 01. System Architecture & Data Pipeline
<system-architecture-data-pipeline>
This document details the end-to-end data ingestion, preparation, and
orchestration pipeline powering the #strong[PredSea] oceanographic
forecasting platform.

#divider()

== 1. High-Level Data Flow Pipeline
<high-level-data-flow-pipeline>
The PredSea automated data pipeline operates on a daily serverless
schedule. Upstream global weather and ocean state datasets are
retrieved, interpolated across spatial and vertical coordinate systems
using parallel processes, fed into coupled numerical solvers, and
transformed into optimized NetCDF4 and BigQuery datasets for downstream
decision APIs.

```mermaid
flowchart TD
    subgraph Upstream Data Sources
        ECMWF["ECMWF Open Data<br/>(IFS Atmospheric Forcing)"]
        CMEMS["Copernicus Marine (CMEMS)<br/>(MED-PHYS 3D Hydrodynamics)"]
    end

    subgraph Data Ingestion & Pre-Processing
        FetchWRF["fetch_ecmwf_forcing.py<br/>(10m Wind, T2, Q2, Rad Fluxes)"]
        FetchCMEMS["fetch_cmems_forcing.py<br/>(u, v, T, S, Zeta Extents)"]
        
        GILBypass["prepare_croco_forcing.py<br/>(ProcessPoolExecutor Parallel Processing)"]
    end

    subgraph Model Forcing Artifacts
        CROCO_BLK["croco_blk.nc<br/>(Surface Bulk Atmosphere)"]
        CROCO_BRY["croco_bry.nc<br/>(3D Open Boundary Data)"]
        CROCO_CLM["croco_clm.nc<br/>(Climatology Restoring)"]
        CROCO_INI["croco_ini.nc<br/>(Initial Condition State)"]
    end

    subgraph Numerical Compute Engine
        GCPBatch["GCP Batch Spot Instance<br/>(c2d-highcpu-16 / 16 MPI Ranks)"]
        CROCO_Exec["CROCO 2.1.3 Executable<br/>(croco_balearic.exe)"]
    end

    subgraph Storage & Product Ingestion
        GCS_Out["Canonical NetCDF Output<br/>gs://predsea-daily-outputs-test/"]
        ETL_BQ["BigQuery Ingestor<br/>(3,046 Harbors & 127 Routes)"]
        FastAPI["PredSea REST API & Maps<br/>(FastAPI / Deck.gl)"]
    end

    ECMWF --> FetchWRF
    CMEMS --> FetchCMEMS
    FetchWRF --> GILBypass
    FetchCMEMS --> GILBypass

    GILBypass --> CROCO_BLK
    GILBypass --> CROCO_BRY
    GILBypass --> CROCO_CLM
    GILBypass --> CROCO_INI

    CROCO_BLK --> GCPBatch
    CROCO_BRY --> GCPBatch
    CROCO_CLM --> GCPBatch
    CROCO_INI --> GCPBatch

    GCPBatch --> CROCO_Exec
    CROCO_Exec --> GCS_Out
    GCS_Out --> ETL_BQ
    ETL_BQ --> FastAPI
```

#divider()

== 2. Atmospheric & Boundary Ingestion Specifications
<atmospheric-boundary-ingestion-specifications>
=== A. WRF Atmospheric Forcing Ingestion
<a.-wrf-atmospheric-forcing-ingestion>
Atmospheric driving variables are downloaded hourly from ECMWF
high-resolution operational models and refined via PredSea's Weather
Research and Forecasting (WRF v4.5) $3 upright(" km")\/1 upright(" km")$
nested model runs. The required bulk surface forcing parameters include:

#figure(
  align(center)[#table(
    columns: (22.22%, 27.78%, 27.78%, 22.22%),
    align: (left,center,center,left,),
    table.header([Variable Name], [Symbol], [Units], [Physical
      Description],),
    table.hline(),
    [#strong[Zonal Wind
    Vector]], [$U_10$], [$upright("m/s")$], [$10 upright(" m")$ Eastward
    wind component],
    [#strong[Meridional Wind
    Vector]], [$V_10$], [$upright("m/s")$], [$10 upright(" m")$
    Northward wind component],
    [#strong[Air
    Temperature]], [$T_a$], [$upright("K") upright(" or ")^compose upright("C")$], [$2 upright(" m")$
    Surface air temperature],
    [#strong[Specific
    Humidity]], [$q_a$], [$upright("kg/kg")$], [$2 upright(" m")$
    Specific humidity derived from relative humidity ($R H$)],
    [#strong[Surface Pressure]], [$P_(a t m)$], [$upright("Pa")$], [Mean
    sea level atmospheric pressure],
    [#strong[Downward Shortwave
    Flux]], [$S W_arrow.b$], [$upright("W/m")^2$], [Solar radiation
    reaching the sea surface],
    [#strong[Downward Longwave
    Flux]], [$L W_arrow.b$], [$upright("W/m")^2$], [Atmospheric thermal
    infrared radiation reaching the sea surface],
    [#strong[Precipitation
    Rate]], [$P_(upright("rate"))$], [$upright("kg/m")^2\/upright("s")$], [Total
    precipitation for surface freshwater flux calculations],
  )]
  , kind: table
  )

=== B. CMEMS Hydrodynamic Boundary Ingestion
<b.-cmems-hydrodynamic-boundary-ingestion>
Open ocean boundary conditions are sourced from the Copernicus Marine
Service (CMEMS Mediterranean Physics Analysis and Forecast model). Data
fields are extracted in 3D across the full geographic domain:

- #strong[3D Velocity Fields ($u\,v$):] Zonal and meridional oceanic
  current components across all vertical levels.
- #strong[3D Temperature ($T$) & Salinity ($S$):] Hydrographic state
  variables resolving pycnoclines and thermoclines.
- #strong[Sea Surface Height ($zeta$):] Free-surface barotropic
  elevation for boundary pressure gradient forcing.

#divider()

== 3. High-Performance File Preparation Workflow
<high-performance-file-preparation-workflow>
Translating raw 3D CMEMS and WRF datasets into CROCO-compatible NetCDF
input files (`croco_blk.nc`, `croco_bry.nc`, `croco_clm.nc`,
`croco_ini.nc`) was historically a single-threaded bottleneck, requiring
#strong[\~40 minutes] per 24-hour simulation cycle.

=== Process-Level GIL Bypass Design
<process-level-gil-bypass-design>
To overcome Python's Global Interpreter Lock (GIL), PredSea's
pre-processor
#link("file:///Users/charles.santana/Kultrip/predsea-system/scripts/prepare_croco_forcing.py")[`scripts/prepare_croco_forcing.py`]
implements process-level concurrency via
`concurrent.futures.ProcessPoolExecutor`.

```python
# Architecture snippet: ProcessPoolExecutor GIL bypass for 3D interpolation
from concurrent.futures import ProcessPoolExecutor
import numpy as np

def interpolate_3d_timestep(t_idx, cmems_data, target_croco_grid):
    """
    Independent process worker function interpolating 3D CMEMS variables
    onto CROCO curvilinear rho/u/v points and stretched s-vertical levels.
    """
    # ... spatial SciPy RegularGridInterpolator logic ...
    return interpolated_slice_t

def prepare_croco_forcing_parallel(time_steps, max_workers=16):
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(interpolate_3d_timestep, t, raw_cmems, target_grid)
            for t in range(time_steps)
        ]
        results = [f.result() for f in futures]
    return assemble_croco_netcdf(results)
```

=== Pre-Processing Performance Benchmarks
<pre-processing-performance-benchmarks>
#figure(
  align(center)[#table(
    columns: (21.05%, 26.32%, 26.32%, 26.32%),
    align: (left,center,center,center,),
    table.header([Processing Stage], [Legacy Single-Threaded
      Time], [PredSea Parallel Time (`c2d-highcpu-16`)], [Acceleration
      Factor],),
    table.hline(),
    [#strong[Atmospheric Bulk (`croco_blk.nc`)]], [8 min 12
    sec], [#strong[0 min 22 sec]], [#strong[22.3x]],
    [#strong[Open Boundaries (`croco_bry.nc`)]], [22 min 45
    sec], [#strong[0 min 58 sec]], [#strong[23.5x]],
    [#strong[Climatology & Init (`croco_clm/ini.nc`)]], [9 min 03
    sec], [#strong[0 min 22 sec]], [#strong[23.9x]],
    [#strong[Total Pre-Processing Pipeline]], [#strong[40 min 00
    sec]], [#strong[1 min 42 sec]], [#strong[23.5x]],
  )]
  , kind: table
  )

#divider()

== 4. Execution Workflow in `run_marine_simulation.py`
<execution-workflow-in-run_marine_simulation.py>
The master orchestration script
#link("file:///Users/charles.santana/Kultrip/predsea-system/simulation/run_marine_simulation.py")[`simulation/run_marine_simulation.py`]
executes the following strict sequence:

+ #strong[Validation of Spatial Domain Config]: Parses regional JSON
  specs (e.g.~`balearic_1km.json`) to confirm grid dimensions
  ($L M = 499\,M M = 399\,N = 32$).
+ #strong[Upstream Ingestion Check]: Verifies that WRF surface forcing
  and CMEMS 3D boundaries exist in GCS staging buckets and contain zero
  corrupt NaN/Inf values.
+ #strong[Parallel Forcing Assembly]: Triggers
  `prepare_croco_forcing.py` with multi-core process pools.
+ #strong[Batch Instance Provisioning]: Launches a GCP Batch job on
  `c2d-highcpu-16` Spot nodes running the compiled CROCO container.
+ #strong[Output Validation & Canonicalization]: Verifies that generated
  history NetCDF files (`croco_his.nc`) pass physical range gates before
  writing a durable `SUCCESS` token to GCS.
