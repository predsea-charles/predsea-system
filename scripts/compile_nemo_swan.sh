#!/bin/bash
# ==============================================================================
# PredSea Ocean Modeling Suite Compiling Automation Script (NEMO & SWAN)
# Designed for standard x86_64 GCE VM instances (e.g., Debian/Ubuntu).
# ==============================================================================

set -euo pipefail

# Configurations
GCS_BUCKET="predsea-daily-outputs"
XIOS_SVN_URL="http://forge.ipsl.jussieu.fr/ioserver/svn/XIOS/branchs/xios-2.5"
NEMO_GIT_URL="https://forge.nemo-ocean.eu/nemo/nemo.git"
NEMO_BRANCH="4.2.0"
SWAN_TAR_URL="https://swanmodel.sourceforge.io/download/zip/swan4141.tar.gz"

BUILD_DIR="$HOME/predsea_build"
BIN_DIR="$BUILD_DIR/bin"
mkdir -p "$BUILD_DIR" "$BIN_DIR"

echo "========================================================================="
echo "🏗️  Starting PredSea Ocean Model Compilations (XIOS, NEMO, SWAN)"
echo "📂 Working directory: $BUILD_DIR"
echo "☁️  Target GCS bucket: gs://$GCS_BUCKET"
echo "========================================================================="

# ------------------------------------------------------------------------------
# Step 1: Install System Dependencies
# ------------------------------------------------------------------------------
echo "👉 [STEP 1/5] Installing system compiler and NetCDF dependencies..."
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
    liburi-perl \
    subversion \
    wget \
    tar \
    git

# ------------------------------------------------------------------------------
# Step 2: Download and Compile XIOS (XML Input/Output Server)
# ------------------------------------------------------------------------------
echo "👉 [STEP 2/5] Downloading and compiling XIOS (Parallel IO Server)..."
cd "$BUILD_DIR"
if [ ! -d "xios" ]; then
    echo "📥 Cloning XIOS from GitLab mirror..."
    git clone --branch xios-2.5 --depth 1 "https://gitlab.in2p3.fr/ipsl/projets/xios-projects/xios.git" xios || {
        echo "⚠️ Failed cloning xios-2.5 branch. Trying default branch..."
        git clone --depth 1 "https://gitlab.in2p3.fr/ipsl/projets/xios-projects/xios.git" xios
    }
else
    echo "ℹ️ XIOS source directory already exists. Skipping download."
fi

cd xios
# Build XIOS using standard GCC compilation flags
echo "⚙️  Building XIOS-2.5 (this can take several minutes)..."
./make_xios --prod --arch GCC_LINUX --job 4 || {
    echo "⚠️ Failed compiling XIOS. Trying fallback with fewer parallel jobs..."
    ./make_xios --prod --arch GCC_LINUX --job 1
}

# ------------------------------------------------------------------------------
# Step 3: Download and Compile NEMO (v4.2)
# ------------------------------------------------------------------------------
echo "👉 [STEP 3/5] Downloading and compiling NEMO v4.2..."
cd "$BUILD_DIR"
if [ ! -d "nemo-4.2" ]; then
    echo "📥 Cloning NEMO ocean model (branch $NEMO_BRANCH)..."
    git clone --branch "$NEMO_BRANCH" "$NEMO_GIT_URL" nemo-4.2
else
    echo "ℹ️ NEMO source directory already exists."
fi

cd nemo-4.2
# Copy default ORCA2 ocean configuration as reference template
echo "⚙️ Creating BALEARIC_MED custom configurations..."
if [ ! -d "cfgs/BALEARIC_MED" ]; then
    cp -r cfgs/ORCA2_ICE cfgs/BALEARIC_MED
fi

# Configure NEMO compiler flags & XIOS paths
# Set standard compiler and include paths to GCC/gfortran
echo "⚙️ Setting up compilation architecture paths..."
ARCH_FILE="arch/arch-GCC_GCE.fcm"
cat << 'EOF' > "$ARCH_FILE"
%NUD_INC              -I/usr/include
%NUD_LIB              -lnetcdff -lnetcdf -lhdf5_hl -lhdf5 -lz
%XIOS_INC             -I$BUILD_DIR/xios/inc
%XIOS_LIB             -L$BUILD_DIR/xios/lib -lxios
%CPP                  cpp -D_GLIBCXX_USE_CXX11_ABI=0
%FC                   mpif90
%FCFLAGS              -fdefault-real-8 -O3 -funroll-loops -fcray-pointer -ffree-line-length-none
%FFLAGS               %FCFLAGS
%LD                   mpif90
%LDFLAGS              -O3
%FPPFLAGS             -P -C -traditional
%AR                   ar
%ARFLAGS              rs
%MAKE                 make
EOF

# Resolve variables in the arch configuration file
sed -i "s|\$BUILD_DIR|$BUILD_DIR|g" "$ARCH_FILE"

# Build NEMO executable
echo "⚙️  Running makenemo compile..."
./makenemo -r BALEARIC_MED -m GCC_GCE -j 4

# Extract binary
if [ -f "cfgs/BALEARIC_MED/BLD/bin/nemo.exe" ]; then
    echo "✅ NEMO compiled successfully."
    cp "cfgs/BALEARIC_MED/BLD/bin/nemo.exe" "$BIN_DIR/nemo.exe"
else
    echo "❌ Error: nemo.exe compilation failed."
    exit 1
fi

# ------------------------------------------------------------------------------
# Step 4: Download and Compile SWAN Wave Model
# ------------------------------------------------------------------------------
echo "👉 [STEP 4/5] Downloading and compiling SWAN wave model..."
cd "$BUILD_DIR"
if [ ! -d "swan4141" ]; then
    echo "📥 Downloading SWAN distribution..."
    wget "$SWAN_TAR_URL"
    tar -zxvf swan4141.tar.gz
fi

cd swan4141
echo "⚙️  Configuring SWAN for GCC + MPI..."
# Configures make rules for Linux architecture with MPI/gfortran compilers
make config

echo "⚙️  Compiling SWAN parallel MPI executable..."
make mpi

# Extract binary
if [ -f "swan.exe" ]; then
    echo "✅ SWAN compiled successfully."
    cp "swan.exe" "$BIN_DIR/swan.exe"
else
    echo "❌ Error: swan.exe compilation failed."
    exit 1
fi

# ------------------------------------------------------------------------------
# Step 5: Upload Executables to Google Cloud Storage
# ------------------------------------------------------------------------------
echo "👉 [STEP 5/5] Archiving binaries to Google Cloud Storage..."
cd "$BIN_DIR"

if command -v gcloud &> /dev/null; then
    echo "Uploading to gs://predsea-daily-outputs/binaries/ ..."
    gcloud storage cp nemo.exe "gs://predsea-daily-outputs/binaries/nemo.exe" || true
    gcloud storage cp swan.exe "gs://predsea-daily-outputs/binaries/swan.exe" || true
    echo "Uploading to gs://predsea-hpc-outputs/binaries/ ..."
    gcloud storage cp nemo.exe "gs://predsea-hpc-outputs/binaries/nemo.exe" || true
    gcloud storage cp swan.exe "gs://predsea-hpc-outputs/binaries/swan.exe" || true
    echo "🎉 Compilation Suite complete. Executables archived successfully in both GCS buckets!"
else
    echo "⚠️ Warning: 'gcloud' command line tool not found. Compiled executables remain stored at $BIN_DIR."
fi
