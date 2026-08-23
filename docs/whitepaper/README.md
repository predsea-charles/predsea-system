---
title: "PredSea: A Scalable Cloud-Native Oceanographic Forecasting System"
subtitle: "1 km High-Resolution Coastal Intelligence & Operational Decision Framework"
author: "PredSea Oceanographic Research & Engineering Group"
date: "July 2026"
status: "Active Development — Regional Validation In Progress (not yet operational)"
abstract: |
  Traditional coastal oceanography and wave dynamics modeling rely on dedicated high-performance computing (HPC) clusters or monolithic, expensive cloud runners. These legacy paradigms suffer from rigid resource allocation, high capital expenditure, and slow multi-domain scheduling.

  PredSea is building a cloud-native oceanographic forecasting architecture that replaces fixed HPC infrastructure with GCP Batch compute and MPI-parallelized numerical engines (CROCO, SWAN, WRF), each compiled per region and orchestrated through a staging pipeline with fail-closed output validation.

  As of this writing, the CROCO ocean model has a validated, repeatable run on the Balearic 1 km tile (both a 24-hour reference run and a faster-timestep 6-hour confirmation) and a first successful run on the Gulf of Lion 1 km tile. Three additional Western Mediterranean tiles (Tyrrhenian, Algerian Basin, Alboran/Gibraltar) are in their first CROCO test as of this update; their outcome is not yet known. WRF and SWAN generalization to the full five-tile footprint, and any live coupling between the three models, remain open engineering work — see Sections 2 and 6.
---

# Executive Summary & Core Positioning

## 1. The Operational Problem: Coarse Grids Miss Coastal Physics
Global physical products—such as those from ECMWF and Copernicus Marine Environment Monitoring Service (CMEMS)—provide essential ocean-state baselines at $4.2\text{ km}$ to $25\text{ km}$ horizontal resolutions. However, coarse global grids smooth out critical coastal bathymetric features, flatten narrow island channels (e.g., Freus channel between Ibiza and Formentera, Dragonera channel off Mallorca), and underestimate wave-current interactions and local wind-sea generation.

## 2. The Commercial & Coastal Value of 1 km Resolution
PredSea's target positioning:

> **Ocean data is everywhere. Operational decisions are not.**

By downscaling regional ocean state data onto a high-resolution **$1\text{ km}$ curvilinear grid** ($401 \times 501$ rho points across 32 vertical $\sigma$-layers in the validated Balearic tile), PredSea targets:
* **Sub-Kilometer Coastal Accuracy:** Resolving steep shoreline bathymetry, narrow island channels, and localized coastal effects that coarse global products smooth over.
* **Predictive Decision Intelligence:** Converting raw 3D velocity vectors and wave spectra into vessel response metrics, port safety alerts, and captain-facing advice (not yet built — see Section 6 roadmap).
* **Cost-Efficient Compute:** Running each regional tile as an isolated GCP Batch job sized to its own grid, rather than a single always-on cluster. Actual measured per-run costs and a mature multi-region daily cadence are not yet established; see Section 5 for what has actually been measured so far.

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
|                  |    GCP Batch Execution (STANDARD)     |                        |
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

---

## Status by Capability

Legend: ✅ implemented and verified · 🧪 implemented, under validation · 🛠 designed, not yet implemented · 🎯 performance target, not yet measured

| Capability | Status | Note |
| :--- | :---: | :--- |
| Serverless GCP Batch execution (CROCO + SWAN per region) | ✅ | STANDARD provisioning during validation; SPOT is the future cost-optimization mode, not current default (see `05_cloud_deployment_and_ops.md`) |
| $1.0\text{ km}$ regional grid definitions (5 Western Med tiles) | ✅ | Grid files and compiled CROCO binaries exist for all 5 regions |
| CROCO 6h / 24h numerical stability gates | ✅ | Passed for most regions; exact per-region status in `04_empirical_validation.md` |
| CROCO 72h gate | 🧪 | Blocked on a WRF-forcing horizon mismatch; fix in progress |
| SWAN across all 5 regions | 🧪 | Bathymetry is baked into the image for all 5 regions; a 2026-07-29 fix (`PROP BSBT` numerics + an explicit boundary-walk-inward limit) addressed real bugs found in `alboran_1km`/`gulf_of_lion_1km`/`algerian_1km`; a fresh 3-region validation test is in progress, result not yet known — see `02_modeling_suite.md` §4.5 and `04_empirical_validation.md` |
| Live WRF↔CROCO↔SWAN dynamic coupling | 🛠 | Current pipeline is one-way, file-mediated forcing only (see `02_modeling_suite.md`) |
| Pre-processing time, total compute time, daily infrastructure cost | 🎯 | Not re-measured since the pipeline changed this cycle; prior figures were not independently verified and are not repeated here |
| $H_s$ RMSE vs. SOCIB buoys or any independent observation source | 🎯 | No wave-height or observational validation has been performed yet |

---

## Table of Contents

The complete technical specification is structured across six dedicated sub-documents:

1. [**01_system_architecture.md**](./01_system_architecture.md)  
   *End-to-end Data Pipeline: Upstream ECMWF/CMEMS ingestion, Python GIL-bypass pre-processing, bulk forcing compilation (`croco_blk.nc`, `croco_bry.nc`, `croco_ini.nc`), and GCS cloud storage hierarchy.*
2. [**02_modeling_suite.md**](./02_modeling_suite.md)  
   *Core Numerical Engines & Current Data-Exchange Pipeline: WRF atmospheric physics, CROCO 3D hydrostatic primitive equations ($s$-vertical coordinates), SWAN 3D spectral wave dynamics, the current one-way file-mediated forcing chain between them, and the planned (not yet built) OASIS3-MCT-style two-way/three-way coupling.*
3. [**03_thermodynamics_and_fluxes.md**](./03_thermodynamics_and_fluxes.md)  
   *Physical Formulations & Bulk Parameterization: Thermodynamic surface heat flux equations ($\text{shflux}$ decomposition), and the one verified fix actually in the codebase — a sign-convention correction in `bulk_flux.F`.*
4. [**04_empirical_validation.md**](./04_empirical_validation.md)  
   *Current validation status across all 5 Western Mediterranean regions: which region/horizon combinations have passed the structural validation gate, and an explicit list of what has not yet been validated (observational comparison, wave height, multi-day horizons).*
5. [**05_cloud_deployment_and_ops.md**](./05_cloud_deployment_and_ops.md)  
   *GCP Batch Execution & Serverless Infrastructure: containerized MPI architecture, digest-pinned image requirements, current STANDARD (not SPOT) provisioning and why, automated self-deletion traps, and run-scoped output storage.*
6. [**06_conclusion_and_roadmap.md**](./06_conclusion_and_roadmap.md)  
   *Current Architectural State & Roadmap: what is implemented and verified today versus designed-but-not-built, and the engineering roadmap (multi-day horizons, live model coupling, captain-facing decision APIs).*
