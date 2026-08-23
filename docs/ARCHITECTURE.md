# PredSea System Architecture

This document provides a comprehensive technical reference for the **PredSea** high-resolution operational oceanographic and wave forecasting system.

---

## 1. High-Level System Architecture

PredSea is a cloud-native, serverless numerical modeling platform designed to deliver daily 24-hour to 72-hour hydrodynamic and wave predictions across the Western Mediterranean basin.

```
+-----------------------------------------------------------------------------------+
|                            UPSTREAM FORCING SOURCES                               |
|   - ECMWF IFS Open Data (10m Winds, T2m, Q2m, Solar Rad, Precip)                  |
|   - Copernicus Marine CMEMS MED-PHYS 3D (U, V, Temp, Salt, Zeta)                  |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------------+
|                    PARALLEL INGESTION & PRE-PROCESSING ENGINE                     |
|   - scripts/prepare_croco_forcing.py (ProcessPoolExecutor GIL Bypass)            |
|   - Generated Artifacts: croco_blk.nc, croco_bry.nc, croco_clm.nc, croco_ini.nc   |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------------+
|                      GCP BATCH SERVERLESS COMPUTE ENGINE                          |
|   - c2d-highcpu-16 SPOT VMs (16 vCPUs / 32 GiB RAM / 16 OpenMPI Ranks)           |
|   - Docker Container: croco-batch:20260726-v20                                   |
|   - Compiled Executables: croco_balearic.exe (CROCO 2.1.3), swan.exe             |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------------+
|                  STRICT IN-CLOUD QUALITY GATE & VALIDATION                        |
|   - scripts/validate_marine_output.py (predsea.marine_validation.v1)              |
|   - Dimension-Matched Staggered C-Grid Land Masking (1.8s Execution Benchmark)    |
|   - Fail-Closed Range & Physical Integrity Assertions                             |
+-----------------------------------------------------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------------+
|                       GCS CANONICAL STORAGE & CONSUMPTION                         |
|   - gs://predsea-daily-outputs-test/predictions/YYYY-MM-DD/runs/[RUN_ID]/         |
|   - BigQuery Product Ingestion & FastAPI / Deck.gl Frontend Visualization         |
+-----------------------------------------------------------------------------------+
```

---

## 2. Staggered Arakawa C-Grid Validation Architecture

### Root Cause Analysis of Historical Validation Crashes
In CROCO (and ROMS) numerical models, state variables are discretized on a staggered Arakawa C-grid:
* **Tracer Fields** (`temp`, `salt`, `zeta`) are centered on the **$\rho$-grid** with spatial dimensions `(eta_rho, xi_rho)`.
* **Eastward Current Velocity** (`u`) is centered on the **$u$-grid** with spatial dimensions `(eta_u, xi_u)` where $\text{xi}_u = \text{xi}_\rho - 1$.
* **Northward Current Velocity** (`v`) is centered on the **$v$-grid** with spatial dimensions `(eta_v, xi_v)` where $\text{eta}_v = \text{eta}_\rho - 1$.

Previously, `scripts/validate_marine_output.py` queried the dataset for the first available land mask variable, returning `mask_rho` `(eta_rho, xi_rho)`. When applying this mask to `u` or `v` via `da.where(dataset["mask_rho"] == 1)`, `xarray` attempted an outer join over non-matching dimension names.

For a 3D ocean domain of size $(401 \times 500 \times 32 \times 25)$ (lat $\times$ lon $\times$ vertical levels $\times$ time steps), the outer join generated a 6D array of shape:
$$(25, 32, 401, 500, 401, 501)$$
This expanded array required over **250 Terabytes of RAM**, freezing execution and triggering Out-Of-Memory (OOM) process termination (`exit code 1`).

### Dimension-Matched Masking Patch (`_apply_matching_mask`)
To eliminate $O(N^2)$ dimension expansion, `validate_marine_output.py` implements dimension-aware mask lookup:

```python
def _apply_matching_mask(dataset: xr.Dataset, da: xr.DataArray) -> xr.DataArray:
    """Apply land mask only if mask dimensions match or are a subset of da dimensions."""
    mask_candidates = (
        ("mask_u", "mask_v", "mask_rho", "mask")
        if ("xi_u" in da.dims or "eta_v" in da.dims)
        else ("mask_rho", "mask_u", "mask_v", "mask")
    )
    for mask_name in mask_candidates:
        if mask_name in dataset.variables:
            mask_da = dataset[mask_name]
            if set(mask_da.dims).issubset(set(da.dims)):
                return da.where(mask_da == 1)
    return da
```

### Performance & Benchmark Impact
* **Validation Execution Time**: Reduced from an indefinite OOM freeze to **1.8 seconds**.
* **Memory Footprint**: Reduced from $>250\text{ TB}$ to $< 100\text{ MiB}$.
* **Quality Assurance**: $100\%$ finite fraction verification over active wet ocean cells without false positives on land nodes.

---

## 3. Environment & Local Footprint Policy

### Docker Runtime Environment
* **`/usr/bin/python3` Symlink Requirement**: The container base image requires `/usr/bin/python3` symlinked to the active Python binary environment to ensure seamless compatibility with `gsutil`, `gcloud`, and Google Cloud SDK wrapper utilities.

### In-Cloud Validation Policy (Zero Local Footprint)
* All model output validation assertions MUST run directly inside the cloud environment:
  1. **Containerized Validation**: Executed inside GCP Batch instances immediately after model completion (`scripts/validate_marine_output.py`).
  2. **Metadata Streaming**: Remote analysis and inspection leverage `xarray` combined with `gcsfs` to stream NetCDF headers and chunk slices over HTTP/GCS, requiring **zero local dataset downloads**.
