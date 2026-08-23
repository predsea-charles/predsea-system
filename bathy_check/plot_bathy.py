import xarray as xr
import numpy as np
import matplotlib.pyplot as plt

REGIONS = ["alboran_1km", "gulf_of_lion_1km", "algerian_1km", "balearic"]

# First pass: load everything and find the shared depth range across all 4
# regions (ignoring land/NaN cells) so every subplot uses the same color scale.
loaded = {}
global_min, global_max = np.inf, -np.inf
for region in REGIONS:
    ds = xr.open_dataset(f"{region}_bathymetry_swan.nc")
    depth = ds["depth"].transpose("latitude", "longitude").values
    lat = ds["latitude"].values
    lon = ds["longitude"].values
    wet = depth > 0.0
    depth_masked = np.where(wet, depth, np.nan)
    loaded[region] = (depth_masked, lat, lon)
    global_min = min(global_min, np.nanmin(depth_masked))
    global_max = max(global_max, np.nanmax(depth_masked))

print(f"Shared depth scale: {global_min:.1f} to {global_max:.1f} m")

# Second pass: plot with the shared vmin/vmax.
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
axes = axes.flatten()
im = None
for ax, region in zip(axes, REGIONS):
    depth_masked, lat, lon = loaded[region]
    im = ax.imshow(depth_masked, origin="lower",
                    extent=[lon.min(), lon.max(), lat.min(), lat.max()],
                    cmap="viridis", aspect="auto", vmin=global_min, vmax=global_max)
    ax.set_title(region)
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")

fig.suptitle("Bathymetry depth (land masked, shared color scale)")
fig.colorbar(im, ax=axes.tolist(), label="depth (m)", shrink=0.8)
fig.savefig("4region_depth_comparison.png", dpi=150)
print("Saved 4region_depth_comparison.png")
plt.show()
