#!/bin/bash
set -euo pipefail

# scripts/compile_roms.sh
# Compilation script for CROCO (open-source community ROMS fork) on a standard c2d-standard-16.

echo "=== Step 1: Install Dependencies ==="
apt-get update && apt-get install -y \
  gfortran gcc g++ \
  mpich libmpich-dev \
  libnetcdf-dev libnetcdff-dev \
  libhdf5-dev \
  wget git

echo "=== Step 2: Clone CROCO Repository ==="
# Community ROMS fork (no licensing registration needed)
if [ ! -d "croco" ]; then
    git clone https://github.com/CROCO-ocean/croco.git
fi
cd croco

echo "=== Step 3: Configure Balearic Domain cppdefs.h ==="
cp OCEAN/cppdefs.h OCEAN/cppdefs.h.bak

# Inject the BALEARIC specific ocean model parameters into cppdefs.h
cat << 'EOF' >> OCEAN/cppdefs.h

/*
 * ====================================================================
 * PREDSEA BALEARIC EXPERIMENT DEFINITIONS
 * ====================================================================
 */
#define BALEARIC
#ifdef BALEARIC
# define UV_ADV            /* Advection of momentum */
# define UV_COR            /* Coriolis terms */
# define UV_VIS2           /* Lateral harmonic viscosity */
# define MIX_S_UV          /* Mixing of momentum along sigma-surfaces */
# define DJ_GRADPS         /* Hydrostatic pressure gradient error reduction */
# define NONLIN_EOS        /* Non-linear Equation of State */
# define BULK_FLUXES       /* For bulk formulation of WRF atmospheric forcing */
# define SPONGE            /* Enable boundary sponge layers for numerical stability */
#endif
EOF

echo "=== Step 4: Run CROCO jobcomp Compiler Script ==="
cd OCEAN
chmod +x jobcomp

# Configure compilers and netcdf paths inside jobcomp for gfortran
sed -i 's/FC=gfortran/FC=gfortran/' jobcomp || true

# Run compilation
./jobcomp 2>&1 | tee compile_croco.log

echo "=== Step 5: Verify croco Binary & Upload ==="
if [ -f croco ]; then
    ls -la croco
    gsutil cp croco gs://predsea-hpc-outputs/binaries/roms/croco.exe
    echo "ROMS/CROCO compilation complete and uploaded successfully!"
else
    echo "ERROR: CROCO compilation failed. Executable not found."
    exit 1
fi
