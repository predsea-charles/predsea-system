BALEARIC HIGH-RESOLUTION DOMAIN SPECIFICATION
============================================

This document specifies the authoritative grid parameters, coordinates, nested domains, and forcing conditions for the PredSea parallel high-performance ocean-atmosphere coupled physics modeling system.

## Geographic Boundaries
* **Longitude Range**: $0.5^\circ\text{ E}$ to $5.5^\circ\text{ E}$
* **Latitude Range**:  $37.5^\circ\text{ N}$ to $41.5^\circ\text{ N}$

---

## 1. WRF Nested Domains
The Weather Research and Forecasting (WRF) model utilizes a three-tier nested grid configuration to downscale global inputs to high-resolution wind fields for localized wave and current forcing.

* **d01 (Coarse)**: 9km horizontal resolution
  * **Coverage**: Western Mediterranean
  * **Bounds**: Longitude $-5.0^\circ$ to $15.0^\circ$, Latitude $34.0^\circ$ to $48.0^\circ$
* **d02 (Intermediate)**: 3km horizontal resolution
  * **Coverage**: Balearic Basin
* **d03 (Fine Nest)**: 1km horizontal resolution
  * **Coverage**: Local Balearic channels, coastlines, and harbor approaches

---

## 2. ROMS / CROCO Grid
The regional ocean model uses a single high-resolution grid aligned with the fine-scale atmospheric forcing.

* **Horizontal Resolution**: 1km ($1/111^\circ$ grid spacing)
* **Vertical Structure**: 30 terrain-following sigma levels ($\sigma$-coordinates)
* **Bathymetry**: GEBCO 2023 15-arc-second gridded database
  * **Processing**: Interpolated to 1km grid, clipped to a minimum depth of $5\text{ m}$ to ensure numerical wetting-drying stability, and smoothed with a Gaussian filter ($\sigma = 1.0$) to minimize hydrostatic pressure gradient errors.

---

## 3. SWAN Wave Grid
The Simulating Waves Nearshore (SWAN) model shares the same bathymetric and horizontal grid structure as ROMS to facilitate future potential coupling.

* **Horizontal Resolution**: 1km (coaligned with ROMS rho-grid)
* **Spectral Resolution**: 36 directions ($10^\circ$ directional spacing), 32 frequencies
* **Atmospheric Forcing**: Wind speed and direction from WRF d03 1km nested output
* **Boundary Forcing**: CMEMS Mediterranean Wave forecast 2D wave spectra at the open ocean boundary edges

---

## 4. Initial and Boundary Conditions

* **Atmospheric Force**: ECMWF IFS (Integrated Forecasting System) high-resolution global fields (already downloaded daily by the production pipeline).
* **Ocean Physics Boundary**: CMEMS Mediterranean Sea Physics Analysis and Forecast (NEMO model output, downloaded daily by the production pipeline).
* **Waves Boundary**: CMEMS Mediterranean Sea Wave Analysis and Forecast (SWAN/WAM output, downloaded daily).
