# PredSea WRF/WPS image.
#
# This build follows the proven Debian Bullseye WRF pattern and builds Jasper
# from source to avoid stale architecture-specific binary URLs.
# It is intended for linux/amd64 cloud runners. On Apple Silicon, build with:
# docker build --platform linux/amd64 -t predsea-wrf:4.5 -f simulation/Dockerfile simulation
FROM debian:bullseye AS wrf-builder

ARG DEBIAN_FRONTEND=noninteractive
ARG WRF_VERSION=4.5
ARG WPS_VERSION=4.5
ARG JASPER_VERSION=2.0.33
ARG WRF_CONFIGURE_OPTION=34
ARG WPS_CONFIGURE_OPTION=3

ENV DIR=/opt \
    WRF_DIR=/opt/WRF \
    WPS_DIR=/opt/WPS \
    JASPERLIB=/usr/local/lib \
    JASPERINC=/usr/local/include \
    LD_LIBRARY_PATH=/usr/local/lib \
    WRFIO_NCD_LARGE_FILE_SUPPORT=1 \
    NETCDF=/usr \
    NETCDF_classic=1 \
    WRF_EM_CORE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    cmake \
    csh \
    curl \
    file \
    flex \
    gfortran \
    gcc \
    g++ \
    git \
    libjpeg-dev \
    libnetcdf-dev \
    libnetcdff-dev \
    libopenmpi-dev \
    libpng-dev \
    m4 \
    make \
    netcdf-bin \
    openmpi-bin \
    perl \
    python3 \
    tcsh \
    wget \
    bzip2 \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/lib/x86_64-linux-gnu/libnetcdf* /usr/lib/

WORKDIR /opt

# Change "$(nproc)" to 1 to prevent QEMU segmentation faults on Mac
RUN wget -q https://github.com/jasper-software/jasper/archive/refs/tags/version-${JASPER_VERSION}.tar.gz -O jasper.tar.gz \
    && tar -xzf jasper.tar.gz \
    && cmake -S jasper-version-${JASPER_VERSION} -B jasper-build \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/usr/local \
        -DCMAKE_SKIP_INSTALL_RPATH=YES \
        -DJAS_ENABLE_DOC=OFF \
    && cmake --build jasper-build -j 1 \
    && cmake --install jasper-build \
    && rm -rf jasper.tar.gz jasper-version-${JASPER_VERSION} jasper-build

RUN git clone --branch v${WRF_VERSION} --depth 1 https://github.com/wrf-model/WRF.git WRF \
    && cd WRF \
    && git submodule update --init --recursive


WORKDIR /opt/WRF

RUN printf "%s\n1\n" "${WRF_CONFIGURE_OPTION}" | ./configure \
    && ./compile -j 1 em_real \
    && test -x run/real.exe \
    && test -x run/wrf.exe

WORKDIR /opt

RUN wget -q https://github.com/wrf-model/WPS/archive/refs/tags/v${WPS_VERSION}.tar.gz -O wps.tar.gz \
    && tar -xzf wps.tar.gz \
    && mv WPS-${WPS_VERSION} WPS \
    && rm wps.tar.gz

WORKDIR /opt/WPS

RUN printf "%s\n" "${WPS_CONFIGURE_OPTION}" | ./configure \
    && ./compile \
    && test -x geogrid.exe \
    && test -x ungrib.exe \
    && test -x metgrid.exe

FROM debian:bullseye-slim AS wrf-runtime

ARG DEBIAN_FRONTEND=noninteractive

ENV WRF_DIR=/opt/WRF \
    WPS_DIR=/opt/WPS \
    JASPERLIB=/usr/local/lib \
    JASPERINC=/usr/local/include \
    LD_LIBRARY_PATH=/usr/local/lib \
    PATH=/opt/WRF/run:/opt/WPS:${PATH}

RUN apt-get update && apt-get install -y --no-install-recommends \
    csh \
    libeccodes-tools \
    libgfortran5 \
    libnetcdf-dev \
    libnetcdff-dev \
    libpng16-16 \
    openmpi-bin \
    python3 \
    python3-netcdf4 \
    python3-pip \
    zlib1g \
    && rm -rf /var/lib/apt/lists/*

RUN mpirun --version

RUN mkdir -p /opt/predsea/bin

COPY --from=wrf-builder /usr/local/lib/libjasper* /usr/local/lib/
COPY --from=wrf-builder /usr/local/include/jasper /usr/local/include/jasper
COPY --from=wrf-builder /opt/WRF /opt/WRF
COPY --from=wrf-builder /opt/WPS /opt/WPS
COPY --from=wrf-builder /opt/WRF/run/real.exe /opt/predsea/bin/real.exe
COPY --from=wrf-builder /opt/WRF/run/wrf.exe /opt/predsea/bin/wrf.exe
COPY --from=wrf-builder /opt/WPS/geogrid.exe /opt/predsea/bin/geogrid.exe
COPY --from=wrf-builder /opt/WPS/ungrib.exe /opt/predsea/bin/ungrib.exe
COPY --from=wrf-builder /opt/WPS/metgrid.exe /opt/predsea/bin/metgrid.exe
COPY setup_domain.py /opt/predsea/setup_domain.py
COPY run_pipeline.sh /opt/predsea/run_pipeline.sh

WORKDIR /workspace

ENTRYPOINT ["/bin/bash"]
