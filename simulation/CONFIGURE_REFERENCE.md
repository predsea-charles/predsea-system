# WRF Configure Reference

This project targets the same WRF/WPS configure path that previously worked on
the cloud VM:

- WRF version: `4.5`
- WPS version: `4.5`
- Base image family: Debian Bullseye
- WRF compiler choice: `34`
- Nesting option: `1`
- Architecture: `Linux x86_64`, GNU compiler with gcc, `dmpar`
- MPI wrappers: `mpif90`, `mpicc`
- NetCDF root: `/usr`
- WRF external NetCDF link path: `/usr/lib/x86_64-linux-gnu`
- NetCDF libraries: `-lnetcdff -lnetcdf`
- Jasper: source-built `2.0.33` installed under `/usr/local`

The Dockerfile is intentionally documented as a `linux/amd64` build because the
known-good WRF configure reference came from an x86_64 cloud VM.
