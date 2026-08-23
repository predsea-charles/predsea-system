# PredSea Multi-Tier Evidence Aggregator — PRD

## Original Problem Statement
Refactor ETL into a Multi-Tiered, High-Resolution Aggregator (AROME, HARMONIE, Copernicus, and SOCIB) for the PredSea maritime decision intelligence system. Phase 2 implements real API fetchers for atmospheric data sources, Puertos del Estado observation ingestion, pipeline integration, and grid blending.

## Architecture
- **Atmospheric Tier System**: Météo-France AROME (1.3km) → AEMET HARMONIE-AROME (2.5km) → ECMWF Open Data IFS (9km)
- **Oceanographic Baseline**: Copernicus Mediterranean (4km) as core non-blocking anchor
- **Observation Ground-Truth**: SOCIB buoys + Puertos del Estado (REDEXT/REDCOS)
- **Grid Blending**: xarray-based interpolation aligning ocean data onto atmospheric grid
- **Evidence Lineage**: Full tracking of which models were blended in every output JSON

## User Personas
- **Yacht captains**: Need operational route decisions (go/no-go, timing, comfort)
- **Maritime operators**: Need multi-route weather intelligence for Balearic Islands
- **PredSea team**: Need validated, multi-source pipeline with lineage tracking

## Core Requirements (Static)
1. Tiered atmospheric wind ingestion with priority fallback
2. Copernicus ocean forecast as baseline
3. SOCIB + Puertos del Estado observation ground-truth
4. Spatial grid blending (xarray interpolation)
5. Evidence package with full data lineage
6. Source-aware GenAI prompt wording (resolution-dependent)
7. Cloud-agnostic deployment (Docker, S3-compatible)

## What's Been Implemented

### Phase 1 (Completed by previous agent — 2026-06-08)
- `ingest_atmosphere.py`: Tier system with stub fetchers
- `grid_blender.py`: xarray interpolation engine
- `evidence_package.py`: Lineage schema
- `decision_engine.py`: Source-aware wording
- `forecast_sources.py`: SOCIB gating
- Tests: 18 tests all passing

### Phase 2 (Completed — 2026-06-08)
- **`fetch_meteo_france.py`**: Météo-France AROME WCS API fetcher (1.3km, needs `METEO_FRANCE_API_KEY`)
- **`fetch_aemet.py`**: AEMET HARMONIE-AROME OpenData API fetcher (2.5km, needs `AEMET_API_KEY`)
- **`fetch_ecmwf.py`**: ECMWF Open Data fetcher via `ecmwf-opendata` package (9km, no key needed)
- **`fetch_puertos_estado.py`**: Puertos del Estado REDEXT/REDCOS buoy observation fetcher (Mahón, Dragonera, Valencia, Tarragona)
- **`ingest_observations.py`**: Multi-source observation orchestrator combining SOCIB + Puertos del Estado
- **`wind_loader.py`**: GRIB2/NetCDF to xarray wind dataset loader with variable normalization
- **`pipeline.py`**: Full 6-step ETL pipeline orchestrator wiring all components
- **`ingest_atmosphere.py`**: Updated with `build_fetchers()` and `run_atmospheric_ingestion()`
- **Bug fixes**: ECMWF resolution corrected from 25km to 9km, `datetime.utcnow()` fixed in socib_thredds.py
- **Tests**: 38 new tests (total 93 all passing)

## Prioritized Backlog

### P0 — Required for Production
- ~~Test ECMWF real download~~ **DONE** — Real ECMWF IFS download verified: 28.2MB GRIB2 → subset to 11x15 Balearic grid, 17 forecast steps (0-48h), wind speed ~5 kn average. Current open data is 0.25° (~27.8km); native 9km coming later 2026.
- ~~Test Puertos del Estado real endpoint~~ **DONE** — Discovered and connected to `opendap.puertos.es/thredds` OPeNDAP server. Real wave forecast data: 127×295 Balearic grid, 72 time steps, 15 variables (VHM0, direction, swell partitions). Sampled real wave data at Palma-Ibiza midpoint (0.7-0.91m).
- Obtain Météo-France AROME API key and test real data download
- Obtain AEMET HARMONIE-AROME API key and test real data download (note: Puertos del Estado also hosts HARMONIE 2.5km BALE data at opendap.puertos.es but it requires authentication)
- End-to-end pipeline test with real Copernicus credentials

### P1 — High Value
- Update provider-release-monitor.yml to include AROME/HARMONIE/ECMWF monitoring probes
- Add cfgrib-based GRIB2 spatial subsetting for Balearic bbox (instead of relying on API-side subsetting)
- Implement automatic model run detection (latest available cycle)
- Add retry logic with exponential backoff for all atmospheric fetchers
- Integrate pipeline.py as alternative to briefing.py for ETL runs

### P2 — Nice to Have
- GitHub Actions workflow for multi-source credential handling
- Docker layer for the full pipeline (cloud-agnostic)
- NEMO/SWAN integration (Phase 2A/2B from PLAN.md)
- Open-Meteo as secondary ECMWF 9km source when native open data is 25km
- Puertos del Estado time-series validation (not just real-time snapshots)

## Next Tasks
1. Obtain API credentials (Météo-France, AEMET) and run real fetcher tests
2. Test ECMWF Open Data real download against Balearic bbox
3. Run `pipeline.py` end-to-end with Copernicus credentials
4. Add atmospheric provider probes to monitor_provider_releases.py
5. Continue to Phase 2A/2B (NEMO/SWAN) as defined in PLAN.md
