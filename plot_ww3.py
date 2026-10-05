import xarray as xr
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from pathlib import Path

PATH = Path.home() / "predsea-data/2026-09-17/ww3.202609.nc"

# Open WW3 output
ds = xr.open_dataset(PATH)

print(ds)

print("\nForecast times:")
for i, t in enumerate(ds.time.values):
    print(f"  {i}: {t}")

# Coordinates
lon = ds.longitude
lat = ds.latitude

# Significant wave height at first timestep
hs = ds.hs.isel(time=0)

print("\nWave-height statistics:")
print(f"  min:  {float(hs.min()):.2f} m")
print(f"  max:  {float(hs.max()):.2f} m")
print(f"  mean: {float(hs.mean()):.2f} m")

# ------------------------------------------------------------------
# Plot
# ------------------------------------------------------------------

fig = plt.figure(figsize=(13, 8))

ax = plt.axes(
    projection=ccrs.PlateCarree()
)

# Plot wave height
hs.plot(
    ax=ax,
    transform=ccrs.PlateCarree(),
    cmap="viridis",
    vmin=0,
    vmax=6,
    cbar_kwargs={
        "label": "Significant Wave Height (m)"
    },
)

# Coastline
ax.coastlines(
    resolution="10m",
    linewidth=0.8,
)

# Land
ax.add_feature(
    cfeature.LAND,
    facecolor="lightgray",
    edgecolor="black",
    linewidth=0.4,
)

# Use actual dataset extent
ax.set_extent(
    [
        float(lon.min()),
        float(lon.max()),
        float(lat.min()),
        float(lat.max()),
    ],
    crs=ccrs.PlateCarree(),
)

# DON'T use ax.gridlines() for now.
# Your Cartopy/Shapely installation is failing there.

# Add simple longitude/latitude ticks instead
ax.set_xticks([-5, 0, 5, 10, 15], crs=ccrs.PlateCarree())
ax.set_yticks([35, 37.5, 40, 42.5, 45], crs=ccrs.PlateCarree())

ax.set_xlabel("Longitude")
ax.set_ylabel("Latitude")

# Time
time = ds.time.isel(time=0).values

ax.set_title(
    "WW3 Significant Wave Height\n"
    f"Western Mediterranean — {time}"
)

plt.tight_layout()

output = "ww3_wave_height_2026-09-16T0000.png"

plt.savefig(
    output,
    dpi=150,
    bbox_inches="tight",
)

print(f"\nSaved: {output}")

plt.show()
