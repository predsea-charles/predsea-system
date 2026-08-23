#!/usr/bin/env bash
# compile_croco_balearic.sh - Compile custom CROCO binary for the Balearic 1 km Grid.
set -euo pipefail

CROCO_VERSION="2.1.3"
CROCO_SHA256="4b7464365f3e6197ed83b5ae8842cc1efc736add2c86e16a0ff188e7650661c1"

echo "========================================================================="
echo "🛠️ Starting Regional CROCO compiler"
echo "========================================================================="

# 1. Setup a temporary build directory inside our workspace
BUILD_DIR="tmp/croco_build"
mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"

# 2. Download stable CROCO source if not already present
if [ ! -f "croco.tar.gz" ]; then
    echo "📥 Downloading CROCO v${CROCO_VERSION} source..."
    curl --fail --location --retry 4 \
         "https://gitlab.inria.fr/croco-ocean/croco/-/archive/v${CROCO_VERSION}/croco-v${CROCO_VERSION}.tar.gz" \
         --output croco.tar.gz
    echo "${CROCO_SHA256}  croco.tar.gz" | shasum -a 256 -c
fi

# Extract source
if [ ! -d "croco_src" ]; then
    echo "📦 Extracting CROCO source..."
    tar -xzf croco.tar.gz
    mv "croco-v${CROCO_VERSION}" croco_src
fi

# 3. Copy source jobcomp and configurations
echo "⚙️ Configuring compile-time dimensions and options..."
# Ensure Homebrew path is loaded
export PATH="/opt/homebrew/bin:$PATH"

cp croco_src/OCEAN/jobcomp .
chmod +x jobcomp

# Conditional patching of jobcomp based on OS (macOS vs Linux/Docker)
if [[ "$OSTYPE" == "darwin"* ]]; then
  # Remove -mcmodel=medium flag on macOS ARM (unsupported by Apple Silicon gfortran)
  sed -i '' 's/-mcmodel=medium//g' jobcomp
  # Append the C netcdf library path to NETCDFLIB (since Homebrew installs C netcdf separately from netcdf-fortran)
  sed -i '' 's/NETCDFLIB=$(nf-config --flibs)/NETCDFLIB="$(nf-config --flibs) -L\/opt\/homebrew\/lib"/g' jobcomp
else
  # On standard Linux, we don't strip -mcmodel=medium, but we can do any other standard patches using standard sed -i (no empty quotes)
  echo "🐧 Standard Linux detected, compiling with default system netcdf-fortran links"
fi

# Run the unified, robust cross-platform Python patching utility
python3 ../../simulation/marine/croco/patch_croco_source.py

# 4. Invoke jobcomp
echo "🏗️ Compiling CROCO Balearic regional binary..."
# We pass source path and enable jobs parallelization
./jobcomp --src croco_src/OCEAN --jobs 4

# Check output executable
if [ -f "croco" ]; then
    cp croco ../../simulation/marine/croco/croco_balearic.exe
    echo "========================================================================="
    echo "✅ CROCO Balearic compiled successfully!"
    echo "   Binary saved: simulation/marine/croco/croco_balearic.exe"
    echo "========================================================================="
else
    echo "❌ Error: Compilation failed! Executable 'croco' not produced."
    exit 1
fi
