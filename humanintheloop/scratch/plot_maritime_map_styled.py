import sys
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from pathlib import Path
import matplotlib.patches as patches

# Add project root to path
sys.path.append("/Users/charles.santana/PredSea/predsea-system/humanintheloop")
import place_registry

def plot_maritime_destinations_styled():
    # Load all places from the registry (Seeds + OSM)
    place_ids = place_registry.available_place_ids()
    places = []
    for pid in place_ids:
        defn = place_registry.place_definition(pid)
        if defn:
            defn["place_id"] = pid
            places.append(defn)
    
    total_count = len(places)
    print(f"Loaded {total_count} places from registry.")
    
    # Setup plot - PredSea standard 1440p-ish aspect
    fig = plt.figure(figsize=(16, 9), dpi=200)
    ax = plt.axes(projection=ccrs.Mercator())
    
    # Set extent with some padding for the Western Med
    ax.set_extent([-2.0, 17.5, 34.5, 46.0], crs=ccrs.PlateCarree())
    
    # PredSea Official Style Colors
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

    # Category styling
    category_styles = {
        "marina": {"color": "#1e40af", "label": "Marina", "marker": "o", "size": 8},
        "anchorage": {"color": "#15803d", "label": "Anchorage", "marker": "s", "size": 7},
        "harbour": {"color": "#b45309", "label": "Harbour", "marker": "D", "size": 7},
        "ferry_terminal": {"color": "#be123c", "label": "Ferry Terminal", "marker": "^", "size": 9},
        "commercial_port": {"color": "#7e22ce", "label": "Commercial Port", "marker": "H", "size": 10},
        "town": {"color": "#475569", "label": "Port Town", "marker": "p", "size": 8},
        "place": {"color": "#475569", "label": "Other", "marker": "o", "size": 5}
    }
    
    # Group by category
    by_category = {}
    for p in places:
        cat = p.get("kind") or p.get("type") or "place"
        if cat not in by_category:
            by_category[cat] = {"lats": [], "lons": []}
        by_category[cat]["lats"].append(p["latitude"])
        by_category[cat]["lons"].append(p["longitude"])
        
    # Plot points with high-quality markers
    for cat, coords in by_category.items():
        style = category_styles.get(cat, category_styles["place"])
        label = style.get("label", cat.replace("_", " ").title())
        ax.scatter(coords["lons"], coords["lats"], 
                   color=style["color"], s=style["size"], 
                   marker=style["marker"], label=label,
                   transform=ccrs.PlateCarree(), alpha=0.85, 
                   edgecolors='white', linewidth=0.4, zorder=10)
    
    # Header and Titles (PredSea Style)
    plt.text(0.5, 1.08, "PREDSEA MARITIME DESTINATION NETWORK", 
             transform=ax.transAxes, color=TEXT_COLOR, fontsize=22, 
             weight="bold", ha="center")
    plt.text(0.5, 1.03, "Complete Registry Coverage | Primary Seeds + OSM Destinations", 
             transform=ax.transAxes, color="#6b573b", fontsize=14, ha="center")
    
    # Legend
    legend = plt.legend(loc='lower left', frameon=True, facecolor='white', 
                        edgecolor=GRID_COLOR, fontsize=11, title="DESTINATION TYPE",
                        bbox_to_anchor=(0.02, 0.05), title_fontsize=12)
    legend.get_frame().set_alpha(0.9)
    legend.get_frame().set_boxstyle("round,pad=0.5")
    plt.setp(legend.get_title(), fontweight='bold', color=TEXT_COLOR)
    
    # Stats Box (Bottom Right)
    stats_text = (
        "NETWORK SUMMARY\n"
        f"• Total Places: {total_count}\n"
        f"• Registry: Balearic Seeds + Western Med OSM\n"
        "• Optimization: Paginated & Vectorized\n"
        "• Coverage: Western Mediterranean"
    )
    ax.text(0.98, 0.05, stats_text, transform=ax.transAxes, 
            color=TEXT_COLOR, fontsize=10, ha="right", va="bottom",
            bbox=dict(boxstyle="round,pad=0.8", facecolor="white", edgecolor=GRID_COLOR, alpha=0.9))
    
    # Save high-res map
    output_path = "/Users/charles.santana/.gemini/antigravity/brain/751e399c-28be-4432-8f2e-0c0ff03d0348/maritime_network_styled_complete.png"
    plt.savefig(output_path, facecolor='white', bbox_inches='tight', dpi=250)
    plt.close()
    print(f"Complete styled map saved to {output_path}")

if __name__ == "__main__":
    plot_maritime_destinations_styled()
