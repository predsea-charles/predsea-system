import re

import source_lineage


def _canal(snapshot):
    return snapshot.get("observations", {}).get("canal_de_ibiza", {})


def _forecast(snapshot):
    return snapshot.get("forecast", {})


def _recommendation(snapshot):
    return snapshot.get("recommendation", {})


def _confidence_label(value):
    if value in (None, "", "null"):
        return None
    return str(value).strip().capitalize()


def _source_text(snapshot):
    return source_lineage.summarize_sources(snapshot=snapshot).get("text")


def _soften_clock_times(text, replacement="the relevant window"):
    if not text:
        return text
    return re.sub(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", replacement, str(text))


def _cardinal_direction(deg):
    if deg is None:
        return "N/A"
    try:
        deg = float(deg)
    except (TypeError, ValueError):
        return "N/A"
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    ix = int((deg + 22.5) / 45) % 8
    return dirs[ix]


def render_linkedin(snapshot):
    canal = _canal(snapshot)
    forecast = _forecast(snapshot)
    rec = _recommendation(snapshot)
    briefing = snapshot.get("daily_briefing") or {}
    source_text = _source_text(snapshot)
    lines = [
        f"PredSea Mediterranean Corridor Briefing | {snapshot['route']}",
        "",
        f"Current: {canal.get('name', 'SOCIB buoy')} reports {canal.get('wave_height_m', 'N/A')} m significant wave height and {canal.get('water_temp_c', 'N/A')} C water.",
        f"Wind: {briefing.get('wind_speed_kn', 'N/A')} kn from {_cardinal_direction(briefing.get('wind_direction_deg'))}, gusts to {briefing.get('wind_gust_kn', 'N/A')} kn ({briefing.get('wind_trend', 'steady')}).",
        f"Trend: {briefing.get('wave_trend', 'steady')} seas, with swell direction {briefing.get('swell_direction', 'N/A')}.",
    ]
    if source_text:
        lines.append(source_text)
    lines.extend(
        [
            f"Best window: {rec.get('best_window', 'check manually')}.",
            f"Windows: best crossing window is {rec.get('best_window', 'check manually')}.",
            f"Watch out: {_soften_clock_times(rec.get('watch_out', 'conditions require manual review'))}.",
            f"Confidence: {_confidence_label(rec.get('confidence')) or 'Low'}.",
            f"Next 24h: forecast wave peak near {forecast.get('wave_max_m', 'N/A')} m during the {peak_period_label(forecast.get('wave_peak_time'))} period.",
            "",
            "Illustrative route intelligence example, based on public marine data.",
        ]
    )
    return "\n".join(lines)


def render_whatsapp(snapshot):
    canal = _canal(snapshot)
    forecast = _forecast(snapshot)
    rec = _recommendation(snapshot)
    briefing = snapshot.get("daily_briefing") or {}
    source_text = _source_text(snapshot)
    lines = [
        "PredSea Captain's Briefing",
        f"Route: {snapshot['route']}",
        f"Current: {canal.get('wave_height_m', 'N/A')} m waves, water {canal.get('water_temp_c', 'N/A')} C.",
        f"Wind: {briefing.get('wind_speed_kn', 'N/A')} kn from {_cardinal_direction(briefing.get('wind_direction_deg'))}, gusts to {briefing.get('wind_gust_kn', 'N/A')} kn.",
        f"Trend: {briefing.get('wave_trend', 'steady')} seas; swell direction {briefing.get('swell_direction', 'N/A')}.",
    ]
    if source_text:
        lines.append(source_text)
    lines.extend(
        [
            f"Best window: {rec.get('best_window', 'check manually')}.",
            f"Windows: {rec.get('best_window', 'check manually')}.",
            f"Watch out: {_soften_clock_times(rec.get('watch_out', 'conditions require manual review'))}.",
            f"Confidence: {_confidence_label(rec.get('confidence')) or 'Low'}.",
            f"Next 24h: peak near {forecast.get('wave_max_m', 'N/A')} m during the {peak_period_label(forecast.get('wave_peak_time'))} period.",
        ]
    )
    return "\n".join(lines)


def render_whatsapp_screenshot_script(snapshot):
    forecast = _forecast(snapshot)
    rec = _recommendation(snapshot)
    vessel_label = snapshot.get("vessel_profile", {}).get("label", "the selected vessel class")
    source_text = _source_text(snapshot)
    wave_max = forecast.get("wave_max_m")
    peak_time = forecast.get("wave_peak_time")
    if wave_max is not None and peak_time and peak_time != "N/A":
        peak_text = f"{snapshot['route']} peaks near {wave_max:.1f} m during the {peak_period_label(peak_time)} period."
    elif wave_max is not None:
        peak_text = f"{snapshot['route']} peaks near {wave_max:.1f} m later."
    else:
        peak_text = f"{snapshot['route']} needs a manual forecast check."
    route_is_calm_now = "The route is manageable this morning, but exposed wave energy builds later."
    if wave_max is not None and wave_max <= 1.0:
        route_is_calm_now = "The route looks manageable today, but exposed sections still deserve attention."
    confidence = _confidence_label(rec.get("confidence")) or "Low"
    lines = [
        "Illustrative WhatsApp screenshot script",
        "Captain: [Shared live location]",
        f"Captain: {snapshot['route']} today. Best time to leave?",
        f"PredSea: Go earlier. {route_is_calm_now}",
        f"PredSea: {peak_text}",
    ]
    if source_text:
        lines.append(f"PredSea: {source_text}.")
    else:
        lines.append("PredSea: Sources used are shown in the briefing.")
    lines.extend(
        [
            f"PredSea: Operational read: {rec.get('vessel_advice', f'check manually for vessels {vessel_label}')}.",
            f"PredSea: Watch out: {_soften_clock_times(rec.get('watch_out', 'conditions require manual review'))}.",
            f"PredSea: Confidence: {confidence}.",
            "Caption note: illustrative product example based on public marine data.",
        ]
    )
    return "\n".join(lines)


def peak_period_label(time_text):
    try:
        hour = int(str(time_text).split(":", 1)[0])
    except (TypeError, ValueError):
        return "available period"
    if hour < 6:
        return "overnight"
    if hour < 10:
        return "early morning"
    if hour < 12:
        return "late morning"
    if hour < 18:
        return "daylight hours"
    if hour < 22:
        return "this evening"
    return "overnight"
