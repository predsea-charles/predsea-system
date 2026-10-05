"""
strip_croco.py -- removes the unused CROCO builder stage from
Dockerfile.ww3-batch, now that CROCO is no longer part of this pipeline.

Run this from the ROOT of your predsea-system repo:

    python3 strip_croco.py

It edits Dockerfile.ww3-batch IN PLACE. Review the change with
`git diff Dockerfile.ww3-batch` before committing.

Each of the 4 edits below is guarded by an `assert ... in text` check --
if the exact text isn't found (e.g. the file has since changed), it will
raise an AssertionError and stop WITHOUT writing anything, rather than
silently making a partial or incorrect edit.
"""
from pathlib import Path

path = Path("Dockerfile.ww3-batch")
if not path.exists():
    raise SystemExit(
        "ERROR: Dockerfile.ww3-batch not found in the current directory. "
        "Run this script from the root of your predsea-system repo."
    )

text = path.read_text()
original_text = text

# 1. Remove the entire croco_builder stage
old1 = '''FROM debian:bookworm-slim AS croco_builder

ARG CROCO_VERSION=2.1.3
ARG CROCO_SHA256=4b7464365f3e6197ed83b5ae8842cc1efc736add2c86e16a0ff188e7650661c1
ARG PREDSEA_CROCO_LM=499
ARG PREDSEA_CROCO_MM=399
ARG PREDSEA_CROCO_N=32
RUN apt-get update && apt-get install -y --no-install-recommends \\
      ca-certificates curl gfortran libnetcdf-dev libnetcdff-dev make \\
      openmpi-bin libopenmpi-dev python3 \\
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN curl --fail --location --retry 4 \\
      "https://gitlab.inria.fr/croco-ocean/croco/-/archive/v${CROCO_VERSION}/croco-v${CROCO_VERSION}.tar.gz" \\
      --output croco.tar.gz \\
    && echo "${CROCO_SHA256}  croco.tar.gz" | sha256sum --check \\
    && mkdir -p tmp/croco_build \\
    && tar -xzf croco.tar.gz -C tmp/croco_build \\
    && mv "tmp/croco_build/croco-v${CROCO_VERSION}" tmp/croco_build/croco_src
COPY simulation/marine/croco/patch_croco_source.py /build/patch_croco_source.py
RUN mkdir -p /usr/local/bin \\
    && for region in alboran_1km:499:249 algerian_1km:949:299 balearic_1km:499:399 gulf_of_lion_1km:498:198 tyrrhenian_1km:648:649; do \\
         name=$(echo $region | cut -d: -f1); \\
         lm=$(echo $region | cut -d: -f2); \\
         mm=$(echo $region | cut -d: -f3); \\
         echo "Building CROCO binary for $name (LM=$lm, MM=$mm)..."; \\
         rm -rf /build/tmp/croco_build/Build /build/tmp/croco_build/Compile; \\
         PREDSEA_CROCO_LM=$lm PREDSEA_CROCO_MM=$mm PREDSEA_CROCO_N=32 python3 /build/patch_croco_source.py; \\
         cp /build/tmp/croco_build/croco_src/OCEAN/jobcomp /build/tmp/croco_build/jobcomp; \\
         chmod 0755 /build/tmp/croco_build/jobcomp; \\
         (cd /build/tmp/croco_build && ./jobcomp --src croco_src/OCEAN --jobs 8 && test -x croco && mv croco /usr/local/bin/croco_${name}); \\
       done \\
    && ln -s /usr/local/bin/croco_balearic_1km /usr/local/bin/croco_balearic

FROM python:3.11-slim-bookworm'''

new1 = '''# NOTE: the CROCO builder stage that used to live here was removed once
# this project stopped running CROCO -- this image now only builds WW3.
FROM python:3.11-slim-bookworm'''

assert old1 in text, "STEP 1 FAILED: croco_builder stage block not found verbatim -- aborting, check for whitespace drift"
text = text.replace(old1, new1)
print("Step 1/4: removed croco_builder stage -- OK")

# 2. Remove the COPY --from=croco_builder + chmod lines
old2 = '''COPY --from=croco_builder /usr/local/bin/croco_* /usr/local/bin/
RUN chmod 0755 /usr/local/bin/croco_*

'''
assert old2 in text, "STEP 2 FAILED: croco COPY/chmod lines not found verbatim -- aborting"
text = text.replace(old2, "")
print("Step 2/4: removed croco binary COPY + chmod -- OK")

# 3. Remove the croco.in.balearic + prepare_croco_in.py COPY lines
old3 = '''COPY simulation/marine/croco/croco.in.balearic /app/simulation/marine/croco/croco.in.balearic
COPY simulation/marine/croco/prepare_croco_in.py /app/simulation/marine/croco/prepare_croco_in.py
'''
assert old3 in text, "STEP 3 FAILED: croco.in.balearic/prepare_croco_in.py COPY lines not found verbatim -- aborting"
text = text.replace(old3, "")
print("Step 3/4: removed croco.in.balearic + prepare_croco_in.py COPY lines -- OK")

# 4. Trim the validation RUN chain
old4 = '''RUN test -x /usr/local/bin/croco_balearic \\
    && test -x /usr/local/bin/ww3_grid \\
    && test -x /usr/local/bin/ww3_prnc \\
    && test -x /usr/local/bin/ww3_bounc \\
    && test -x /usr/local/bin/ww3_shel \\
    && test -x /usr/local/bin/ww3_ounf \\
    && python3 -c "import copernicusmarine, netCDF4, numpy, scipy, xarray" \\
    && python3 /app/scripts/prepare_croco_bulk_forcing.py --help \\
    && python3 /app/scripts/run_marine_simulation.py --help'''

new4 = '''RUN test -x /usr/local/bin/ww3_grid \\
    && test -x /usr/local/bin/ww3_prnc \\
    && test -x /usr/local/bin/ww3_bounc \\
    && test -x /usr/local/bin/ww3_shel \\
    && test -x /usr/local/bin/ww3_ounf \\
    && python3 -c "import copernicusmarine, netCDF4, numpy, scipy, xarray" \\
    && python3 /app/scripts/run_marine_simulation.py --help'''

assert old4 in text, "STEP 4 FAILED: validation RUN chain not found verbatim -- aborting"
text = text.replace(old4, new4)
print("Step 4/4: trimmed validation RUN chain -- OK")

path.write_text(text)
lines_before = original_text.count("\n")
lines_after = text.count("\n")
print(f"\nDone. Dockerfile.ww3-batch: {lines_before} lines -> {lines_after} lines "
      f"({lines_before - lines_after} lines removed).")
print("Now run: git diff Dockerfile.ww3-batch   (review before committing)")
