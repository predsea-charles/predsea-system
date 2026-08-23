# 🌊 PredSea API Technical Briefing & Endpoint Specification
## 🧭 Comprehensive Conceptual & Technical Manual

This technical document outlines the architecture, data layers, endpoint specifications, routing behavior, and operational analysis of the PredSea Forecasting, Simulation, and Routing Engine. It serves as both a high-level conceptual manual and a concrete technical reference for engineering, oceanographic, and product teams.

---

## 🏗️ 1. Technical Architecture & Forecast Horizons

PredSea utilizes a **hybrid-resolution temporal and spatial architecture** to balance highly accurate localized coastal simulations with global maritime routing forecasts:

```
[Days 1-5 / 0-120 Hours]  ===================> High-Resolution Local Simulations (1h intervals)
                                              (WRF 1.3km | ROMS/NEMO 1km | SWAN 1km)

[Days 6-10 / 121-240 Hours] ================> Global Coarser Forecasts (6h intervals)
                                              (ECMWF 9km | Copernicus Marine 4.2km)
```

### 🌍 The 10-Day Hybrid-Resolution Forecasting Strategy

Running localized high-resolution simulations over a full 10-day (240 hours) horizon presents exponential compute, file storage, and data transfer costs. To achieve optimal performance and utility, PredSea implements a **two-tier temporal and spatial hybrid architecture**:

| Forecast Phase | Horizon | Spatial Resolution | Time Resolution | Data Sources |
| :--- | :--- | :--- | :--- | :--- |
| **Short-Range** | Days 1–5 (0–120h) | **High-Res (~1 km to 1.3 km)** | **Hourly (1h)** | Local nested **WRF**, **ROMS**, **NEMO**, and **SWAN** simulations. |
| **Long-Range** | Days 6–10 (121–240h) | **Standard (~4.2 km to 9 km)** | **6-Hourly (6h)** | **ECMWF** Open Data wind & **Copernicus Marine (CMEMS)** waves and currents. |

#### Why 5 Days at High-Resolution and 5 Days Coarser?
1. **Physical Predictability Limits**:
   High-resolution coastal models (1 km) are designed to capture non-hydrostatic atmospheric details (such as land-sea thermal contrasts driving sea breezes) and localized wave refraction. Beyond Day 5, global boundary-condition errors dominate. Running a 1 km simulation at Day 8 provides no additional physical accuracy compared to standard forecasts.
2. **Computational & Financial Efficiency**:
   A 24-hour run of our localized 1 km models takes ~20 minutes on a 16 vCPU Spot instance. Running this for 240 hours would take over **2.5 hours**, increasing Spot VM preemption risk and scaling VM runtime costs.
3. **Storage & Bandwidth Optimization**:
   Full 10-day hourly NetCDF outputs scale file sizes from 4 GB up to **40+ GB daily**, multiplying cloud bandwidth costs. Subsampling to 6-hour global data for Days 6–10 keeps GCS transfer times fast and API latency low.

---

## 🔌 2. API Endpoints Specification & Routing Engine

All endpoints are hosted via our serverless FastAPI engine. 

### 🧭 2.1 Multi-Mode Routing & Coordinate-Place Splicing
Our routing engine supports **four routing modes** by seamlessly mixing and matching named places with raw coordinates:

```
Mode A: Name ───> Name      (e.g., /places/route/palma/cagliari)
Mode B: Coords ─> Coords    (e.g., /places/route/custom/custom?origin_latitude=39.52...)
Mode C: Name ───> Coords    (e.g., /places/route/palma/custom?destination_latitude=39.21...)
Mode D: Coords ─> Name      (e.g., /places/route/custom/cagliari?origin_latitude=39.52...)
```

#### How Name and Coordinate Overrides Work (Conceptual Guide)
* **Path Parameter Resolution**: The `{origin}` and `{destination}` path parameters are treated as queries. The engine checks them against `places_seed_balearics.json` and `aliases_balearics.json`.
* **Registry Fallback**: If you omit coordinates for a side, the engine uses the exact coordinates registered for that place.
* **Coordinate Precedence**: If you supply coordinates (e.g. `origin_latitude` & `origin_longitude`), they **always take precedence** over the name's database coordinates.
* **Spliced Metadata**: If you provide a valid place name (e.g., `palma`) AND coordinates for that side, the engine will use your custom coordinates for the routing grid, but it will still attach the resolved `place_name` and `place_id` metadata to the response! This allows you to say "Departing from Palma harbor, but with my custom GPS coordinates."

---

### 🔌 2.2 Endpoint Reference

#### `GET /places/route/{origin}/{destination}`
*   **Summary**: Compute optimal navigable sea route waypoints.
*   **Routing Logic**:
    *   **Within Western Med Bounds**: Calls our custom **4D A* Metocean Weather Routing Engine** (`astar_weather_route_v1`). It models spatial land cells as search obstacles, adjusts vessel speed based on projected current vectors, and applies quadratic penalties for wave heights ($H_s^2$).
    *   **Outside Bounds**: Safely falls back to the static `searoute` library (`graph_sea_route_v1`).
*   **Parameters**:
    *   `origin` (str, required): Place ID or `"custom"`.
    *   `destination` (str, required): Place ID or `"custom"`.
    *   `origin_latitude` (float, optional): Exact coordinate override.
    *   `origin_longitude` (float, optional): Exact coordinate override.
    *   `destination_latitude` (float, optional): Exact coordinate override.
    *   `destination_longitude` (float, optional): Exact coordinate override.
    *   `typical_speed_kn` (float, optional, default `15.0`): Speed of vessel in knots.
    *   `departure_time` (str, optional, default `"08:30"`): local departure time format `HH:MM`.
*   **Expected Output**:
    ```json
    {
      "origin_place_id": "palma",
      "origin_place_name": "Palma",
      "destination_place_id": "custom",
      "destination_place_name": "custom",
      "distance_nm": 338.17,
      "estimated_time_h": 22.28,
      "typical_speed_kn": 15.0,
      "source_tag": "astar_weather_route_v1",
      "waypoints": [
        {"lat": 39.52, "lng": 2.58, "name": "Start"},
        {"lat": 39.41, "lng": 2.82, "name": "Waypoint 1"},
        ...
      ]
    }
    ```

---

#### `GET /routes/optimal/{origin}/{destination}`
*   **Summary**: Return weather-optimized routes with hourly meteorological metrics plotted along each waypoint of the voyage.
*   **Parameters**: Same as `/places/route/{origin}/{destination}`.
*   **Expected Output**: Includes detailed metocean forecast metrics (wind, wave, current, temperatures) blended for the voyage's timeline at each waypoint.

---

### 🌤️ Weather & Oceanic Inquiries

#### `GET /places/{place_id}/weather`
*   **Summary**: Fetch the combined weather package for a canonical port or passage.
*   **Observations**: Injects live measurements from the closest physical oceanographic buoy.
*   **Expected Output**:
    *   `live_observations`: Wave heights, sea surface temperature, and wind vectors from active sensors.
    *   `hourly`: 240-hour continuous timeline containing blended wind speed, air/water temperatures, tide elevations, wave vectors, swells, and current speed/directions.

#### `GET /locations/weather`
*   **Summary**: Fetch a blended 10-day weather package for a raw, arbitrary coordinate pair (`latitude`, `longitude`) by dynamically resolving the nearest grid cells.

---

## 🕒 3. Daily ETL Pipeline Run Time

The complete end-to-end Daily ETL Pipeline operates autonomously on Google Cloud Platform:

```
[04:00 UTC] ──> Boundary Download (CMEMS & ECMWF) ──> Launch Spot VM (16 vCPUs) ──> WRF/ROMS/SWAN Simulation (120h) ──> BigQuery & GCS Upload ──> Observation Ingestion & Briefing [Done]
```

*   **Phase 1: Boundary Fetching** (`~10 mins`): Downloads parent meteorological and hydrodynamic boundaries.
*   **Phase 2: Numerical Simulations** (`~90 mins`): Executes WRF, ROMS, and SWAN models in parallel for 120 hours.
*   **Phase 3: Database & Ingestion Loading** (`~15 mins`): Ingests physical prediction grids into GCS and BigQuery.
*   **Phase 4: Diagnostics, Buoys, & Renderers** (`~5 mins`): Fetches physical buoy streams and generates Leaflet tile layers.
*   **Total Duration**: **`1 hour 45 minutes to 2 hours`** from end to end.

---

## 💰 4. Daily & Monthly Operational Cost Analysis

Our serverless, Spot-VM-based architecture is highly optimized for cost-efficiency. It operates well within the team's €2,000 budget:

### 1. Compute Costs (Spot VMs)
*   **Instance**: `c2d-standard-16` (16 vCPUs, 64 GiB RAM) in `europe-west1` (Belgium).
*   **Spot VM Price (60-80% discount)**: **`~$0.20 / hour`**.
*   **Daily Run Cost** (2 hours): **`~$0.40 / day`**.
*   **Monthly Compute Total**: **`~$12.00 / month`**.

### 2. Tabular Database Costs (BigQuery)
*   **Storage**: Tabular logs consume ~3 GB of storage annually.
*   **Monthly Database Storage**: **`~$0.06 / month`**.
*   **Query Scans**: Date-partitioning and clustering restrict query scans to the active daily partition.
    *   All API lookups fit entirely within the **1 TB/month BigQuery free tier** ($0.00).

### 3. Object Storage Costs (Google Cloud Storage)
*   **GCS Storage**: Stores raw NetCDFs (~4 GB/day) and prepackaged JSON.
*   **Lifecycle Policy**: Transferred automatically to `Nearline` archive storage after 30 days.
*   **Monthly GCS Storage**: **`~$6.00 / month`**.

### 4. Serverless Serving Costs (Cloud Run & Build)
*   **Cloud Run (FastAPI API)**: Serves standard client traffic easily within GCP's serverless free tiers.
*   **Monthly Serverless Cost**: **`~$1.50 / month`**.

---

### 💳 Summary of Total Expenses
*   **Daily Running Cost**: **`~$0.60 / day`**
*   **Total Monthly Operational Cost**: **`~$19.50 / month`**
