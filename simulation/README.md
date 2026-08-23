# Simulation

WRF/WPS build artifacts, domain setup scripts, namelists, and run automation live here.

Phase 2 includes:

- WRF v4.5 multi-stage Dockerfile
- WPS/WRF NetCDF-4 compilation support
- a two-domain operational profile (`d01` 9 km, `d02` 3 km)
- a preserved seven-domain 1 km profile for later high-resolution experiments
- GRIB2-to-`wrf.exe` pipeline automation

The operational profile deliberately stops at `d02`. Same-resolution child
domains are rejected before WPS/WRF execution, and the selected MPI layout is
validated against every active grid before `real.exe` runs.

Generate the default Balearic WPS namelist:

```bash
python simulation/setup_domain.py --output simulation/namelist.wps
```

Generate the preserved seven-domain 1 km research profile explicitly:

```bash
python simulation/setup_domain.py \
  --resolution-profile ultra-1km \
  --output simulation/namelist.wps
```

Build the WRF/WPS image:

```bash
docker build --platform linux/amd64 -t predsea-wrf:4.5 -f simulation/Dockerfile simulation
```

Run the pipeline inside the container with GRIB2 files mounted at `/data/gfs`.
