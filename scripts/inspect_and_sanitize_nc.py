import os
import glob
import xarray as xr
import numpy as np

# Directory containing downloaded croco_his_*.nc files
DATA_DIR = "./nc_outputs"

def analyze_and_clean_netcdf(file_path):
    print(f"\n==================================================")
    print(f" Inspecting: {os.path.basename(file_path)}")
    print(f"==================================================")
    
    ds = xr.open_dataset(file_path)
    
    # Check variables for NaNs across time steps
    vars_to_check = ['temp', 'salt', 'u', 'v', 'zeta']
    valid_hours = 0
    
    for t_idx, time_val in enumerate(ds.time.values):
        has_nan = False
        nan_summary = []
        
        for var in vars_to_check:
            if var in ds:
                data_slice = ds[var].isel(time=t_idx).values
                nan_count = np.isnan(data_slice).sum()
                if nan_count > 0:
                    has_nan = True
                    nan_summary.append(f"{var}: {nan_count} NaNs")
                    
        if not has_nan:
            valid_hours += 1
        else:
            print(f"⚠️ Hour {t_idx} ({str(time_val)[:19]}): NaNs Detected -> {', '.join(nan_summary)}")
            
    print(f"\n✅ Total Clean / Valid Hours: {valid_hours} / {len(ds.time)}")
    
    # Create a sanitized version containing ONLY valid non-NaN time steps for the API
    if valid_hours > 0 and valid_hours < len(ds.time):
        sanitized_ds = ds.isel(time=slice(0, valid_hours))
        sanitized_filename = file_path.replace(".nc", "_sanitized_api.nc")
        sanitized_ds.to_netcdf(sanitized_filename)
        print(f"🚀 Saved sanitized dataset for API: {sanitized_filename} ({valid_hours} hours)")

if __name__ == "__main__":
    nc_files = sorted(glob.glob(os.path.join(DATA_DIR, "*.nc")))
    for f in nc_files:
        analyze_and_clean_netcdf(f)
