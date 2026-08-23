#!/usr/bin/env python3
"""
PredSea White Paper Typst Master Compiler (v5)
Converts modular Markdown white paper files into a publication-grade, investor-ready PDF via Typst.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

WHITEpaper_DIR = Path("/Users/charles.santana/PredSea/predsea-system/docs/whitepaper")

MD_FILES = [
    "README.md",
    "01_system_architecture.md",
    "02_modeling_suite.md",
    "03_thermodynamics_and_fluxes.md",
    "04_empirical_validation.md",
    "05_cloud_deployment_and_ops.md",
    "06_conclusion_and_roadmap.md",
]

TYPST_PREAMBLE = r"""// PredSea White Paper Typst Setup & Custom Styling (Publication Grade v5)

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
"""


def replace_code_block_containing(text, keyword, replacement):
    pattern = (
        r"```[a-zA-Z]*\n(?:(?!```)[\s\S])*?"
        + re.escape(keyword)
        + r"(?:(?!```)[\s\S])*\n```"
    )
    return re.sub(pattern, replacement, text)


def process_md_file(filename):
    filepath = WHITEpaper_DIR / filename
    if not filepath.exists():
        return ""

    res = subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "typst", str(filepath)],
        capture_output=True,
        text=True,
        check=True,
    )

    content = res.stdout

    if filename == "README.md":
        content = replace_code_block_containing(
            content, "PredSea Platform", "#platform_architecture_diagram()"
        )

    elif filename == "01_system_architecture.md":
        content = replace_code_block_containing(
            content, "flowchart TD", "#system_pipeline_diagram()"
        )

    elif filename == "02_modeling_suite.md":
        content = replace_code_block_containing(
            content, "PredSea Modeling Suite", "#platform_architecture_diagram()"
        )
        content = replace_code_block_containing(content, "flowchart TD", "")

    elif filename == "03_thermodynamics_and_fluxes.md":
        content = replace_code_block_containing(
            content, "Surface Heat Flux", "#heat_flux_diagram()"
        )
        content = replace_code_block_containing(
            content, "Atmosphere", "#heat_flux_diagram()"
        )

    elif filename == "04_empirical_validation.md":
        content = replace_code_block_containing(
            content, "Mallorca Island", "#dragonera_diagram()"
        )

    elif filename == "05_cloud_deployment_and_ops.md":
        content = replace_code_block_containing(
            content, "flowchart TD", "#cloud_deployment_diagram()"
        )

    return content


def build_master_typst():
    master_typ = TYPST_PREAMBLE

    for filename in MD_FILES:
        typ_content = process_md_file(filename)
        master_typ += f"\n// --- FILE: {filename} ---\n\n" + typ_content + "\n"

    master_path = WHITEpaper_DIR / "PredSea_White_Paper_v5.typ"
    with open(master_path, "w", encoding="utf-8") as f:
        f.write(master_typ)

    print(f"Generated {master_path}")

    # Compile with typst
    out_pdf = WHITEpaper_DIR / "PredSea_White_Paper_v5.pdf"
    res = subprocess.run(
        ["typst", "compile", str(master_path), str(out_pdf)],
        capture_output=True,
        text=True,
    )

    print(f"Typst compilation exit code: {res.returncode}")
    if res.stdout:
        print(f"Stdout:\n{res.stdout}")
    if res.stderr:
        print(f"Stderr:\n{res.stderr}")

    if res.returncode == 0:
        target_pdf = WHITEpaper_DIR / "PredSea_White_Paper.pdf"
        shutil.copy(out_pdf, target_pdf)
        print(
            f"Successfully compiled {out_pdf} and copied to {target_pdf} (Publication Grade v5)"
        )


if __name__ == "__main__":
    build_master_typst()
