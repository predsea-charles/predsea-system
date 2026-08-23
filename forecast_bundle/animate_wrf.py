import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.animation as animation
from matplotlib.path import Path  # <-- ADDED THIS IMPORT
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

# 1. Load the dataset
ds = xr.open_dataset("predsea_atmosphere.nc")

# 2. Extract coordinates and variables
times = [
    t.decode("utf-8") if isinstance(t, bytes) else str(t)
    for t in ds["Times"].values
]

lats = ds["XLAT"].isel(Time=0).values  # 2D array
lons = ds["XLONG"].isel(Time=0).values  # 2D array

t2_celsius = ds["T2"].values - 273.15
u10 = ds["U10"].values
v10 = ds["V10"].values
wind_speed = np.sqrt(u10**2 + v10**2)

# 3. Setup Cartopy Projection
proj = ccrs.LambertConformal(
    central_longitude=float(ds.attrs["STAND_LON"]),
    central_latitude=float(ds.attrs["CEN_LAT"]),
    standard_parallels=(
        float(ds.attrs["TRUELAT1"]),
        float(ds.attrs["TRUELAT2"]),
    ),
)

# 4. Initialize Plot
fig, ax = plt.subplots(
    figsize=(10, 8), subplot_kw={"projection": proj}, dpi=150
)

# Clip boundary strictly to the grid perimeter
boundary_lons = np.concatenate([lons[0, :], lons[:, -1], lons[-1, ::-1], lons[::-1, 0]])
boundary_lats = np.concatenate([lats[0, :], lats[:, -1], lats[-1, ::-1], lats[::-1, 0]])

ax.set_boundary(
    Path(np.column_stack([boundary_lons, boundary_lats])),
    transform=ccrs.PlateCarree(),
)



# Add geographic features
ax.add_feature(
    cfeature.COASTLINE.with_scale("10m"), linewidth=0.8, edgecolor="black"
)
ax.add_feature(
    cfeature.BORDERS.with_scale("10m"),
    linestyle=":",
    linewidth=0.5,
    edgecolor="black",
)
ax.add_feature(cfeature.LAND, facecolor="#f0f0f0", zorder=0)
ax.add_feature(cfeature.OCEAN, facecolor="#e0f3f8", zorder=0)

# Set up temperature color limits across the whole timeframe
vmin, vmax = np.min(t2_celsius), np.max(t2_celsius)

# Initial frame plot (pcolormesh with PlateCarree coordinate transform)
mesh = ax.pcolormesh(
    lons,
    lats,
    t2_celsius[0],
    transform=ccrs.PlateCarree(),
    cmap="turbo",
    vmin=vmin,
    vmax=vmax,
    shading="auto",
    alpha=0.85,
)

# Add Colorbar
cbar = fig.colorbar(mesh, ax=ax, orientation="horizontal", pad=0.04, shrink=0.7)
cbar.set_label("2m Temperature (°C)", fontsize=11, fontweight="bold")

# Title setup
title_text = ax.set_title(
    f"WRF Forecast - {times[0]}", fontsize=12, fontweight="bold", loc="left"
)

# Subsample wind vectors for clarity (quiver)
step = 8  # Skip every 8 grid points
q = ax.quiver(
    lons[::step, ::step],
    lats[::step, ::step],
    u10[0, ::step, ::step],
    v10[0, ::step, ::step],
    transform=ccrs.PlateCarree(),
    scale=300,
    color="k",
    width=0.002,
)


# 5. Animation Update Function
def update(frame):
    # Update temperature map
    mesh.set_array(t2_celsius[frame].ravel())

    # Update wind vectors
    q.set_UVC(u10[frame, ::step, ::step], v10[frame, ::step, ::step])

    # Update timestamp
    time_str = times[frame].replace("_", " ")
    title_text.set_text(f"Western Med WRF | Time: {time_str}")

    return mesh, q, title_text


# 6. Create & Save Animation
anim = animation.FuncAnimation(
    fig, update, frames=len(times), interval=200, blit=False
)

# Save as MP4 video (requires ffmpeg)
anim.save("wrf_forecast_animation.mp4", writer="ffmpeg", fps=5, dpi=150)

# Alternatively, save as GIF:
# anim.save("wrf_forecast_animation.gif", writer="pillow", fps=5)

plt.close()
print("Animation successfully generated!")
