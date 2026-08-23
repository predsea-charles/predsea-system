import json
import subprocess
import sys
from pathlib import Path
import xarray as xr
import numpy as np

print("Downloading croco_his.nc...")
subprocess.run([
    "gcloud", "storage", "cp",
    "gs://predsea-daily-outputs-test/predictions/2026-07-16/runs/2026-07-16T0000Z-croco-balearic-24h-gate8c-v5/balearic_1km/failure-diagnostics/croco_balearic_1km/croco_his.nc",
    "/tmp/croco_his.nc"
], check=True)

ds = xr.open_dataset("/tmp/croco_his.nc")
mask = ds["mask_rho"].values if "mask_rho" in ds else None

temp_surf = ds["temp"].isel(s_rho=-1).values

if mask is not None:
    # mask is 2D (eta, xi)
    ocean_temp = temp_surf[:, mask == 1]
    print("Masked Ocean SST min:", np.nanmin(ocean_temp), "max:", np.nanmax(ocean_temp), "mean:", np.nanmean(ocean_temp))
    land_temp = temp_surf[:, mask == 0]
    print("Land SST min:", np.nanmin(land_temp), "max:", np.nanmax(land_temp))
else:
    print("No mask_rho found")
