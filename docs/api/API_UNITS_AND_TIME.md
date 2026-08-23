# PredSea Marine Units and Time Semantics Reference

Marine navigation requires strict compliance with geographical coordinates, oceanographic variables, and absolute time semantics. This guide defines how PredSea formats and interprets these fields.

---

## 📐 Oceanographic & Meteorological Variables

The API delivers all physical metrics using standard nautical and scientific units. **The frontend must preserve these units exactly and display them as specified below:**

| Physical Variable | Meaning | Unit | Valid Range | JSON Field Name (Examples) |
| :--- | :--- | :--- | :--- | :--- |
| **Latitude** | Decimal latitude | Degrees North | $-90.0 \text{ to } +90.0$ | `latitude` |
| **Longitude** | Decimal longitude | Degrees East | $-180.0 \text{ to } +180.0$ | `longitude` |
| **Distance** | Sea-distance between points | Nautical Miles (NM) | $\ge 0.0$ | `distance_nm` |
| **Wind Speed** | Meteorological wind velocity | Knots (kn) | $0.0 \text{ to } 120.0$ | `wind_speed_kn` |
| **Wind Direction** | Heading wind is coming *from* | Degrees ($^\circ$ True) | $0.0 \text{ to } 360.0$ | `wind_direction_deg` |
| **Wave Height** | Significant wave height ($H_s$) | Meters (m) | $0.0 \text{ to } 15.0$ | `wave_height_m`, `wave_max_m` |
| **Wave Period** | Peak wave period ($T_p$) | Seconds (s) | $0.0 \text{ to } 25.0$ | `wave_period_s` |
| **Wave Direction** | Direction waves are travelling *to*| Degrees ($^\circ$ True) | $0.0 \text{ to } 360.0$ | `wave_direction_deg` |
| **Current Speed**| Significant surface ocean current | Knots (kn) | $0.0 \text{ to } 6.0$ | `current_speed_kn` |
| **Current Direction**| Direction current is moving *to* | Degrees ($^\circ$ True) | $0.0 \text{ to } 360.0$ | `current_direction_deg`|

---

## ⏰ Time Semantics & Conversions

The backend is the authoritative source for all timelines and models. **All timestamps are strict ISO-8601 UTC formats (`YYYY-MM-DDTHH:MM:SSZ`).**

The frontend may convert UTC timestamps to the captain's local device timezone for local screen display, but must **never** modify or reinterpret the raw payload timestamp for backend requests.

### Key Timestamps Explained:

1.  **Forecast Generation Time (`forecast_run_at`):**
    *   The timestamp when the meteorological or numerical models completed their run on GCP.
2.  **Forecast Valid Time (`valid_at` / `timestep`):**
    *   The specific hourly target slice representing the ocean state. All wave and wind values in evidence timelines represent the environment *at* this specific valid time.
3.  **Observation Time (`observed_at_utc`):**
    *   The precise UTC time that a physical sensor (SOCIB buoy or Copernicus Mooring) recorded a real physical value in-situ.
4.  **Client-Side Display Conversion:**
    *   To display time on-screen, use standard timezone conversions:
    ```typescript
    const utcDate = new Date(apiTimestamp); // Parsed correctly as UTC due to 'Z' suffix
    const localTimeString = utcDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    ```
