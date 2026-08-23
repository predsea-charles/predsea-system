import argparse
import json
from pathlib import Path

import numpy as np


VARIABLES = {
    "wave_height": {
        "dataset": "waves",
        "source_variable": "VHM0",
        "units": "m",
        "vmin": 0.0,
        "vmax": 2.5,
        "palette": "turbo",
    },
    "swell_1_height": {
        "dataset": "waves",
        "source_variable": "VHM0_SW1",
        "units": "m",
        "vmin": 0.0,
        "vmax": 2.5,
        "palette": "turbo",
    },
    "swell_1_direction": {
        "dataset": "waves",
        "source_variable": "VMDR_SW1",
        "units": "degree",
        "vmin": 0.0,
        "vmax": 360.0,
        "palette": "twilight",
    },
    "swell_2_height": {
        "dataset": "waves",
        "source_variable": "VHM0_SW2",
        "units": "m",
        "vmin": 0.0,
        "vmax": 2.5,
        "palette": "turbo",
    },
    "swell_2_direction": {
        "dataset": "waves",
        "source_variable": "VMDR_SW2",
        "units": "degree",
        "vmin": 0.0,
        "vmax": 360.0,
        "palette": "twilight",
    },
    "wind_wave_height": {
        "dataset": "waves",
        "source_variable": "VHM0_WW",
        "units": "m",
        "vmin": 0.0,
        "vmax": 2.5,
        "palette": "turbo",
    },
    "wind_wave_direction": {
        "dataset": "waves",
        "source_variable": "VMDR_WW",
        "units": "degree",
        "vmin": 0.0,
        "vmax": 360.0,
        "palette": "twilight",
    },
    "current_speed": {
        "dataset": "currents",
        "units": "m/s",
        "vmin": 0.0,
        "vmax": 1.2,
        "palette": "viridis",
    },
}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Generate Leaflet-ready forecast image overlays.")
    parser.add_argument("--waves", required=True, help="Path to Copernicus wave NetCDF.")
    parser.add_argument("--currents", required=True, help="Path to Copernicus current NetCDF.")
    parser.add_argument("--output-dir", required=True, help="Directory where maps/<variable>/ files are written.")
    parser.add_argument("--variable", action="append", choices=sorted(VARIABLES), help="Variable to generate.")
    parser.add_argument("--alpha", type=int, default=178, help="Overlay alpha, 0-255.")
    return parser.parse_args(argv)


def rgba_for_field(values, vmin, vmax, palette, alpha=178):
    import matplotlib

    normalized = (values - vmin) / (vmax - vmin)
    normalized = np.clip(normalized, 0.0, 1.0)
    cmap = matplotlib.colormaps[palette]
    rgba = (cmap(normalized) * 255).astype(np.uint8)
    valid = np.isfinite(values)
    rgba[..., 3] = np.where(valid, alpha, 0).astype(np.uint8)
    rgba = fill_transparent_rgb_from_neighbors(rgba, valid)
    return rgba


def fill_transparent_rgb_from_neighbors(rgba, valid):
    """Avoid black interpolation halos around transparent no-data pixels."""
    if valid.all() or not valid.any():
        return rgba

    height, width = valid.shape
    filled = valid.copy()
    rgb = rgba[..., :3].copy()
    max_iterations = min(10, height + width)

    for _ in range(max_iterations):
        missing = ~filled
        if not missing.any():
            break

        previous_filled = filled.copy()
        previous_rgb = rgb.copy()
        totals = np.zeros((height, width, 3), dtype=np.uint32)
        counts = np.zeros((height, width), dtype=np.uint16)

        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                src_y = slice(max(0, -dy), height - max(0, dy))
                dst_y = slice(max(0, dy), height - max(0, -dy))
                src_x = slice(max(0, -dx), width - max(0, dx))
                dst_x = slice(max(0, dx), width - max(0, -dx))

                neighbor_mask = previous_filled[src_y, src_x]
                target_mask = missing[dst_y, dst_x] & neighbor_mask
                if not target_mask.any():
                    continue
                totals[dst_y, dst_x][target_mask] += previous_rgb[src_y, src_x][target_mask]
                counts[dst_y, dst_x][target_mask] += 1

        update_mask = missing & (counts > 0)
        if not update_mask.any():
            break
        rgb[update_mask] = (totals[update_mask] / counts[update_mask, None]).astype(np.uint8)
        filled[update_mask] = True

    rgba[..., :3] = rgb
    return rgba


def image_bounds(data_array):
    lons = data_array["longitude"].values
    lats = data_array["latitude"].values
    return [
        [float(np.nanmin(lats)), float(np.nanmin(lons))],
        [float(np.nanmax(lats)), float(np.nanmax(lons))],
    ]


def time_label(dataset, index):
    return str(dataset["time"].dt.strftime("%Y-%m-%dT%H:%M:%SZ").values[index])


def filename_for(variable, iso_time):
    compact = iso_time.replace("-", "").replace(":", "").replace("T", "_").replace("Z", "Z")
    return f"{variable}_{compact}.png"


def grid_filename_for(variable, iso_time):
    return filename_for(variable, iso_time).replace(".png", ".grid.json")


def field_for_variable(variable, waves, currents, index):
    meta = VARIABLES[variable]
    source_variable = meta.get("source_variable")
    if meta["dataset"] == "waves" and source_variable:
        if source_variable not in waves:
            return None
        return waves[source_variable].isel(time=index).rename(variable)
    if variable == "current_speed":
        current_index = min(index, currents.sizes.get("time", 1) - 1)
        u = currents["uo"].isel(time=current_index)
        v = currents["vo"].isel(time=current_index)
        speed = np.hypot(u, v)
        return speed.rename("current_speed")
    raise ValueError(f"Unsupported overlay variable: {variable}")


def save_overlay_png(data_array, output_path, variable, alpha):
    from PIL import Image

    meta = VARIABLES[variable]
    values = np.asarray(data_array.values, dtype=float)
    # Image rows are top-to-bottom; latitude coordinates are usually south-to-north.
    if float(data_array["latitude"].values[0]) < float(data_array["latitude"].values[-1]):
        values = np.flipud(values)
    rgba = rgba_for_field(values, meta["vmin"], meta["vmax"], meta["palette"], alpha=alpha)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(output_path)


def save_value_grid(data_array, output_path):
    values = np.asarray(data_array.values, dtype=float)
    values = np.where(np.isfinite(values), values, None)
    payload = {
        "latitudes": [float(value) for value in data_array["latitude"].values],
        "longitudes": [float(value) for value in data_array["longitude"].values],
        "values": values.tolist(),
    }
    output_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def generate_leaflet_overlays(waves_path, currents_path, output_dir, variables=None, alpha=178):
    import xarray as xr

    waves_path = Path(waves_path)
    currents_path = Path(currents_path)
    output_dir = Path(output_dir)
    selected_variables = variables or sorted(VARIABLES)
    written = {}

    with xr.open_dataset(waves_path) as waves, xr.open_dataset(currents_path) as currents:
        for variable in selected_variables:
            meta = VARIABLES[variable]
            variable_dir = output_dir / "maps" / variable
            overlays = []
            for index in range(waves.sizes.get("time", 1)):
                field = field_for_variable(variable, waves, currents, index)
                if field is None:
                    break
                iso_time = time_label(waves, index)
                filename = filename_for(variable, iso_time)
                grid_filename = grid_filename_for(variable, iso_time)
                save_overlay_png(field, variable_dir / filename, variable, alpha)
                save_value_grid(field, variable_dir / grid_filename)
                overlays.append(
                    {
                        "time": iso_time,
                        "filename": filename,
                        "grid_filename": grid_filename,
                        "bounds": image_bounds(field),
                    }
                )
            if not overlays:
                continue

            index_payload = {
                "variable": variable,
                "source_variable": meta.get("source_variable"),
                "units": meta["units"],
                "color_scale": {
                    "min": meta["vmin"],
                    "max": meta["vmax"],
                    "palette": meta["palette"],
                },
                "opacity": round(alpha / 255, 3),
                "overlays": overlays,
            }
            (variable_dir / "index.json").write_text(json.dumps(index_payload, indent=2), encoding="utf-8")
            written[variable] = variable_dir
    return written


def main():
    args = parse_args()
    written = generate_leaflet_overlays(
        args.waves,
        args.currents,
        args.output_dir,
        variables=args.variable,
        alpha=args.alpha,
    )
    for variable, path in written.items():
        print(f"Wrote {variable} overlays to {path}")


if __name__ == "__main__":
    main()
