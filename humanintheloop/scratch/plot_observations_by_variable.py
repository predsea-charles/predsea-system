import json
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from pathlib import Path
import os

def plot_observations_by_variable():
    json_path = "/Users/charles.santana/PredSea/predsea-system/humanintheloop/extracted_observations.json"
    output_dir = "/Users/charles.santana/.gemini/antigravity/brain/751e399c-28be-4432-8f2e-0c0ff03d0348"
    
    print(f"Reading observations from {json_path}...")
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    # Group data by variable
    by_variable = {}
    for obs in data:
        var = obs['variable']
        if var not in by_variable:
            by_variable[var] = {}
        
        lat = float(obs['lat'])
        lon = float(obs['lon'])
        key = (lat, lon)
        by_variable[var][key] = True

    variables = sorted(by_variable.keys())
    print(f"Found variables: {variables}")

    # PredSea Official Style Colors (Vintage Maritime)
    LAND_COLOR = "#ded1a9"
    WATER_COLOR = "#d3e2dc"
    COASTLINE_COLOR = "#3a3226"
    GRID_COLOR = "#b3a67d"
    TEXT_COLOR = "#2f2a20"
    STATION_COLOR = "#be123c"

    for var in variables:
        print(f"Plotting map for {var}...")
        
        unique_locations = by_variable[var]
        lats_list = [loc[0] for loc in unique_locations.keys()]
        lons_list = [loc[1] for loc in unique_locations.keys()]

        # Setup plot
        fig = plt.figure(figsize=(16, 9), dpi=200)
        ax = plt.axes(projection=ccrs.Mercator())
        
        # Set extent based on these specific points
        if lats_list and lons_list:
            ax.set_extent([min(lons_list) - 2.0, max(lons_list) + 2.0, min(lats_list) - 2.0, max(lats_list) + 2.0], crs=ccrs.PlateCarree())
        else:
            ax.set_extent([-5.0, 20.0, 34.0, 46.0], crs=ccrs.PlateCarree())
        
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
        ax.scatter(lons_list, lats_list, 
                   color=STATION_COLOR, s=20, 
                   marker="o", label=f"{var.replace('_', ' ').title()} Station",
                   transform=ccrs.PlateCarree(), alpha=0.8, 
                   edgecolors='white', linewidth=0.4, zorder=10)
        
        # Header and Titles
        plt.text(0.5, 1.08, f"PREDSEA OBSERVATION NETWORK: {var.upper().replace('_', ' ')}", 
                 transform=ax.transAxes, color=TEXT_COLOR, fontsize=20, 
                 weight="bold", ha="center")
        plt.text(0.5, 1.03, f"Spatial distribution of {len(unique_locations)} active stations", 
                 transform=ax.transAxes, color="#6b573b", fontsize=14, ha="center")
        
        # Stats Box
        stats_text = (
            f"VARIABLE: {var.replace('_', ' ').title()}\n"
            f"• Active Stations: {len(unique_locations)}\n"
            "• Coverage: Western Mediterranean\n"
            "• Data Source: PredSea Validation Engine"
        )
        ax.text(0.98, 0.05, stats_text, transform=ax.transAxes, 
                color=TEXT_COLOR, fontsize=10, ha="right", va="bottom",
                bbox=dict(boxstyle="round,pad=0.8", facecolor="white", edgecolor=GRID_COLOR, alpha=0.9))
        
        # Save high-res map
        filename = f"obs_map_{var}.png"
        output_path = os.path.join(output_dir, filename)
        plt.savefig(output_path, facecolor='white', bbox_inches='tight', dpi=250)
        plt.close()
        print(f"Map for {var} saved to {output_path}")

if __name__ == "__main__":
    plot_observations_by_variable()
