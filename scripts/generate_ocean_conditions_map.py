import argparse
from pathlib import Path


DEFAULT_TITLE = "PredSea Oceanographic Conditions"
DEFAULT_RESOLUTION_LABEL = "Copernicus Med ~4.2 km ocean forecast grid"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate a captain-facing ocean conditions map with real coastline context."
    )
    parser.add_argument("--waves", required=True, help="Path to Copernicus wave NetCDF file.")
    parser.add_argument("--currents", help="Optional path to Copernicus surface-current NetCDF file.")
    parser.add_argument("--wind", help="Optional path to Copernicus/GFS/ECMWF wind NetCDF/GRIB file.")
    parser.add_argument("--scalar-var", default="VHM0", help="Scalar variable to plot as filled contours (e.g. VHM0, VHM0_SW1, VHM0_SW2, VHM0_WW, wind_speed, wind_gust).")
    parser.add_argument("--vector-var", default="currents", choices=["currents", "wave_dir", "swell1_dir", "swell2_dir", "wind_wave_dir", "wind_dir"], help="Vector field to plot as arrows.")
    parser.add_argument("--output", required=True, help="Output PNG path.")
    parser.add_argument("--time", help="Model time to plot, e.g. 12:00 or 2026-05-15T12:00.")
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--resolution-label", default=DEFAULT_RESOLUTION_LABEL)
    parser.add_argument("--coastline-resolution", default="10m", choices=["10m", "50m", "110m"])
    parser.add_argument("--extent", nargs=4, type=float, metavar=("LON_MIN", "LON_MAX", "LAT_MIN", "LAT_MAX"))
    parser.add_argument("--dpi", type=int, default=220)
    parser.add_argument("--arrow-density", default="normal", choices=["sparse", "normal", "dense"])
    parser.add_argument("--arrow-color", default="black", help="Vector arrow color.")
    parser.add_argument("--no-currents", action="store_true", help="Do not draw current vectors (legacy argument, maps to vector-var=none).")
    return parser.parse_args(argv)


def select_time_index(dataset, requested_time=None):
    if "time" not in dataset:
        return 0
    labels = [str(value) for value in dataset["time"].dt.strftime("%H:%M").values]
    iso_labels = [str(value) for value in dataset["time"].values]
    if requested_time in labels:
        return labels.index(requested_time)
    if requested_time:
        for index, label in enumerate(iso_labels):
            if requested_time in label:
                return index
    return 0


def infer_extent(wave, padding_degrees=0.08):
    lons = wave["longitude"].values
    lats = wave["latitude"].values
    return [
        float(lons.min()) - padding_degrees,
        float(lons.max()) + padding_degrees,
        float(lats.min()) - padding_degrees,
        float(lats.max()) + padding_degrees,
    ]


def compute_map_extent(scalar_data, waypoints=None, extent=None, padding_degrees=0.08, wp_padding=0.6):
    if extent is not None:
        return extent

    map_extent = infer_extent(scalar_data, padding_degrees=padding_degrees)
    if waypoints:
        lons = []
        lats = []
        for wp in waypoints:
            if "lng" in wp:
                lons.append(wp["lng"])
            elif "longitude" in wp:
                lons.append(wp["longitude"])
            if "lat" in wp:
                lats.append(wp["lat"])
            elif "latitude" in wp:
                lats.append(wp["latitude"])

        if lons and lats:
            wp_lon_min = min(lons) - wp_padding
            wp_lon_max = max(lons) + wp_padding
            wp_lat_min = min(lats) - wp_padding
            wp_lat_max = max(lats) + wp_padding

            map_extent = [
                min(map_extent[0], wp_lon_min),
                max(map_extent[1], wp_lon_max),
                min(map_extent[2], wp_lat_min),
                max(map_extent[3], wp_lat_max),
            ]
    return map_extent


def quiver_steps(lon_count, lat_count, density="normal"):
    targets = {
        "sparse": (10, 7),
        "normal": (14, 10),
        "dense": (22, 15),
    }
    target_lon, target_lat = targets[density]
    return max(1, lon_count // target_lon), max(1, lat_count // target_lat)


def dependency_error(error):
    message = (
        "Publication map generation requires matplotlib and cartopy. "
        "Install the map extras with: python -m pip install matplotlib cartopy"
    )
    runtime_error = RuntimeError(message)
    runtime_error.__cause__ = error
    return runtime_error


def _humanintheloop_path_on_sys_path():
    import sys
    human_path = str(Path(__file__).resolve().parent.parent / "humanintheloop")
    if human_path not in sys.path:
        sys.path.insert(0, human_path)
    return human_path


def waypoints_from_weather_router(route, waves_path, currents_path, router_cls=None):
    """Resolve the sea-route path via the A* weather router that backs the /places/route
    API endpoint, using the exact wave/current files a given map is plotting so the drawn
    path matches what a captain would actually be shown. Returns [] on any failure so
    callers can fall back to a cruder route geometry.
    """
    if currents_path is None:
        return []
    try:
        if router_cls is None:
            _humanintheloop_path_on_sys_path()
            from api.weather_routing import AStarWeatherRouter as router_cls

        lat1 = float(route["origin"]["latitude"])
        lon1 = float(route["origin"]["longitude"])
        lat2 = float(route["destination"]["latitude"])
        lon2 = float(route["destination"]["longitude"])

        # The router caches datasets at the class level keyed only on "loaded or not" --
        # force a reload so it doesn't serve stale data left behind by a previous
        # route/source that used different forcing files.
        router_cls.clear_cache()
        router = router_cls(waves_path=str(waves_path), currents_path=str(currents_path))
        if not (router.in_bounds(lat1, lon1) and router.in_bounds(lat2, lon2)):
            return []
        route_metrics = router.find_route(
            origin_lat=lat1,
            origin_lon=lon1,
            dest_lat=lat2,
            dest_lon=lon2,
        )
        return route_metrics.get("waypoints", [])
    except Exception as e:
        print(f"Warning: A* weather routing unavailable for map waypoints: {e}")
        return []


def waypoints_from_place_registry(route):
    """Resolve route geometry via place_registry's simpler (non-weather-aware) geometry
    function. Used as a fallback when the A* weather router can't produce a path.
    """
    try:
        _humanintheloop_path_on_sys_path()
        import place_registry

        lat1 = float(route["origin"]["latitude"])
        lon1 = float(route["origin"]["longitude"])
        lat2 = float(route["destination"]["latitude"])
        lon2 = float(route["destination"]["longitude"])

        origin_id = route.get("origin_place_id") or place_registry.default_place_id_for_query(route["origin"]["name"])
        destination_id = route.get("destination_place_id") or place_registry.default_place_id_for_query(route["destination"]["name"])
        if not (origin_id and destination_id):
            return []
        metrics = place_registry.coordinates_route_geometry_metrics(
            origin_place_id=origin_id,
            origin_place_name=route["origin"]["name"],
            origin_latitude=lat1,
            origin_longitude=lon1,
            destination_place_id=destination_id,
            destination_place_name=route["destination"]["name"],
            destination_latitude=lat2,
            destination_longitude=lon2,
        )
        return metrics.get("waypoints", [])
    except Exception as e:
        print(f"Warning: could not resolve waypoints dynamically: {e}")
        return []


def waypoints_from_sample_points(route):
    """Fall back to the route's own coarse sample_points (origin + a handful of
    hand-picked points + destination) when no real route geometry is available.
    """
    if "sample_points" not in route:
        return []
    sample = route.get("sample_points", [])
    waypoints = [{"lat": route["origin"]["latitude"], "lng": route["origin"]["longitude"]}]
    for sp in sample:
        waypoints.append({"lat": sp["latitude"], "lng": sp["longitude"]})
    waypoints.append({"lat": route["destination"]["latitude"], "lng": route["destination"]["longitude"]})
    return waypoints


def resolve_route_waypoints(route, waves_path=None, currents_path=None):
    """Resolve the list of {lat, lng} waypoints to draw for a route, preferring (in order):
    1. Waypoints already attached to the route dict (e.g. from a /places/route response).
    2. The A* weather router, using the same forcing files this map is plotting.
    3. place_registry's simpler route geometry.
    4. The route's own coarse sample_points.
    """
    if isinstance(route, list):
        return route
    if not isinstance(route, dict):
        return []

    waypoints = route.get("waypoints", [])
    if not waypoints:
        waypoints = waypoints_from_weather_router(route, waves_path, currents_path)
    if not waypoints:
        waypoints = waypoints_from_place_registry(route)
    if not waypoints:
        waypoints = waypoints_from_sample_points(route)
    return waypoints


def generate_ocean_conditions_map(
    waves_path,
    output_path,
    currents_path=None,
    wind_path=None,
    scalar_var="VHM0",
    vector_var="currents",
    requested_time=None,
    title=DEFAULT_TITLE,
    resolution_label=DEFAULT_RESOLUTION_LABEL,
    coastline_resolution="10m",
    extent=None,
    dpi=220,
    arrow_density="normal",
    arrow_color="white",
    draw_currents=True,
    route=None,
):
    try:
        import numpy as np
        import xarray as xr
        import matplotlib.pyplot as plt
        import cartopy
        import cartopy.crs as ccrs
        import cartopy.feature as cfeature

        # Configure Cartopy to use local offline shapefiles to prevent dynamic downloads
        cartopy.config['data_dir'] = str(Path(__file__).resolve().parent.parent / "assets" / "cartopy_data")
    except ImportError as error:
        raise dependency_error(error)

    waves_path = Path(waves_path)
    output_path = Path(output_path)
    
    # Check legacy override
    if not draw_currents:
        vector_var = "none"

    # Step 1: Load scalar dataset and extract grid + values
    is_wind_scalar = scalar_var in ("wind_speed", "wind_gust", "u10", "v10")
    
    if is_wind_scalar:
        if not wind_path:
            raise ValueError(f"A --wind dataset path must be specified to plot scalar wind variable: {scalar_var}")
        with xr.open_dataset(wind_path) as wind_ds:
            # Coordinates and variables normalization
            renames = {}
            for c in ("latitude", "lat", "y"):
                if c in wind_ds.coords:
                    renames[c] = "latitude"
            for c in ("longitude", "lon", "x"):
                if c in wind_ds.coords:
                    renames[c] = "longitude"
            for v in ("u10", "10u", "U_COMPONENT_OF_WIND", "u_wind"):
                if v in wind_ds.data_vars:
                    renames[v] = "u10"
            for v in ("v10", "10v", "V_COMPONENT_OF_WIND", "v_wind"):
                if v in wind_ds.data_vars:
                    renames[v] = "v10"
            for v in ("wind_gust", "i10fg", "WIND_SPEED_GUST", "gust"):
                if v in wind_ds.data_vars:
                    renames[v] = "wind_gust"
            if renames:
                wind_ds = wind_ds.rename(renames)
            if "u10" in wind_ds and "v10" in wind_ds and "wind_speed" not in wind_ds:
                wind_ds["wind_speed"] = np.sqrt(wind_ds["u10"]**2 + wind_ds["v10"]**2)
                wind_ds["wind_speed"].attrs["units"] = "m s-1"
                
            time_index = select_time_index(wind_ds, requested_time)
            scalar_data = wind_ds[scalar_var].isel(time=time_index)
            time_label = str(wind_ds["time"].dt.strftime("%Y-%m-%d %H:%M UTC").values[time_index])
            scalar_vals = scalar_data.values
            lons_grid = scalar_data["longitude"].values
            lats_grid = scalar_data["latitude"].values
    else:
        with xr.open_dataset(waves_path) as waves:
            time_index = select_time_index(waves, requested_time)
            scalar_data = waves[scalar_var].isel(time=time_index)
            time_label = str(waves["time"].dt.strftime("%Y-%m-%d %H:%M UTC").values[time_index])
            scalar_vals = scalar_data.values
            lons_grid = scalar_data["longitude"].values
            lats_grid = scalar_data["latitude"].values

    # Step 2: Load vector dataset and compute arrow components
    vector_u, vector_v = None, None
    vector_lons, vector_lats = None, None
    vector_scale = 1.0
    vector_label = "none"

    if vector_var == "currents" and currents_path:
        with xr.open_dataset(currents_path) as currents:
            current_index = min(time_index, currents.sizes.get("time", 1) - 1)
            u_c = currents["uo"].isel(time=current_index)
            v_c = currents["vo"].isel(time=current_index)
            vector_lons = u_c["longitude"].values
            vector_lats = u_c["latitude"].values
            vector_u = u_c.values
            vector_v = v_c.values
            vector_scale = 6.8
            vector_label = "surface currents"

    elif vector_var in ("wave_dir", "swell1_dir", "swell2_dir", "wind_wave_dir"):
        dir_mapping = {
            "wave_dir": "VMDR",
            "swell1_dir": "VMDR_SW1",
            "swell2_dir": "VMDR_SW2",
            "wind_wave_dir": "VMDR_WW",
        }
        dir_var_name = dir_mapping[vector_var]
        with xr.open_dataset(waves_path) as waves:
            time_index = select_time_index(waves, requested_time)
            dir_data = waves[dir_var_name].isel(time=time_index)
            vector_lons = dir_data["longitude"].values
            vector_lats = dir_data["latitude"].values
            theta_rad = np.radians(dir_data.values)
            vector_u = -np.sin(theta_rad)
            vector_v = -np.cos(theta_rad)
            
            # Mask NaNs (keep arrows on water only)
            vhm0_vals = waves["VHM0"].isel(time=time_index).values
            nan_mask = np.isnan(vhm0_vals) | np.isnan(dir_data.values)
            vector_u[nan_mask] = np.nan
            vector_v[nan_mask] = np.nan
            
            vector_scale = 22.0
            vector_label = {
                "wave_dir": "wave direction",
                "swell1_dir": "primary swell direction",
                "swell2_dir": "secondary swell direction",
                "wind_wave_dir": "wind wave direction",
            }[vector_var]

    elif vector_var == "wind_dir":
        if not wind_path:
            raise ValueError("A --wind dataset path must be specified to plot wind direction arrows.")
        with xr.open_dataset(wind_path) as wind_ds:
            renames = {}
            for c in ("latitude", "lat", "y"):
                if c in wind_ds.coords:
                    renames[c] = "latitude"
            for c in ("longitude", "lon", "x"):
                if c in wind_ds.coords:
                    renames[c] = "longitude"
            for v in ("u10", "10u", "U_COMPONENT_OF_WIND", "u_wind"):
                if v in wind_ds.data_vars:
                    renames[v] = "u10"
            for v in ("v10", "10v", "V_COMPONENT_OF_WIND", "v_wind"):
                if v in wind_ds.data_vars:
                    renames[v] = "v10"
            if renames:
                wind_ds = wind_ds.rename(renames)

            time_index = select_time_index(wind_ds, requested_time)
            if "u10" in wind_ds and "v10" in wind_ds:
                u_w = wind_ds["u10"].isel(time=time_index).values
                v_w = wind_ds["v10"].isel(time=time_index).values
                vector_lons = wind_ds["longitude"].values
                vector_lats = wind_ds["latitude"].values
                speed = np.sqrt(u_w**2 + v_w**2)
                speed_safe = np.where(speed == 0, 1.0, speed)
                vector_u = u_w / speed_safe
                vector_v = v_w / speed_safe
                vector_scale = 22.0
            elif "wind_direction" in wind_ds:
                dir_data = wind_ds["wind_direction"].isel(time=time_index)
                vector_lons = dir_data["longitude"].values
                vector_lats = dir_data["latitude"].values
                theta_rad = np.radians(dir_data.values)
                vector_u = -np.sin(theta_rad)
                vector_v = -np.cos(theta_rad)
                vector_scale = 22.0
            vector_label = "10m wind direction"

    # Resolve route waypoints early if provided, to ensure map extent fully encompasses them
    waypoints = []
    if route is not None:
        waypoints = resolve_route_waypoints(route, waves_path=waves_path, currents_path=currents_path)

    # Step 3: Draw geography and coastline
    map_extent = compute_map_extent(scalar_data, waypoints=waypoints, extent=extent)

    projection = ccrs.PlateCarree()
    figure = plt.figure(figsize=(14, 11), dpi=dpi)
    axis = plt.axes(projection=projection)
    axis.set_extent(map_extent, crs=projection)
    axis.set_facecolor("#06202d")

    land = cfeature.NaturalEarthFeature(
        "physical",
        "land",
        coastline_resolution,
        edgecolor="#111111",
        facecolor="#c7ccd1",
    )
    axis.add_feature(land, zorder=4, linewidth=0.8)
    axis.coastlines(resolution=coastline_resolution, color="#111111", linewidth=0.8, zorder=5)

    # Step 4: Draw scalar contours
    if scalar_var.startswith("VHM0"):
        from matplotlib.colors import ListedColormap, BoundaryNorm
        wave_colors = ["#d0e6e4", "#78b5c5", "#2c6d8a", "#d6802c", "#b32c2c"]
        cmap = ListedColormap(wave_colors)
        levels = [0.0, 0.5, 1.25, 2.5, 4.0, 8.0]
        norm = BoundaryNorm(levels, cmap.N)
        extend_behavior = "max"
    else:
        cmap = "turbo"
        levels = np.linspace(0.0, 30.0, 31)
        norm = None
        extend_behavior = "both"

    field = axis.contourf(
        lons_grid,
        lats_grid,
        scalar_vals,
        levels=levels,
        cmap=cmap,
        norm=norm,
        extend=extend_behavior,
        transform=projection,
        zorder=1,
    )

    # Step 5: Overlay vector arrows
    if vector_u is not None and vector_v is not None:
        lon_step, lat_step = quiver_steps(len(vector_lons), len(vector_lats), arrow_density)
        axis.quiver(
            vector_lons[::lon_step],
            vector_lats[::lat_step],
            vector_u[::lat_step, ::lon_step],
            vector_v[::lat_step, ::lon_step],
            color=arrow_color,
            scale=vector_scale,
            width=0.002,
            headwidth=3.2,
            transform=projection,
            zorder=6,
        )

    # Step 5b: Overlay route waypoints if provided
    if route is not None:
        if waypoints:
            lons = []
            lats = []
            for wp in waypoints:
                if "lng" in wp:
                    lons.append(wp["lng"])
                elif "longitude" in wp:
                    lons.append(wp["longitude"])
                if "lat" in wp:
                    lats.append(wp["lat"])
                elif "latitude" in wp:
                    lats.append(wp["latitude"])
            
            if lons and lats:
                # Plot the path line connecting the waypoints
                axis.plot(
                    lons,
                    lats,
                    color="#22e6f0",
                    linewidth=3.0,
                    transform=projection,
                    zorder=8,
                    label="Route Path"
                )
                
                # Plot individual waypoint nodes/markers
                axis.scatter(
                    lons,
                    lats,
                    color="#f4fbff",
                    edgecolor="#06202d",
                    s=80,
                    linewidth=1.5,
                    transform=projection,
                    zorder=9,
                    label="Waypoints"
                )
                
                # Highlight origin and destination specifically with distinct styling
                # Origin (Green)
                axis.scatter(
                    [lons[0]],
                    [lats[0]],
                    color="#2cf37d",
                    edgecolor="#06202d",
                    s=120,
                    linewidth=2.0,
                    transform=projection,
                    zorder=10,
                )
                # Destination (Red)
                axis.scatter(
                    [lons[-1]],
                    [lats[-1]],
                    color="#f32c2c",
                    edgecolor="#06202d",
                    s=120,
                    linewidth=2.0,
                    transform=projection,
                    zorder=10,
                )
                
                # Add labels for Origin and Destination
                if isinstance(route, dict):
                    origin_name = route.get("origin", {}).get("name", "Origin")
                    dest_name = route.get("destination", {}).get("name", "Destination")
                else:
                    origin_name = "Origin"
                    dest_name = "Destination"
                
                axis.text(
                    lons[0],
                    lats[0] + 0.08,
                    origin_name,
                    transform=projection,
                    fontsize=10,
                    fontweight="bold",
                    color="#2cf37d",
                    ha="center",
                    bbox={"facecolor": "#06202d", "alpha": 0.85, "edgecolor": "none", "pad": 3},
                    zorder=11
                )
                axis.text(
                    lons[-1],
                    lats[-1] + 0.08,
                    dest_name,
                    transform=projection,
                    fontsize=10,
                    fontweight="bold",
                    color="#f32c2c",
                    ha="center",
                    bbox={"facecolor": "#06202d", "alpha": 0.85, "edgecolor": "none", "pad": 3},
                    zorder=11
                )

    gridlines = axis.gridlines(
        draw_labels=True,
        linewidth=0.4,
        color="#5e7480",
        alpha=0.5,
        linestyle="--",
    )
    gridlines.top_labels = False
    gridlines.right_labels = False
    gridlines.xlabel_style = {"size": 10}
    gridlines.ylabel_style = {"size": 10}

    # Step 6: Configure colorbar
    colorbar = figure.colorbar(field, ax=axis, shrink=0.82, pad=0.03)
    if scalar_var.startswith("VHM0"):
        colorbar.set_label("Significant wave height (m)", fontsize=12)
        colorbar.set_ticks([0.0, 0.5, 1.25, 2.5, 4.0])
        colorbar.ax.set_yticklabels(["0.0 (Smooth)", "0.5 (Slight)", "1.25 (Moderate)", "2.5 (Rough)", "4.0 (Very rough)"])
    else:
        units_str = scalar_data.attrs.get("units", "m s-1")
        colorbar.set_label(f"{scalar_var} ({units_str})", fontsize=12)

    # Configure headers and descriptions
    axis.set_title(f"{title}\n{time_label} | {resolution_label}", fontsize=17, pad=18)

    scalar_desc = {
        "VHM0": "significant wave height",
        "VHM0_SW1": "primary swell height",
        "VHM0_SW2": "secondary swell height",
        "VHM0_WW": "wind wave height",
        "wind_speed": "10m wind speed",
        "wind_gust": "10m wind gust",
    }.get(scalar_var, scalar_var)

    axis.text(
        0.01,
        0.02,
        f"Forecast field: {scalar_desc}. Arrows: {vector_label}.",
        transform=axis.transAxes,
        fontsize=10,
        color="#f7fbff",
        bbox={"facecolor": "#06202d", "alpha": 0.78, "edgecolor": "none", "pad": 6},
        zorder=10,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # REMOVED bbox_inches="tight" to prevent headless cropping bug
    figure.savefig(output_path, facecolor="white")
    plt.close(figure)
    return output_path


def main():
    args = parse_args()
    output = generate_ocean_conditions_map(
        args.waves,
        args.output,
        currents_path=args.currents,
        wind_path=args.wind,
        scalar_var=args.scalar_var,
        vector_var=args.vector_var,
        requested_time=args.time,
        title=args.title,
        resolution_label=args.resolution_label,
        coastline_resolution=args.coastline_resolution,
        extent=args.extent,
        dpi=args.dpi,
        arrow_density=args.arrow_density,
        arrow_color=args.arrow_color,
        draw_currents=not args.no_currents,
    )
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
