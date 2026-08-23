FROM debian:bookworm-slim AS builder

ARG SWAN_VERSION=4151
ARG SWAN_SHA256=325c229f3dde0b812db4ec9ae6fa1cd4086d2109562c389576590ce8f94b26bb

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gfortran \
        libnetcdf-dev \
        libnetcdff-dev \
        make \
        openmpi-bin \
        libopenmpi-dev \
        perl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN curl --fail --location --retry 4 \
      "https://swanmodel.sourceforge.io/download/zip/swan${SWAN_VERSION}.tar.gz" \
      --output swan.tar.gz \
    && echo "${SWAN_SHA256}  swan.tar.gz" | sha256sum --check \
    && tar -xzf swan.tar.gz

WORKDIR /src/swan4151
# SWAN's generated Makefile does not declare all Fortran module dependencies,
# so parallel compilation can race on *.mod creation.
RUN make config \
    && sed -i 's|^NETCDFROOT =.*|NETCDFROOT = /usr|' macros.inc \
    && sed -i 's|^  LIBS_SER = $(LIBS_SER) |  LIBS_SER += |' macros.inc \
    && sed -i 's|^  LIBS_OMP = $(LIBS_OMP) |  LIBS_OMP += |' macros.inc \
    && sed -i 's|^  LIBS_MPI = $(LIBS_MPI) |  LIBS_MPI += |' macros.inc \
    && sed -i 's|^  swch = $(swch) -netcdf|  swch += -netcdf|' macros.inc \
    && make mpi \
    && sed -i 's|echo "localhost" > machinefile|echo "localhost slots=$npmpi" > machinefile|' swanrun \
    && test -x swan.exe

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgfortran5 \
        libnetcdf19 \
        libnetcdff7 \
        openmpi-bin \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /src/swan4151/swan.exe /usr/local/bin/swan.exe
COPY --from=builder /src/swan4151/swanrun /usr/local/bin/swanrun

RUN useradd --create-home --uid 10001 predsea \
    && mkdir -p /work \
    && chown predsea:predsea /work \
    && chmod 0755 /usr/local/bin/swan.exe /usr/local/bin/swanrun

USER predsea
WORKDIR /work
ENTRYPOINT ["/usr/local/bin/swanrun"]
