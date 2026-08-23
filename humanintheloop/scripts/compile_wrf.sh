#!/bin/bash
set -euo pipefail

# scripts/compile_wrf.sh
# Script to compile WRF 4.5 and WPS 4.5 on a standard c2d-standard-16 VM.
# Run with root or sudo privileges.

echo "=== Step 1: System Dependencies ==="
apt-get update && apt-get install -y \
  gfortran gcc g++ \
  mpich libmpich-dev \
  libnetcdf-dev libnetcdff-dev \
  libhdf5-dev \
  libpng-dev libjasper-dev \
  wget curl git csh tcsh \
  m4 perl

echo "=== Step 2: Set Environment ==="
export NETCDF=/usr
export HDF5=/usr
export JASPERLIB=/usr/lib
export JASPERINC=/usr/include

echo "=== Step 3: Download WRF 4.5 Source ==="
wget https://github.com/wrf-model/WRF/releases/download/v4.5/v4.5.tar.gz
tar -xzf v4.5.tar.gz
cd WRFV4.5

echo "=== Step 4: Configure for GNU + dmpar (Option 34) ==="
# Using printf is highly portable to feed interactive configuration prompts
printf "34\n1\n" | ./configure

echo "=== Step 5: Compile em_real (Takes 60-90 minutes) ==="
./compile -j 8 em_real 2>&1 | tee compile_wrf.log

echo "=== Step 6: Verify WRF Binaries ==="
ls -la main/wrf.exe main/real.exe main/ndown.exe

echo "=== Step 7: Download and Compile WPS ==="
cd ..
wget https://github.com/wrf-model/WPS/releases/download/v4.5/v4.5.tar.gz -O WPS.tar.gz
tar -xzf WPS.tar.gz
cd WPSV4.5

printf "1\n" | ./configure  # gfortran serial
./compile 2>&1 | tee compile_wps.log

echo "=== Verify WPS Binaries ==="
ls -la geogrid.exe metgrid.exe ungrib.exe

echo "=== Step 8: Upload Compiled Binaries to GCS ==="
gsutil -m cp main/wrf.exe gs://predsea-hpc-outputs/binaries/wrf/ || gsutil cp main/wrf.exe gs://predsea-hpc-outputs/binaries/wrf/
gsutil -m cp main/real.exe gs://predsea-hpc-outputs/binaries/wrf/ || gsutil cp main/real.exe gs://predsea-hpc-outputs/binaries/wrf/
gsutil -m cp *.exe gs://predsea-hpc-outputs/binaries/wps/ || gsutil cp *.exe gs://predsea-hpc-outputs/binaries/wps/

echo "WRF and WPS compilation complete. Binaries uploaded successfully."
