import json
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from pathlib import Path

def plot_observations_map():
    json_path = "/Users/charles.santana/PredSea/predsea-system/humanintheloop/extracted_observations.json"
    print(f"Reading observations from {json_path}...")
    
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    total_records = len(data)
    print(f"Loaded {total_records} records.")
    
    # Extract unique locations
    unique_locations = {}
    for obs in data:
        lat = float(obs['lat'])
        lon = float(obs['lon'])
        key = (lat, lon)
        if key not in unique_locations:
            unique_locations[key] = set()
        unique_locations[key].add(obs['variable'])
    
    print(f"Found {len(unique_locations)} unique maritime observation locations.")
    
    # Setup plot - PredSea standard 1440p-ish aspect
    fig = plt.figure(figsize=(16, 9), dpi=200)
    ax = plt.axes(projection=ccrs.Mercator())
    
    # Set extent for the Western Med (adjusted to fit all observations)
    lats = [loc[0] for loc in unique_locations.keys()]
    lons = [loc[1] for loc in unique_locations.keys()]
    
    if lats and lons:
        ax.set_extent([min(lons) - 2.0, max(lons) + 2.0, min(lats) - 2.0, max(lats) + 2.0], crs=ccrs.PlateCarree())
    else:
        ax.set_extent([-5.0, 20.0, 30.0, 50.0], crs=ccrs.PlateCarree())
    
    # PredSea Official Style Colors (Vintage Maritime)
    LAND_COLOR = "#ded1a9"
    WATER_COLOR = "#d3e2dc"
    COASTLINE_COLOR = "#3a3226"
    GRID_COLOR = "#b3a67d"
    TEXT_COLOR = "#2f2a20"
    
    # Add features
    ax.add_feature(cfeature.LAND.with_scale("10m"), facecolor=LAND_COLOR, edgecolor='none')
    ax.add_feature(cfeature.OCEAN.with_scale("10m"), facecolor=WATER_COLOR)
    ax.add_feature(cfeature.COASTLINE.with_scale("10m"), edgecolor=COASTLINE_COLOR, linewidth=1.2)
    ax.add_feature(cfeature.BORDERS.with_scale("10m"), edgecolor=COASTLINE_COLOR, linewidth=0.5, linestyle=':')
    
    # Gridlines
    gl = ax.gridlines(draw_labels=True, dms=True, x_inline=False, y_inline=False, 
                      linestyle="--", color=GRID_COLOR, linewidth=0.5, alpha=0.6)
    gl.top_labels = False
    gl.right_labels = False
    gl.xlabel_style = {"size": 10, "color": "#6b573b"}
    gl.ylabel_style = {"size": 10, "color": "#6b573b"}

    # Plot points
    lats_list = [loc[0] for loc in unique_locations.keys()]
    lons_list = [loc[1] for loc in unique_locations.keys()]
    
    ax.scatter(lons_list, lats_list, 
               color="#be123c", s=15, 
               marker="o", label="Observation Station",
               transform=ccrs.PlateCarree(), alpha=0.7, 
               edgecolors='white', linewidth=0.3, zorder=10)
    
    # Header and Titles
    plt.text(0.5, 1.08, "PREDSEA HISTORICAL OBSERVATION NETWORK", 
             transform=ax.transAxes, color=TEXT_COLOR, fontsize=22, 
             weight="bold", ha="center")
    plt.text(0.5, 1.03, f"Spatial Coverage of {len(unique_locations)} Active Stations | Data since 2026-06-20", 
             transform=ax.transAxes, color="#6b573b", fontsize=14, ha="center")
    
    # Stats Box
    stats_text = (
        "NETWORK SUMMARY\n"
        f"• Total Stations: {len(unique_locations)}\n"
        f"• Total Data Points: {total_records:,}\n"
        f"• Time Range: 2026-06-20 to Present\n"
        "• Regions: Western Mediterranean & Atlantic Coast"
    )
    ax.text(0.98, 0.05, stats_text, transform=ax.transAxes, 
            color=TEXT_COLOR, fontsize=10, ha="right", va="bottom",
            bbox=dict(boxstyle="round,pad=0.8", facecolor="white", edgecolor=GRID_COLOR, alpha=0.9))
    
    # Save high-res map
    output_path = "/Users/charles.santana/.gemini/antigravity/brain/751e399c-28be-4432-8f2e-0c0ff03d0348/historical_observations_map.png"
    plt.savefig(output_path, facecolor='white', bbox_inches='tight', dpi=250)
    plt.close()
    print(f"Map saved to {output_path}")

if __name__ == "__main__":
    plot_observations_map()
