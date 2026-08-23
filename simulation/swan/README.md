# SWAN (Simulating WAves Nearshore)

This directory houses the scaffolding, computational grid boundaries, and bathymetry specifications for compiling and running the SWAN coastal/shallow wave modeling system.

---

## 🏗️ SWAN Compilation & Build Guide

SWAN is optimized for shallow wave transformation, local wind-wave generation, bathymetric refraction, and coastal sheltering around islands. It should be built on the same Google Compute Engine x86_64 VM.

### 1. Build Requirements
Ensure GFortran and standard MPI packages are present:
```bash
sudo apt-get update && sudo apt-get install -y gfortran mpich
```

### 2. Download and Compile SWAN
```bash
# Download the pinned stable SWAN 41.51 distribution
wget https://swanmodel.sourceforge.io/download/zip/swan4151.tar.gz
echo "325c229f3dde0b812db4ec9ae6fa1cd4086d2109562c389576590ce8f94b26bb  swan4151.tar.gz" | sha256sum -c -
tar -zxvf swan4151.tar.gz
cd swan4151

# Generate the appropriate Makefile (e.g., for GCC + MPI)
make config

# Compile the MPI version
make mpi
```
* **Compiled Binary**: Creates `swan.exe`. Move this binary into the execution folder of your Spot VM startup routine.

The reproducible production build is now
`simulation/marine/swan/Dockerfile`. Build it with:

```bash
gcloud builds submit \
  simulation/marine/swan \
  --project=predsea-api \
  --region=europe-west1 \
  --config=simulation/marine/swan/cloudbuild.yaml
```

Do not use the old 41.41 compile script for a native forecast benchmark.

---

## 🌐 Computational Grid: Spanish Coast & Balearic Coastal Domain

SWAN utilizes a high-resolution regular coordinate grid matching our WRF `d03` nest:
* **Horizontal Coverage**: `-1.5° E` to `5.0° E`, `37.5° N` to `42.5° N`
* **Grid Resolution**: `0.01°` ($\approx 1\text{ km}$ spacing).
* **Bathymetry Input**: GEBCO (General Bathymetric Chart of the Oceans) 15 arc-second high-precision dataset cropped to domain coordinates.
* **Open Boundaries**: Wave spectra at open sea boundaries are forced by CMEMS Mediterranean wave models or global WW3 forecasts.
* **Wind Forcing**: Driven directly by high-resolution WRF 10m wind fields (`u10`, `v10`) updated hourly.

---

## 📈 Standard Parameters & NetCDF Output Layout

SWAN simulations generate a single time-series NetCDF output file containing primary wave variables (e.g., `BALEARIC_waves_forecast.nc`).
The output dataset conforms to the following NetCDF schemas:

| Variable | Description | Dimension | Standard Unit |
| :--- | :--- | :--- | :--- |
| `longitude` | Grid point longitude | `(longitude)` | Degrees East |
| `latitude` | Grid point latitude | `(latitude)` | Degrees North |
| `time` | Forecast timestamp | `(time)` | Seconds since epoch |
| `hs` | Significant wave height | `(time, latitude, longitude)` | $m$ |
| `tpp` | Peak wave period | `(time, latitude, longitude)` | $s$ |
| `dir` | Mean wave direction (meteorological) | `(time, latitude, longitude)` | Degrees |
