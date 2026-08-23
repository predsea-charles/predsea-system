import argparse
import json
import math
from pathlib import Path


def finite_float(value):
    value = float(value)
    if math.isnan(value) or math.isinf(value):
        return None
    return round(value, 4)


def export_ocean_conditions_layer(
    waves_path,
    currents_path,
    output_path,
    time_index=0,
    wave_step=2,
    current_step=6,
):
    try:
        import xarray as xr
    except ImportError as error:
        raise RuntimeError("xarray is required to export the ocean conditions layer") from error

    waves_path = Path(waves_path)
    currents_path = Path(currents_path)
    output_path = Path(output_path)

    with xr.open_dataset(waves_path) as waves, xr.open_dataset(currents_path) as currents:
        wave_index = min(int(time_index), waves.sizes.get("time", 1) - 1)
        current_index = min(int(time_index), currents.sizes.get("time", 1) - 1)

        wave = waves["VHM0"].isel(time=wave_index)
        current_u = currents["uo"].isel(time=current_index)
        current_v = currents["vo"].isel(time=current_index)

        wave_lats = [float(value) for value in wave["latitude"].values]
        wave_lons = [float(value) for value in wave["longitude"].values]
        current_lats = [float(value) for value in current_u["latitude"].values]
        current_lons = [float(value) for value in current_u["longitude"].values]

        wave_points = []
        for lat_index in range(0, len(wave_lats), wave_step):
            for lon_index in range(0, len(wave_lons), wave_step):
                value = finite_float(wave.values[lat_index][lon_index])
                if value is None:
                    continue
                wave_points.append(
                    {
                        "lat": round(wave_lats[lat_index], 5),
                        "lon": round(wave_lons[lon_index], 5),
                        "wave_m": value,
                    }
                )

        current_points = []
        for lat_index in range(0, len(current_lats), current_step):
            for lon_index in range(0, len(current_lons), current_step):
                u = finite_float(current_u.values[lat_index][lon_index])
                v = finite_float(current_v.values[lat_index][lon_index])
                if u is None or v is None:
                    continue
                speed_mps = math.hypot(u, v)
                direction_deg = (math.degrees(math.atan2(u, v)) + 360) % 360
                current_points.append(
                    {
                        "lat": round(current_lats[lat_index], 5),
                        "lon": round(current_lons[lon_index], 5),
                        "u_mps": round(u, 4),
                        "v_mps": round(v, 4),
                        "speed_mps": round(speed_mps, 4),
                        "speed_kn": round(speed_mps * 1.94384, 2),
                        "direction_deg": round(direction_deg, 1),
                    }
                )

        wave_values = [point["wave_m"] for point in wave_points]
        current_values = [point["speed_kn"] for point in current_points]
        payload = {
            "source": {
                "waves": str(waves_path),
                "currents": str(currents_path),
                "wave_model": waves.attrs.get("source", "unknown"),
                "current_model": currents.attrs.get("source", "unknown"),
            },
            "time": str(waves["time"].dt.strftime("%Y-%m-%d %H:%M UTC").values[wave_index]),
            "bounds": {
                "south": min(wave_lats),
                "north": max(wave_lats),
                "west": min(wave_lons),
                "east": max(max(wave_lons), max(current_lons)),
            },
            "summary": {
                "wave_min_m": round(min(wave_values), 2),
                "wave_max_m": round(max(wave_values), 2),
                "wave_mean_m": round(sum(wave_values) / len(wave_values), 2),
                "current_max_kn": round(max(current_values), 2),
                "current_mean_kn": round(sum(current_values) / len(current_values), 2),
            },
            "wave_points": wave_points,
            "current_points": current_points,
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Export gridded ocean variables for the static web demo.")
    parser.add_argument("--waves", default="humanintheloop/mvp_data/balearic_waves.nc")
    parser.add_argument("--currents", default="humanintheloop/mvp_data/balearic_currents.nc")
    parser.add_argument("--output", default="web/data/ocean_conditions.json")
    parser.add_argument("--time-index", type=int, default=0)
    parser.add_argument("--wave-step", type=int, default=2)
    parser.add_argument("--current-step", type=int, default=6)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    output = export_ocean_conditions_layer(
        waves_path=args.waves,
        currents_path=args.currents,
        output_path=args.output,
        time_index=args.time_index,
        wave_step=args.wave_step,
        current_step=args.current_step,
    )
    print(f"Wrote ocean conditions layer to {output}")


if __name__ == "__main__":
    main()
