import numpy as np
import xarray as xr

import grid_blender


def test_blend_wind_and_ocean_interpolates_ocean_to_wind_grid():
    wind = xr.Dataset(
        {
            "u10": (("latitude", "longitude"), [[1.0, 2.0], [3.0, 4.0]]),
            "v10": (("latitude", "longitude"), [[0.0, 0.5], [1.0, 1.5]]),
        },
        coords={"latitude": [39.0, 39.5], "longitude": [2.0, 2.5]},
    )
    ocean = xr.Dataset(
        {
            "wave_height": (("latitude", "longitude"), [[0.0, 1.0], [2.0, 3.0]]),
            "current_speed": (("latitude", "longitude"), [[0.2, 0.4], [0.6, 0.8]]),
        },
        coords={"latitude": [38.5, 40.0], "longitude": [1.5, 3.0]},
    )

    blended, lineage = grid_blender.blend_wind_and_ocean(
        wind,
        ocean,
        wind_lineage={"source": "meteo_france_arome", "resolution_km": 1.3, "status": "active"},
        ocean_lineage={"source": "copernicus_med", "resolution_km": 4.0, "status": "active"},
    )

    assert blended["u10"].shape == (2, 2)
    assert blended["wave_height"].shape == (2, 2)
    assert np.isclose(float(blended["wave_height"].sel(latitude=39.0, longitude=2.0)), 1.0)
    assert lineage["wind_forecast"]["source"] == "meteo_france_arome"
    assert lineage["ocean_forecast"] == {
        "source": "copernicus_med",
        "resolution_km": 4.0,
        "status": "interpolated_to_1.3km",
    }


def test_blender_normalizes_lat_lon_coordinate_names():
    wind = xr.Dataset(
        {"u10": (("lat", "lon"), [[1.0]])},
        coords={"lat": [39.0], "lon": [2.0]},
    )
    ocean = xr.Dataset(
        {"wave_height": (("lat", "lon"), [[0.8]])},
        coords={"lat": [39.0], "lon": [2.0]},
    )

    blended, _ = grid_blender.blend_wind_and_ocean(
        wind,
        ocean,
        wind_lineage={"source": "ecmwf_open_data", "resolution_km": 25.0, "status": "active"},
        ocean_lineage={"source": "copernicus_med", "resolution_km": 4.0, "status": "active"},
    )

    assert "latitude" in blended.coords
    assert "longitude" in blended.coords
