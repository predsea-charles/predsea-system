FROM debian:bookworm-slim AS builder

ARG CROCO_VERSION=2.1.3
ARG CROCO_SHA256=4b7464365f3e6197ed83b5ae8842cc1efc736add2c86e16a0ff188e7650661c1

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
        python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN curl --fail --location --retry 4 \
      "https://gitlab.inria.fr/croco-ocean/croco/-/archive/v${CROCO_VERSION}/croco-v${CROCO_VERSION}.tar.gz" \
      --output croco.tar.gz \
    && echo "${CROCO_SHA256}  croco.tar.gz" | sha256sum --check \
    && tar -xzf croco.tar.gz \
    && mv "croco-v${CROCO_VERSION}" croco

# Compile the official analytic BASIN case as an executable/runtime smoke
# target. The realistic Balearic executable is compiled separately because
# CROCO dimensions and physics are configuration-specific compile-time values.
WORKDIR /build
RUN cp /src/croco/OCEAN/jobcomp . \
    && cp /src/croco/OCEAN/cppdefs.h . \
    && sed -i 's/^#undef  BASIN/#define BASIN/' cppdefs.h \
    && sed -i 's/^#define REGIONAL/#undef  REGIONAL/' cppdefs.h \
    && chmod +x jobcomp \
    && ./jobcomp --src /src/croco/OCEAN --jobs 1 \
    && test -x croco

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgfortran5 \
        libnetcdf19 \
        libnetcdff7 \
        openmpi-bin \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/croco /usr/local/bin/croco
COPY --from=builder /src/croco/TEST_CASES/croco.in.Basin /opt/croco/croco.in.Basin
COPY smoke_basin.sh /usr/local/bin/smoke_basin.sh

RUN useradd --create-home --uid 10001 predsea \
    && mkdir -p /work \
    && chown predsea:predsea /work \
    && chmod 0755 /usr/local/bin/croco /usr/local/bin/smoke_basin.sh

USER predsea
WORKDIR /work
ENTRYPOINT ["/usr/local/bin/croco"]
