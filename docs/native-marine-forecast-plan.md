# PredSea Native Marine Forecast Implementation

Last updated: 2026-07-22

## System-of-record statement

PredSea owns and runs the WRF atmospheric forecast. A native Balearic SWAN
24-hour staging forecast has now been validated. Native CROCO is not yet
validated: its real grid and forcing preparation pass, but the first bounded
execution stopped on a climatology NetCDF time-coordinate contract. That defect
is fixed and the corrected immutable image is ready for the six-hour rerun.
Customer-facing production remains on the existing fallback path.

The target is:

```text
ECMWF -> WPS/WRF -> PredSea atmosphere
                    |              |
                    v              v
             SWAN waves       CROCO ocean
                    \              /
                     PredSea forecast bundle
                              |
                         API -> Relay
```

Copernicus Marine remains an upstream source for initial/open-boundary
conditions, an independent validation baseline, and an operational fallback. It
must not be labelled as native PredSea output.

## Safety boundary

Native marine development runs only in staging and writes immutable,
run-scoped objects. The existing production API and daily ETL remain unchanged
until all promotion gates pass. A failed SWAN or CROCO run cannot replace a
valid Copernicus-backed product.

## First Region & Multi-Region Coastal Expansion

The authoritative first tile is `simulation/marine/regions/balearic_1km.json`, representing the baseline benchmark region. Further regions expand the system across the Western Mediterranean, partitioning the domain into high-resolution 1 km tiles that align perfectly with the national coastlines of Spain, France, and Italy:

### 1. Spain East Coast & Balearics (Authority Tile)
* **Configuration**: `simulation/marine/regions/balearic_1km.json`
* **Bounds**: `0.5° E to 5.5° E`, `37.5° N to 41.5° N`
* **Coverage**: Catalonia (Barcelona, Tarragona), Valencia, Alicante, and the Balearic Islands.

### 2. Spain South Coast & Gibraltar
* **Configuration**: `simulation/marine/regions/alboran_1km.json`
* **Bounds**: `-6.0° E to -1.0° E`, `35.0° N to 37.5° N`
* **Coverage**: Andalusia (Málaga, Almería, Marbella) and the Strait of Gibraltar gateway.

### 3. France South Coast & Gulf of Lion
* **Configuration**: `simulation/marine/regions/gulf_of_lion_1km.json`
* **Bounds**: `2.0° E to 6.5° E`, `41.5° N to 44.5° N`
* **Coverage**: Occitanie, Provence-Alpes-Côte d'Azur (Marseille, Toulon, Cannes, Nice), and the wind-swept Gulf of Lion shelf.

### 4. Italy West Coast & Tyrrhenian
* **Configuration**: `simulation/marine/regions/tyrrhenian_1km.json`
* **Bounds**: `7.5° E to 14.0° E`, `38.0° N to 44.5° N`
* **Coverage**: Liguria (Genoa), Tuscany (Livorno), Lazio (Rome), Campania (Naples), Sardinia, Corsica, and Western Sicily.

### 5. Southern Western Mediterranean (Algerian Basin)
* **Configuration**: `simulation/marine/regions/algerian_1km.json`
* **Bounds**: `-1.0° E to 8.5° E`, `35.0° N to 38.0° N`
* **Coverage**: Algerian coast (Algiers, Oran) and steep southern continental slopes.

All regions are defined using the same versioned JSON schema (`marine_region.schema.json`). Inland destinations do not expand a marine compute region. This spatial partitioning ensures optimal computational efficiency, custom-tuned local timesteps (to handle regional wave propagation CFL limits), and direct alignment with regional buoy validation datasets.

## Execution stages

| Stage | Output required for success |
|---|---|
| Select cycle and region | Immutable run manifest |
| Fetch WRF/CMEMS inputs | Checksummed forcing inventory |
| Validate forcing | Complete time, variable, depth and boundary coverage |
| Prepare grid/bathymetry | Versioned grid files and validation report |
| Run SWAN | Native parallel SWAN VTK plus logs |
| Canonicalize SWAN | Deterministic consolidated PredSea NetCDF |
| Validate SWAN | Hourly coverage, full bbox, finite and physical wave values |
| Run CROCO | Native CROCO NetCDF plus logs/restarts |
| Validate CROCO | Hourly coverage, full bbox, finite and physical ocean values |
| Expand validated regional tiles | Alboran/Gibraltar, Gulf of Lion, Tyrrhenian and Algerian tiles each pass 6 h then 24 h SWAN/CROCO gates |
| Assemble multi-region bundle | All regional manifests align in time, overlap, variables, grid and lineage |
| Publish staging bundle | PredSea-owned immutable bundle and lineage manifest |
| Validate API | Route/place JSON and maps across every supported region consume native outputs |
| Promote | Atomic production pointer update |

The benchmark runner `scripts/run_marine_benchmark.py` is fail-closed. It only
writes `SUCCESS` when the command exits zero, the output exists, and
`scripts/validate_marine_output.py` verifies its content. It records real wall
time, disk growth, output size, CPU count and compute cost when a current hourly
VM price is supplied.

## Forcing correction discovered during audit

The retained object
`forcing/cmems/2026-07-16/cmems_ocean_forcing.nc` contains 121 hourly surface
current fields (`uo`, `vo`) on a 228 x 519 grid. This is useful for comparison
and possibly surface-current nudging, but it is not sufficient to initialize
and force CROCO. CROCO also requires three-dimensional temperature, salinity
and velocity fields, sea-surface height, vertical coordinates, and open-boundary
coverage.

The forcing downloader must therefore produce separate, validated products:

- `cmems_ocean_3d.nc`: temperature, salinity, 3-D currents and depth;
- `cmems_sea_level.nc`: sea-surface height;
- `cmems_wave_boundary.nc`: wave spectra or the complete boundary parameters
  required by the selected SWAN boundary formulation;
- `predsea_wrf_surface.nc`: hourly WRF wind and pressure on the marine grid.

No native marine benchmark may proceed on the current surface-current file
alone and claim to represent CROCO.

`scripts/fetch_native_marine_forcing.py` now implements that split using the
current Copernicus Mediterranean catalogue:

- hourly 3-D currents:
  `cmems_mod_med_phy-cur_anfc_4.2km-3D_PT1H-m`;
- hourly 3-D temperature:
  `cmems_mod_med_phy-tem_anfc_4.2km-3D_PT1H-m`;
- hourly 3-D salinity:
  `cmems_mod_med_phy-sal_anfc_4.2km-3D_PT1H-m`;
- hourly sea-surface height:
  `cmems_mod_med_phy-ssh_anfc_4.2km-2D_PT1H-m`;
- hourly wave parameters:
  `cmems_mod_med_wav_anfc_4.2km_PT1H-i`.

The Mediterranean wave product exposes integrated fields rather than full
directional spectra. The first SWAN implementation will therefore construct
parametric open-boundary conditions from significant wave height, mean
direction and peak period. It must record this boundary formulation explicitly
in its lineage.

All catalogue requests use timezone-aware UTC bounds and validation checks the
first and last timestamps as well as the count. A staging download made with
naive datetimes was shifted two hours earlier by Europe/Madrid daylight-saving
time; the regression test now rejects that failure mode.

## SWAN runtime baseline

SWAN 41.51 is built from the pinned official source archive and checksum in
`simulation/marine/swan/Dockerfile`. The image is independent of the production
WRF image. Its immutable staging build
`sha256:50c5d25f818e742bb57bf9c73a3849acd8f16de73e53c3c92d015d332d5980e3`
passed the official A11 refraction reference case with a normal SWAN
termination. This proves the executable and NetCDF-enabled runtime; it does not
by itself validate the PredSea domain.

`scripts/prepare_swan_run.py` builds the first real-domain package from:

- the versioned 1 km Balearic bathymetry;
- ECMWF 10 m U/V wind fields, with SWAN temporal interpolation between the
  three-hourly fields;
- hourly Copernicus Mediterranean wave parameters converted into explicit
  parametric JONSWAP conditions on all four open boundaries.

The initial six-hour run is a bounded staging benchmark. Copernicus is boundary
forcing and validation data, while the gridded forecast is computed by PredSea's
SWAN executable.

For MPI runs, SWAN writes its native structured VTK output. SWAN's NetCDF
collector was observed to abort with an EOF while merging otherwise-created
per-rank files on this grid. The official SWAN manual identifies VTK as the
parallel format that does not require collection. PredSea converts those native
parallel outputs into one canonical, validated NetCDF during publication; this
conversion is deterministic and does not alter model values.

The Balearic 1 km profile uses a five-minute internal computational timestep
while retaining hourly published products. A ten-minute step was rejected by
SWAN itself because the higher-order geographic propagation CFL exceeded 10.
The timestep is versioned in the region profile and must divide the publication
interval exactly.

## CROCO runtime baseline

CROCO 2.1.3 is pinned to the official stable-release archive and checksum in
`simulation/marine/croco/Dockerfile`. CROCO requires compilation for each
regional grid and physics configuration. The first image therefore compiles and
runs the official analytic BASIN case only as a compiler, MPI/NetCDF-linkage,
initialization, integration, and output smoke test. Passing that smoke test does
not count as a Balearic forecast. The Balearic executable will be compiled from
the same pinned source after the versioned grid, vertical coordinates, open
boundaries, initial state, and WRF surface-forcing files are generated and
validated.

### Current CROCO reference evidence (2026-07-22)

- Validated Balearic file grid: 501 x 401 points, nominal 1 km, exact profile
  bbox, max rx0 0.2, wet fraction about 0.929.
- Matching compiled interior dimensions: LM=499, MM=399, N=32.

The choice of 32 sigma levels is informed by Juza et al. (2016), “SOCIB
operational ocean forecasting system and multi-platform validation in the
Western Mediterranean Sea,” *Journal of Operational Oceanography*, 9:sup1,
s155–s166, https://doi.org/10.1080/1755876X.2015.1117764. This citation
supports only the vertical discretization count. WMOP is a ROMS configuration
at approximately 2 km horizontal resolution over a different domain; it does
not validate PredSea's CROCO implementation or nominal 1 km regional setup.
- Runtime target: `c2d-highcpu-16` Standard, 16 MPI ranks, 32 GiB.
- Real forcing proven through preparation: hourly 3-D CMEMS u/v, temperature,
  salinity and sea level; hourly PredSea WRF bulk surface fields.
- First 6 h execution reached CROCO input parsing but stopped because
  `croco_clm.nc` lacked `tclm_time` (and the other fixed climatology time axes).
- Commit `03aacfc` emits elapsed-day `ssh_time`, `uclm_time`, `tclm_time`, and
  `sclm_time` and rejects invalid timelines.
- Corrected staging image digest:
  `sha256:ee8244de30d0082f7054d73810321ed113fc339c6f00e1ad688da685882be924`.
- The corrected 6 h job is the immediate next gate; it was not yet submitted at
  the time of this documentation update.

Important: the current regional compile uses full-field CMEMS climatology and
nudging and explicitly disables dedicated `FRC_BRY` forcing. This can supply
edge values for the Balearic reference test, but it is not evidence that the
Gibraltar exchange-current/tidal problem is solved. The regional expansion must
make an explicit, evidence-backed decision between full-field climatology and
dedicated open-boundary files. Gibraltar also requires tides and Strait
transport validation; the present Balearic compile does not prove those.

## Current implementation status

| Component | Current status | Required next result |
|---|---|---|
| WRF 3 km / 24 h | proven | retained forcing source for marine gates |
| Balearic SWAN 1 km / 24 h | validated staging output | repeatability during regional rollout |
| Balearic CROCO grid/forcing | validated through input preparation | successful native integration/output |
| Balearic CROCO 6 h | corrected image ready | submit and pass content gate |
| Balearic CROCO 24 h | waiting | run only after 6 h passes |
| Alboran/Gibraltar | profile only | grid + SWAN/CROCO 6 h then 24 h |
| Gulf of Lion | profile only | grid + SWAN/CROCO 6 h then 24 h |
| Tyrrhenian | profile only | grid + SWAN/CROCO 6 h then 24 h |
| Algerian Basin | profile only | grid + SWAN/CROCO 6 h then 24 h |
| Multi-region staging API | waiting | all tile/overlap gates pass |
| 96/120 h horizons | deferred | start after geographic coverage |
| Production | untouched | explicit guarded promotion only |

## Benchmark ladder

1. Compile pinned SWAN and CROCO versions reproducibly.
2. Run a 6-hour 1 km Balearic SWAN benchmark.
3. Run a 6-hour 1 km Balearic CROCO benchmark.
4. If stable, run each model for 24 hours.
5. Project 96-hour and 120-hour runtime/disk/cost from measured throughput.
6. Execute the longest horizon that fits the daily operational window.
7. Validate against Copernicus and real observations without synthetic data.

Every benchmark publishes:

- `swan_benchmark.json` or `croco_benchmark.json`;
- stdout/stderr logs;
- model validation report;
- exact image/source version and command;
- real elapsed time;
- peak/total storage measurement;
- current VM price and measured compute cost;
- explicit exclusion of storage/network charges until those are measured.

## Promotion gates

Native output is eligible for staging publication only when:

1. all expected timestamps exist;
2. mandatory fields are present and at least 90% finite;
3. values remain inside configured physical limits;
4. output covers the configured region;
5. runtime and disk fit the operational envelope with margin;
6. lineage identifies WRF and CMEMS as forcing, not final forecast providers;
7. the API serves route/place values and maps from the native bundle;
8. Copernicus fallback remains available.

Production promotion additionally requires an unattended repeatable run and an
atomic pointer update that can be rolled back without rerunning the models.

## Comparative quality infrastructure

Native SWAN and CROCO validation has two distinct levels:

1. **run validity** — timestamps, coverage, fields, finite fractions, and
   physical limits; and
2. **forecast skill** — comparison with real observations and with Copernicus
   on identical matched samples.

Copernicus remains the baseline for waves and ocean, while buoys, tide gauges,
HF radar, and other quality-controlled measurements are ground truth. The
comparison archive records model cycle, valid time, lead hour, coordinate,
region version, forcing lineage, and raw value for both PredSea and Copernicus.
It must report bias/MAE/RMSE and circular directional errors by lead-time band,
region, station, season, and sea-state regime. Route-level verification also
measures peak-condition error, timing error, best-window agreement, and unsafe
false negatives.

This evaluation runs asynchronously in the staging dataset and bucket. It
cannot update the production `latest` pointer, and missing observations produce
an explicit insufficient-coverage result rather than a fabricated score.
Raw forecasts are scored before bias correction; any correction is trained on
past cycles and evaluated on later untouched cycles.
