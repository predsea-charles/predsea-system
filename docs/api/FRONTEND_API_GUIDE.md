# PredSea Frontend API Guide

This guide is a complete, interactive integration manual for frontend developers. It describes every production endpoint on the PredSea backend, organized by frontend use case, alongside realistic examples and active data registries.

---

## 🌐 Production Environment

*   **Production API Base URL:** `https://predsea-api-193957983101.europe-west1.run.app`
*   **Interactive Swagger Documentation:** [https://predsea-api-193957983101.europe-west1.run.app/docs](https://predsea-api-193957983101.europe-west1.run.app/docs)
*   **Redoc Alternative Documentation:** [https://predsea-api-193957983101.europe-west1.run.app/redoc](https://predsea-api-193957983101.europe-west1.run.app/redoc)

---

## 🗂️ Endpoints organized by Use Case

### 1. Application Bootstrap & System Health
These endpoints are requested once during application launch or used to display status/system parameters.

#### `GET /health`
*   **Purpose:** Check backend API status and database availability.
*   **Authentication:** None.
*   **Response Structure:**
    ```json
    { "status": "healthy", "version": "2.0.0", "timestamp": "2026-07-10T12:00:00Z" }
    ```
*   **cURL Example:**
    ```bash
    curl -X GET "https://predsea-api-193957983101.europe-west1.run.app/health"
    ```
*   **TypeScript Invocation:**
    ```typescript
    const status = await sdk.validation.getHealth();
    ```

#### `GET /navigation/magnetic-variation`
*   **Purpose:** Fetch magnetic declination/variation for navigation calculations.
*   **Query Parameters:** `latitude` (float), `longitude` (float)
*   **Response Structure:**
    ```json
    { "latitude": 43.727, "longitude": 7.361, "magnetic_variation_deg": 1.4 }
    ```

---

### 2. Places Directory
Managing, selecting, and mapping geographical ports, shelters, and coastal areas.

#### `GET /places`
*   **Purpose:** Retrieves all canonical ports, cities, and shelters. Use this to populate origin/destination drop-down menus.
*   **Response Structure:**
    ```json
    [
      {
        "id": "palma",
        "name": "Palma",
        "latitude": 39.5696,
        "longitude": 2.6502,
        "type": "main_port",
        "aliases": ["Palma de Mallorca"]
      }
    ]
    ```

#### `GET /places/resolve`
*   **Purpose:** Resolves a fuzzy string or alias to a canonical Place ID.
*   **Query Parameters:** `query` (string)
*   **Response Example (`query=èze-sur-mer`):**
    ```json
    { "resolved": true, "place_id": "eze", "canonical_name": "Èze" }
    ```

#### `GET /places/{place_id}/weather`
*   **Purpose:** Retrieves specific marine conditions and weather summaries for a port.
*   **Response Structure:**
    ```json
    {
      "place_id": "eze",
      "name": "Èze-sur-Mer",
      "temperature_c": 24.5,
      "wind_speed_kn": 12.4,
      "wind_direction_deg": 185.0,
      "wave_height_m": 0.42,
      "current_speed_kn": 0.15,
      "source": "copernicus_nrt"
    }
    ```

---

### 3. Sea Routes & Waypoints
Loading geometric lines, briefings, and voyage safety metrics.

#### `GET /routes`
*   **Purpose:** Retrieves the list of preconfigured route objects, including metadata and summary descriptors.
*   **Response Structure:**
    ```json
    [
      {
        "id": "nice_eze",
        "name": "Nice -> Èze-sur-Mer",
        "origin": { "name": "Nice", "latitude": 43.696, "longitude": 7.272 },
        "destination": { "name": "Èze-sur-Mer", "latitude": 43.727, "longitude": 7.361 }
      }
    ]
    ```

#### `GET /places/route/{origin}/{destination}`
*   **Purpose:** Computes the high-resolution, navigable waypoints along the sea route avoiding land. **Use this to draw lines on Leaflet/Mapbox.**
*   **Response Structure:**
    ```json
    {
      "route_id": "nice_eze",
      "distance_nm": 6.8,
      "waypoints": [
        [43.696, 7.272],
        [43.702, 7.305],
        [43.727, 7.361]
      ]
    }
    ```

#### `GET /routes/{route_id}/briefing`
*   **Purpose:** Generates a structured Markdown Captain's Briefing, containing specific wave, wind, current summaries, and overall passage feasibility ratings (e.g. `Manageable`, `Caution`, `Unsafe`).
*   **Response Structure:**
    ```json
    {
      "route_id": "nice_eze",
      "feasibility": "Manageable",
      "wave_max_m": 0.45,
      "current_max_kn": 0.22,
      "briefing_markdown": "### Passage Briefing\nNo critical anomalies are expected..."
    }
    ```

#### `GET /routes/{route_id}/evidence`
*   **Purpose:** Detailed hourly/timeline marine conditions along all sampling points.
*   **Response Structure:**
    ```json
    {
      "route_id": "nice_eze",
      "timesteps": ["2026-07-10T12:00:00Z", "2026-07-10T13:00:00Z"],
      "wave_heights": [0.38, 0.42],
      "wind_speeds": [11.2, 12.4]
    }
    ```

#### `GET /routes/{route_id}/artifacts/{artifact_name}`
*   **Purpose:** Retrieves pre-rendered PNG graphics (like `route_decision_map.png`).

---

### 4. Conversational Assistant
Direct interaction with PredSea's oceanographic AI model.

#### `POST /question`
*   **Purpose:** Generates location-aware advice from raw coordinates or coordinates linked to a location.
*   **Request Body:**
    ```json
    { "latitude": 43.727, "longitude": 7.361, "query": "What is the wave trend?" }
    ```

#### `POST /routes/{route_id}/question`
*   **Purpose:** Generates route-aware advice using stored passage weather evidence.
*   **Request Body:**
    ```json
    { "query": "Is there a swell acceleration near Saint-Jean-Cap-Ferrat?" }
    ```

---

## 📊 Active Dataset References

### 1. Active Ports & Coastal Places (76 Total)
These places support localized weather inquiries (`GET /places/{place_id}/weather`):

*   **Ports:** Ajaccio, Alcudia, Alghero, Alicante, Almería, Antibes, Arbatax, Bastia, Bonifacio, Cagliari, Cala d'Or, Calvi, Can Pastilla, Cannes, Cartagena, Ciutadella, Dénia, Genoa, Gibraltar, La Ciotat, Marseille, Messina, Monaco, Montpellier (Sète), Málaga, Naples, Nice, Olbia, Palamos, Palermo, Palma, Port Adriano, Port Vell, Port de Palma, Porto Cervo, Porto Cristo, Porto Rotondo, Porto Vecchio, Portocolom, Puerto Banús, Roses, Saint-Tropez, Santa Eulària, Santa Teresa Gallura, Soller, Sotogrande, Théoule-sur-Mer, Toulon, Villefranche-sur-Mer
*   **Main Places:** Barcelona, Cabrera, Formentera, Ibiza, Marbella, Menorca, Tarragona, Valencia, Èze
*   **Coastal Areas:** Balearic Sea, Bonifacio Strait, Costa Brava, French Riviera, Gulf of Lion, Ligurian Sea, Tyrrhenian Sea, Western Mediterranean, Tuscany, Lazio

### 2. Available Routes (123 Total)
These routes can be requested via `GET /routes/{route_id}/briefing` or `GET /routes/{route_id}/evidence`:

*   **Èze-sur-Mer Connectors:**
    *   `eze_cannes` (Èze-sur-Mer -> Cannes)
    *   `eze_monaco` (Èze-sur-Mer -> Monaco)
    *   `eze_naples` (Èze-sur-Mer -> Naples)
    *   `eze_cagliari` (Èze-sur-Mer -> Cagliari)
    *   `eze_tuscany` (Èze-sur-Mer -> Tuscany)
    *   `eze_lazio` (Èze-sur-Mer -> Lazio)
    *   `eze_barcelona` (Èze-sur-Mer -> Barcelona)
    *   `eze_palma` (Èze-sur-Mer -> Palma)
    *   `eze_marseille` (Èze-sur-Mer -> Marseille)
    *   `eze_montpellier` (Èze-sur-Mer -> Montpellier)
*   **Nice & Monaco Links:** `nice_eze`, `nice_monaco`
*   **French Riviera Links:** `saint_tropez_cannes`, `cannes_antibes`, `antibes_nice`
*   **Major Western Mediterranean Corridors:**
    *   `barcelona_marseille`
    *   `marseille_cagliari`
    *   `monaco_cagliari`
    *   `palma_barcelona`
    *   `palma_marseille`
    *   `palma_nice`
    *   `palma_monaco`
    *   `palma_bonifacio`
    *   `palma_portocervo`
    *   `palma_olbia`
    *   `ibiza_denia`
    *   `ibiza_valencia`
    *   `mahon_bonifacio`
    *   `bonifacio_portocervo`
    *   `portocervo_olbia`

### 3. Active Observation Stations & Physical Sensors
These coordinates retrieve physical live observation verification metrics:
*   **Spain (SOCIB Buoys):** `socib_buoy_palma`, `socib_buoy_cabre`, `socib_buoy_ibiza`, `socib_buoy_mahon`
*   **France (Copernicus In-Situ):** `copernicus_insitu_62001`, `copernicus_insitu_62002` (French Riviera coastal moorings)
*   **Italy (Copernicus In-Situ):** `copernicus_insitu_61001` (Sardinia Basin buoy), `copernicus_insitu_61243` (Tuscany/Lazio coastal array)
