#!/bin/bash
set -euo pipefail

# scripts/compile_swan.sh
# Compilation script for SWAN 41.45 parallel MPI execution on standard c2d-standard-16.

echo "=== Step 1: Install Dependencies ==="
apt-get update && apt-get install -y gfortran mpich libmpich-dev wget

echo "=== Step 2: Download and Extract SWAN 41.45 ==="
wget https://swanmodel.sourceforge.io/download/zip/swan4145.tar.gz
tar -xzf swan4145.tar.gz
cd swan4145

echo "=== Step 3: Configure Parallel MPI Build ==="
cp macros.inc.gfortran macros.inc

# Modify compiler settings in macros.inc for MPI compatibility
sed -i 's/F90_SER\s*=.*/F90_SER=gfortran/' macros.inc || true
sed -i 's/F90_OMP\s*=.*/F90_OMP=gfortran/' macros.inc || true
sed -i 's/F90_MPI\s*=.*/F90_MPI=mpif90/' macros.inc || true

echo "=== Step 4: Build SWAN MPI version ==="
make config
make mpi 2>&1 | tee compile_swan.log

echo "=== Step 5: Verify & Upload Executable ==="
# SWAN output executable is typically named swan.exe or swanrun depending on build
if [ -f swan.exe ]; then
    ls -la swan.exe
    gsutil cp swan.exe gs://predsea-hpc-outputs/binaries/swan/swan.exe
elif [ -f swanrun ]; then
    ls -la swanrun
    gsutil cp swanrun gs://predsea-hpc-outputs/binaries/swan/swan.exe
else
    echo "ERROR: SWAN compilation failed. Executable not found."
    exit 1
fi

echo "SWAN compilation and upload complete!"
