import xarray as xr
import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from matplotlib.colors import BoundaryNorm
from pathlib import Path


# ============================================================
# Configuration
# ============================================================

PATH = Path.home() / "predsea-data/2026-09-17/ww3.202609.nc"

TIME_INDEX = 2 

# Every N grid cells for wave-direction arrows.
# ~1 km grid, so 30 means approximately every 30 km.
QUIVER_STEP = 50

# Don't draw direction arrows where waves are essentially zero.
MIN_WAVE_HEIGHT_FOR_ARROWS = 0.01


# ============================================================
# Load
# ============================================================

ds = xr.open_dataset(PATH)

hs = ds["hs"].isel(time=TIME_INDEX)
direction = ds["dir"].isel(time=TIME_INDEX)

lon = ds.longitude.values
lat = ds.latitude.values

time = ds.time.isel(time=TIME_INDEX).values


# ============================================================
# Statistics
# ============================================================

valid_hs = hs.values[np.isfinite(hs.values)]

print("WW3 output")
print("==========")
print(f"Time:       {time}")
print(f"HS min:     {np.min(valid_hs):.3f} m")
print(f"HS median:  {np.median(valid_hs):.3f} m")
print(f"HS mean:    {np.mean(valid_hs):.3f} m")
print(f"HS max:     {np.max(valid_hs):.3f} m")


# ============================================================
# Color scale
# ============================================================

# Your maximum is ~1.26 m.
# Use a scale appropriate for THIS forecast rather than 0-6 m.

levels = np.arange(0.0, 1.31, 0.1)

cmap = plt.get_cmap("turbo")
norm = BoundaryNorm(levels, cmap.N, extend="max")


# ============================================================
# Figure
# ============================================================

fig = plt.figure(figsize=(15, 10))

ax = plt.axes(
    projection=ccrs.PlateCarree()
)

# Actual model domain
ax.set_extent(
    [
        float(lon.min()),
        float(lon.max()),
        float(lat.min()),
        float(lat.max()),
    ],
    crs=ccrs.PlateCarree(),
)


# ============================================================
# Wave-height contour field
# ============================================================

cf = ax.contourf(
    lon,
    lat,
    hs.values,
    levels=levels,
    cmap=cmap,
    norm=norm,
    extend="max",
    transform=ccrs.PlateCarree(),
)


# ============================================================
# Land / coastline
# ============================================================

ax.add_feature(
    cfeature.LAND,
    facecolor="lightgray",
    edgecolor="black",
    linewidth=0.7,
    zorder=5,
)

ax.coastlines(
    resolution="10m",
    linewidth=0.8,
    zorder=6,
)


# ============================================================
# Geographic grid
# ============================================================

gl = ax.gridlines(
    draw_labels=True,
    linewidth=0.5,
    linestyle="--",
    alpha=0.35,
    zorder=7,
)

gl.top_labels = False
gl.right_labels = False

gl.xlabel_style = {
    "size": 11,
}

gl.ylabel_style = {
    "size": 11,
}


# ============================================================
# Wave direction arrows
# ============================================================

# Downsample the 1-km grid.
lon_q = lon[::QUIVER_STEP]
lat_q = lat[::QUIVER_STEP]

dir_q = direction.values[::QUIVER_STEP, ::QUIVER_STEP]
hs_q = hs.values[::QUIVER_STEP, ::QUIVER_STEP]


# WW3 dir is wave FROM direction.
#
# Convert "coming FROM" direction into a vector pointing
# toward the direction of wave propagation.
#
# Direction convention:
#   0°   = from north
#   90°  = from east
#   180° = from south
#   270° = from west
#
# Therefore:
#
#   u = -sin(direction)
#   v = -cos(direction)

dir_rad = np.deg2rad(dir_q)

u = -np.sin(dir_rad)
v = -np.cos(dir_rad)


# Mask arrows where there is no useful wave field.
valid = (
    np.isfinite(hs_q)
    & np.isfinite(dir_q)
    & (hs_q >= MIN_WAVE_HEIGHT_FOR_ARROWS)
)

u = np.where(valid, u, np.nan)
v = np.where(valid, v, np.nan)


ax.quiver(
    lon_q,
    lat_q,
    u,
    v,
    transform=ccrs.PlateCarree(),

    # Arrow appearance
    color="black",
    scale=35,
    width=0.0022,
    headwidth=3.5,
    headlength=4.5,
    headaxislength=4,

    # Don't let arrows dominate the wave field
    pivot="middle",

    zorder=8,
)


# ============================================================
# Colorbar
# ============================================================

cbar = plt.colorbar(
    cf,
    ax=ax,
    pad=0.025,
    shrink=0.92,
    ticks=np.arange(0, 1.31, 0.1),
)

cbar.set_label(
    "Significant wave height (m)",
    fontsize=13,
)


# ============================================================
# Title
# ============================================================

time_str = np.datetime_as_string(time, unit="m")

ax.set_title(
    "PredSea Western Mediterranean Wave Conditions\n"
    f"WW3 1 km forecast | {time_str} UTC",
    fontsize=20,
    pad=15,
)


# ============================================================
# Save
# ============================================================

output = (
    f"ww3_wave_height_{np.datetime_as_string(time, unit='h')}"
    ".png"
)

plt.savefig(
    output,
    dpi=180,
    bbox_inches="tight",
)

print(f"\nSaved: {output}")

plt.show()
