
#set page(paper: "a4", margin: 2.5cm)
#set text(font: "Avenir Next", size: 10.5pt)
#show raw.where(block: true): it => rect(fill: rgb("#f8fafc"), inset: 8pt, width: 100%)[#it]

= Executive Summary & Core Positioning
<executive-summary-core-positioning>
== 1. The Operational Problem: Coarse Grids Miss Coastal Physics
<the-operational-problem-coarse-grids-miss-coastal-physics>
Global physical products---such as those from ECMWF and Copernicus
Marine Environment Monitoring Service (CMEMS)---provide essential
ocean-state baselines at $4.2 upright(" km")$ to $25 upright(" km")$
horizontal resolutions. However, coarse global grids smooth out critical
coastal bathymetric features, flatten narrow island channels (e.g.,
Freus channel between Ibiza and Formentera, Dragonera channel off
Mallorca), and underestimate wave-current interactions and local
wind-sea generation.

== 2. The Commercial & Coastal Value of 1 km Resolution
<the-commercial-coastal-value-of-1-km-resolution>
PredSea bridges this operational gap with an explicit positioning
philosophy:

#quote(block: true)[
#strong[Ocean data is everywhere. Operational decisions are not.]
]

By downscaling regional ocean state data onto a high-resolution
#strong[$1 upright(" km")$ curvilinear grid] ($401 times 501$ nodes
across 32 vertical $sigma$-layers in the Balearic Basin), PredSea
provides: \* #strong[Sub-Kilometer Coastal Accuracy:] Resolves steep
shoreline bathymetry, narrow island channels, and localized coastal
upwelling anomalies. \* #strong[Predictive Decision Intelligence:]
Converts raw 3D velocity vectors and wave spectra into vessel response
metrics, port safety alerts, and captain-facing advice. \*
#strong[Unmatched Unit Economics:] Delivers regional scale
high-resolution forecasts at \~\$2.22/day using serverless GCP Batch
Spot execution---a \>90% reduction compared to legacy HPC
infrastructure.

```
+-----------------------------------------------------------------------------------+
|                                 PredSea Platform                                  |
|                                                                                   |
|  +--------------------+    +--------------------+    +-------------------------+  |
|  |   WRF Atmosphere   |    |    SWAN Waves      |    |       CROCO Ocean       |  |
|  |  (10m Wind, Flux)  |    | (Hs, Tp, Spectrum) |    |  (3D u, v, T, S, Zeta)  |  |
|  +---------+----------+    +---------+----------+    +------------+------------+  |
|            |                         |                            |               |
|            +-------------------------+----------------------------+               |
|                                      |                                            |
|                                      v                                            |
|                  +---------------------------------------+                        |
|                  |      GCP Batch Spot Execution         |                        |
|                  +-------------------+-------------------+                        |
|                                      |                                            |
|                                      v                                            |
|                  +---------------------------------------+                        |
|                  |    Canonical NetCDF4 + GCS Pipeline   |                        |
|                  +-------------------+-------------------+                        |
|                                      |                                            |
|                                      v                                            |
|                  +---------------------------------------+                        |
|                  | BigQuery Decision Engine & REST APIs  |                        |
|                  +---------------------------------------+                        |
+-----------------------------------------------------------------------------------+
```

#divider()

== Key Performance Indicators (KPIs)
<key-performance-indicators-kpis>
#figure(
  align(center)[#table(
    columns: (33.33%, 33.33%, 33.33%),
    align: (left,left,left,),
    table.header([Parameter], [Legacy Cluster Model], [PredSea
      Cloud-Native Architecture],),
    table.hline(),
    [#strong[Execution Paradigm]], [Fixed On-Prem / Monolithic
    VM], [#strong[Serverless GCP Batch Spot Instances]],
    [#strong[Grid
    Resolution]], [$4.2 upright(" km") - 10 upright(" km")$
    (Global/Regional)], [#strong[$1.0 upright(" km")$ (High-Resolution
    Coastal Tiles)]],
    [#strong[Pre-Processing Time]], [40 minutes
    (Single-threaded)], [#strong[1 min 42 sec] (Python
    `ProcessPoolExecutor`)],
    [#strong[Total Western Med Compute Time]], [\> 28 Hours
    (Sequential)], [#strong[\< 35 Minutes] (Parallel Region Spot
    Execution)],
    [#strong[Daily Infrastructure Cost]], [\~\$45.00 /
    day], [#strong[\~\$2.22 / day] (Spot VM + GCS + BigQuery)],
    [#strong[Validation
    Benchmark]], [$H_s upright(" RMSE") approx 0.42 upright(" m")$], [#strong[$H_s upright(" RMSE") lt.eq 0.11 upright(" m")$]
    (SOCIB Buoy Ground Truth)],
  )]
  , kind: table
  )

#divider()

== Table of Contents
<table-of-contents>
The complete technical specification is structured across six dedicated
sub-documents:

+ #link("./01_system_architecture.md")[#strong[01\_system\_architecture.md]]
  \ #emph[End-to-end Data Pipeline: Upstream ECMWF/CMEMS ingestion,
  Python GIL-bypass pre-processing, bulk forcing compilation
  (`croco_blk.nc`, `croco_bry.nc`, `croco_ini.nc`), and GCS cloud
  storage hierarchy.]
+ #link("./02_modeling_suite.md")[#strong[02\_modeling\_suite.md]] \
  #emph[Core Numerical Engines & Coupling Mechanics: WRF atmospheric
  physics, CROCO 3D hydrostatic primitive equations ($s$-vertical
  coordinates), SWAN 3D spectral wave dynamics, and OASIS3-MCT/COAWST
  two-way and three-way flux exchange mechanics.]
+ #link("./03_thermodynamics_and_fluxes.md")[#strong[03\_thermodynamics\_and\_fluxes.md]]
  \ #emph[Physical Formulations & Bulk Parameterization: Thermodynamic
  surface heat flux equations ($upright("shflux")$ decomposition),
  resolution of unit conversion errors and uncoupled loops in
  `bulk_flux.F`, and nocturnal boundary cooling physics.]
+ #link("./04_empirical_validation.md")[#strong[04\_empirical\_validation.md]]
  \ #emph[Balearic Basin Benchmark Case Study: Domain specification
  ($401 times 501 times 32$), July 2026 Gate 8c SST empirical metrics,
  and coastal latent heat flux anomaly diagnostics off Dragonera Island
  ($39.58^compose upright("N")\,2.34^compose upright("E")$).]
+ #link("./05_cloud_deployment_and_ops.md")[#strong[05\_cloud\_deployment\_and\_ops.md]]
  \ #emph[GCP Batch Execution & Serverless Infrastructure: Containerized
  MPI architecture (`predsea-croco-staging`), Spot VM cost optimization,
  automated self-deletion traps, and multi-tile output consolidation.]
+ #link("./06_conclusion_and_roadmap.md")[#strong[06\_conclusion\_and\_roadmap.md]]
  \ #emph[Future Outlook & Engineering Roadmap: Diurnal thermal cycle
  tracking, full operational CROCO-SWAN wave-current coupling, and
  automated captain-facing decision APIs.]
