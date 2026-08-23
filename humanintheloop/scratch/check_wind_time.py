import xarray as xr
import numpy as np

grib_path = "humanintheloop/mvp_data/ecmwf_wind_global.grib2"
u_dataset = xr.open_dataset(
    grib_path,
    backend_kwargs={"filter_by_keys": {"shortName": "10u"}, "indexpath": ""},
    engine="cfgrib",
)

valid_times = u_dataset.valid_time.values
print("First valid time:", valid_times[0])
print("Last valid time:", valid_times[-1])
print("Number of steps:", len(valid_times))
print("Step values:", valid_times)
u_dataset.close()
