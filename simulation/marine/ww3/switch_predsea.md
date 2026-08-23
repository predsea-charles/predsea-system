# `switch_predsea` — WW3 compile-time switch rationale

This file documents the token choices in `switch_predsea`, the WW3
compile-time switch file used by `Dockerfile.ww3-batch`
(`cmake -DSWITCH=/path/to/switch_predsea`).

**Update 2026-08-04, post first build attempt**: the first real Cloud Build
(`9063a3e8`) failed fast at CMake configure time — exactly the kind of
cheap, well-localized error anticipated below — with `No valid grib
switches found, but one is required`. Rather than patch that one error and
resubmit blind, the actual validation schema WW3's CMake build uses
(`model/src/cmake/check_switches.cmake` + `model/src/cmake/switches.json`)
was fetched and audited in full against this file. That audit caught three
more errors that would have failed the next three build attempts one at a
time: `stress` and `s_ln` are also required categories and were both
missing entirely, and `STAB2` (originally chosen below) actually *requires*
`ST2` per the schema — the correct pairing for `ST4` is `STAB3`. It also
turned up that `NC4` and `O0`-`O7` (originally included below) aren't valid
tokens in this schema at all — they're leftover from an older, pre-CMake
WW3 switch-file convention and would have been silently inert (not an
error, just dead weight). All of this is corrected in the current
`switch_predsea` and the table below.

**Caveat**: WW3's CMake build mechanism, and every specific token/category
name in the table below, are now verified directly against the live
`NOAA-EMC/WW3` `develop` branch source (`CMakeLists.txt`,
`check_switches.cmake`, `switches.json`, all fetched 2026-08-04) — this is
no longer a from-memory reconstruction. What's still not verified is
whether this specific *combination* of choices (as opposed to the schema
validity of each individual token) is the best physics configuration for
this project's wave climate — that's a Phase 1 validation question against
the SWAN baseline, not a build-time one.

| Token | Category (schema) | Required? | Why |
|---|---|---|---|
| `NOGRB` | `grib` | Required (one of `NOGRB`/`NCEP2`) | We don't need WW3 to natively decode GRIB; forcing goes through `ww3_prnc` from NetCDF, matching the rest of this pipeline's NetCDF-based I/O. |
| `DIST` | `shared` | Required (one of `SHRD`/`DIST`) | Distributed-memory model; mutually exclusive with `SHRD` (shared-memory/single-process). |
| `MPI` | `mpp` | Required (one of `SHRD`/`MPI`) | Matches the existing per-region Batch job pattern (16-64 MPI ranks). |
| `PR3` | `GSE` | Required (one of `PR0`-`PR3`) | Third-order Garden Sprinkler Effect alleviation scheme — WW3's recommended propagation scheme for production use. |
| `UQ` | `prop` | Required (one of `PR0`/`PR1`/`UQ`/`UNO`) | Universal quantity limiter, pairs with `PR3`. |
| `FLX0` | `stress` | Required (one of `FLX0`-`FLX5`) | Simplest/baseline stress computation. `ST4` explicitly *conflicts* with `FLX1`-`FLX4` per the verified schema (a genuine correction to this document's first draft, which had assumed a different, incompatible pairing from general recollection) — only `FLX0`/`FLX5` are valid with `ST4`. Chosen `FLX0` as the safe minimal default; whether `FLX5`'s more detailed formulation is worth the extra assumption is a Phase 1 physics-tuning question, same bucket as the `TR0`/`REF0` items below. |
| `LN0` | `s_ln` | Required (one of `LN0`/`SEED`/`LN1`) | No separate linear wind-input term — `ST4`'s own exponential growth formulation already captures this; not previously included at all in this document's first draft (a second genuine gap the schema audit caught). |
| `ST4` | `sterm` | Required (one of `ST0`-`ST6`) | Ardhuin et al. (2010) source term package — physics package confirmed in the 2026-08-04 migration decision. |
| `STAB3` | `stab` | Optional (`upto1`), but required *given* `ST4` | Corrects this document's first draft, which specified `STAB2` — the schema shows `STAB2` `requires: [ST2]`, which we don't have. `STAB3` is `requires_any: [ST3, ST4]`, the actually-valid pairing with `ST4`. |
| `NL1` | `s_nl` | Required (one of `NL0`-`NL5`) | Discrete Interaction Approximation (DIA) for nonlinear wave-wave interactions; standard default, the more expensive exact methods (`NL2`-`NL5`) aren't justified for an operational daily pipeline. |
| `BT4` | `s_bot` | Required (one of `BT0`/`BT1`/`BT4`/`BT8`/`BT9`) | SHOWEX-based bottom friction — more physically detailed than constant-coefficient `BT1`, worth the modest extra cost given this project's shallow coastal regions (alboran, gulf_of_lion). |
| `DB1` | `s_db` | Required (one of `DB0`/`DB1`) | Depth-induced (surf-zone) breaking — on, needed for the same coastal regions. |
| `TR0` | `s_tr` | Required (one of `TR0`/`TR1`) | Triad interactions off. SWAN's config has `TRIAD` on; WW3's `TR1` support is less mature/more expensive. Starting with `TR0` for Phase 0 to isolate propagation/convergence behavior first; revisit if nearshore validation against the SWAN baseline shows a meaningful gap. |
| `BS0` | `s_bs` | Required (one of `BS0`/`BS1`) | Bottom scattering off — not relevant for this region's bathymetry. |
| `IC0` | `s_ice` | Required (one of `IC0`-`IC5`) | No sea ice in the Western Mediterranean. |
| `IS0` | `s_is` | Required (one of `IS0`-`IS2`) | No icebergs in the Western Mediterranean. |
| `REF0` | `reflection` | Required (one of `REF0`/`REF1`) | Wave reflection off — starting point; revisit only if validation shows a specific coastal-reflection gap. |
| `WNT1` | `wind` | Required (one of `WNT0`-`WNT2`) | Linear time interpolation of wind forcing. |
| `WNX1` | `windx` | Required (one of `WNX0`-`WNX2`) | Linear spatial interpolation of wind forcing. |
| `CRT1` | `curr` | Required (one of `CRT0`-`CRT2`) | Linear time interpolation of current forcing. |
| `CRX1` | `currx` | Required (one of `CRX0`-`CRX2`) | Linear spatial interpolation of current forcing — enables reading CROCO current fields as forcing input, matching the existing CMEMS-current pattern in `fetch_native_marine_forcing.py`. |
| `BIN2NC` | `bin2nc` | Optional (`upto1`) | Use NetCDF instead of binary for model output — matches the rest of this pipeline's NetCDF-based I/O (bathymetry, forcing, BigQuery ingestion all already assume NetCDF). Replaces this document's first draft's non-existent `NC4` token. |

## Known open item

Whether triad interactions (`TR0` vs `TR1`) and reflection (`REF0` vs
`REF1`) need to be revisited depends on how WW3's output compares to the
SWAN baseline in Phase 1 validation, specifically in the shallow/coastal
parts of alboran and gulf_of_lion — exactly the regions this migration is
meant to fix. Not a blocker for Phase 0's smoke test on `tyrrhenian_1km`/
`balearic_1km`, but flagged here so it isn't forgotten before Phase 2.
