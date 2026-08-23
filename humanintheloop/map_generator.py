import math
from pathlib import Path
import sys
import io

from PIL import Image, ImageDraw, ImageFilter, ImageFont

WIDTH = 1440
HEIGHT = 1800
BG = "#eee3c8"
PANEL = "#ded1a9"
GRID = "#b3a67d"
CYAN = "#8a7350"
TEXT = "#2f2a20"
MUTED = "#6b573b"
GREEN = "#2e7d5b"
YELLOW = "#c98a1b"
RED = "#a83232"
LOW_WAVE = "#e4e6d8"


def map_metadata():
    return {
        "title": "OCEANOGRAPHIC CONDITIONS MAP",
        "primary_layers": ["wave_height", "current_vectors", "land_context"],
        "route_role": "none",
        "extent": "dynamic_route_corridor",
        "current_resolution": "Copernicus Mediterranean 4.2km forecast grid",
        "coastline_source": "Natural Earth 10m high-resolution coastlines",
    }


def add_rounded_corners(img, radius=34):
    mask = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, img.size[0], img.size[1]), radius=radius, fill=255)
    result = Image.new("RGBA", img.size)
    result.paste(img, (0, 0), mask=mask)
    return result


def compute_map_extent_from_route(lons, lats, padding=0.55):
    lon_min = min(lons) - padding
    lon_max = max(lons) + padding
    lat_min = min(lats) - padding
    lat_max = max(lats) + padding

    # Target aspect ratio of the map container (12.80 / 8.85)
    target_aspect = 12.80 / 8.85  # ~1.4463

    # Calculate midpoints and current spans
    lat_mid = (lat_min + lat_max) / 2
    lon_mid = (lon_min + lon_max) / 2

    import math
    cos_lat = math.cos(math.radians(lat_mid))
    if cos_lat <= 0.1:
        cos_lat = 1.0

    d_lat = lat_max - lat_min
    d_lon = lon_max - lon_min

    # Calculate current screen-equivalent aspect ratio
    current_aspect = (d_lon * cos_lat) / d_lat

    if current_aspect < target_aspect:
        # Extent is too tall/narrow, expand longitude
        d_lon_needed = (d_lat * target_aspect) / cos_lat
        lon_min = lon_mid - d_lon_needed / 2
        lon_max = lon_mid + d_lon_needed / 2
    else:
        # Extent is too wide/short, expand latitude
        d_lat_needed = (d_lon * cos_lat) / target_aspect
        lat_min = lat_mid - d_lat_needed / 2
        lat_max = lat_mid + d_lat_needed / 2

    return [lon_min, lon_max, lat_min, lat_max]


def resolve_route_waypoints(route, waves_path=None, currents_path=None):
    if not isinstance(route, dict):
        return []
    waypoints = route.get("waypoints", [])
    if not waypoints:
        import json
        route_id = route.get("id") or route.get("route_id")
        if route_id:
            try:
                routes_path = Path(__file__).resolve().parent / "routes.json"
                if routes_path.exists():
                    with open(routes_path, "r") as f:
                        routes_data = json.load(f)
                    if route_id in routes_data:
                        waypoints = routes_data[route_id].get("waypoints", [])
            except Exception as e:
                print(f"Warning: map_generator could not load waypoints from routes.json for {route_id}: {e}")

    if not waypoints and waves_path and currents_path:
        try:
            import os
            if os.path.exists(waves_path) and os.path.exists(currents_path):
                from api.weather_routing import AStarWeatherRouter
                lat1 = float(route["origin"]["latitude"])
                lon1 = float(route["origin"]["longitude"])
                lat2 = float(route["destination"]["latitude"])
                lon2 = float(route["destination"]["longitude"])
                
                router = AStarWeatherRouter(waves_path=str(waves_path), currents_path=str(currents_path))
                if router.in_bounds(lat1, lon1) and router.in_bounds(lat2, lon2):
                    res = router.find_route(
                        origin_lat=lat1,
                        origin_lon=lon1,
                        dest_lat=lat2,
                        dest_lon=lon2
                    )
                    waypoints = res.get("waypoints", [])
        except Exception as e:
            print(f"Warning: map_generator could not resolve dynamic weather route: {e}")

    if not waypoints:
        try:
            # Add workspace path to resolve place_registry
            human_path = str(Path(__file__).resolve().parent)
            if human_path not in sys.path:
                sys.path.insert(0, human_path)
            import place_registry

            lat1 = float(route["origin"]["latitude"])
            lon1 = float(route["origin"]["longitude"])
            lat2 = float(route["destination"]["latitude"])
            lon2 = float(route["destination"]["longitude"])
            origin_id = route.get("origin_place_id") or place_registry.default_place_id_for_query(route["origin"]["name"])
            destination_id = route.get("destination_place_id") or place_registry.default_place_id_for_query(route["destination"]["name"])
            if origin_id and destination_id:
                metrics = place_registry.coordinates_route_geometry_metrics(
                    origin_place_id=origin_id,
                    origin_place_name=route["origin"]["name"],
                    origin_latitude=lat1,
                    origin_longitude=lon1,
                    destination_place_id=destination_id,
                    destination_place_name=route["destination"]["name"],
                    destination_latitude=lat2,
                    destination_longitude=lon2,
                    simplify=False,
                )
                waypoints = metrics.get("waypoints", [])
        except Exception as e:
            print(f"Warning: map_generator could not resolve place registry waypoints: {e}")

    if not waypoints:
        # Fallback to sample points
        waypoints = [{"lat": route["origin"]["latitude"], "lng": route["origin"]["longitude"]}]
        for sp in route.get("sample_points", []):
            waypoints.append({"lat": sp["latitude"], "lng": sp["longitude"]})
        waypoints.append({"lat": route["destination"]["latitude"], "lng": route["destination"]["longitude"]})

    return waypoints


def render_matplotlib_map(waves_path, currents_path, route, snapshot, target_time=None):
    import numpy as np
    import xarray as xr
    import matplotlib
    matplotlib.use("Agg")  # Use non-interactive backend
    import matplotlib.pyplot as plt
    import cartopy
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    from matplotlib.colors import ListedColormap, BoundaryNorm

    # Configure Cartopy to use local offline shapefiles
    cartopy.config['data_dir'] = str(Path(__file__).resolve().parent.parent / "assets" / "cartopy_data")

    # 1. Resolve waypoints
    waypoints = resolve_route_waypoints(route, waves_path, currents_path)
    lons = []
    lats = []
    for wp in waypoints:
        lons.append(wp.get("lng") or wp.get("longitude"))
        lats.append(wp.get("lat") or wp.get("latitude"))

    # 2. Compute map extent
    extent = compute_map_extent_from_route(lons, lats, padding=0.55)

    # 3. Create matplotlib figure and PlateCarree axes
    # Dimension is exactly 1280x885 pixels at 100 DPI
    fig = plt.figure(figsize=(12.80, 8.85), dpi=100, facecolor="none")
    axis = fig.add_axes([0.06, 0.06, 0.88, 0.88], projection=ccrs.PlateCarree())
    axis.set_extent(extent, crs=ccrs.PlateCarree())
    axis.set_facecolor("#e4e6d8")  # sea base fill

    # 4. Draw wave height contours
    wave_loaded = False
    try:
        with xr.open_dataset(waves_path) as waves:
            time_index = select_time_index(waves, target_time or snapshot.get("forecast", {}).get("wave_peak_time"))
            wave = waves["VHM0"].isel(time=time_index)
            lons_grid = wave["longitude"].values
            lats_grid = wave["latitude"].values
            wave_vals = wave.values

            # Thresholds and colors matching RELAY-46
            levels = [0.0, 0.5, 1.25, 2.5, 4.0, 15.0]
            colors = ["#e4e6d8", "#c8d1c1", "#9fb2a9", "#c99a5a", "#a05a4a"]
            cmap = ListedColormap(colors)
            norm = BoundaryNorm(levels, cmap.N)

            axis.contourf(
                lons_grid, lats_grid, wave_vals,
                levels=levels, cmap=cmap, norm=norm,
                extend="max", transform=ccrs.PlateCarree(), zorder=1
            )
            wave_loaded = True
    except Exception as e:
        print(f"Warning: Failed to load waves contour in map_generator: {e}")

    # 5. Draw current arrows (if currents available)
    currents_drawn = False
    if currents_path and Path(currents_path).exists():
        try:
            with xr.open_dataset(currents_path) as currents:
                time_index_currents = min(time_index if wave_loaded else 0, currents.sizes.get("time", 1) - 1)
                u_c = currents["uo"].isel(time=time_index_currents)
                v_c = currents["vo"].isel(time=time_index_currents)
                vector_lons = u_c["longitude"].values
                vector_lats = u_c["latitude"].values
                vector_u = u_c.values
                vector_v = v_c.values

                # Density reduction to fit spec spacing
                lon_step = max(1, len(vector_lons) // 10)
                lat_step = max(1, len(vector_lats) // 10)

                axis.quiver(
                    vector_lons[::lon_step],
                    vector_lats[::lat_step],
                    vector_u[::lat_step, ::lon_step],
                    vector_v[::lat_step, ::lon_step],
                    color="#4a3f2d",  # current arrows color
                    scale=6.5,
                    width=0.003,
                    headwidth=3.2,
                    transform=ccrs.PlateCarree(),
                    zorder=6,
                )
                currents_drawn = True
        except Exception as e:
            print(f"Warning: Failed to load currents in map_generator: {e}")

    # 6. Draw coastal halo (coastal halo under land, width ~12, round joins)
    axis.coastlines(resolution="10m", color="#d3e2dc", linewidth=12, zorder=3)

    # 7. Draw land
    land = cfeature.NaturalEarthFeature(
        "physical", "land", "10m",
        edgecolor="none", facecolor="#ded1a9"
    )
    axis.add_feature(land, zorder=4)

    # 8. Draw coastline ink
    axis.coastlines(resolution="10m", color="#3a3226", linewidth=1.5, zorder=5)

    # 9. Draw graticule lines styled according to spec (#b3a67d, opacity 0.7, dash 3,5)
    gl = axis.gridlines(draw_labels=True, dms=True, x_inline=False, y_inline=False, zorder=2, linewidth=1.2, color="#b3a67d", alpha=0.7)
    gl.xlines = True
    gl.ylines = True
    gl.top_labels = False
    gl.right_labels = False
    gl.line_style = (0, (3, 5))
    gl.xlabel_style = {'size': 16, 'color': '#6b573b', 'weight': 'semibold'}
    gl.ylabel_style = {'size': 16, 'color': '#6b573b', 'weight': 'semibold'}

    # 10. Draw route casing and route graded segments
    if lons and lats:
        route_values = []
        for lon, lat in zip(lons, lats):
            if wave_loaded:
                try:
                    val = float(wave.sel(longitude=lon, latitude=lat, method="nearest").values)
                    if val != val:  # NaN check
                        val = 0.0
                except Exception:
                    val = 0.0
            else:
                val = 0.0
            route_values.append(val)

        # 10.1 Draw route casing (dark ink #2f2a20, width 12)
        axis.plot(lons, lats, color="#2f2a20", linewidth=12, transform=ccrs.PlateCarree(), zorder=7, solid_capstyle='round', solid_joinstyle='round')

        # 10.2 Draw route graded segments (width 7)
        for i in range(len(lons) - 1):
            segment_lon = [lons[i], lons[i+1]]
            segment_lat = [lats[i], lats[i+1]]

            val = max(route_values[i], route_values[i+1])
            if val <= 0.5:
                color = "#2e7d5b"  # route fair
                linewidth = 7
            elif val <= 1.25:
                color = "#c98a1b"  # route caution
                linewidth = 7
            else:
                color = "#a83232"  # route unsafe
                linewidth = 9

            axis.plot(segment_lon, segment_lat, color=color, linewidth=linewidth, transform=ccrs.PlateCarree(), zorder=8, solid_capstyle='round', solid_joinstyle='round')

        # 10.3 Draw waypoint circles
        if len(lons) > 2:
            axis.scatter(lons[1:-1], lats[1:-1], color="#eee3c8", edgecolor="#2f2a20", s=64, linewidth=2, transform=ccrs.PlateCarree(), zorder=9)

        # 10.4 Draw origin and destination markers
        axis.scatter([lons[0]], [lats[0]], color="#2e7d5b", edgecolor="#2f2a20", s=180, linewidth=2.5, transform=ccrs.PlateCarree(), zorder=10)
        dest_color = "#2e7d5b" if route_values[-1] <= 0.5 else ("#c98a1b" if route_values[-1] <= 1.25 else "#a83232")
        axis.scatter([lons[-1]], [lats[-1]], color=dest_color, edgecolor="#2f2a20", s=180, linewidth=2.5, transform=ccrs.PlateCarree(), zorder=10)

        # 10.5 Draw labels with distinct colored backgrounds
        axis.text(
            lons[0] + 0.12, lats[0] + 0.05, route["origin"]["name"],
            color="#ffffff", weight="bold", size=18,
            bbox=dict(facecolor="#2e7d5b", edgecolor="#2f2a20", boxstyle="round,pad=0.3", linewidth=1.5),
            transform=ccrs.PlateCarree(), zorder=11
        )
        axis.text(
            lons[-1] + 0.12, lats[-1] + 0.05, route["destination"]["name"],
            color="#ffffff", weight="bold", size=18,
            bbox=dict(facecolor=dest_color, edgecolor="#2f2a20", boxstyle="round,pad=0.3", linewidth=1.5),
            transform=ccrs.PlateCarree(), zorder=11
        )

    # 11. Style spines to represent a clean map bounding box border
    axis.spines['geo'].set_edgecolor("#6b573b")  # MUTED frame dark color
    axis.spines['geo'].set_linewidth(2)

    # 12. Save to PIL image
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=100, pad_inches=0, transparent=True)
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf), wave_loaded, currents_drawn


def generate_route_decision_map(waves_path, currents_path, route, snapshot, output_path, target_time=None):
    try:
        import xarray as xr
    except ImportError as error:
        raise RuntimeError("xarray is required to generate PredSea Decision Maps") from error

    output_path = Path(output_path)
    with xr.open_dataset(waves_path) as waves:
        time_index = select_time_index(waves, target_time or snapshot.get("forecast", {}).get("wave_peak_time"))
        time_label = str(waves["time"].dt.strftime("%H:%M UTC").values[time_index])

    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    fonts = load_fonts()

    draw_background(draw)
    draw_header(draw, fonts, route, time_label)

    map_box = (80, 350, 1360, 1235)

    # 1. Render map using matplotlib and cartopy
    map_image, wave_loaded, currents_drawn = render_matplotlib_map(waves_path, currents_path, route, snapshot, target_time)

    # 2. Match map image to exact 1280x885 map_box size in case of rounding discrepancies
    if map_image.size != (1280, 885):
        map_image = map_image.resize((1280, 885), Image.Resampling.LANCZOS)

    # 3. Add rounded corners to the map image
    rounded_map = add_rounded_corners(map_image, radius=34)

    # 4. Paste on main canvas
    image.paste(rounded_map, (80, 350), mask=rounded_map.getchannel("A"))

    # 5. Draw frame outline
    draw.rounded_rectangle(map_box, radius=34, outline=MUTED, width=4)

    # 6. Compose dynamic caption based on actual loaded components
    if wave_loaded:
        caption = "field: significant wave height — max over passage window"
    else:
        caption = "field: unavailable — verdict from along-route sampling only"

    if currents_drawn:
        caption += " · arrows: surface current"

    draw.text((80 + 84, 350 + 30), caption, font=fonts["small"], fill=TEXT)

    # 7. Draw outer chrome components
    draw_legend(draw, map_box, fonts)
    draw_decision_panel(draw, fonts, snapshot)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path


def select_time_index(dataset, peak_time):
    if not peak_time or peak_time == "N/A" or "time" not in dataset:
        return 0
    labels = [str(value) for value in dataset["time"].dt.strftime("%H:%M").values]
    if peak_time in labels:
        return labels.index(peak_time)
    return 0


def draw_background(draw):
    return


def draw_dashed_line(draw, start, end, fill, width=1, dash_len=6, gap_len=10):
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    dist = math.hypot(dx, dy)
    if dist == 0:
        return
    dx /= dist
    dy /= dist

    pos = 0.0
    while pos < dist:
        segment_end = min(pos + dash_len, dist)
        sx = x1 + dx * pos
        sy = y1 + dy * pos
        ex = x1 + dx * segment_end
        ey = x1 + dx * segment_end
        draw.line((sx, sy, ex, ey), fill=fill, width=width)
        pos += dash_len + gap_len


def draw_centered_text(draw, text, center_x, y, font, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    draw.text((center_x - w / 2, y), text, font=font, fill=fill)


def draw_header(draw, fonts, route, time_label):
    draw.text((80, 70), "PredSea", font=fonts["brand"], fill=TEXT)
    draw.text((80, 165), "OCEANOGRAPHIC CONDITIONS MAP", font=fonts["title"], fill=TEXT)
    draw.line((80, 245, 760, 245), fill=CYAN, width=4)
    draw.text((80, 278), "Mediterranean corridor forecast region", font=fonts["subtitle"], fill=CYAN)
    draw.text((980, 92), f"Model slice: {time_label}", font=fonts["small"], fill=MUTED)


def draw_legend(draw, map_box, fonts):
    left, top, right, bottom = map_box
    # Place extremely compact, horizontal, thin floating legend in the bottom-right corner above tick labels
    legend_w = 450
    legend_h = 56
    legend_left = right - 34 - legend_w
    legend_top = bottom - 74 - legend_h
    legend = (legend_left, legend_top, legend_left + legend_w, legend_top + legend_h)

    # Drawing a soft parchment/sea blend that looks almost invisible and floating
    draw.rounded_rectangle(legend, radius=12, fill="#ebece0", outline="#a8b29c", width=1)
    
    # 1. Label: "Wave height"
    draw.text((legend_left + 12, legend_top + 19), "Wave height", font=fonts["micro"], fill=TEXT)

    # 2. Continuous horizontal swatch bar
    start_x = legend_left + 125
    swatch_y1 = legend_top + 15
    swatch_y2 = legend_top + 25
    swatch_w = 28

    swatches = [
        "#e4e6d8",  # smooth
        "#c8d1c1",  # slight
        "#9fb2a9",  # moderate
        "#c99a5a",  # rough
        "#a05a4a",  # very rough
    ]

    for index, color in enumerate(swatches):
        x1 = start_x + index * swatch_w
        x2 = x1 + swatch_w
        draw.rectangle((x1, swatch_y1, x2, swatch_y2), fill=color)

    # Ticks and tick labels below the bar
    ticks = [
        ("0", start_x),
        ("0.5", start_x + swatch_w),
        ("1.2", start_x + 2 * swatch_w),
        ("2.5", start_x + 3 * swatch_w),
        ("4.0", start_x + 4 * swatch_w),
        ("4+", start_x + 5 * swatch_w),
    ]
    for label, x in ticks:
        draw.line((x, swatch_y2, x, swatch_y2 + 4), fill=MUTED, width=1)
        draw_centered_text(draw, label, x, swatch_y2 + 6, fonts["nano"], fill=MUTED)

    # 3. Label: "surface current" and its arrow
    current_x = legend_left + 280
    current_y = legend_top + 28
    
    # Custom sharp horizontal arrow: text first, then arrow
    draw.text((current_x, legend_top + 19), "surface current", font=fonts["micro"], fill=TEXT)
    
    arrow_start_x = current_x + 120
    draw.line((arrow_start_x, current_y, arrow_start_x + 22, current_y), fill=MUTED, width=2)
    # Arrow head
    p1 = (arrow_start_x + 22, current_y)
    p2 = (arrow_start_x + 16, current_y - 3)
    p3 = (arrow_start_x + 16, current_y + 3)
    draw.polygon([p1, p2, p3], fill=MUTED)


def draw_arrow_legend(draw, start, end, fill, width=3):
    draw.line((*start, *end), fill=fill, width=width)
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    angle = math.atan2(dy, dx)
    head_len = 14
    left_angle = angle + math.pi - 0.4
    right_angle = angle + math.pi + 0.4
    p1 = end
    p2 = (end[0] + math.cos(left_angle) * head_len, end[1] + math.sin(left_angle) * head_len)
    p3 = (end[0] + math.cos(right_angle) * head_len, end[1] + math.sin(right_angle) * head_len)
    draw.polygon([p1, p2, p3], fill=fill)


def draw_decision_panel(draw, fonts, snapshot):
    forecast = snapshot.get("forecast", {})
    rec = snapshot.get("recommendation", {})
    panel = (80, 1315, 1360, 1705)
    draw.rounded_rectangle(panel, radius=28, fill=PANEL, outline=MUTED, width=3)
    status = status_label(rec.get("vessel_severity"))
    color = severity_color(rec.get("vessel_severity"))
    draw.ellipse((122, 1372, 152, 1402), fill=color)
    draw.text((175, 1350), "PREDSEA SEA-STATE READ", font=fonts["status"], fill=TEXT)
    draw.text((175, 1410), f"{status}: {rec.get('vessel_advice', 'manual review needed')}", font=fonts["body"], fill=color)
    wave_min = forecast.get("wave_min_m")
    wave_max = forecast.get("wave_max_m")
    wave_text = "Wave range unavailable"
    if wave_min is not None and wave_max is not None:
        wave_text = f"Wave range: {wave_min:.1f}-{wave_max:.1f} m"
    draw.text((175, 1482), wave_text, font=fonts["body"], fill=CYAN)
    draw.text((175, 1538), f"Peak: {forecast.get('wave_peak_time', 'N/A')}", font=fonts["body"], fill=TEXT)
    current = forecast.get("current_max_kn")
    current_text = "Current max: unavailable" if current is None else f"Current max: {current:.1f} kn"
    draw.text((760, 1482), current_text, font=fonts["body"], fill=TEXT)
    confidence = rec.get("confidence")
    confidence_text = "Low" if confidence in (None, "", "null") else str(confidence).strip().capitalize()
    draw.text((760, 1538), f"Confidence: {confidence_text}", font=fonts["body"], fill=TEXT)
    draw.text((175, 1622), "Forecast field for human review: waves first, currents second, decision after interpretation.", font=fonts["small"], fill=MUTED)


def status_label(severity):
    if severity == "restricted":
        return "RESTRICTED"
    if severity == "caution":
        return "CONSERVATIVE"
    if severity == "manageable":
        return "WORKABLE"
    return "MANUAL REVIEW"


def severity_color(severity):
    if severity == "restricted":
        return RED
    if severity == "caution":
        return YELLOW
    return GREEN


def load_fonts():
    import matplotlib
    import os
    font_dir = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
    regular_path = os.path.join(font_dir, "DejaVuSans.ttf")
    bold_path = os.path.join(font_dir, "DejaVuSans-Bold.ttf")

    regular_candidates = [
        regular_path,
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    bold_candidates = [
        bold_path,
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    regular = next((path for path in regular_candidates if Path(path).exists()), None)
    bold = next((path for path in bold_candidates if Path(path).exists()), regular)
    if regular:
        return {
            "brand": ImageFont.truetype(bold, 44),
            "title": ImageFont.truetype(bold, 48),
            "subtitle": ImageFont.truetype(regular, 32),
            "status": ImageFont.truetype(bold, 42),
            "body": ImageFont.truetype(regular, 34),
            "small": ImageFont.truetype(regular, 25),
            "micro": ImageFont.truetype(regular, 18),
            "nano": ImageFont.truetype(regular, 13),
        }
    default = ImageFont.load_default()
    return {key: default for key in ("brand", "title", "subtitle", "status", "body", "small", "micro", "nano")}
