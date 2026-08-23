LATITUDE_ALIASES = ("latitude", "lat", "y")
LONGITUDE_ALIASES = ("longitude", "lon", "x")


def standard_lat_lon_names(dataset):
    rename = {}
    latitude_name = first_present(dataset.coords, LATITUDE_ALIASES)
    longitude_name = first_present(dataset.coords, LONGITUDE_ALIASES)
    if latitude_name is None or longitude_name is None:
        raise ValueError("Dataset must contain latitude/longitude coordinates.")
    if latitude_name != "latitude":
        rename[latitude_name] = "latitude"
    if longitude_name != "longitude":
        rename[longitude_name] = "longitude"
    return dataset.rename(rename) if rename else dataset


def first_present(mapping, candidates):
    for candidate in candidates:
        if candidate in mapping:
            return candidate
    return None


def interpolate_ocean_to_wind_grid(ocean_ds, wind_ds):
    wind = standard_lat_lon_names(wind_ds)
    ocean = standard_lat_lon_names(ocean_ds)
    return ocean.interp(
        latitude=wind["latitude"],
        longitude=wind["longitude"],
    )


def blend_wind_and_ocean(wind_ds, ocean_ds, wind_lineage, ocean_lineage):
    wind = standard_lat_lon_names(wind_ds)
    interpolated_ocean = interpolate_ocean_to_wind_grid(ocean_ds, wind)
    blended = wind.merge(interpolated_ocean, compat="override")
    lineage = {
        "wind_forecast": dict(wind_lineage),
        "ocean_forecast": interpolated_ocean_lineage(wind_lineage, ocean_lineage),
    }
    blended.attrs["data_lineage"] = lineage
    return blended, lineage


def interpolated_ocean_lineage(wind_lineage, ocean_lineage):
    lineage = dict(ocean_lineage)
    target_resolution = wind_lineage.get("resolution_km")
    if target_resolution:
        lineage["status"] = f"interpolated_to_{target_resolution:g}km"
    else:
        lineage["status"] = "interpolated_to_wind_grid"
    return lineage
