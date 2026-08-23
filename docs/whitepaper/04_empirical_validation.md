# 04. Empirical Validation: Current Status Across the 5 Western Mediterranean Regions

This document tracks which region/horizon/timestep combinations have actually been run to completion and passed the structural validation gate (`scripts/validate_marine_output.py`), as opposed to a single polished "benchmark" narrative. It intentionally does not include specific SST/salinity/current numeric results, buoy RMSE figures, or named-location anomaly case studies, because none of those have actually been pulled from a completed run's validation JSON and cross-checked yet — see "What is not yet validated" below.

---

## 1. Regional Domain Specifications

| Region ID | Extent (lon / lat) | Grid ($\xi_\rho \times \eta_\rho$) | Grid Points | Vertical Levels ($N$) |
| :--- | :--- | :---: | :---: | :---: |
| **Balearic 1km** | $0.5$–$5.5^\circ\text{E}$, $37.5$–$41.5^\circ\text{N}$ | $501 \times 401$ | $200{,}901$ | 32 |
| **Alboran 1km** | $-6.0$–$-1.0^\circ\text{E}$, $35.0$–$37.5^\circ\text{N}$ | $501 \times 251$ | $124{,}203$ | 32 |
| **Gulf of Lion 1km** | $2.0$–$6.5^\circ\text{E}$, $41.5$–$43.3^\circ\text{N}$ | $500 \times 200$ | not recomputed for new bbox* | 32 |
| **Tyrrhenian 1km** | $7.5$–$14.0^\circ\text{E}$, $38.0$–$44.5^\circ\text{N}$ | $650 \times 651$ | $391{,}379$ | 32 |
| **Algerian Basin 1km** | $-1.0$–$8.5^\circ\text{E}$, $35.0$–$38.0^\circ\text{N}$ | $951 \times 301$ | $282{,}273$ | 32 |

*Gulf of Lion's extent and grid were changed on 2026-07-29 (bbox `latitude_max` reduced from $44.5^\circ$ to $43.3^\circ$; see `02_modeling_suite.md` §4.4). The grid dimensions above (`xi_rho=500, eta_rho=200`) are confirmed directly from the regenerated CROCO grid's NetCDF; the "Grid Points" figure used elsewhere in this suite has not been recomputed against the new bbox and is omitted here rather than restating the stale pre-resize number.

## 2. What Has Actually Passed the Validation Gate

The proven CROCO timestep configuration this development cycle is $\Delta t = 30\text{ s}$ baroclinic / `NDTFAST=45` barotropic substeps (matching the historically stable $\Delta t_{fast} \approx 0.667\text{ s}$ from an earlier confirmed $\Delta t=20\text{ s}$/`NDTFAST=30` configuration). Runs are accepted only if `validate_marine_output.py` confirms `finite_fraction: 1.0` (no `NaN`/`Inf`/uninitialized cells) and all output variables fall within their configured physical ranges, before a `CROCO_SUCCESS` marker is written.

| Region | 6h gate | 24h gate | 72h gate |
| :--- | :---: | :---: | :---: |
| **Balearic 1km** | ✅ passed | ✅ passed | attempted, hit a WRF-forcing data-availability limit (see below), not yet re-run |
| **Alboran 1km** | ✅ passed | ✅ passed | attempted, failed on the same WRF-forcing limit |
| **Gulf of Lion 1km** | ✅ passed | ✅ passed | attempted, failed on the same WRF-forcing limit |
| **Tyrrhenian 1km** | ✅ passed | not yet run (user deferred after 6h/72h decision) | attempted, hit the same WRF-forcing limit |
| **Algerian Basin 1km** | ✅ passed | ✅ passed | attempted, hit the same WRF-forcing limit |

The 72h attempts across all 5 regions failed not from a CROCO numerical problem, but because the WRF atmospheric forcing dataset reused for that test only had 24 hours of `wrfout_d02_*` output available (confirmed directly via `gsutil ls`) against a `run_marine_simulation.py` check requiring `forecast_hours + 1` hourly files. The fix in progress is to run WRF fresh for each forecast horizon (via the corrected `daily_orchestrator.py --use-gcp-batch` path) rather than reusing an older, shorter WRF dataset.

**Gulf of Lion's grid was regenerated on 2026-07-29** (bbox resize described in `02_modeling_suite.md` §4.4, new dimensions $500 \times 200$, replacing the previous $451 \times 301$ grid). The 6h/24h passes recorded in the table above were run against the *old* grid; the new grid has not yet been re-run at any CROCO horizon. A 3-region validation test covering the new Gulf of Lion grid (alongside Alboran and Algerian) is in progress as of this writing — see Section 3 below.

## 3. What Is Not Yet Validated

To avoid repeating the previous version of this document's mistake, the following are explicitly **not yet done**, not just "not shown here":

*   No SST/salinity/current/sea-level numeric results (min/max/mean) from any completed run have been pulled from GCS and recorded in this document.
*   No comparison against SOCIB buoys, CMEMS satellite SST, or any other independent observation source has been performed.
*   No wave height ($H_s$) validation has been done — SWAN has not yet been run to completion across all 5 regions in a single pipeline run. A live 6-hour-forecast attempt this cycle surfaced two real, since-fixed bugs (a silently-deep land-boundary substitution and a missing numerical scheme accommodation for geometrically constrained domains — see `02_modeling_suite.md` §§4.4–4.5) plus an unrelated orchestrator timeout-sharing bug that killed the run prematurely (see `05_cloud_deployment_and_ops.md` §1a). A subsequent 3-region test (`alboran_1km`, `gulf_of_lion_1km`, `algerian_1km`) with the fixes applied got a mixed result: `gulf_of_lion_1km` failed fast on a genuine bbox problem (now fixed by a bbox resize), while `alboran_1km`/`algerian_1km` ran 3.5+ hours without completing before being orphaned when the run aborted — inconclusive, not a pass. A fresh 3-region test with the fully-fixed image is in progress as of this writing (Cloud Build ID `a8b61b91-2302-4d24-81ad-70f64951922e`, started 2026-07-29T14:41:36Z); its result is not yet known.
*   No named-location physical anomaly (e.g. a specific channel wind-acceleration or upwelling case study) has been identified from real model output. Any such example in an earlier version of this document was illustrative, not measured.

## 4. C-Grid Dimension-Aware Masking

In 3D hydrodynamic solvers using staggered Arakawa C-grids, variables reside on distinct spatial sub-grids:
$$\text{Tracers } (T, S, \zeta) \in \text{Grid}_{\rho}(\eta_{\rho}, \xi_{\rho}), \quad U \in \text{Grid}_{u}(\eta_u, \xi_u), \quad V \in \text{Grid}_{v}(\eta_v, \xi_v)$$

If a validation script blindly applies $\text{Mask}_{\rho}(\eta_{\rho}, \xi_{\rho})$ to velocity components on a different sub-grid, `xarray` can perform an unintended outer join across non-matching spatial dimensions, ballooning memory use. `validate_marine_output.py`'s `_apply_matching_mask` guards against this by confirming $\text{dims}(\text{Mask}) \subseteq \text{dims}(\text{DataArray})$ before masking. (The specific "reduces to 1.8 seconds" performance figure from an earlier version of this document was not independently re-measured for this rewrite and has been removed rather than repeated unverified.)

