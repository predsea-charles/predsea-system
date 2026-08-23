import json
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from pathlib import Path

def plot_maritime_destinations():
    # Load data
    data_path = Path("humanintheloop/osm_maritime_destinations.json")
    with open(data_path, "r") as f:
        data = json.load(f)
    
    places = data["places"]
    bbox = data["bbox"]
    
    # Setup plot
    plt.figure(figsize=(15, 10), dpi=150)
    ax = plt.axes(projection=ccrs.Mercator())
    
    # Set extent (W, E, S, N)
    ax.set_extent([bbox["west"], bbox["east"], bbox["south"], bbox["north"]], crs=ccrs.PlateCarree())
    
    # Add features for a "beautiful" look
    ax.add_feature(cfeature.LAND, facecolor='#2c3e50', edgecolor='none')
    ax.add_feature(cfeature.OCEAN, facecolor='#1a1a1a')
    ax.add_feature(cfeature.COASTLINE, edgecolor='#444444', linewidth=0.5)
    ax.add_feature(cfeature.BORDERS, edgecolor='#444444', linewidth=0.3, linestyle=':')
    
    # Category colors
    category_colors = {
        "marina": "#3498db",          # Blue
        "anchorage": "#2ecc71",       # Green
        "harbour": "#f1c40f",         # Yellow
        "ferry_terminal": "#e67e22",  # Orange
        "commercial_port": "#e74c3c"  # Red
    }
    
    # Group by category for cleaner legend
    by_category = {}
    for p in places:
        cat = p["category"]
        if cat not in by_category:
            by_category[cat] = {"lats": [], "lons": []}
        by_category[cat]["lats"].append(p["latitude"])
        by_category[cat]["lons"].append(p["longitude"])
        
    # Plot points
    for cat, coords in by_category.items():
        color = category_colors.get(cat, "#95a5a6")
        ax.scatter(coords["lons"], coords["lats"], 
                   color=color, s=5, label=cat.replace("_", " ").title(),
                   transform=ccrs.PlateCarree(), alpha=0.7, edgecolors='none')
    
    # Styling
    plt.title("PredSea Maritime Network - Western Mediterranean", 
              color='white', fontsize=18, pad=20, fontweight='bold')
    
    legend = plt.legend(loc='lower right', frameon=True, facecolor='#1a1a1a', 
                        edgecolor='#444444', fontsize=12)
    for text in legend.get_texts():
        text.set_color("white")
        
    plt.text(0.5, 0.02, f"Total Integrated Destinations: {data['count']}", 
             color='white', ha='center', transform=ax.transAxes, fontsize=10)
    
    # Dark mode background
    plt.gcf().set_facecolor('#121212')
    
    output_path = "/Users/charles.santana/.gemini/antigravity/brain/751e399c-28be-4432-8f2e-0c0ff03d0348/maritime_destinations_map.png"
    plt.savefig(output_path, facecolor='#121212', bbox_inches='tight')
    print(f"Map saved to {output_path}")

if __name__ == "__main__":
    plot_maritime_destinations()
