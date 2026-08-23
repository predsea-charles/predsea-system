import sys
import math
from datetime import datetime, timedelta, timezone
sys.path.append("/Users/charles.santana/PredSea/predsea-system/humanintheloop")
from scratch.plot_forecast import generate_forecast_series, get_cardinal, get_direction_arrow, PLACES

# Load standard forecast series
palma_wind = generate_forecast_series("palma", "wind_speed", 5)
palma_wave = generate_forecast_series("palma", "wave_height", 5)
ibiza_wind = generate_forecast_series("ibiza", "wind_speed", 5)
ibiza_wave = generate_forecast_series("ibiza", "wave_height", 5)

def get_fetch_wave(place_id, series, h_idx, d):
    dt_val = d["datetime"]
    local_dt = dt_val + timedelta(hours=2)
    hour_of_day = local_dt.hour + local_dt.minute / 60.0
    
    is_southerly_fetch = (local_dt.strftime('%m-%d') == '06-29')
    
    # Model the winds to find the gusty speed
    wind_front = [1.0 + 0.45 * math.sin(2 * math.pi * h_idx / (len(series) * 0.6) + 1.2) for h_idx in range(len(series))]
    synoptic_wind = PLACES[place_id]["default_wind"] * wind_front[h_idx]
    breeze_cycle = 4.0 * math.sin(2.0 * math.pi * (hour_of_day - 10.5) / 24.0)
    gust_cycle = 0.5 * math.sin(2.0 * math.pi * hour_of_day / 8.0)
    wind_speed_calc = max(1.5, synoptic_wind + breeze_cycle + gust_cycle)
    
    if place_id == "palma":
        if is_southerly_fetch and wind_speed_calc > 12.0:
            fetch_h = d["value"] + 0.05 * (wind_speed_calc - 10.0) ** 1.35
        else:
            fetch_h = d["value"]
    elif place_id == "ibiza":
        if is_southerly_fetch and wind_speed_calc > 10.0:
            fetch_h = d["value"] + 0.13 * (wind_speed_calc - 10.0) ** 1.02
        else:
            fetch_h = d["value"]
    else:
        fetch_h = d["value"]
    return fetch_h

output_file = "/Users/charles.santana/.gemini/antigravity/brain/6c302f3b-86b0-4691-83ca-2206aef6fa23/hourly_forecast_table.md"

with open(output_file, "w", encoding="utf-8") as f:
    f.write("# 5-Day Hourly Forecast (Palma vs. Ibiza)\n\n")
    current_day_str = ""
    for i in range(len(palma_wind)):
        pw = palma_wind[i]
        p_wav = palma_wave[i]
        iw = ibiza_wind[i]
        i_wav = ibiza_wave[i]
        
        dt_utc = pw["datetime"]
        day_str = dt_utc.strftime("%A, %B %d")
        
        if day_str != current_day_str:
            f.write(f"\n## {day_str} (UTC)\n\n")
            f.write("| Time (UTC) | Palma Wind | Palma Gusts | Palma Model Wave | Palma Fetch Risk | Ibiza Wind | Ibiza Gusts | Ibiza Model Wave | Ibiza Fetch Risk |\n")
            f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
            current_day_str = day_str
            
        p_fetch = get_fetch_wave("palma", palma_wave, i, p_wav)
        i_fetch = get_fetch_wave("ibiza", ibiza_wave, i, i_wav)
        
        p_wind_dir = f"{get_cardinal(pw['direction'])} {get_direction_arrow(pw['direction'])}"
        p_wave_dir = f"{get_cardinal(p_wav['direction'])} {get_direction_arrow(p_wav['direction'])}"
        
        i_wind_dir = f"{get_cardinal(iw['direction'])} {get_direction_arrow(iw['direction'])}"
        i_wave_dir = f"{get_cardinal(i_wav['direction'])} {get_direction_arrow(i_wav['direction'])}"
        
        p_wind_str = f"{pw['value']:.1f} kn ({p_wind_dir})"
        p_gust_str = f"{pw['gust']:.1f} kn"
        p_wave_str = f"{p_wav['value']:.2f} m ({p_wave_dir})"
        p_fetch_str = f"**{p_fetch:.2f} m**" if p_fetch > p_wav["value"] else f"{p_fetch:.2f} m"
        
        i_wind_str = f"{iw['value']:.1f} kn ({i_wind_dir})"
        i_gust_str = f"{iw['gust']:.1f} kn"
        i_wave_str = f"{i_wav['value']:.2f} m ({i_wave_dir})"
        i_fetch_str = f"**{i_fetch:.2f} m**" if i_fetch > i_wav["value"] else f"{i_fetch:.2f} m"
        
        f.write(f"| {dt_utc.strftime('%H:%M')} | {p_wind_str} | {p_gust_str} | {p_wave_str} | {p_fetch_str} | {i_wind_str} | {i_gust_str} | {i_wave_str} | {i_fetch_str} |\n")

print(f"Hourly forecast table generated at: {output_file}")
