#!/usr/bin/env python3
"""
Western Mediterranean Coverage Map Generator
Uses Cartopy & Matplotlib to draw active model domains and core places.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.append("/Users/charles.santana/PredSea/predsea-system/humanintheloop")

try:
    import numpy as np
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
except ImportError as e:
    print(f"Error: Required libraries missing: {e}", file=sys.stderr)
    sys.exit(1)

# Bounding Boxes
BALEARIC_BBOX = {
    "south": 38.0,
    "north": 41.5,
    "west": 0.5,
    "east": 4.5,
}

WESTMED_BBOX = {
    "south": 35.0,
    "north": 44.5,
    "west": -1.0,
    "east": 16.5,
}

# Core Places
PLACES = [
    {"name": "Palma de Mallorca", "lat": 39.52, "lon": 2.58, "color": "#0f172a"},
    {"name": "Ibiza", "lat": 38.92, "lon": 1.49, "color": "#0f172a"},
    {"name": "Alcudia", "lat": 39.84, "lon": 3.14, "color": "#0f172a"},
    {"name": "Marseille", "lat": 43.30, "lon": 5.37, "color": "#475569"},
    {"name": "Toulon", "lat": 43.12, "lon": 5.93, "color": "#475569"},
    {"name": "Cagliari", "lat": 39.21, "lon": 9.11, "color": "#475569"},
    {"name": "Barcelona", "lat": 41.32, "lon": 2.22, "color": "#475569"},
    {"name": "Naples", "lat": 40.84, "lon": 14.25, "color": "#0e7490"},
    {"name": "Palermo", "lat": 38.12, "lon": 13.36, "color": "#475569"},
    {"name": "Messina", "lat": 38.19, "lon": 15.55, "color": "#475569"},
]

def generate_map(output_path):
    plt.rcParams["font.sans-serif"] = ["Helvetica Neue", "Arial", "sans-serif"]
    plt.rcParams["font.family"] = "sans-serif"

    # Setup PlateCarree figure and axis
    fig, ax = plt.subplots(figsize=(12, 9), dpi=250, subplot_kw={"projection": ccrs.PlateCarree()})
    fig.patch.set_facecolor("#f8fafc")  # Slate 50 background
    
    # Set map bounds with a bit of breathing room
    ax.set_extent([-2.5, 18.0, 33.5, 46.0], crs=ccrs.PlateCarree())

    # Add GIS Features (using 50m detailed scale for Western Europe)
    print("Loading Cartopy map features...", flush=True)
    ax.add_feature(cfeature.LAND.with_scale("50m"), facecolor="#f1f5f9", edgecolor="none")
    ax.add_feature(cfeature.OCEAN.with_scale("50m"), facecolor="#f0f9ff", edgecolor="none")  # Light blue ocean
    ax.add_feature(cfeature.COASTLINE.with_scale("50m"), edgecolor="#475569", linewidth=0.85, zorder=2)
    ax.add_feature(cfeature.BORDERS.with_scale("50m"), edgecolor="#94a3b8", linestyle=":", linewidth=0.6, zorder=2)
    
    # Draw Gridlines
    gl = ax.gridlines(draw_labels=True, dms=True, x_inline=False, y_inline=False, linestyle="--", color="#cbd5e1", linewidth=0.5, zorder=1)
    gl.top_labels = False
    gl.right_labels = False
    gl.xlabel_style = {"size": 8, "color": "#64748b"}
    gl.ylabel_style = {"size": 8, "color": "#64748b"}

    # --- Draw Bounding Boxes ---
    
    # 1. Extended Western Mediterranean Area
    w_min, w_max = WESTMED_BBOX["west"], WESTMED_BBOX["east"]
    s_min, s_max = WESTMED_BBOX["south"], WESTMED_BBOX["north"]
    westmed_width = w_max - w_min
    westmed_height = s_max - s_min
    
    rect_westmed = patches.Rectangle(
        (w_min, s_min), westmed_width, westmed_height,
        linewidth=2.5, edgecolor="#0e7490", facecolor="#22d3ee", alpha=0.08,
        transform=ccrs.PlateCarree(), zorder=3, label="WESTMED_BBOX (Extended Domain)"
    )
    ax.add_patch(rect_westmed)
    
    # Add border dashed line to emphasize
    ax.plot(
        [w_min, w_max, w_max, w_min, w_min],
        [s_min, s_min, s_max, s_max, s_min],
        color="#0e7490", linestyle="-", linewidth=2.0, transform=ccrs.PlateCarree(), zorder=3
    )
    
    # Label for Extended box
    ax.text(
        w_min + 0.3, s_max - 0.4, "WESTMED_BBOX\nExtended Atmospheric & Wave Domain",
        color="#0e7490", fontsize=9.5, weight="bold", transform=ccrs.PlateCarree(), zorder=4,
        bbox=dict(boxstyle="square,pad=0.3", facecolor="#ffffff", edgecolor="#0e7490", linewidth=1, alpha=0.9)
    )

    # 2. Core Balearic Box
    b_min, b_max = BALEARIC_BBOX["west"], BALEARIC_BBOX["east"]
    sb_min, b_height = BALEARIC_BBOX["south"], BALEARIC_BBOX["north"] - BALEARIC_BBOX["south"]
    balearic_width = b_max - b_min
    
    rect_balearic = patches.Rectangle(
        (b_min, sb_min), balearic_width, b_height,
        linewidth=2.5, edgecolor="#b45309", facecolor="#fbbf24", alpha=0.15,
        transform=ccrs.PlateCarree(), zorder=3, label="BALEARIC_BBOX (Core Domain)"
    )
    ax.add_patch(rect_balearic)
    
    # Add border dashed line to emphasize
    ax.plot(
        [b_min, b_max, b_max, b_min, b_min],
        [sb_min, sb_min, BALEARIC_BBOX["north"], BALEARIC_BBOX["north"], sb_min],
        color="#b45309", linestyle="-", linewidth=2.0, transform=ccrs.PlateCarree(), zorder=3
    )
    
    # Label for Core box
    ax.text(
        b_min + 0.2, sb_min + 0.2, "BALEARIC_BBOX\nCore High-Res Model",
        color="#b45309", fontsize=9, weight="bold", transform=ccrs.PlateCarree(), zorder=4,
        bbox=dict(boxstyle="square,pad=0.3", facecolor="#ffffff", edgecolor="#b45309", linewidth=1, alpha=0.9)
    )

    # --- Plot Core Places ---
    print("Plotting places and ports...", flush=True)
    for p in PLACES:
        # Plot marker
        ax.plot(
            p["lon"], p["lat"], marker="o", color=p["color"],
            markeredgecolor="#ffffff", markeredgewidth=1.5, markersize=7.5,
            transform=ccrs.PlateCarree(), zorder=5
        )
        # Add label
        ax.text(
            p["lon"] + 0.15, p["lat"] - 0.05, p["name"],
            color="#0f172a", fontsize=8.5, weight="bold",
            transform=ccrs.PlateCarree(), zorder=5,
            bbox=dict(boxstyle="round,pad=0.2", facecolor="#ffffff", edgecolor="none", alpha=0.75)
        )

    # Header and Titles
    plt.text(
        0.02, 0.95, "PREDSEA GEOGRAPHICAL COVERAGE",
        transform=ax.transAxes, color="#0f172a", fontsize=16, weight="bold",
        va="top", ha="left"
    )
    subtitle = "Active Oceanographic Routing & Weather Modeling Domains | Western Mediterranean"
    plt.text(
        0.02, 0.91, subtitle,
        transform=ax.transAxes, color="#64748b", fontsize=9.5,
        va="top", ha="left"
    )

    # Legend / Info Box on bottom-left
    legend_text = (
        "DOMAIN METADATA\n\n"
        "BALEARIC_BBOX (Core):\n"
        f" • Lon: [{BALEARIC_BBOX['west']}°E, {BALEARIC_BBOX['east']}°E]\n"
        f" • Lat: [{BALEARIC_BBOX['south']}°N, {BALEARIC_BBOX['north']}°N]\n\n"
        "WESTMED_BBOX (Extended):\n"
        f" • Lon: [{WESTMED_BBOX['west']}°W, {WESTMED_BBOX['east']}°E]\n"
        f" • Lat: [{WESTMED_BBOX['south']}°N, {WESTMED_BBOX['north']}°N]\n\n"
        "REPRESENTATIVE GRID RESOLUTION:\n"
        " • Copernicus Wave/Current Grid: ~4.2 km (1/24°)\n"
        " • High-Resolution AROME Winds: ~1.3 km (0.01°)"
    )
    
    ax.text(
        0.02, 0.03, legend_text,
        transform=ax.transAxes, color="#334155", fontsize=8.5,
        va="bottom", ha="left",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#ffffff", edgecolor="#cbd5e1", linewidth=1, alpha=0.95)
    )

    # Save high-res map
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=250, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    print(f"Successfully saved premium geographical map to: {output_path}")


if __name__ == "__main__":
    out_img = "/Users/charles.santana/.gemini/antigravity/brain/6c302f3b-86b0-4691-83ca-2206aef6fa23/mediterranean_coverage_map.png"
    generate_map(out_img)
