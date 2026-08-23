# NEMO (Nucleus for European Modelling of the Ocean) Scaffold & Setup Guide

This directory houses the scaffolding, coordinates templates, and compilation specifications for compiling and running the proprietary physical ocean model (NEMO currents, sea surface height, temperature, and salinity) on high-performance compute resources.

---

## 🏗️ Recommended Compilation Architecture (GCE x86_64)

NEMO is MPI-heavy and compiler-sensitive. We strongly recommend compiling and running simulations on a Google Compute Engine **x86_64 VM** (e.g., standard `c2d-standard-8` spot instance running Debian/Rocky Linux), as local Apple Silicon environments require specialized architecture-specific adjustments.

### 1. System Dependencies Installation
Install standard GCC, GFortran, MPI, and NetCDF development packages:
```bash
sudo apt-get update && sudo apt-get install -y \
    build-essential \
    gfortran \
    mpich \
    libopenmpi-dev \
    libnetcdf-dev \
    libnetcdff-dev \
    libhdf5-serial-dev \
    hdf5-tools \
    m4 \
    cmake \
    liburi-perl
```

### 2. Compile XIOS (XML Input Output Server)
NEMO v4.2 requires XIOS-2.5 or XIOS-3.0 for highly parallelized output.
```bash
# Clone or download XIOS
svn co http://forge.ipsl.jussieu.fr/ioserver/svn/XIOS/branchs/xios-2.5 xios
cd xios

# Configure your architecture file (arch-GCC_LINUX.fcm / arch-GCC_LINUX.path)
# Run FCM compile
./make_xios --prod --arch GCC_LINUX
```

### 3. Extract & Compile NEMO v4.2
```bash
# Download NEMO release
git clone --branch 4.2.0 https://forge.nemo-ocean.eu/nemo/nemo.git nemo-4.2
cd nemo-4.2

# Copy model configuration templates
cp -r cfgs/ORCA2_ICE cfgs/BALEARIC_MED

# Linkcompiled XIOS libraries in your arch-GCC_GCE.fcm configuration
# Build configuration using 'makenemo'
./makenemo -r BALEARIC_MED -m GCC_GCE -j 8
```

---

## 🌐 Target Domain Specifications: Spanish Coast & Balearic Basin

NEMO runs are configured to cover the unified 1km Spanish Coast & Balearic Sea domain:
* **Longitude Range**: `-1.5° E` to `5.0° E`
* **Latitude Range**: `37.5° N` to `42.5° N`
* **Focus Areas**: Spanish Mediterranean coast (Valencia, Tarragona, Barcelona) and the Balearic Islands.
* **Vertical Grid**: 31 vertical depth $z$-levels, utilizing partial-step bathymetric masking for shallow coastal passages (SWAN wave boundary transition).

---

## 📈 Standard Parameters & NetCDF Output Layout

The compiled NEMO execution will generate daily hourly-interval files (e.g., `BALEARIC_1h_grid_T.nc`, `BALEARIC_1h_grid_U.nc`, `BALEARIC_1h_grid_V.nc`). 
The output dataset conforms to the following NetCDF coordinate schemas:

| Variable | Description | Dimension | Standard Unit |
| :--- | :--- | :--- | :--- |
| `nav_lon` | Grid point longitude | `(y, x)` | Degrees East |
| `nav_lat` | Grid point latitude | `(y, x)` | Degrees North |
| `time_counter` | Forecast timestamp | `(time)` | Seconds since epoch |
| `uo` | Eastward surface sea-water velocity | `(time, depth, y, x)` | $m/s$ |
| `vo` | Northward surface sea-water velocity | `(time, depth, y, x)` | $m/s$ |
| `zos` | Sea surface height above geoid | `(time, y, x)` | $m$ |
| `tos` | Sea surface temperature | `(time, y, x)` | °C or K |
| `sos` | Sea surface salinity | `(time, y, x)` | $psu$ |
