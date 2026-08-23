import importlib.util
import json
from pathlib import Path

import numpy as np
import xarray as xr
from PIL import Image


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_leaflet_overlays.py"


def load_overlay_script():
    spec = importlib.util.spec_from_file_location("generate_leaflet_overlays", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_test_forecasts(tmp_path):
    times = np.array(["2026-05-31T12:00:00", "2026-05-31T14:00:00"], dtype="datetime64[ns]")
    lats = [38.5, 39.5, 40.5]
    lons = [1.0, 2.0, 3.0, 4.5]
    waves = xr.Dataset(
        {
            "VHM0": (
                ("time", "latitude", "longitude"),
                np.array(
                    [
                        np.full((3, 4), 0.5),
                        np.full((3, 4), 1.2),
                    ]
                ),
            ),
            "VHM0_SW1": (("time", "latitude", "longitude"), np.full((2, 3, 4), 0.8)),
            "VHM0_SW2": (("time", "latitude", "longitude"), np.full((2, 3, 4), 0.3)),
            "VHM0_WW": (("time", "latitude", "longitude"), np.full((2, 3, 4), 0.5)),
        },
        coords={"time": times, "latitude": lats, "longitude": lons},
    )
    currents = xr.Dataset(
        {
            "uo": (("time", "latitude", "longitude"), np.full((2, 3, 4), 0.2)),
            "vo": (("time", "latitude", "longitude"), np.full((2, 3, 4), 0.1)),
        },
        coords={"time": times, "latitude": lats, "longitude": lons},
    )
    waves_path = tmp_path / "waves.nc"
    currents_path = tmp_path / "currents.nc"
    waves.to_netcdf(waves_path)
    currents.to_netcdf(currents_path)
    return waves_path, currents_path


def test_generate_leaflet_overlays_writes_index_and_png(tmp_path):
    module = load_overlay_script()
    waves_path, currents_path = write_test_forecasts(tmp_path)

    module.generate_leaflet_overlays(
        waves_path,
        currents_path,
        tmp_path / "run",
        variables=["wave_height"],
    )

    index_path = tmp_path / "run" / "maps" / "wave_height" / "index.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))

    assert payload["variable"] == "wave_height"
    assert payload["units"] == "m"
    assert payload["bounds"] if "bounds" in payload else True
    assert len(payload["overlays"]) == 2
    assert payload["overlays"][0]["bounds"] == [[38.5, 1.0], [40.5, 4.5]]
    image_path = index_path.parent / payload["overlays"][0]["filename"]
    assert image_path.exists()
    assert Image.open(image_path).mode == "RGBA"
    grid_path = index_path.parent / payload["overlays"][0]["grid_filename"]
    grid = json.loads(grid_path.read_text(encoding="utf-8"))
    assert grid["latitudes"] == [38.5, 39.5, 40.5]
    assert grid["longitudes"] == [1.0, 2.0, 3.0, 4.5]
    assert grid["values"][0][0] == 0.5


def test_current_speed_overlay_uses_current_vector_magnitude(tmp_path):
    module = load_overlay_script()
    waves_path, currents_path = write_test_forecasts(tmp_path)

    module.generate_leaflet_overlays(
        waves_path,
        currents_path,
        tmp_path / "run",
        variables=["current_speed"],
    )

    payload = json.loads((tmp_path / "run" / "maps" / "current_speed" / "index.json").read_text())
    assert payload["variable"] == "current_speed"
    assert payload["units"] == "m/s"
    assert len(payload["overlays"]) == 2


def test_wave_partition_overlays_are_generated_when_available(tmp_path):
    module = load_overlay_script()
    waves_path, currents_path = write_test_forecasts(tmp_path)

    module.generate_leaflet_overlays(
        waves_path,
        currents_path,
        tmp_path / "run",
        variables=["swell_1_height", "swell_2_height", "wind_wave_height"],
    )

    for variable, expected_value in (
        ("swell_1_height", 0.8),
        ("swell_2_height", 0.3),
        ("wind_wave_height", 0.5),
    ):
        index_path = tmp_path / "run" / "maps" / variable / "index.json"
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        assert payload["variable"] == variable
        assert payload["units"] == "m"
        assert payload["source_variable"] in {"VHM0_SW1", "VHM0_SW2", "VHM0_WW"}
        grid_path = index_path.parent / payload["overlays"][0]["grid_filename"]
        grid = json.loads(grid_path.read_text(encoding="utf-8"))
        assert grid["values"][0][0] == expected_value


def test_transparent_no_data_pixels_do_not_keep_black_rgb():
    module = load_overlay_script()
    values = np.array(
        [
            [0.6, 0.7, 0.8],
            [0.5, np.nan, 0.9],
            [0.4, 0.3, 0.2],
        ]
    )

    rgba = module.rgba_for_field(values, 0.0, 2.5, "turbo", alpha=178)

    assert rgba[1, 1, 3] == 0
    assert rgba[1, 1, :3].sum() > 0


def test_filename_for_is_stable_and_url_safe():
    module = load_overlay_script()

    assert (
        module.filename_for("wave_height", "2026-05-31T14:00:00Z")
        == "wave_height_20260531_140000Z.png"
    )
    assert (
        module.grid_filename_for("wave_height", "2026-05-31T14:00:00Z")
        == "wave_height_20260531_140000Z.grid.json"
    )
