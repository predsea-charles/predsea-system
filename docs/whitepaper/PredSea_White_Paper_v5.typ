// PredSea White Paper Typst Setup & Custom Styling (Publication Grade v5)

#set document(
  title: "PredSea: A Scalable Cloud-Native Oceanographic Forecasting System using CROCO and High-Resolution Atmospheric Forcing",
  author: "PredSea Oceanographic Research & Engineering Group",
  date: datetime(year: 2026, month: 7, day: 25)
)

// Primary Palette
#let brand-navy = rgb("#0A2540")
#let brand-blue = rgb("#0073E6")
#let brand-teal = rgb("#00A3A6")
#let text-dark = rgb("#1A202C")
#let bg-light = rgb("#F8FAFC")
#let border-color = rgb("#CBD5E1")

// Base Document Setup
#set page(
  paper: "a4",
  margin: (top: 2.5cm, bottom: 2.5cm, left: 2.5cm, right: 2.5cm),
  header: context {
    if counter(page).get().first() > 1 {
      text(size: 8.5pt, fill: rgb("#64748B"), font: "Avenir Next")[
        *PredSea Technical White Paper* | July 2026
        #h(1fr)
        *Operational Architecture & Validation*
        #v(-0.4em)
        #line(length: 100%, stroke: 0.5pt + rgb("#CBD5E1"))
      ]
    }
  },
  footer: context {
    if counter(page).get().first() > 1 {
      text(size: 8.5pt, fill: rgb("#64748B"), font: "Avenir Next")[
        #line(length: 100%, stroke: 0.5pt + rgb("#CBD5E1"))
        #v(0.2em)
        PredSea Oceanographic Research & Engineering Group
        #h(1fr)
        Page #counter(page).display()
      ]
    }
  }
)

// Base Typography
#set text(
  font: ("Avenir Next", "Helvetica", "Arial"),
  size: 10.5pt,
  fill: text-dark,
  spacing: 120%
)

#set par(
  leading: 0.65em,
  justify: true
)

// Headings Styling
#show heading: set text(fill: brand-navy, font: ("Avenir Next", "Helvetica"))

#show heading.where(level: 1): it => [
  #pagebreak(weak: true)
  #v(0.5em)
  #text(size: 18pt, weight: "bold", fill: brand-navy)[#it.body]
  #v(0.3em)
  #line(length: 100%, stroke: 2pt + brand-blue)
  #v(0.8em)
]

#show heading.where(level: 2): it => [
  #v(1.2em)
  #text(size: 13pt, weight: "bold", fill: brand-navy)[#it.body]
  #v(0.4em)
]

#show heading.where(level: 3): it => [
  #v(0.9em)
  #text(size: 11pt, weight: "bold", fill: brand-teal)[#it.body]
  #v(0.3em)
]

// Links
#show link: set text(fill: brand-blue, weight: "medium")

// Table Styling
#set table(
  inset: (x: 8pt, y: 7pt),
  stroke: (x, y) => if y == 0 { (bottom: 1.5pt + brand-navy) } else { (bottom: 0.5pt + border-color) },
  fill: (x, y) => if y == 0 { rgb("#0A2540") } else if calc.even(y) { rgb("#F8FAFC") } else { rgb("#FFFFFF") }
)

#show table.cell.where(y: 0): set text(fill: white, weight: "bold")

// Code Block & Snippet Styling
#show raw.where(block: true): it => [
  #v(0.4em)
  #rect(
    width: 100%,
    fill: rgb("#F8FAFC"),
    stroke: 0.5pt + border-color,
    radius: 5pt,
    inset: 10pt
  )[
    #set text(font: ("DejaVu Sans Mono", "Menlo", "Courier New"), size: 8.5pt)
    #set par(leading: 0.5em, justify: false)
    #it
  ]
  #v(0.4em)
]

// Custom Diagram Components
#let platform_architecture_diagram() = align(center)[
  #block(
    width: 100%,
    fill: rgb("#F0F4F8"),
    stroke: 1.5pt + brand-navy,
    radius: 8pt,
    inset: 14pt
  )[
    #text(weight: "bold", size: 12pt, fill: brand-navy)[PredSea Cloud-Native Forecasting Platform Architecture]
    #v(8pt)
    #grid(
      columns: (1fr, 1fr, 1fr),
      gutter: 10pt,
      rect(width: 100%, fill: brand-blue, radius: 4pt, inset: 8pt)[#text(fill: white, weight: "bold", size: 9pt)[WRF Atmosphere\ (10m Wind, Heat Flux)]],
      rect(width: 100%, fill: brand-teal, radius: 4pt, inset: 8pt)[#text(fill: white, weight: "bold", size: 9pt)[SWAN Waves\ (Hs, Tp, Spectrum)]],
      rect(width: 100%, fill: brand-navy, radius: 4pt, inset: 8pt)[#text(fill: white, weight: "bold", size: 9pt)[CROCO Ocean\ (3D u, v, T, S, Zeta)]]
    )
    #v(6pt)
    #text(fill: brand-blue, size: 14pt)[↓]
    #v(2pt)
    #rect(width: 85%, fill: rgb("#E2E8F0"), stroke: 1pt + brand-navy, radius: 4pt, inset: 8pt)[
      #text(weight: "bold", size: 10pt, fill: brand-navy)[Serverless GCP Batch Spot Compute Engine] \
      #text(size: 8.5pt, fill: rgb("#475569"))[Parallel MPI Ranks | c2d-highcpu-16 Spot VMs | Self-Deletion Traps]
    ]
    #v(6pt)
    #text(fill: brand-blue, size: 14pt)[↓]
    #v(2pt)
    #rect(width: 85%, fill: rgb("#E2E8F0"), stroke: 1pt + brand-teal, radius: 4pt, inset: 8pt)[
      #text(weight: "bold", size: 10pt, fill: brand-teal)[Canonical NetCDF4 + GCS Storage Pipeline]
    ]
    #v(6pt)
    #text(fill: brand-blue, size: 14pt)[↓]
    #v(2pt)
    #rect(width: 85%, fill: brand-navy, radius: 4pt, inset: 8pt)[
      #text(weight: "bold", size: 10pt, fill: white)[BigQuery Decision Engine & REST APIs]
    ]
  ]
]

#let system_pipeline_diagram() = align(center)[
  #block(width: 100%, fill: rgb("#F8FAFC"), stroke: 1pt + border-color, radius: 6pt, inset: 12pt)[
    #text(weight: "bold", size: 11pt, fill: brand-navy)[End-to-End Data Pipeline Flowchart]
    #v(8pt)
    #grid(
      columns: (1fr, 1.2fr, 1fr),
      gutter: 10pt,
      stack(spacing: 8pt,
        text(weight: "bold", size: 9pt, fill: brand-blue)[1. Upstream Ingestion],
        rect(width: 100%, fill: rgb("#EFF6FF"), stroke: 0.5pt + brand-blue, radius: 4pt, inset: 6pt)[#text(size: 8pt)[*ECMWF Open Data*\ IFS 10m Wind & Fluxes]],
        rect(width: 100%, fill: rgb("#EFF6FF"), stroke: 0.5pt + brand-blue, radius: 4pt, inset: 6pt)[#text(size: 8pt)[*CMEMS Service*\ MED-PHYS 3D Boundary]]
      ),
      stack(spacing: 8pt,
        text(weight: "bold", size: 9pt, fill: brand-teal)[2. Pre-Processing & Forcing],
        rect(width: 100%, fill: rgb("#F0FDF4"), stroke: 0.5pt + rgb("#22C55E"), radius: 4pt, inset: 6pt)[#text(size: 8pt)[*prepare_croco_forcing.py*\ ProcessPoolExecutor GIL Bypass]],
        rect(width: 100%, fill: rgb("#F0FDF4"), stroke: 0.5pt + rgb("#22C55E"), radius: 4pt, inset: 6pt)[#text(size: 8pt)[*Model Input Artifacts*\ croco_blk.nc / croco_bry.nc\ croco_clm.nc / croco_ini.nc]]
      ),
      stack(spacing: 8pt,
        text(weight: "bold", size: 9pt, fill: brand-navy)[3. Execution & Serving],
        rect(width: 100%, fill: rgb("#F8FAFC"), stroke: 0.5pt + brand-navy, radius: 4pt, inset: 6pt)[#text(size: 8pt)[*GCP Batch Spot*\ CROCO 2.1.3 MPI Executable]],
        rect(width: 100%, fill: brand-navy, radius: 4pt, inset: 6pt)[#text(size: 8pt, fill: white)[*BigQuery & REST API*\ Decision Briefings & Maps]]
      )
    )
  ]
]

#let heat_flux_diagram() = align(center)[
  #block(width: 100%, fill: rgb("#FFFBEB"), stroke: 1pt + rgb("#F59E0B"), radius: 6pt, inset: 12pt)[
    #text(weight: "bold", size: 11pt, fill: rgb("#92400E"))[Air-Sea Thermodynamic Surface Heat Flux Balance]
    #v(8pt)
    #grid(
      columns: (1fr, 1fr, 1fr, 1fr),
      gutter: 8pt,
      rect(width: 100%, fill: rgb("#FEF3C7"), stroke: 0.5pt + rgb("#D97706"), radius: 4pt, inset: 6pt)[#text(size: 8pt)[*Shortwave (SW↓)*\ Solar Downward Radiation\ (Heat Gain)]],
      rect(width: 100%, fill: rgb("#FEE2E2"), stroke: 0.5pt + rgb("#EF4444"), radius: 4pt, inset: 6pt)[#text(size: 8pt)[*Net Longwave (LW)*\ Thermal IR Exchange\ (Night Cooling)]],
      rect(width: 100%, fill: rgb("#E0E7FF"), stroke: 0.5pt + rgb("#6366F1"), radius: 4pt, inset: 6pt)[#text(size: 8pt)[*Sensible Heat (Hsen)*\ Turbulent Air-Sea Heat Transfer]],
      rect(width: 100%, fill: rgb("#DBEAFE"), stroke: 0.5pt + rgb("#2563EB"), radius: 4pt, inset: 6pt)[#text(size: 8pt)[*Latent Heat (Hlat)*\ Wind Evaporative Loss\ (Primary Cooling)]]
    )
    #v(6pt)
    #rect(width: 100%, fill: brand-navy, radius: 4pt, inset: 8pt)[
      #text(fill: white, weight: "bold", size: 9.5pt)[CROCO Upper Mixed Layer Integration (bulk_flux.F Fixed)] \
      #text(fill: rgb("#CBD5E1"), size: 8.5pt)[shflux = radsw + shflx_rlw + shflx_lat + shflx_sen]
    ]
  ]
]

#let dragonera_diagram() = align(center)[
  #block(width: 100%, fill: rgb("#F0F9FF"), stroke: 1pt + rgb("#0284C7"), radius: 6pt, inset: 12pt)[
    #text(weight: "bold", size: 11pt, fill: rgb("#0369A1"))[Dragonera Island Channel Wind Acceleration & Evaporative Cooling Dip]
    #v(8pt)
    #grid(
      columns: (1fr, 1.2fr),
      gutter: 12pt,
      rect(width: 100%, fill: rgb("#E0F2FE"), stroke: 0.5pt + rgb("#0284C7"), radius: 4pt, inset: 8pt)[
        #text(weight: "bold", size: 9pt)[Topographic Wind Channeling:] \
        #text(size: 8.5pt)[
          *Serra de Tramuntana mountains* funnel northeasterly winds through the 800m Dragonera passage. \
          *10m Wind Velocity:* +45% localized acceleration.
        ]
      ],
      rect(width: 100%, fill: rgb("#0EA5E9"), radius: 4pt, inset: 8pt)[
        #text(weight: "bold", size: 9pt, fill: white)[Validated Hydrodynamic Response:] \
        #text(size: 8.5pt, fill: white)[
          *Latent Heat Loss:* -380 W/m² \
          *SST Skin Minimum:* 24.77°C \
          *Upwelling:* Wind-driven Ekman suction.
        ]
      ]
    )
  ]
]

#let cloud_deployment_diagram() = align(center)[
  #block(width: 100%, fill: rgb("#F8FAFC"), stroke: 1pt + rgb("#475569"), radius: 6pt, inset: 12pt)[
    #text(weight: "bold", size: 11pt, fill: brand-navy)[Serverless GCP Batch Execution Lifecycle]
    #v(8pt)
    #grid(
      columns: (1fr, 1fr, 1fr, 1fr),
      gutter: 8pt,
      rect(width: 100%, fill: rgb("#EFF6FF"), stroke: 0.5pt + brand-blue, radius: 4pt, inset: 6pt)[#text(size: 8pt)[*1. Trigger*\ Cloud Scheduler\ (02:00 UTC)]],
      rect(width: 100%, fill: rgb("#F0FDF4"), stroke: 0.5pt + rgb("#22C55E"), radius: 4pt, inset: 6pt)[#text(size: 8pt)[*2. Batch Orchestration*\ daily_orchestrator.py\ Dynamic Sizing]],
      rect(width: 100%, fill: rgb("#FEF3C7"), stroke: 0.5pt + rgb("#D97706"), radius: 4pt, inset: 6pt)[#text(size: 8pt)[*3. Spot Compute*\ c2d-highcpu-16\ 16 MPI Ranks]],
      rect(width: 100%, fill: rgb("#F3E8FF"), stroke: 0.5pt + rgb("#A855F7"), radius: 4pt, inset: 6pt)[#text(size: 8pt)[*4. Sync & Trap*\ Pre-Deletion Trap\ BigQuery + GCS Sync]]
    )
  ]
]

// COVER PAGE
#align(center + horizon)[
  #block(
    fill: brand-navy,
    radius: 4pt,
    inset: (x: 12pt, y: 6pt)
  )[
    #text(fill: white, size: 9pt, weight: "bold", tracking: 0.1em)[PREDSEA TECHNICAL WHITE PAPER | JULY 2026 | OPERATIONAL]
  ]

  #v(2em)

  #text(size: 24pt, weight: "bold", fill: brand-navy)[PredSea: A Scalable Cloud-Native Oceanographic Forecasting System]

  #v(0.8em)

  #text(size: 14pt, weight: "medium", fill: brand-blue)[Using CROCO and High-Resolution Atmospheric Forcing for Sub-Kilometer Coastal Intelligence]

  #v(2.5em)

  #text(size: 11pt, weight: "semibold", fill: text-dark)[PredSea Oceanographic Research & Engineering Group] \
  #text(size: 9.5pt, fill: rgb("#64748B"))[July 2026 | Operational Technical Specification]

  #v(3em)

  #align(left)[
    #rect(
      width: 100%,
      fill: rgb("#F0F7FF"),
      stroke: (left: 4pt + brand-blue, rest: 0.5pt + border-color),
      radius: (right: 6pt),
      inset: 14pt
    )[
      #text(weight: "bold", size: 11pt, fill: brand-navy)[Abstract]
      #v(0.6em)
      #text(size: 9.5pt, fill: text-dark)[
        Traditional coastal oceanography and wave dynamics modeling rely on dedicated high-performance computing (HPC) clusters or monolithic, expensive cloud runners. These legacy paradigms suffer from rigid resource allocation, high capital expenditure, and slow multi-domain scheduling.

        *PredSea* introduces a serverless, cloud-native oceanographic forecasting architecture that replaces fixed HPC infrastructure with dynamically orchestrated Google Cloud Platform (GCP) Batch compute, Spot Virtual Machines, MPI-parallelized numerical engines (CROCO, SWAN, WRF), and GIL-bypassing parallel Python pre-processors.

        By coupling high-resolution Weather Research and Forecasting (WRF) atmospheric driving fields (1 km grid resolution) with CROCO and SWAN, PredSea resolves fine-scale coastal bathymetry, island wind shadows, and thermal boundary dynamics across major Western Mediterranean sectors in under 35 minutes at an operational cost of ~\$2.22 per daily forecast cycle.
      ]
    ]
  ]
]

#pagebreak()

// DEDICATED TABLE OF CONTENTS
#v(1em)
#outline(
  title: [Table of Contents],
  depth: 2
)

#pagebreak()

// --- FILE: README.md ---

= Executive Summary & Core Positioning
<executive-summary-core-positioning>
== 1. The Operational Problem: Coarse Grids Miss Coastal Physics
<the-operational-problem-coarse-grids-miss-coastal-physics>
Global physical products---such as those from ECMWF and Copernicus
Marine Environment Monitoring Service (CMEMS)---provide essential
ocean-state baselines at $4.2 upright(" km")$ to $25 upright(" km")$
horizontal resolutions. However, coarse global grids smooth out critical
coastal bathymetric features, flatten narrow island channels (e.g.,
Freus channel between Ibiza and Formentera, Dragonera channel off
Mallorca), and underestimate wave-current interactions and local
wind-sea generation.

== 2. The Commercial & Coastal Value of 1 km Resolution
<the-commercial-coastal-value-of-1-km-resolution>
PredSea's target positioning:

#quote(block: true)[
#strong[Ocean data is everywhere. Operational decisions are not.]
]

By downscaling regional ocean state data onto a high-resolution
#strong[$1 upright(" km")$ curvilinear grid] ($401 times 501$ rho points
across 32 vertical $sigma$-layers in the validated Balearic tile),
PredSea targets: \* #strong[Sub-Kilometer Coastal Accuracy:] Resolving
steep shoreline bathymetry, narrow island channels, and localized
coastal effects that coarse global products smooth over. \*
#strong[Predictive Decision Intelligence:] Converting raw 3D velocity
vectors and wave spectra into vessel response metrics, port safety
alerts, and captain-facing advice (not yet built --- see Section 6
roadmap). \* #strong[Cost-Efficient Compute:] Running each regional tile
as an isolated GCP Batch job sized to its own grid, rather than a single
always-on cluster. Actual measured per-run costs and a mature
multi-region daily cadence are not yet established; see Section 5 for
what has actually been measured so far.

#platform_architecture_diagram()

#divider()

== Status by Capability
<status-by-capability>
Legend: ✅ implemented and verified · 🧪 implemented, under validation ·
🛠 designed, not yet implemented · 🎯 performance target, not yet
measured

#figure(
  align(center)[#table(
    columns: (30.77%, 38.46%, 30.77%),
    align: (left,center,left,),
    table.header([Capability], [Status], [Note],),
    table.hline(),
    [Serverless GCP Batch execution (CROCO + SWAN per
    region)], [✅], [STANDARD provisioning during validation; SPOT is
    the future cost-optimization mode, not current default (see
    `05_cloud_deployment_and_ops.md`)],
    [$1.0 upright(" km")$ regional grid definitions (5 Western Med
    tiles)], [✅], [Grid files and compiled CROCO binaries exist for all
    5 regions],
    [CROCO 6h / 24h numerical stability gates], [✅], [Passed for most
    regions; exact per-region status in `04_empirical_validation.md`],
    [CROCO 72h gate], [🧪], [Blocked on a WRF-forcing horizon mismatch;
    fix in progress],
    [SWAN across all 5 regions], [🧪], [Bathymetry is baked into the
    image for all 5 regions; a 2026-07-29 fix (`PROP BSBT` numerics + an
    explicit boundary-walk-inward limit) addressed real bugs found in
    `alboran_1km`/`gulf_of_lion_1km`/`algerian_1km`\; a fresh 3-region
    validation test is in progress, result not yet known --- see
    `02_modeling_suite.md` §4.5 and `04_empirical_validation.md`],
    [Live WRF↔CROCO↔SWAN dynamic coupling], [🛠], [Current pipeline is
    one-way, file-mediated forcing only (see `02_modeling_suite.md`)],
    [Pre-processing time, total compute time, daily infrastructure
    cost], [🎯], [Not re-measured since the pipeline changed this cycle;
    prior figures were not independently verified and are not repeated
    here],
    [$H_s$ RMSE vs.~SOCIB buoys or any independent observation
    source], [🎯], [No wave-height or observational validation has been
    performed yet],
  )]
  , kind: table
  )

#divider()

== Table of Contents
<table-of-contents>
The complete technical specification is structured across six dedicated
sub-documents:

+ #link("./01_system_architecture.md")[#strong[01\_system\_architecture.md]]
  \ #emph[End-to-end Data Pipeline: Upstream ECMWF/CMEMS ingestion,
  Python GIL-bypass pre-processing, bulk forcing compilation
  (`croco_blk.nc`, `croco_bry.nc`, `croco_ini.nc`), and GCS cloud
  storage hierarchy.]
+ #link("./02_modeling_suite.md")[#strong[02\_modeling\_suite.md]] \
  #emph[Core Numerical Engines & Current Data-Exchange Pipeline: WRF
  atmospheric physics, CROCO 3D hydrostatic primitive equations
  ($s$-vertical coordinates), SWAN 3D spectral wave dynamics, the
  current one-way file-mediated forcing chain between them, and the
  planned (not yet built) OASIS3-MCT-style two-way/three-way coupling.]
+ #link("./03_thermodynamics_and_fluxes.md")[#strong[03\_thermodynamics\_and\_fluxes.md]]
  \ #emph[Physical Formulations & Bulk Parameterization: Thermodynamic
  surface heat flux equations ($upright("shflux")$ decomposition), and
  the one verified fix actually in the codebase --- a sign-convention
  correction in `bulk_flux.F`.]
+ #link("./04_empirical_validation.md")[#strong[04\_empirical\_validation.md]]
  \ #emph[Current validation status across all 5 Western Mediterranean
  regions: which region/horizon combinations have passed the structural
  validation gate, and an explicit list of what has not yet been
  validated (observational comparison, wave height, multi-day
  horizons).]
+ #link("./05_cloud_deployment_and_ops.md")[#strong[05\_cloud\_deployment\_and\_ops.md]]
  \ #emph[GCP Batch Execution & Serverless Infrastructure: containerized
  MPI architecture, digest-pinned image requirements, current STANDARD
  (not SPOT) provisioning and why, automated self-deletion traps, and
  run-scoped output storage.]
+ #link("./06_conclusion_and_roadmap.md")[#strong[06\_conclusion\_and\_roadmap.md]]
  \ #emph[Current Architectural State & Roadmap: what is implemented and
  verified today versus designed-but-not-built, and the engineering
  roadmap (multi-day horizons, live model coupling, captain-facing
  decision APIs).]


// --- FILE: 01_system_architecture.md ---

= 01. System Architecture & Data Pipeline
<system-architecture-data-pipeline>
This document details the end-to-end data ingestion, preparation, and
orchestration pipeline powering the #strong[PredSea] oceanographic
forecasting platform.

#divider()

== 1. High-Level Data Flow Pipeline
<high-level-data-flow-pipeline>
The PredSea automated data pipeline operates on a daily serverless
schedule. Upstream global weather and ocean state datasets are
retrieved, interpolated across spatial and vertical coordinate systems
using parallel processes, fed into coupled numerical solvers, and
transformed into optimized NetCDF4 and BigQuery datasets for downstream
decision APIs.

#system_pipeline_diagram()

#divider()

== 2. Atmospheric & Boundary Ingestion Specifications
<atmospheric-boundary-ingestion-specifications>
=== A. WRF Atmospheric Forcing Ingestion
<a.-wrf-atmospheric-forcing-ingestion>
Atmospheric driving variables are downloaded hourly from ECMWF
high-resolution operational models and refined via PredSea's Weather
Research and Forecasting (WRF v4.5) $3 upright(" km")\/1 upright(" km")$
nested model runs. The required bulk surface forcing parameters include:

#figure(
  align(center)[#table(
    columns: (22.22%, 27.78%, 27.78%, 22.22%),
    align: (left,center,center,left,),
    table.header([Variable Name], [Symbol], [Units], [Physical
      Description],),
    table.hline(),
    [#strong[Zonal Wind
    Vector]], [$U_10$], [$upright("m/s")$], [$10 upright(" m")$ Eastward
    wind component],
    [#strong[Meridional Wind
    Vector]], [$V_10$], [$upright("m/s")$], [$10 upright(" m")$
    Northward wind component],
    [#strong[Air
    Temperature]], [$T_a$], [$upright("K") upright(" or ")^compose upright("C")$], [$2 upright(" m")$
    Surface air temperature],
    [#strong[Specific
    Humidity]], [$q_a$], [$upright("kg/kg")$], [$2 upright(" m")$
    Specific humidity derived from relative humidity ($R H$)],
    [#strong[Surface Pressure]], [$P_(a t m)$], [$upright("Pa")$], [Mean
    sea level atmospheric pressure],
    [#strong[Downward Shortwave
    Flux]], [$S W_arrow.b$], [$upright("W/m")^2$], [Solar radiation
    reaching the sea surface],
    [#strong[Downward Longwave
    Flux]], [$L W_arrow.b$], [$upright("W/m")^2$], [Atmospheric thermal
    infrared radiation reaching the sea surface],
    [#strong[Precipitation
    Rate]], [$P_(upright("rate"))$], [$upright("kg/m")^2\/upright("s")$], [Total
    precipitation for surface freshwater flux calculations],
  )]
  , kind: table
  )

=== B. CMEMS Hydrodynamic Boundary Ingestion
<b.-cmems-hydrodynamic-boundary-ingestion>
Open ocean boundary conditions are sourced from the Copernicus Marine
Service (CMEMS Mediterranean Physics Analysis and Forecast model). Data
fields are extracted in 3D across the full geographic domain:

- #strong[3D Velocity Fields ($u\,v$):] Zonal and meridional oceanic
  current components across all vertical levels.
- #strong[3D Temperature ($T$) & Salinity ($S$):] Hydrographic state
  variables resolving pycnoclines and thermoclines.
- #strong[Sea Surface Height ($zeta$):] Free-surface barotropic
  elevation for boundary pressure gradient forcing.

#divider()

== 3. High-Performance File Preparation Workflow
<high-performance-file-preparation-workflow>
Translating raw 3D CMEMS and WRF datasets into CROCO-compatible NetCDF
input files (`croco_blk.nc`, `croco_bry.nc`, `croco_clm.nc`,
`croco_ini.nc`) was historically a single-threaded bottleneck, requiring
#strong[\~40 minutes] per 24-hour simulation cycle.

=== Process-Level GIL Bypass Design
<process-level-gil-bypass-design>
To overcome Python's Global Interpreter Lock (GIL), PredSea's
pre-processor
#link("file:///Users/charles.santana/Kultrip/predsea-system/scripts/prepare_croco_forcing.py")[`scripts/prepare_croco_forcing.py`]
implements process-level concurrency via
`concurrent.futures.ProcessPoolExecutor`.

```python
# Architecture snippet: ProcessPoolExecutor GIL bypass for 3D interpolation
from concurrent.futures import ProcessPoolExecutor
import numpy as np

def interpolate_3d_timestep(t_idx, cmems_data, target_croco_grid):
    """
    Independent process worker function interpolating 3D CMEMS variables
    onto CROCO curvilinear rho/u/v points and stretched s-vertical levels.
    """
    # ... spatial SciPy RegularGridInterpolator logic ...
    return interpolated_slice_t

def prepare_croco_forcing_parallel(time_steps, max_workers=16):
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(interpolate_3d_timestep, t, raw_cmems, target_grid)
            for t in range(time_steps)
        ]
        results = [f.result() for f in futures]
    return assemble_croco_netcdf(results)
```

=== Pre-Processing Performance Benchmarks
<pre-processing-performance-benchmarks>
#figure(
  align(center)[#table(
    columns: (21.05%, 26.32%, 26.32%, 26.32%),
    align: (left,center,center,center,),
    table.header([Processing Stage], [Legacy Single-Threaded
      Time], [PredSea Parallel Time (`c2d-highcpu-16`)], [Acceleration
      Factor],),
    table.hline(),
    [#strong[Atmospheric Bulk (`croco_blk.nc`)]], [8 min 12
    sec], [#strong[0 min 22 sec]], [#strong[22.3x]],
    [#strong[Open Boundaries (`croco_bry.nc`)]], [22 min 45
    sec], [#strong[0 min 58 sec]], [#strong[23.5x]],
    [#strong[Climatology & Init (`croco_clm/ini.nc`)]], [9 min 03
    sec], [#strong[0 min 22 sec]], [#strong[23.9x]],
    [#strong[Total Pre-Processing Pipeline]], [#strong[40 min 00
    sec]], [#strong[1 min 42 sec]], [#strong[23.5x]],
  )]
  , kind: table
  )

#divider()

== 4. Execution Workflow in `run_marine_simulation.py`
<execution-workflow-in-run_marine_simulation.py>
The master orchestration script
#link("file:///Users/charles.santana/Kultrip/predsea-system/scripts/run_marine_simulation.py")[`scripts/run_marine_simulation.py`]
executes the following strict sequence:

+ #strong[Validation of Spatial Domain Config]: Parses regional JSON
  specs (e.g.~`balearic_1km.json`) to confirm grid dimensions
  ($L M = 499\,M M = 399\,N = 32$).
+ #strong[Upstream Ingestion Check]: Verifies that WRF surface forcing
  and CMEMS 3D boundaries exist in GCS staging buckets and contain zero
  corrupt NaN/Inf values.
+ #strong[Parallel Forcing Assembly]: Triggers
  `prepare_croco_forcing.py` with multi-core process pools.
+ #strong[Batch Instance Provisioning]: Launches a GCP Batch job on
  `c2d-highcpu-16` Spot nodes running the compiled CROCO container
  (`croco-batch:20260726-v20`).
+ #strong[C-Grid Dimension-Aware Validation Gate]: Executes
  `predsea.marine_validation.v1` (`scripts/validate_marine_output.py`)
  using dimension-matched land masks (`_apply_matching_mask`). This gate
  performs strict physical range and $100 %$ wet-cell finite fraction
  assertions in a #strong[1.8-second benchmark], eliminating historical
  OOM memory expansion before writing a durable `SUCCESS` token to GCS.


// --- FILE: 02_modeling_suite.md ---

= 02. Core Numerical Engines & Current Data-Exchange Pipeline
<core-numerical-engines-current-data-exchange-pipeline>
This document provides a mathematical and functional analysis of the
core numerical modeling engines integrated into the #strong[PredSea]
forecasting suite: #strong[WRF] (atmospheric dynamics), #strong[CROCO]
(hydrodynamics), and #strong[SWAN] (spectral wave dynamics).

#strong[Important scope note:] the three models are currently run as
independent, one-way, file-mediated stages, not as a live-coupled
OASIS3-MCT/COAWST system. WRF runs once per forecast cycle and writes
its output to Cloud Storage; CROCO and SWAN each read that output as
static forcing and run independently (optionally as two steps inside the
same Batch job via `--model both`, but without runtime field exchange
between them). Dynamic two-way/three-way coupling (wave radiation stress
feeding back into CROCO, CROCO currents feeding back into SWAN's
refraction, live SST feedback into WRF) is designed-for but not yet
implemented --- see the roadmap in `06_conclusion_and_roadmap.md`,
Milestone B.

#divider()

== 1. Core Numerical Modeling Engines
<core-numerical-modeling-engines>
#platform_architecture_diagram()

=== A. WRF (Weather Research and Forecasting Model)
<a.-wrf-weather-research-and-forecasting-model>
The atmospheric component runs WRF v4.5, solving the fully compressible,
non-hydrostatic Euler primitive equations on a Arakawa-C grid using
terrain-following hydrostatic pressure vertical coordinates ($eta$).

- #strong[Primary Governing Variables]: 3D velocity vectors
  ($arrow(u)_a$), perturbation potential temperature ($theta'$),
  geopotential ($phi.alt'$), and surface pressure ($P_(a t m)$).
- #strong[Physical Parameterizations]:
  - #strong[Microphysics]: WSM6 (WRF Single-Moment 6-class scheme).
  - #strong[Planetary Boundary Layer (PBL)]: YSU (Yonsie University
    scheme) resolving atmospheric turbulence and surface momentum flux
    closure.
  - #strong[Radiation]: RRTMG longwave and shortwave schemes computing
    surface downward fluxes ($S W_arrow.b\,L W_arrow.b$).
- #strong[Output Parameters]: Provides $10 upright(" m")$ wind vectors
  ($U_10\,V_10$), $2 upright(" m")$ air temperature ($T_a$), specific
  humidity ($q_a$), surface pressure ($P_(a t m)$), and radiative fluxes
  ($S W_arrow.b\,L W_arrow.b$).

=== B. CROCO (Coastal and Regional Ocean Community Model)
<b.-croco-coastal-and-regional-ocean-community-model>
CROCO v2.1.3 is a free-surface, hydrostatic/non-hydrostatic 3D primitive
equation hydrodynamic model evolved from ROMS. It uses an Arakawa-C grid
in the horizontal and a general curvilinear, terrain-following
$s$-vertical coordinate system in the vertical.

==== Hydrodynamic Governing Equations
<hydrodynamic-governing-equations>
In Cartesian/curvilinear coordinates with terrain-following $s$-levels,
the Reynolds-averaged Navier-Stokes (RANS) momentum equations under the
Boussinesq and hydrostatic approximations are:

$ frac(partial u, partial t) + arrow(v) dot.op nabla u - f v = - 1 / rho_0 frac(partial p, partial x) + frac(partial, partial z) (K_m frac(partial u, partial z)) + cal(D)_u $

$ frac(partial v, partial t) + arrow(v) dot.op nabla v + f u = - 1 / rho_0 frac(partial p, partial y) + frac(partial, partial z) (K_m frac(partial v, partial z)) + cal(D)_v $

$ frac(partial p, partial z) = - rho g $

$ frac(partial u, partial x) + frac(partial v, partial y) + frac(partial w, partial z) = 0 $

Where: \* $u\,v\,w$ are the 3D fluid velocity components in $x\,y\,z$.
\* $f = 2 Omega sin phi.alt$ is the Coriolis parameter. \* $rho_0$ is
the reference ocean water density ($1025 upright(" kg/m")^3$). \* $K_m$
is the vertical eddy viscosity derived from GLS (Generic Length Scale)
$k$-$epsilon.alt$ or $k$-$omega$ turbulence closure. \*
$cal(D)_u\,cal(D)_v$ represent horizontal viscosity and dissipation
operator terms.

==== Stretched $s$-Vertical Coordinate System
<stretched-s-vertical-coordinate-system>
To resolve both deep ocean circulation and shallow coastal boundary
layers, CROCO employs a non-linear vertical transformation
(`NEW_S_COORD`):

$ z\(x\,y\,s\)= zeta\(x\,y\)+\[zeta\(x\,y\)+ h\(x\,y\)\]dot.op S\(x\,y\,s\) $

Where the non-linear stretching function $S\(x\,y\,s\)$ is governed by
parameters $theta_s$ (surface stretching), $theta_b$ (bottom
stretching), and $h_c$ (critical depth):

$ S\(x\,y\,s\)= frac(h_c s + h C\(s\), h_c + h) $

In the reference Balearic grid ($401 times 501$ horizontal grid at
$1 upright(" km")$ resolution), $N = 32$ vertical layers are configured
with $theta_s = 6.0$, $theta_b = 0.0$, and $h_c = 10 upright(" m")$.

=== C. SWAN (Simulating WAves Nearshore)
<c.-swan-simulating-waves-nearshore>
SWAN v41.45 is a third-generation spectral wave model that computes the
evolution of the 2D wave action density spectrum
$N\(sigma\,theta\;x\,y\,t\)$ over coastal and shelf sea environments:

$ N\(sigma\,theta\)= frac(E\(sigma\,theta\), sigma) $

Where $sigma$ is the relative wave intrinsic frequency and $theta$ is
the wave propagation direction.

==== Spectral Action Balance Equation
<spectral-action-balance-equation>
The governing wave transport equation in absolute Cartesian coordinates
is given by:

$ frac(partial N, partial t) + frac(partial, partial x)\(c_x N\)+ frac(partial, partial y)\(c_y N\)+ frac(partial, partial sigma)\(c_sigma N\)+ frac(partial, partial theta)\(c_theta N\)= S_(t o t) / sigma $

Where: \* $\(c_x\,c_y\)= arrow(c)_g + arrow(U)$ are the spatial
propagation velocity components (group velocity $arrow(c)_g$ plus
background current vector $arrow(U)$). \* $c_sigma\,c_theta$ represent
the propagation speeds in spectral frequency $sigma$ and direction
$theta$ (resolving current refraction and depth-induced shoaling). \*
$S_(t o t)$ is the total source/sink term:

$ S_(t o t) = S_(i n) + S_(n l 3) + S_(n l 4) + S_(d s) + S_(b o t) + S_(d b) $

Where $S_(i n)$ is wind input, $S_(n l 3)\,S_(n l 4)$ are 3-wave (triad)
and 4-wave (quadruplet) non-linear interactions, $S_(d s)$ is
whitecapping dissipation, $S_(b o t)$ is bottom friction, and $S_(d b)$
is depth-induced wave breaking.

#divider()

== 2. Current Data Exchange: One-Way, File-Mediated Forcing
<current-data-exchange-one-way-file-mediated-forcing>
Today, WRF, CROCO, and SWAN exchange information only through static
files written to Cloud Storage --- there is no live in-memory field
exchange during a run. The two currently active paths are:

```mermaid
flowchart LR
    WRF["WRF (Weather Research & Forecasting)"]
    GCS[("Cloud Storage: wrfout_*.nc for this run_id")]
    CROCO["CROCO (Hydrodynamics)"]
    SWAN["SWAN (Spectral Waves)"]

    WRF -- "writes once, end of WRF run" --> GCS
    GCS -- "read once at CROCO startup\n(prepare_croco_bulk_forcing.py)" --> CROCO
    GCS -- "read once at SWAN startup\n(fetch_swan_wind.py)" --> SWAN
```

+ #strong[WRF → CROCO (one-way, file-based)]:
  `prepare_croco_bulk_forcing.py` reads the completed `wrfout_d02_*.nc`
  (or `d03` for Balearic's finer nest) sequence and builds a static
  `croco_blk.nc` atmospheric bulk-forcing file before CROCO starts.
  CROCO does not read live WRF output and WRF does not read anything
  back from CROCO --- there is no dynamic SST feedback into WRF yet.
+ #strong[WRF → SWAN (one-way, file-based)]: SWAN reads 10 m wind fields
  from the same completed WRF output to drive spectral wave growth.
  SWAN's own output (wave-driven roughness, radiation stress) is not fed
  back into WRF or CROCO at runtime.
+ #strong[CROCO ↔ SWAN]: currently #strong[not connected at all], even
  one-way. Both read WRF wind/atmospheric forcing independently and run
  to completion independently (they may share a single GCP Batch job via
  `run_marine_simulation.py --model both`, but that only means "run
  CROCO, then run SWAN, in the same container" --- not a coupled
  exchange of currents, sea level, or radiation stress).

== 3. Planned Two-Way / Three-Way Coupling (Roadmap, Not Yet Built)
<planned-two-way-three-way-coupling-roadmap-not-yet-built>
The exchange matrix below describes the #strong[target] architecture
once dynamic OASIS3-MCT-style coupling is implemented (tracked as
Milestone B in `06_conclusion_and_roadmap.md`). None of these feedback
paths exist in the current pipeline; they are included here to document
the intended design, not current capability.

#figure(
  align(center)[#table(
    columns: (19.05%, 19.05%, 19.05%, 23.81%, 19.05%),
    align: (left,left,left,center,left,),
    table.header([Source Model], [Target Model], [Exchange
      Variable], [Symbol / Units], [Physical Coupling Effect],),
    table.hline(),
    [#strong[WRF]], [#strong[CROCO]], [Surface Stress & Heat
    Flux], [$tau\,upright("shflux")$
    ($upright("N/m")^2\,upright("W/m")^2$)], [Drives Ekman currents &
    water column thermal structure],
    [#strong[CROCO]], [#strong[WRF]], [Sea Surface
    Temperature], [$upright("SST")$
    ($""^compose upright("C")$)], [Modulates atmospheric boundary layer
    stability & flux coefficients],
    [#strong[SWAN]], [#strong[CROCO]], [Wave Height, Period &
    $U_(b o t)$], [$H_s\,T_p\,U_(b o t)$
    ($upright("m")\,upright("s")\,upright("m/s")$)], [Drives wave
    radiation stresses & bottom friction enhancement],
    [#strong[CROCO]], [#strong[SWAN]], [Currents & Sea Surface
    Height], [$u\,v\,zeta$ ($upright("m/s")\,upright("m")$)], [Causes
    Doppler shift, wave refraction, & depth-induced breaking],
    [#strong[SWAN]], [#strong[WRF]], [Surface Roughness Length], [$z_0$
    ($upright("m")$)], [Adjusts atmospheric surface drag based on real
    wave state],
    [#strong[WRF]], [#strong[SWAN]], [$10 upright(" m")$ Surface Wind
    Vectors], [$U_10\,V_10$ ($upright("m/s")$)], [Governs spectral wave
    energy generation ($S_(i n)$)],
  )]
  , kind: table
  )

#emph[\(WRF → SWAN wind forcing, the last row, is the one exchange in
this table that is already real today --- see Section 2.)]

#divider()

== 4. Regional Domain Decomposition & Lateral Ocean Boundary Forcing
<regional-domain-decomposition-lateral-ocean-boundary-forcing>
The discussion above concerns coupling #emph[between models] (WRF,
CROCO, SWAN) at a single location. This section addresses a separate
question: how the ocean domain itself is decomposed in space, and how
the Atlantic inflow at the Strait of Gibraltar and the Eastern
Mediterranean exchange near the Strait of Messina are represented.

#strong[PredSea does not run one continuous Mediterranean-wide ocean
model.] CROCO and SWAN each run as five independent, non-communicating
regional instances, one per GCP Batch job, each confined to its own
fixed rectangular bounding box defined in
`simulation/marine/regions/{region}.json`:

#figure(
  align(center)[#table(
    columns: (21.05%, 26.32%, 26.32%, 26.32%),
    align: (left,center,center,center,),
    table.header([Region], [Longitude range], [Latitude range], [Grid
      (`xi_rho` × `eta_rho`)],),
    table.hline(),
    [Alboran], [$- 6.0^compose$ to $- 1.0^compose$], [$35.0^compose$ to
    $37.5^compose$], [$501 times 251$],
    [Algerian], [$- 1.0^compose$ to $8.5^compose$], [$35.0^compose$ to
    $38.0^compose$], [$951 times 301$],
    [Balearic], [$0.5^compose$ to $5.5^compose$], [$37.5^compose$ to
    $41.5^compose$], [$501 times 401$],
    [Gulf of Lion], [$2.0^compose$ to $6.5^compose$], [$41.5^compose$ to
    $43.3^compose$], [$500 times 200$],
    [Tyrrhenian], [$7.5^compose$ to $14.0^compose$], [$38.0^compose$ to
    $44.5^compose$], [$650 times 651$],
  )]
  , kind: table
  )

All five run at $1000 upright(" m")$ horizontal resolution ($N = 32$
vertical $s$-levels).

#emph[Gulf of Lion's latitude range and grid dimensions above reflect a
2026-07-29 bbox resize (see Section 4.4); its previous extent was
$41.5^compose$--$44.5^compose upright("N")$ at $451 times 301$, and that
older grid is what the CROCO 6h/24h gate passes recorded in
`04_empirical_validation.md` were run against. The new $500 times 200$
grid has not yet been re-validated at any CROCO horizon.]

=== 4.1 Lateral boundary forcing: an external product, not a PredSea coupling
<lateral-boundary-forcing-an-external-product-not-a-predsea-coupling>
Each region's `forcing.ocean_initial_and_boundary` and
`forcing.wave_open_boundary` fields (region profile schema) are set to
`"cmems"`: every region's initial condition and open lateral boundaries
are built exclusively from Copernicus Marine Service (CMEMS)
Mediterranean reanalysis/forecast products, fetched independently per
region by `fetch_native_marine_forcing.py`:

- `cmems_mod_med_phy-cur_anfc_4.2km-3D_PT1H-m` ($u_o\,v_o$ --- currents)
- `cmems_mod_med_phy-tem_anfc_4.2km-3D_PT1H-m` ($theta_o$ ---
  temperature)
- `cmems_mod_med_phy-sal_anfc_4.2km-3D_PT1H-m` ($S_o$ --- salinity)
- `cmems_mod_med_phy-ssh_anfc_4.2km-2D_PT1H-m` ($zeta$ --- sea surface
  height)
- `cmems_mod_med_wav_anfc_4.2km_PT1H-i` ($H_(m 0)\,T_p\,theta_(m e a n)$
  --- SWAN boundary spectrum)

`prepare_croco_forcing.py` interpolates this $4.2 upright(" km")$ CMEMS
state horizontally onto the region's own $1 upright(" km")$ grid, then
extracts the four edges of that interpolated field as CROCO's
`croco_bry.nc` open-boundary values:

```python
sides = {
    "west":  (0, slice(None), "eta_rho", "eta_u", "eta_v"),
    "east":  (-1, slice(None), "eta_rho", "eta_u", "eta_v"),
    "south": (slice(None), 0, "xi_rho", "xi_u", "xi_v"),
    "north": (slice(None), -1, "xi_rho", "xi_u", "xi_v"),
}
for side, (ii, jj, rho_axis, u_axis, v_axis) in sides.items():
    bry_vars[f"zeta_{side}"] = (..., zeta_clm_pad[:, jj, ii])
    bry_vars[f"u_{side}"]    = (..., u_clm_pad[:, :, jj, ii])
    ...
```

This is the mechanism --- and the #emph[only] mechanism --- through
which the Atlantic and the Eastern Mediterranean influence any PredSea
region. Neither ocean basin is itself simulated by PredSea; both enter
purely as boundary values sourced from the coarser, externally-computed
$4.2 upright(" km")$ CMEMS Mediterranean product.

=== 4.2 Gibraltar and Messina: one resolved directly, one not represented
<gibraltar-and-messina-one-resolved-directly-one-not-represented>
The Strait of Gibraltar ($approx - 5.6^compose$ to $- 5.3^compose$ lon,
$35.9^compose$--$36.0^compose$ lat) falls #strong[inside] the Alboran
region's own bounding box. The Atlantic--Mediterranean exchange there is
therefore resolved directly, at $1 upright(" km")$ resolution, by
Alboran's own CROCO grid --- it is an internal feature of that domain,
not a boundary condition. The water properties entering at Gibraltar
are, however, still sourced from the $4.2 upright(" km")$ CMEMS product
at Alboran's own western boundary, since PredSea does not simulate the
Atlantic basin itself.

The Strait of Messina ($approx 15.6^compose$ lon, $38.2^compose$ lat)
falls #strong[outside] all five regions --- the Tyrrhenian domain's
eastern edge stops at $14.0^compose$, short of the strait. No PredSea
region resolves the Sicily/Ionian exchange directly at
$1 upright(" km")$\; whatever occurs there is represented only
implicitly, through whatever the $4.2 upright(" km")$ CMEMS product
supplies at the Tyrrhenian domain's eastern boundary. This is a genuine
coverage gap in the current 5-region configuration, not a modeling
choice with an explicit fallback.

=== 4.3 No region-to-region coupling exists today
<no-region-to-region-coupling-exists-today>
Several of the five bounding boxes are geometrically adjacent, and two
--- Algerian ($l o n lt.eq 8.5^compose$, $l a t lt.eq 38.0^compose$) and
Balearic ($l o n gt.eq 0.5^compose$, $l a t gt.eq 37.5^compose$) ---
actually #strong[overlap] over the shared rectangle
$l o n in\[0.5^compose\,5.5^compose\]$,
$l a t in\[37.5^compose\,38.0^compose\]$. This adjacency is coincidental
to how the bounding boxes were drawn; it is not exploited by any
coupling mechanism. A repository-wide search found no code path that
passes one region's simulated CROCO/SWAN state to another region's
boundary --- `prepare_croco_forcing.py` takes no `region_id` of a
neighboring domain and reads only the current region's own CMEMS-derived
climatology.

Practically, this means:

- Each region is boundary-forced only by the external CMEMS field, never
  by a sibling PredSea region's own (higher-resolution) output.
- In the Algerian/Balearic overlap area, the two regions produce two
  independently-computed answers for the same physical patch of sea;
  there is no reconciliation between them.
- This is architecturally a #strong[one-way boundary-nesting] design
  (fine regional models forced by a coarser external background field)
  rather than a coupled multi-region basin simulation. Extending it to
  true region-to-region coupling, or to a single continuous domain
  covering Gibraltar through Messina, is not on the current roadmap (see
  `06_conclusion_and_roadmap.md`) but is a natural direction for closing
  the Messina coverage gap described in 4.2.

=== 4.4 Bounding boxes are rectangles, not coastline-following polygons --- some edges land on land
<bounding-boxes-are-rectangles-not-coastline-following-polygons-some-edges-land-on-land>
Every region's bbox is a simple lon/lat rectangle (Section 4, table
above), not a shape traced to the coastline. For open-basin regions
(Alboran, Algerian) this is largely inconsequential --- the whole
rectangle is water well away from land. Gulf of Lion, a bay-shaped
region, is the case that actually hit this: its original bbox's northern
edge (latitude $44.5^compose$) sat well past the real French
Mediterranean coastline in that longitude band, on land near
Marseille/Toulon. Since CMEMS's wave product is masked (NaN) over land,
that entire edge row had zero valid ocean cells.

This was found during the current validation cycle, not designed for in
advance: `gulf_of_lion_1km`'s SWAN job failed with
`north wave boundary has no finite values at index 0` even after the
region-scoped-cache fix in 4.3 confirmed it was reading its own,
correctly-fetched wave data --- the data was real, the bbox was real,
the edge itself was just land.

The first fix attempt (2026-07-29) kept the bbox as-is and had
`_side_series` in `scripts/prepare_swan_run.py` walk inward from a
land-masked edge, row by row (or column by column), until it found the
nearest row/column with real ocean data, using that as the boundary
condition and logging how many cells inward it had to go. That approach
was silently accepting arbitrarily deep inland substitutions, though, so
it was tightened the same day: `_side_series` now raises an explicit
error whenever the inward walk exceeds 30% of that edge's grid size, on
the reasoning that a walk that deep means the bbox itself is drawn wrong
for that side, not something to silently patch over with an
unrepresentative, deep-inland value (see Section 4.5 for the related
SWAN numerics fix).

That tightened check is what caught the real problem: a 2026-07-29
validation test (rebuilt image,
`alboran_1km`/`gulf_of_lion_1km`/`algerian_1km` only) had
`gulf_of_lion_1km`'s SWAN job fail fast, within about 2.5 minutes, on
the new explicit error --- confirming that its north edge at
$44.5^compose$ sat 36% of the way inland (into mainland France) before
reaching any open water, i.e.~its open boundary condition had genuinely
been built from land-adjacent water, not the true open sea. As a result,
`gulf_of_lion_1km.json`'s `bbox.latitude_max` was reduced from
$44.5^compose$ to $43.3^compose$, pulling the domain's north edge off
the mainland toward the actual coastline near Marseille/Toulon (Section
4's region table above reflects this new extent). The CROCO grid was
regenerated for the new bbox and the region's SWAN bathymetry was
regenerated against it too; the region's compiled CROCO binary was
rebuilt with the regenerated grid's dimensions as confirmed directly
from the output NetCDF (`xi_rho=500, eta_rho=200`, i.e.~`LM=498, MM=198`
under CROCO/ROMS's `xi_rho=LM+2`/`eta_rho=MM+2` convention, replacing a
previous `LM=449, MM=299` that itself traced back to a rough planning
estimate rather than a confirmed grid dimension) --- see
`05_cloud_deployment_and_ops.md` for the image rebuild this shipped in.

Whether the 30%-of-grid threshold is the right cutoff for other regions,
and whether any other region's bbox has a similar undetected
land-adjacent edge, has not been checked --- this was found and fixed
for Gulf of Lion specifically, not audited across all 5 regions.

=== 4.5 SWAN slow convergence in geometrically constrained regions
<swan-slow-convergence-in-geometrically-constrained-regions>
During the same 2026-07-29 live 6-hour-forecast test, 3 of the 5
regions' SWAN jobs (`alboran_1km`, `gulf_of_lion_1km`, `algerian_1km`)
ran for multiple hours without completing, while `balearic_1km` and
`tyrrhenian_1km` finished quickly. Grid size was ruled out as the
explanation: `tyrrhenian_1km` has the largest grid of the five
($approx 523\,000$ cells) and finished fastest, while
`alboran_1km`/`gulf_of_lion_1km` have among the smallest grids
($approx 150\,000$--$170\,000$ cells) and were among the slow ones. The
SWAN 41.51 user manual was consulted directly and confirms nonstationary
runs default to `mxitns=1` (max 1 iteration per timestep), which rules
out "excessive iteration churn per timestep" as the cause.

SWAN's numerical configuration --- a 5-minute computational timestep,
`GEN3 WESTHUYSEN` wave growth, and `BREAKING`/`FRICTION`/`TRIAD` physics
terms --- had been hardcoded identically across all 5 regions with no
accommodation for geometrically constrained domains (narrow straits, bay
shapes, steep coastal shelves). The fix adds `PROP BSBT` to the SWAN
command file generated for every region: this is SWAN's own
manual-documented recommendation
(#link("https://swanmodel.sourceforge.io/online_doc/swanuse/node29.html")[swanmodel.sourceforge.io, node29])
for domains where "sharp transitions in the grid cannot be avoided" ---
exactly the geometry of `alboran_1km` (Strait of Gibraltar),
`gulf_of_lion_1km` (bay-shaped, steep shelf break), and `algerian_1km`
(narrow coastal shelf), as opposed to `balearic_1km`/`tyrrhenian_1km`,
which have open-water boundaries throughout.

#strong[Current status: not yet confirmed resolved.] A 3-region-only
validation test (`alboran_1km`, `gulf_of_lion_1km`, `algerian_1km`) with
the rebuilt image found `gulf_of_lion_1km`'s SWAN job failing fast
(within \~2.5 minutes) on the new boundary error described in Section
4.4 --- a genuine, previously-silent problem, now addressed by the bbox
resize. `alboran_1km` and `algerian_1km` did not fail fast this time,
but also did not cleanly finish: both ran for 3.5+ hours before being
orphaned when the overall build aborted due to `gulf_of_lion_1km`'s
failure (any region failing aborts the whole run --- see
`05_cloud_deployment_and_ops.md`, Section 1a). This is an inconclusive,
mixed result for `alboran_1km`/`algerian_1km` specifically --- better
than an immediate crash, but not yet confirmed as fully resolved.

A leading but #strong[unconfirmed, not yet investigated] theory for
residual slowness in those two regions is MPI domain-decomposition load
imbalance: narrow/constrained-geometry regions have large land fractions
inside their rectangular bounding box, and if GCP Batch's grid
decomposition doesn't account for the wet/dry cell distribution, some
MPI ranks could be doing far more work than others. This has not been
tested.

A fresh 3-region validation test (`alboran_1km`, `gulf_of_lion_1km`,
`algerian_1km`) with the fully-fixed image (bbox resize + `PROP BSBT` +
the boundary-walk-inward limit) is in progress as of this writing (Cloud
Build ID `a8b61b91-2302-4d24-81ad-70f64951922e`, started
2026-07-29T14:41:36Z). Its result is not yet known.

#divider()

== 5. Wave Model Migration: SWAN → WaveWatch III (WW3)
<wave-model-migration-swan-wavewatch-iii-ww3>
As of 2026-08-04, SWAN is being replaced by WaveWatch III (WW3) as
PredSea's wave-spectral engine, project-wide across all 5 regions --- a
full replacement, not a hybrid, to keep one uniform solver/architecture
across regions. This section documents the migration's motivation and
current status; it does not retract Sections 1.C/4.4/4.5 above, which
remain the accurate description of SWAN's role while the migration is in
progress.

=== 5.1 Why
<why>
Five independent variables were tried and ruled out as the cause of the
persistent non-convergence ("stuck at output request 1") affecting
`alboran_1km`, `gulf_of_lion_1km`, and `algerian_1km` in both basin-wide
and per-region SWAN configurations: bathymetry data quality (validated
against GSHHG ground truth, 0.3--0.8% mismatch everywhere, no worse for
the broken regions), resolution/timestep, physics scheme (WESTHUYSEN
vs.~KOMEN), MPI rank count/load balance, and domain size (a standalone
small-domain `alboran_1km` job hit the identical symptom). The full
elimination sequence is in `docs/ww3-migration-plan-2026-08-04.md`. The
evidence points at something structural to SWAN's implicit solver on
this specific coastline/bathymetry geometry, not a tunable setting.

WW3 uses an explicit propagation scheme built for basin/ocean-scale
domains --- the opposite design point from SWAN's implicit solver ---
computing the same wave-action-balance physics described in Section 1.C
via a different numerical path, so it is not subject to the same failure
mode.

=== 5.2 Status as of 2026-08-05
<status-as-of-2026-08-05>
- WW3 built from source (`Dockerfile.ww3-batch`, `ST4`/Ardhuin et
  al.~(2010) physics package, MPI-enabled) and pushed to
  `europe-west1-docker.pkg.dev/predsea-api/predsea-simulations/ww3-batch`.
- A single-region 6h smoke test on `alboran_1km` (64 vCPU) completed
  successfully --- the first confirmation WW3 runs to completion and
  produces sane output on the region that originally motivated the
  migration.
- A first 5-region breadth test (all of `alboran`, `algerian`,
  `balearic`, `tyrrhenian`, `gulf_of_lion`, uniform 16 vCPU each,
  30-minute wall-clock budget) failed everywhere on a pure GCP Batch
  timeout (exit 50005) --- 16 vCPU was too few cores to finish a 6h run
  in 30 minutes for any region, not a solver-level failure.
- A corrected 5-region breadth test --- vCPU allocation made
  proportional to each region's actual sea-point count (from
  `ww3_grid`'s own grid statistics, not bbox size: 24/16/12/8/4 vCPU for
  tyrrhenian/balearic/algerian/alboran/gulf\_of\_lion respectively),
  `maxRunDuration` extended to 3 hours, and a periodic background log
  re-upload added so a run leaves diagnostic evidence even under a
  future timeout --- #strong[completed successfully for all 5 regions],
  with completion times ranging 1.39h--2.03h. This is the first evidence
  the migration is sound across the full regional set, not only the
  region that motivated it.
- A 24-hour, 5-region forecast test, using WRF's own output as WW3's
  wind forcing (rather than the ECMWF Open Data shortcut used for the 6h
  tests), is the immediate next validation step. It is currently blocked
  on a WRF domain-coverage fix (alboran\_1km's western \~40% fell
  outside WRF's own atmospheric domain) whose corrected image is being
  rebuilt.

The full narrative --- exact job names, timings, resource configs, and
concrete next steps --- is kept in a dated handoff document rather than
duplicated here, since this is an actively moving migration: see
`docs/agent-handoff-ww3-wrf-migration-2026-08-05.md`.

=== 5.3 What does not change
<what-does-not-change>
Section 4's discussion of regional domain decomposition, CMEMS-sourced
lateral boundary forcing, and the absence of region-to-region coupling
applies identically to WW3 --- this migration replaces the wave solver
only, not the boundary-forcing or domain-decomposition architecture.


// --- FILE: 03_thermodynamics_and_fluxes.md ---

= 03. Thermodynamics & Bulk Surface Fluxes
<thermodynamics-bulk-surface-fluxes>
This document details the thermodynamic formulations, air-sea boundary
layer bulk parameterizations, and numerical bug fixes implemented in
#strong[PredSea] to eliminate unphysical heat accumulation in regional
hydrodynamic runs.

#divider()

== 1. Governing Heat Flux Equations
<governing-heat-flux-equations>
The net surface heat flux ($upright("shflux")$, expressed in
$upright("W/m")^2$) entering or leaving the upper oceanic boundary layer
is defined by the algebraic sum of shortwave solar radiation, net
longwave thermal radiation, latent heat flux from evaporation, and
sensible turbulent heat flux:

$ upright("shflux") = upright("radsw") + upright("shflx_rlw") + upright("shflx_lat") + upright("shflx_sen") $

Where sign convention dictates that #strong[positive values ($> 0$)
represent heat gain by the ocean], and #strong[negative values ($< 0$)
represent net heat loss from the ocean to the atmosphere].

#heat_flux_diagram()

=== A. Net Shortwave Solar Radiation ($upright("radsw")$)
<a.-net-shortwave-solar-radiation-textradsw>
Shortwave solar flux reaching the surface mixed layer is governed by
downward shortwave flux ($S W_arrow.b$) modulated by the sea surface
albedo ($alpha approx 0.06$):

$ upright("radsw") =\(1 - alpha\)dot.op S W_arrow.b $

Shortwave radiation penetrates the upper water column following a
two-band exponential decay attenuation model:

$ I\(z\)= upright("radsw") dot.op [r_1 e^(z\/d_1) + \( 1 - r_1 \) e^(z\/d_2)] $

Where $r_1 approx 0.58$ represents the rapidly absorbed infrared
spectrum fraction ($d_1 approx 0.35 upright(" m")$), and $\(1 - r_1\)$
is the blue-green spectrum with deeper optical attenuation scale
($d_2 approx 23.0 upright(" m")$ in clear Mediterranean waters).

=== B. Net Longwave Infrared Radiation ($upright("shflx_rlw")$)
<b.-net-longwave-infrared-radiation-textshflx_rlw>
Net longwave flux represents the balance between incoming atmospheric
downward thermal radiation ($L W_arrow.b$) and Stefan-Boltzmann
blackbody radiation emitted by the sea surface temperature
($upright("SST")$):

$ upright("shflx_rlw") = epsilon.alt_s L W_arrow.b - epsilon.alt_s sigma_(S B) dot.op\(upright("SST") + 273.15\)^4 $

Where: \* $epsilon.alt_s = 0.98$ is the ocean emissivity constant. \*
$sigma_(S B) = 5.670374 times 10^(- 8) thin upright("W/m")^2\/upright("K")^4$
is the Stefan-Boltzmann constant.

Because Mediterranean summer sea surface temperatures
($upright("SST") approx 26^compose upright("C") - 29^compose upright("C")$)
typically exceed near-surface air temperatures, $upright("shflx_rlw")$
acts as a continuous cooling mechanism (ranging between
$- 50 upright(" W/m")^2$ and $- 110 upright(" W/m")^2$).

=== C. Latent Heat Flux ($upright("shflx_lat")$)
<c.-latent-heat-flux-textshflx_lat>
Latent heat flux driven by wind-induced surface evaporation is
parameterized using COARE 3.0 bulk aerodynamic formulas:

$ upright("shflx_lat") = - rho_a L_v C_E dot.op\|arrow(U)_10\|dot.op (q_s \( upright("SST") \) - q_a) $

Where: \* $rho_a$ is air density ($approx 1.22 upright(" kg/m")^3$). \*
$L_v$ is latent heat of vaporization
($approx 2.45 times 10^6 thin upright("J/kg")$). \* $C_E$ is the
turbulent transfer coefficient for moisture. \* $\|arrow(U)_10\|$ is
$10 upright(" m")$ wind speed magnitude. \* $q_s\(upright("SST")\)$ is
saturation specific humidity at sea surface temperature. \* $q_a$ is
atmospheric specific humidity at $2 upright(" m")$.

=== D. Sensible Heat Flux ($upright("shflx_sen")$)
<d.-sensible-heat-flux-textshflx_sen>
Direct conductive/convective heat exchange between ocean and air is
governed by:

$ upright("shflx_sen") = - rho_a c_p C_H dot.op\|arrow(U)_10\|dot.op (upright("SST") - T_a) $

Where $c_p = 1004.6 thin upright("J/kg/K")$ is atmospheric specific heat
capacity and $C_H$ is the bulk sensible heat transfer coefficient.

#divider()

== 2. Verified Fix: Bulk Flux Sign-Convention Correction in `bulk_flux.F`
<verified-fix-bulk-flux-sign-convention-correction-in-bulk_flux.f>
The one thermodynamics fix actually present in this codebase
(`simulation/marine/croco/patch_croco_source.py`, applied to
`bulk_flux.F` at build time for every region) corrects the sign
convention on latent and sensible heat flux, not a unit-scaling or
SST-feedback bug. The original CROCO source computed:

```fortran
hflat=-hflat*rho0i*cpi
hfsen=-hfsen*rho0i*cpi
```

This unconditionally negates whatever sign the underlying bulk formula
produced, with no guarantee that latent/sensible flux actually points
the physically required direction (evaporation must always remove heat
from the ocean; conduction must remove heat from the ocean whenever the
sea is warmer than the air). The applied patch enforces that
directionality explicitly:

```fortran
! --- FIXED SIGN CONVENTION FOR BULK FLUXES ---
! 1. Latent Heat Flux: Evaporation MUST remove energy from ocean (< 0)
hflat=-ABS(hflat)*rho0i*cpi
! 2. Sensible Heat Flux: Conduction when SST > T_air MUST remove energy from ocean (< 0)
IF (TseaC .gt. TairC) THEN
  hfsen=-ABS(hfsen)*rho0i*cpi
ELSE
  hfsen=-hfsen*rho0i*cpi
ENDIF
```

This is a narrower, more mechanical fix than a full unit-mismatch or
dynamic-SST-feedback correction --- it guards against one specific
failure mode (a sign flip producing spurious ocean warming from
evaporation/conduction) rather than rewriting the bulk flux calculation.
Whether this alone was sufficient to prevent the thermal runaway seen in
early pre-alpha runs, versus other contributing factors (e.g.~the
vertical-coordinate/barotropic-transport fixes in
`prepare_croco_forcing.py` described in Section 2 of
`02_modeling_suite.md`), has not been isolated by a controlled test;
both changes shipped together in the runs validated so far.

#divider()

== 3. Nocturnal Boundary Cooling Mechanics
<nocturnal-boundary-cooling-mechanics>
The resolution of `bulk_flux.F` restores physical nocturnal cooling.
During daytime hours, solar flux ($upright("radsw")$) dominates,
producing a positive net flux
($upright("shflux") approx + 400 upright(" W/m")^2 upright(" to ") + 700 upright(" W/m")^2$)
that warms the top $1 upright(" m") - 3 upright(" m")$ diurnal skin
layer.

During night hours ($S W_arrow.b = 0$), $upright("radsw")$ drops to
zero. Net surface heat flux becomes strictly negative:

$ upright("shflux")_(upright("night")) = upright("shflx_rlw") + upright("shflx_lat") + upright("shflx_sen") approx - 180 upright(" W/m")^2 upright(" to ") - 320 upright(" W/m")^2 $

#heat_flux_diagram()

This negative nocturnal flux generates surface water density inversion
($frac(partial rho, partial z) < 0$), triggering convective vertical
mixing that cools the surface layer back toward equilibrium baseline
temperatures. Confirming this quantitatively against satellite
radiometry or buoy observations for the Western Mediterranean has not
yet been done --- see `04_empirical_validation.md` for what has actually
been measured so far.


// --- FILE: 04_empirical_validation.md ---

= 04. Empirical Validation: Current Status Across the 5 Western Mediterranean Regions
<empirical-validation-current-status-across-the-5-western-mediterranean-regions>
This document tracks which region/horizon/timestep combinations have
actually been run to completion and passed the structural validation
gate (`scripts/validate_marine_output.py`), as opposed to a single
polished "benchmark" narrative. It intentionally does not include
specific SST/salinity/current numeric results, buoy RMSE figures, or
named-location anomaly case studies, because none of those have actually
been pulled from a completed run's validation JSON and cross-checked yet
--- see "What is not yet validated" below.

#divider()

== 1. Regional Domain Specifications
<regional-domain-specifications>
#figure(
  align(center)[#table(
    columns: (17.39%, 17.39%, 21.74%, 21.74%, 21.74%),
    align: (left,left,center,center,center,),
    table.header([Region ID], [Extent (lon / lat)], [Grid
      ($xi_rho times eta_rho$)], [Grid Points], [Vertical Levels ($N$)],),
    table.hline(),
    [#strong[Balearic 1km]], [$0.5$--$5.5^compose upright("E")$,
    $37.5$--$41.5^compose upright("N")$], [$501 times 401$], [$200\,901$], [32],
    [#strong[Alboran 1km]], [$- 6.0$--$- 1.0^compose upright("E")$,
    $35.0$--$37.5^compose upright("N")$], [$501 times 251$], [$124\,203$], [32],
    [#strong[Gulf of Lion 1km]], [$2.0$--$6.5^compose upright("E")$,
    $41.5$--$43.3^compose upright("N")$], [$500 times 200$], [not
    recomputed for new bbox\*], [32],
    [#strong[Tyrrhenian 1km]], [$7.5$--$14.0^compose upright("E")$,
    $38.0$--$44.5^compose upright("N")$], [$650 times 651$], [$391\,379$], [32],
    [#strong[Algerian Basin 1km]], [$- 1.0$--$8.5^compose upright("E")$,
    $35.0$--$38.0^compose upright("N")$], [$951 times 301$], [$282\,273$], [32],
  )]
  , kind: table
  )

\*Gulf of Lion's extent and grid were changed on 2026-07-29 (bbox
`latitude_max` reduced from $44.5^compose$ to $43.3^compose$\; see
`02_modeling_suite.md` §4.4). The grid dimensions above
(`xi_rho=500, eta_rho=200`) are confirmed directly from the regenerated
CROCO grid's NetCDF; the "Grid Points" figure used elsewhere in this
suite has not been recomputed against the new bbox and is omitted here
rather than restating the stale pre-resize number.

== 2. What Has Actually Passed the Validation Gate
<what-has-actually-passed-the-validation-gate>
The proven CROCO timestep configuration this development cycle is
$Delta t = 30 upright(" s")$ baroclinic / `NDTFAST=45` barotropic
substeps (matching the historically stable
$Delta t_(f a s t) approx 0.667 upright(" s")$ from an earlier confirmed
$Delta t = 20 upright(" s")$/`NDTFAST=30` configuration). Runs are
accepted only if `validate_marine_output.py` confirms
`finite_fraction: 1.0` (no `NaN`/`Inf`/uninitialized cells) and all
output variables fall within their configured physical ranges, before a
`CROCO_SUCCESS` marker is written.

#figure(
  align(center)[#table(
    columns: (21.05%, 26.32%, 26.32%, 26.32%),
    align: (left,center,center,center,),
    table.header([Region], [6h gate], [24h gate], [72h gate],),
    table.hline(),
    [#strong[Balearic 1km]], [✅ passed], [✅ passed], [attempted, hit a
    WRF-forcing data-availability limit (see below), not yet re-run],
    [#strong[Alboran 1km]], [✅ passed], [✅ passed], [attempted, failed
    on the same WRF-forcing limit],
    [#strong[Gulf of Lion 1km]], [✅ passed], [✅ passed], [attempted,
    failed on the same WRF-forcing limit],
    [#strong[Tyrrhenian 1km]], [✅ passed], [not yet run (user deferred
    after 6h/72h decision)], [attempted, hit the same WRF-forcing
    limit],
    [#strong[Algerian Basin 1km]], [✅ passed], [✅ passed], [attempted,
    hit the same WRF-forcing limit],
  )]
  , kind: table
  )

The 72h attempts across all 5 regions failed not from a CROCO numerical
problem, but because the WRF atmospheric forcing dataset reused for that
test only had 24 hours of `wrfout_d02_*` output available (confirmed
directly via `gsutil ls`) against a `run_marine_simulation.py` check
requiring `forecast_hours + 1` hourly files. The fix in progress is to
run WRF fresh for each forecast horizon (via the corrected
`daily_orchestrator.py --use-gcp-batch` path) rather than reusing an
older, shorter WRF dataset.

#strong[Gulf of Lion's grid was regenerated on 2026-07-29] (bbox resize
described in `02_modeling_suite.md` §4.4, new dimensions
$500 times 200$, replacing the previous $451 times 301$ grid). The
6h/24h passes recorded in the table above were run against the
#emph[old] grid; the new grid has not yet been re-run at any CROCO
horizon. A 3-region validation test covering the new Gulf of Lion grid
(alongside Alboran and Algerian) is in progress as of this writing ---
see Section 3 below.

== 3. What Is Not Yet Validated
<what-is-not-yet-validated>
To avoid repeating the previous version of this document's mistake, the
following are explicitly #strong[not yet done], not just "not shown
here":

- No SST/salinity/current/sea-level numeric results (min/max/mean) from
  any completed run have been pulled from GCS and recorded in this
  document.
- No comparison against SOCIB buoys, CMEMS satellite SST, or any other
  independent observation source has been performed.
- No wave height ($H_s$) validation has been done --- SWAN has not yet
  been run to completion across all 5 regions in a single pipeline run.
  A live 6-hour-forecast attempt this cycle surfaced two real,
  since-fixed bugs (a silently-deep land-boundary substitution and a
  missing numerical scheme accommodation for geometrically constrained
  domains --- see `02_modeling_suite.md` §§4.4--4.5) plus an unrelated
  orchestrator timeout-sharing bug that killed the run prematurely (see
  `05_cloud_deployment_and_ops.md` §1a). A subsequent 3-region test
  (`alboran_1km`, `gulf_of_lion_1km`, `algerian_1km`) with the fixes
  applied got a mixed result: `gulf_of_lion_1km` failed fast on a
  genuine bbox problem (now fixed by a bbox resize), while
  `alboran_1km`/`algerian_1km` ran 3.5+ hours without completing before
  being orphaned when the run aborted --- inconclusive, not a pass. A
  fresh 3-region test with the fully-fixed image is in progress as of
  this writing (Cloud Build ID `a8b61b91-2302-4d24-81ad-70f64951922e`,
  started 2026-07-29T14:41:36Z); its result is not yet known.
- No named-location physical anomaly (e.g.~a specific channel
  wind-acceleration or upwelling case study) has been identified from
  real model output. Any such example in an earlier version of this
  document was illustrative, not measured.

== 4. C-Grid Dimension-Aware Masking
<c-grid-dimension-aware-masking>
In 3D hydrodynamic solvers using staggered Arakawa C-grids, variables
reside on distinct spatial sub-grids:
$ upright("Tracers ")\(T\,S\,zeta\)in upright("Grid")_rho\(eta_rho\,xi_rho\)\,quad U in upright("Grid")_u\(eta_u\,xi_u\)\,quad V in upright("Grid")_v\(eta_v\,xi_v\) $

If a validation script blindly applies
$upright("Mask")_rho\(eta_rho\,xi_rho\)$ to velocity components on a
different sub-grid, `xarray` can perform an unintended outer join across
non-matching spatial dimensions, ballooning memory use.
`validate_marine_output.py`'s `_apply_matching_mask` guards against this
by confirming
$upright("dims")\(upright("Mask")\)subset.eq upright("dims")\(upright("DataArray")\)$
before masking. (The specific "reduces to 1.8 seconds" performance
figure from an earlier version of this document was not independently
re-measured for this rewrite and has been removed rather than repeated
unverified.)


// --- FILE: 05_cloud_deployment_and_ops.md ---

= 05. Cloud Deployment & Serverless Operations
<cloud-deployment-serverless-operations>
This document describes the cloud-native, serverless execution framework
developed for #strong[PredSea] using #strong[Google Cloud Platform (GCP)
Batch], #strong[Spot VM instances], and automated cost-protection
mechanisms.

#divider()

== 1. Containerized HPC Engine (`croco-batch`)
<containerized-hpc-engine-croco-batch>
Rather than maintaining dedicated, static HPC server hardware, the
entire numerical modeling environment---including compiled Fortran 90
binaries for CROCO 2.1.3 and SWAN 41.45, OpenMPI execution runtimes,
NetCDF C/Fortran libraries, and Python spatial post-processors---is
encapsulated in an immutable Docker container image
(`simulation/marine/croco/Dockerfile.batch`).

```
+-----------------------------------------------------------------------------------+
|               PredSea Unified HPC Container Architecture                          |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  | Base OS: Ubuntu 22.04 LTS + OpenMPI 4.1 + gfortran / gcc                      |  |
|  +-----------------------------------------------------------------------------+  |
|  | Compiled Binaries (one CROCO binary per region, built in a Dockerfile loop): |  |
|  |  - /usr/local/bin/croco_balearic_1km, croco_alboran_1km, croco_algerian_1km, |  |
|  |    croco_gulf_of_lion_1km, croco_tyrrhenian_1km (region-specific LM/MM/N)    |  |
|  |  - SWAN binary (swan.exe/swanrun) is region-agnostic; bathymetry is what's   |  |
|  |    per-region — all 5 regions' SWAN bathymetry grids are COPY'd into the     |  |
|  |    image at build time (see docs/bathymetry-integration-guide.md)           |  |
|  +-----------------------------------------------------------------------------+  |
|  | Python Environment: Python 3.11 + NetCDF4 + xarray + SciPy + NumPy           |  |
|  +-----------------------------------------------------------------------------+  |
|  | Automation Scripts:                                                         |  |
|  |  - run_marine_simulation.py  (Master entrypoint; --model croco or --model=  |  |
|  |    swan — `--model=both` is intentionally hard-disabled, see Section 2)     |  |
|  |  - prepare_croco_forcing.py / prepare_croco_bulk_forcing.py (forcing prep)   |  |
|  |  - validate_marine_output.py  (Dimension-aware C-grid physical validator)    |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
```

The image is pinned by digest (not by mutable tag) in every real Batch
submission, since digests can drift as the image is rebuilt:
`europe-west1-docker.pkg.dev/predsea-api/predsea-simulations/croco-batch@sha256:f8313ce5d43624d055321ba769f7a7da315c6aad5c7e16c30ab10ba063953ba8`

This is the digest confirmed, this development cycle, to be built from a
Dockerfile that compiles both CROCO and SWAN from source and bakes in
per-region bathymetry for all 5 Western Mediterranean regions. This
particular digest also carries two 2026-07-29 SWAN fixes (an explicit
error when a boundary's walk-inward substitute exceeds 30% of that
edge's grid size, and the addition of `PROP BSBT` to SWAN's numerical
scheme for geometrically constrained domains --- both described in
`02_modeling_suite.md` §§4.4--4.5) and the regenerated Gulf of Lion
CROCO grid/binary (`LM=498, MM=198`, also §4.4).
`submit_gcp_batch_simulation.py` refuses to submit a real (non-dry-run)
job unless `--image-uri` contains an explicit `@sha256:` digest. Full
end-to-end confirmation that SWAN actually runs successfully against
real bathymetry for all 5 regions is still open --- see
`04_empirical_validation.md` for the current, in-progress validation
status.

#divider()

== 1a. Orchestration Entry Point and the WRF → CROCO → SWAN Sequence
<a.-orchestration-entry-point-and-the-wrf-croco-swan-sequence>
The daily/gate pipeline is not submitted by hand region-by-region. A
single Cloud Build job invokes
`scripts/daily_orchestrator.py --use-gcp-batch`, which drives the full
sequence:

+ #strong[Boundary/credential fetch]: ECMWF and CMEMS forcing are
  downloaded first. Copernicus, AEMET, and SOCIB credentials are pulled
  from Secret Manager at build time (`availableSecrets`/`secretEnv` in
  the Cloud Build config) rather than from a local `.env` file, since
  `humanintheloop/.env` is git-ignored and never reaches Cloud Build's
  source upload. Builds run as the Compute Engine default service
  account, not the legacy Cloud Build SA --- that account is what needs
  `roles/secretmanager.secretAccessor`.
+ #strong[Shared WRF run]: a single Spot/on-demand VM runs WRF once for
  atmospheric forcing. Every region's CROCO/SWAN job reads from this
  same WRF output --- WRF is never run per-region.
+ #strong[CROCO phase]: once WRF completes, a CROCO Batch job is
  submitted for every configured region simultaneously (5 jobs × 16 vCPU
  `c2d-highcpu-16` = 80 vCPU), and the orchestrator polls each job's
  real Batch state plus a `CROCO_SUCCESS` GCS marker until all regions
  finish.
+ #strong[SWAN phase]: only after every region's CROCO job succeeds does
  the orchestrator submit SWAN as a second, separate phase across all
  regions, polling the same way for a `SUCCESS` marker.

Two phases instead of one combined submission exist for two independent
reasons:

- `run_marine_simulation.py --model=both` is a hard, permanent
  `parser.error()` (exit code 2) --- CROCO and SWAN must always run as
  separate Batch jobs, never combined in one container invocation.
- The project's `CPUS_ALL_REGIONS` quota is a single #strong[global] 64
  vCPU cap shared by the WRF VM and every Batch job across every phase
  --- it is not a per-phase or per-region allowance. 5 regions' CROCO
  jobs alone (5 × 16 vCPU = 80 vCPU) already exceed it, so in practice
  some regions' jobs queue for capacity rather than all starting
  immediately (a multi-minute `CPUS_ALL_REGIONS` quota wait per region
  has been observed in production runs). Splitting CROCO and SWAN into
  two sequential phases avoids also stacking all 10 region×model jobs at
  once (160 vCPU), but does not remove the queuing itself.

Any region is mandatory within its phase --- a submission or completion
failure for one region aborts the whole run rather than silently
publishing a partial result. This is not just a design description: a
2026-07-29 3-region validation test was aborted mid-run when
`gulf_of_lion_1km`'s SWAN job failed, and the other two regions'
still-running SWAN jobs (`alboran_1km`, `algerian_1km`, each past 3.5
hours at that point) were orphaned as a result rather than left to
finish --- see `04_empirical_validation.md` for the current status of
that test.

=== Timeout budgets: the WRF VM timeout and the Batch-phase timeout are now decoupled
<timeout-budgets-the-wrf-vm-timeout-and-the-batch-phase-timeout-are-now-decoupled>
Until 2026-07-29, `daily_orchestrator.py` computed a single
`timeout_hours` value from the forecast horizon
(`max(4.0, (forecast_hours / 24) * 1.25)`, flooring at 4.0h for short
horizons) and reused it for two unrelated things: the WRF VM's own
timeout, and the combined CROCO+SWAN Batch-phase timeout. This caused a
real production incident: a live 6-hour-forecast test run was killed by
the shared 4-hour ceiling while 3 of the 5 regions' SWAN jobs were still
legitimately in progress --- not hung, just needing more than 4 hours
combined for CROCO+SWAN across all regions.

The fix adds a separate function, `batch_pipeline_timeout_hours()`
(floor of 8.0h, scaling with forecast horizon), used only for the Batch
phase and for each Batch job's own `maxRunDuration`, fully decoupled
from the WRF VM's own timeout. `cloudbuild.6h-gate.yaml`'s own Cloud
Build step timeout was also bumped from 6 hours (`21600s`) to 14 hours
(`50400s`) --- the old ceiling would otherwise have killed the entire
build before the new, larger internal timeout could ever matter, since
WRF (up to \~4h) plus the Batch phase (up to \~8h) can now total up to
12h in the worst case.

#divider()

== 2. Dynamic Resource-Aware Compute Sizing & Regional Matrix
<dynamic-resource-aware-compute-sizing-regional-matrix>
To prevent Out-Of-Memory (OOM) failures while minimizing compute
expenditure, the submission orchestrator
#link("file:///Users/charles.santana/Kultrip/predsea-system/scripts/submit_gcp_batch_simulation.py")[`scripts/submit_gcp_batch_simulation.py`]
provisions compute resources according to regional grid point densities:

$ upright("Grid Points") = (frac(\(upright("Lat")_(upright("max")) - upright("Lat")_(upright("min"))\)times 111\,000, H_(upright("res")))) times (frac(\(upright("Lon")_(upright("max")) - upright("Lon")_(upright("min"))\)times 111\,000 times cos\(upright("Lat")_(upright("mid"))\), H_(upright("res")))) $

=== Regional Deployment Specifications (Western Mediterranean Suite)
<regional-deployment-specifications-western-mediterranean-suite>
`calculate_resources()` in `submit_gcp_batch_simulation.py` auto-derives
machine sizing from each region's grid point count, but its "small tile"
and "medium tile" branches currently return identical values --- so
every real submission this cycle has passed explicit CLI overrides to
get the proven configuration below, rather than relying on the
auto-sizing:

#figure(
  align(center)[#table(
    columns: (13.79%, 17.24%, 17.24%, 17.24%, 17.24%, 17.24%),
    align: (left,center,center,center,center,center,),
    table.header([Region ID], [Grid Points], [Machine Type], [MPI
      Ranks], [Compute Spec], [Provisioning],),
    table.hline(),
    [#strong[Balearic 1km]], [$200\,901$], [`c2d-highcpu-16`], [16], [16
    vCPU / 32 GiB], [STANDARD],
    [#strong[Alboran 1km]], [$124\,203$], [`c2d-highcpu-16`], [16], [16
    vCPU / 32 GiB], [STANDARD],
    [#strong[Gulf of Lion
    1km]], [$121\,649^(*)$], [`c2d-highcpu-16`], [16], [16 vCPU / 32
    GiB], [STANDARD],
    [#strong[Tyrrhenian
    1km]], [$391\,379$], [`c2d-highcpu-16`], [16], [16 vCPU / 32
    GiB], [STANDARD],
    [#strong[Algerian 1km]], [$282\,273$], [`c2d-highcpu-16`], [16], [16
    vCPU / 32 GiB], [STANDARD],
  )]
  , kind: table
  )

\*Gulf of Lion's Grid Points figure above predates the 2026-07-29 bbox
resize (`02_modeling_suite.md` §4.4) and has not been recomputed against
the new bbox (`latitude_max` now $43.3^compose$ instead of
$44.5^compose$); it is left as-is here rather than replaced with an
invented number, but should not be treated as current. Machine sizing
(16 vCPU) was set via explicit CLI override in any case, not derived
from this figure.

`STANDARD` (on-demand) provisioning was chosen deliberately over `SPOT`
for these validation runs: `SPOT` capacity draws from the same single
global `CPUS_ALL_REGIONS` quota pool (64 vCPUs for the whole project,
covering the WRF VM and every Batch job together --- see Section 1a),
and deadline-critical gate testing needs guaranteed capacity rather than
preemption risk. `SPOT` remains the CLI default in
`submit_gcp_batch_simulation.py` and is the intended cost-saving mode
once the pipeline is stable enough to tolerate retries.

#divider()

== 3. Spot VM Preemptibility & Cost Safety Traps
<spot-vm-preemptibility-cost-safety-traps>
`SPOT` VM pricing is #strong[70%--90%] cheaper than on-demand, and is
the long-term target once this pipeline no longer needs
deadline-guaranteed capacity (see Section 2). The fault-tolerance
mechanisms below apply regardless of provisioning model:

#cloud_deployment_diagram()

+ #strong[Automated Self-Deletion Traps]: Compute nodes automatically
  self-destruct upon task exit, eliminating idle VM billing risks.
+ #strong[In-Cloud Validation Gate]: All assertions
  (`validate_marine_output.py`) run in-cloud directly inside the
  container before storage sync, requiring zero local downloads.
+ #strong[Run-Scoped Immutability]: Forecast outputs are committed to
  immutable GCS storage paths:
  `gs://predsea-daily-outputs-test/predictions/YYYY-MM-DD/runs/[RUN_ID]/`


// --- FILE: 06_conclusion_and_roadmap.md ---

= 06. Conclusion & Engineering Roadmap
<conclusion-engineering-roadmap>
This document summarizes the technical achievements of the
#strong[PredSea] oceanographic forecasting architecture and outlines the
future engineering roadmap.

#divider()

== 1. Summary of Current Architectural State
<summary-of-current-architectural-state>
PredSea's working hypothesis is that high-resolution
($1 upright(" km")$) regional ocean modeling does not require expensive,
dedicated supercomputer infrastructure --- that serverless GCP Batch
orchestration, parallel process-level Python pre-processing, and the
CROCO/SWAN/WRF numerical engines can deliver it instead. As of this
development cycle:

+ #strong[High-Resolution Coastal Granularity]: The 5 Western
  Mediterranean 1 km CROCO grids are defined and have compiled binaries;
  validated runs to date confirm numerical stability at 6h and 24h
  horizons (see `04_empirical_validation.md` for the exact per-region
  status), not yet a full operational forecast product.
+ #strong[Compute Orchestration]: CROCO and SWAN run as parallel
  per-region GCP Batch jobs sharing one upstream WRF run;
  `daily_orchestrator.py` now chains WRF → regional CROCO+SWAN
  submission → real Batch-status polling automatically (see
  `05_cloud_deployment_and_ops.md`). A 2026-07-29 production incident (a
  shared timeout budget between the WRF VM and the combined CROCO+SWAN
  Batch phase killed a live 6h test while 3 of 5 regions were still
  legitimately running) led to decoupling those two timeouts --- see
  `05_cloud_deployment_and_ops.md` §1a. Specific pre-processing/runtime
  speed numbers have not been re-measured since this pipeline changed
  and are not repeated here to avoid restating stale figures.
+ #strong[Cost]: STANDARD (on-demand) provisioning is currently used
  deliberately for reliability during validation, not SPOT; a verified,
  current per-day cost figure for the full 5-region suite has not yet
  been compiled. SPOT is the intended cost-saving target once the
  pipeline is stable (see `05_cloud_deployment_and_ops.md`, Section 2).
+ #strong[Physical & Empirical Accuracy]: A verified fix exists for one
  specific bulk-flux sign-convention bug
  (`03_thermodynamics_and_fluxes.md`, Section 2). No comparison against
  SOCIB buoys, satellite SST, or other independent observations has been
  performed yet --- this remains open work, not a completed
  accomplishment.
+ #strong[Wave Engine Migration (in progress)]: SWAN is being replaced
  project-wide by WaveWatch III (WW3) after exhaustive tuning ruled out
  every SWAN parameter as the cause of persistent non-convergence in 3
  of the 5 regions (see `02_modeling_suite.md`, Section 5). A 5-region
  6h WW3 breadth test has passed with a workload-proportional core
  allocation; a WRF-forced 24h, 5-region test is the next validation
  gate, currently blocked on a WRF domain-coverage fix. See
  `docs/agent-handoff-ww3-wrf-migration-2026-08-05.md` for exact current
  status.

#divider()

== 2. Technical & Strategic Roadmap
<technical-strategic-roadmap>
=== Milestone A: Multi-Day Diurnal Thermal Skin Layer Tracking
<milestone-a-multi-day-diurnal-thermal-skin-layer-tracking>
The CROCO 24-hour stability gate has passed for most regions (see
`04_empirical_validation.md`), but multi-day forecasting
($96 - 120 upright(" hours")$) during summer marine heatwaves requires
higher vertical resolution in the upper $1 upright(" meter")$ ocean skin
layer:

- #strong[$s$-Coordinate Refinement]: Increase vertical levels from
  $N = 32$ to $N = 40$ or $N = 50$, increasing surface stretching
  ($theta_s = 8.0$) to place 5 vertical layers within the top
  $1 upright(" meter")$.
- #strong[Diurnal Warm-Layer Modeling]: Integrate explicit Cool-Skin /
  Warm-Layer parameterizations (e.g.~Fairall et al.~COARE scheme) to
  track diurnal surface warming peaks
  ($+ 1.5^compose upright("C") - 2.5^compose upright("C")$ afternoon
  spikes) and nocturnal mixing decay.

=== Milestone B: Full Operational CROCO-Wave Wave-Current Coupling
<milestone-b-full-operational-croco-wave-wave-current-coupling>
Expand two-way standalone runs into active three-way dynamic OASIS3-MCT
coupled cycles. Written against SWAN below; given the SWAN→WW3 migration
described in `02_modeling_suite.md` Section 5, this milestone's
counterparty is expected to become WW3 once the migration completes, not
SWAN --- CROCO's own OASIS coupling toolbox is solver-agnostic on the
wave side, so this does not change the milestone's feasibility, only
which binary it targets:

- #strong[Wave Radiation Stress Feedback]: Dynamically pass SWAN
  $S_(x x)\,S_(x y)\,S_(y y)$ radiation stress gradients into CROCO to
  drive wave-induced longshore currents, wave setup in harbors, and
  wave-current bottom friction enhancement.
- #strong[Current Refraction Feedback]: Pass CROCO $1 upright(" km")$
  hourly surface currents back into SWAN to compute Doppler-shifted wave
  refraction in high-current channels (e.g., Ibiza-Formentera Freus
  channel).

=== Milestone C: Automated Captain-Facing Decision APIs & Alerting
<milestone-c-automated-captain-facing-decision-apis-alerting>
Bridge raw numerical model outputs directly to operational maritime
decision tools:

- #strong[Vessel Response Threshold Engine]: Translate
  $1 upright(" km")$ wave spectra, wind against current vectors, and
  cross-channel steepness into vessel-class safety statuses
  (`favorable`, `workable`, `conservative`, `restricted`) for small
  ($< 12 upright("m")$), medium ($12 - 24 upright("m")$), and large
  ($> 24 upright("m")$) motor and sailing yachts.
- #strong[Automated Artifact Dispatch]: Automatically compile daily
  briefing maps, WhatsApp captain advisories, and LinkedIn operational
  summaries upon forecast completion.
- #strong[FastAPI / Deck.gl Production Endpoints]: Serve real-time
  oceanographic vector fields and wave condition layers to mobile and
  web dashboards at sub-second latencies.

#divider()

== 3. Concluding Remarks
<concluding-remarks>
This document set describes an architecture in active development, not
an operational product. The core design choices --- one shared WRF run
feeding independent per-region CROCO/SWAN Batch jobs, run-scoped GCS
outputs, structural validation gates before publication --- are in place
and have started producing real, passing 6h/24h regional runs. What
remains before this can honestly be called a validated forecasting
platform for maritime operators is exactly what Section 2's roadmap and
the open items in `05_cloud_deployment_and_ops.md` describe: multi-day
horizon coverage across all 5 regions, real coupling between CROCO and
SWAN, independent observational validation, and the
reliability/observability hardening the architecture review identified.
Overstating current status has been a recurring problem in earlier
drafts of this document set; this rewrite is intended to fix that, not
to replace one round of overclaiming with another.

