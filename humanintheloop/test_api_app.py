import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from api.app import create_app, resolve_map_forecast_files
from api.evidence_store import EvidenceStore, GcsEvidenceStore
import api.warnings_service as warnings_service
import place_registry


def test_resolve_map_forecast_files_prefers_predsea_run_bundle(tmp_path):
    downloaded = []

    class Blob:
        def __init__(self, name):
            self.name = name

        def exists(self):
            return self.name.startswith(
                "predictions/2026-07-16/runs/run-123/forecast_bundle/"
            )

        def download_to_filename(self, destination):
            Path(destination).write_bytes(self.name.encode())
            downloaded.append(self.name)

    class Bucket:
        def blob(self, name):
            return Blob(name)

    class Client:
        def bucket(self, name):
            assert name == "staging-bucket"
            return Bucket()

    store = type(
        "Store",
        (),
        {
            "storage_backend": "gcs",
            "bucket_name": "staging-bucket",
            "client": Client(),
            "_base_prefix": lambda self, run_date, run_id: (
                f"predictions/{run_date}/runs/{run_id or 'run-123'}"
            ),
        },
    )()

    waves, currents = resolve_map_forecast_files(
        store,
        "2026-07-16",
        "run-123",
        tmp_path,
    )

    assert waves.exists()
    assert currents.exists()
    assert downloaded == [
        "predictions/2026-07-16/runs/run-123/forecast_bundle/predsea_waves.nc",
        "predictions/2026-07-16/runs/run-123/forecast_bundle/predsea_ocean.nc",
    ]


class FakeRouteStore:
    def __init__(self):
        self._results = {
            ("palma", "ibiza", "comfort", "medium"): {
                "origin_place_id": "palma",
                "destination_place_id": "ibiza",
                "priority": "comfort",
                "vessel_class": "medium",
                "distance_nm": 46.2,
                "estimated_time_h": 3.1,
                "avg_wave_hs_m": 0.8,
                "max_wave_hs_m": 1.1,
                "avg_current_kn": 0.4,
                "favourable_current_pct": 61.0,
                "forecast_run_utc": "2026-06-14T1049Z",
                "computed_at_utc": "2026-06-14T11:00Z",
                "waypoints": [{"lat": 39.5, "lon": 2.6}],
            },
            ("palma", "ibiza", "time", "medium"): {
                "origin_place_id": "palma",
                "destination_place_id": "ibiza",
                "priority": "time",
                "vessel_class": "medium",
                "distance_nm": 46.2,
                "estimated_time_h": 3.0,
                "avg_wave_hs_m": 0.7,
                "max_wave_hs_m": 1.0,
                "avg_current_kn": 0.5,
                "favourable_current_pct": 64.0,
                "forecast_run_utc": "2026-06-14T1049Z",
                "computed_at_utc": "2026-06-14T11:00Z",
                "waypoints": [{"lat": 39.5, "lon": 2.6}],
            },
        }

    def get(self, origin, destination, priority="comfort", vessel_class="medium"):
        return self._results.get((origin, destination, priority, vessel_class))

    def get_distance_nm(self, origin, destination):
        result = self.get(origin, destination, priority="time", vessel_class="medium")
        return None if result is None else result["distance_nm"]

    def get_typical_time_h(self, origin, destination, vessel_class="medium"):
        result = self.get(origin, destination, priority="time", vessel_class=vessel_class)
        return None if result is None else result["estimated_time_h"]

    def status(self):
        return {"loaded_date": "2026-06-14", "loaded_at": "2026-06-14T11:00Z", "route_count": len(self._results)}


class DummyDistanceResolver:
    def __init__(self):
        self.calls = []

    def resolve(self, origin_place_id, destination_place_id):
        self.calls.append((origin_place_id, destination_place_id))
        return {
            "origin_place_id": origin_place_id,
            "origin_place_name": origin_place_id.title(),
            "destination_place_id": destination_place_id,
            "destination_place_name": destination_place_id.title(),
            "distance_nm": 77.7,
            "typical_speed_kn": 15.0,
            "typical_travel_time_minutes": 311,
            "computed_at_utc": "2026-06-15 10:00 UTC",
            "source_tag": "graph_sea_route_v1",
        }


def write_snapshot(root, date_text="2026-05-29", route_id="ibiza_palma", run_id=None, source_summary=None):
    if run_id:
        route_dir = Path(root) / date_text / "runs" / run_id / route_id
    else:
        route_dir = Path(root) / date_text / route_id
    route_dir.mkdir(parents=True)
    snapshot = {
        "route": "Palma -> Ibiza",
        "route_id": route_id,
        "vessel_class": "medium",
        "vessel_profile": {"label": "15-24m", "manageable_m": 1.5, "restricted_m": 2.2},
        "created_at_utc": "2026-05-29 06:30 UTC",
        "observations": {
            "canal_de_ibiza": {
                "name": "Buoy Canal de Ibiza",
                "last_sample_utc": "2026-05-29 06:30 UTC",
                "wave_height_m": 0.4,
            }
        },
        "forecast": {
            "wave_min_m": 0.3,
            "wave_max_m": 0.5,
            "wave_peak_time": "08:00",
            "current_max_kn": 0.3,
            "current_peak_time": "15:00",
            "hourly": [
                {"time": "08:00", "wave_m": 0.5, "current_kn": 0.1},
                {"time": "17:00", "wave_m": 0.4, "current_kn": 0.3},
            ],
        },
        "recommendation": {
            "best_window": "most daylight windows look manageable",
            "watch_out": "no major wave build-up in the 24h forecast",
            "confidence": "medium",
            "vessel_severity": "manageable",
            "vessel_advice": "manageable for vessels 15-24m",
        },
    }
    if source_summary is not None:
        snapshot["source_summary"] = source_summary
        snapshot["data_lineage"] = {
            "wind_forecast": {
                "source": "ecmwf_open_data",
                "resolution_km": 9.0,
                "status": "active",
                "tier": 3,
            },
            "ocean_forecast": {
                "source": "copernicus_med",
                "resolution_km": 4.0,
                "status": "active",
            },
            "ground_truth_validation": {
                "source": "puertos_observations",
                "status": "matched_successfully",
                "station_count": 1,
            },
            "source_summary": source_summary,
        }
    (route_dir / "daily_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    return snapshot


def utc_text(minutes_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M UTC")


def write_place_weather(root, date_text, run_id, place_id, *, source_label, wave_height_m, observed_at_utc, network=None):
    place_dir = Path(root) / date_text / "runs" / run_id / "places" / place_id
    place_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "place_id": place_id,
        "place_name": place_id.replace("_", " ").title(),
        "source_label": source_label,
        "network": network or source_label,
        "observed_at_utc": observed_at_utc,
        "source_time_coordinate_utc": observed_at_utc,
        "freshness_status": "fresh",
        "freshness_state": "LIVE",
        "freshness_warning": None,
        "wave_height_m": wave_height_m,
        "wind_kn": 12.0,
        "wind_direction_deg": 90.0,
        "current_kn": 0.4,
        "hourly": [
            {
                "time": "08:00",
                "time_utc": observed_at_utc,
                "wave_m": wave_height_m,
                "current_kn": 0.4,
            }
        ],
    }
    (place_dir / "weather.json").write_text(json.dumps(payload), encoding="utf-8")
    return payload


def write_run_snapshot(
    root,
    date_text="2026-05-29",
    run_id="2026-05-29T0630Z",
    route_id="ibiza_palma",
    wave_max=0.5,
    created_at_utc="2026-05-29 06:30 UTC",
):
    route_dir = Path(root) / date_text / "runs" / run_id / route_id
    route_dir.mkdir(parents=True)
    snapshot = write_snapshot_data(route_id, wave_max, created_at_utc=created_at_utc)
    (route_dir / "daily_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (route_dir / "route_decision_map.png").write_bytes(b"fake-png")
    (Path(root) / date_text / "latest_run.json").write_text(
        json.dumps({"run_id": run_id, "path": f"runs/{run_id}"}),
        encoding="utf-8",
    )
    return snapshot


def write_map_overlay(root, date_text="2026-05-31", run_id="2026-05-31T1230Z", variable="wave_height"):
    maps_dir = Path(root) / date_text / "runs" / run_id / "maps" / variable
    maps_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{variable}_20260531_140000Z.png"
    grid_filename = f"{variable}_20260531_140000Z.grid.json"
    (maps_dir / filename).write_bytes(b"overlay-png")
    (maps_dir / grid_filename).write_text(
        json.dumps(
            {
                "latitudes": [38.5, 39.5, 40.5],
                "longitudes": [1.0, 2.0, 3.0, 4.5],
                "values": [
                    [0.4, 0.5, 0.6, 0.7],
                    [0.8, 0.9, 1.0, 1.1],
                    [1.2, 1.3, 1.4, 1.5],
                ],
            }
        ),
        encoding="utf-8",
    )
    midnight_filename = f"{variable}_20260531_000000Z.png"
    midnight_grid_filename = f"{variable}_20260531_000000Z.grid.json"
    (maps_dir / midnight_filename).write_bytes(b"midnight-png")
    (maps_dir / midnight_grid_filename).write_text(
        json.dumps(
            {
                "latitudes": [38.5, 39.5, 40.5],
                "longitudes": [1.0, 2.0, 3.0, 4.5],
                "values": [
                    [0.1, 0.2, 0.3, 0.4],
                    [0.5, 0.6, 0.7, 0.8],
                    [0.9, 1.0, 1.1, 1.2],
                ],
            }
        ),
        encoding="utf-8",
    )
    (maps_dir / "index.json").write_text(
        json.dumps(
            {
                "variable": variable,
                "units": "m",
                "color_scale": {"min": 0, "max": 2.5, "palette": "turbo"},
                "opacity": 0.698,
                "overlays": [
                    {
                        "time": "2026-05-31T00:00:00Z",
                        "filename": midnight_filename,
                        "grid_filename": midnight_grid_filename,
                        "bounds": [[38.5, 1.0], [40.5, 4.5]],
                    },
                    {
                        "time": "2026-05-31T14:00:00Z",
                        "filename": filename,
                        "grid_filename": grid_filename,
                        "bounds": [[38.5, 1.0], [40.5, 4.5]],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return filename


def write_regional_evidence(root, date_text="2026-05-31", run_id="2026-05-31T1230Z"):
    run_dir = Path(root) / date_text / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    regional = {
        "region_id": "balearics",
        "run_date": date_text,
        "run_id": run_id,
        "supported_modes": ["route_question", "location_question", "map_inspect"],
        "available_variables": {
            "wave_height": {"units": "m", "time_count": 2, "bounds": [[38.5, 1.0], [40.5, 4.5]]},
            "current_speed": {"units": "m/s", "time_count": 2, "bounds": [[38.5, 1.0], [40.5, 4.5]]},
        },
        "limitations": [
            "No seabed type",
            "No depth/bathymetry",
            "No anchoring restrictions",
            "No nearby shelter search",
        ],
    }
    (run_dir / "regional_evidence.json").write_text(json.dumps(regional), encoding="utf-8")
    return regional


def write_place_weather(
    root,
    date_text="2026-05-31",
    run_id="2026-05-31T1230Z",
    place_id="ibiza",
    source_label="REDEXT",
    wave_height_m=0.8,
    observed_at_utc="2026-05-31 08:00 UTC",
    network=None,
):
    place_dir = Path(root) / date_text / "runs" / run_id / "places" / place_id
    place_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "place_id": place_id,
        "place_name": "Ibiza",
        "date": date_text,
        "run": run_id,
        "timezone": "Europe/Madrid",
        "time_utc": observed_at_utc,
        "time_local": "2026-05-31 10:00 LT",
        "wave_height_m": wave_height_m,
        "wave_direction_deg": 72.0,
        "swell_1_height_m": 0.5,
        "swell_1_direction_deg": 68.0,
        "wind_kn": 12.0,
        "wind_direction_deg": 70.0,
        "current_kn": 0.4,
        "current_direction_deg": 90.0,
        "source": "copernicus_med",
        "source_system": "place_weather",
        "source_label": source_label,
        "network": network or source_label,
        "freshness_status": "fresh",
        "freshness_warning": None,
        "hourly": [
            {
                "time": "10:00",
                "time_utc": observed_at_utc,
                "wave_m": wave_height_m,
                "wave_direction_deg": 72.0,
                "wave_sea_state": "beam sea",
                "current_kn": 0.4,
            }
        ],
        "observation": {
            "station_id": "canal_de_ibiza",
            "station_name": "Buoy Canal de Ibiza",
            "source_label": source_label,
            "observed_at_utc": observed_at_utc,
            "wave_height_m": wave_height_m,
        },
    }
    (place_dir / "weather.json").write_text(json.dumps(payload), encoding="utf-8")
    return payload


def write_snapshot_data(route_id="ibiza_palma", wave_max=0.5, created_at_utc="2026-05-29 06:30 UTC"):
    return {
        "route": "Palma -> Ibiza",
        "route_id": route_id,
        "vessel_class": "medium",
        "vessel_profile": {"label": "15-24m", "manageable_m": 1.5, "restricted_m": 2.2},
        "created_at_utc": created_at_utc,
        "observations": {
            "canal_de_ibiza": {
                "name": "Buoy Canal de Ibiza",
                "last_sample_utc": "2026-05-29 06:30 UTC",
                "wave_height_m": 0.4,
            }
        },
        "forecast": {
            "wave_min_m": 0.3,
            "wave_max_m": wave_max,
            "wave_peak_time": "08:00",
            "current_max_kn": 0.3,
            "current_peak_time": "15:00",
            "hourly": [
                {"time": "08:00", "wave_m": wave_max, "current_kn": 0.1},
                {"time": "17:00", "wave_m": 0.4, "current_kn": 0.3},
            ],
        },
        "recommendation": {
            "best_window": "most daylight windows look manageable",
            "watch_out": "no major wave build-up in the 24h forecast",
            "confidence": "medium",
            "vessel_severity": "manageable",
            "vessel_advice": "manageable for vessels 15-24m",
        },
    }


def test_routes_endpoint_lists_routes_from_prediction_artifacts(tmp_path):
    write_snapshot(tmp_path)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/routes?date=2026-05-29")

    assert response.status_code == 200
    assert response.json() == {"date": "2026-05-29", "routes": ["ibiza_palma"]}


def test_routes_endpoint_exposes_progressive_publication_status(tmp_path):
    write_run_snapshot(tmp_path)
    status = {
        "run_date": "2026-05-29",
        "run_id": "2026-05-29T0630Z",
        "publication_phase": "preliminary",
        "wrf_status": "running",
        "message": "External-source forecast is online; WRF refinement is running.",
    }
    status_path = (
        Path(tmp_path)
        / "2026-05-29"
        / "runs"
        / "2026-05-29T0630Z"
        / "publication_status.json"
    )
    status_path.write_text(json.dumps(status), encoding="utf-8")
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/routes?date=2026-05-29&run=latest")

    assert response.status_code == 200
    assert response.json()["publication"] == status


def test_routes_endpoint_falls_back_to_configured_catalog_without_predictions(tmp_path):
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/routes")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "configured_catalog"
    assert payload["date"] is None
    assert "ibiza_palma" in payload["routes"]


def test_places_endpoint_lists_canonical_places(tmp_path):
    write_place_weather(tmp_path)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    # Test paginated list (minimal summary)
    response = client.get("/places?limit=4000")
    assert response.status_code == 200
    payload = response.json()
    assert "total" in payload
    assert "places" in payload
    place_ids = [place["place_id"] for place in payload["places"]]
    assert {"san_antonio", "andratx", "fornells", "addaia", "tarragona", "palamos"}.issubset(set(place_ids))
    
    palma = next(place for place in payload["places"] if place["place_id"] == "palma")
    assert palma["place_name"] == "Palma"
    assert "children" not in palma  # Minimal summary
    
    # Test detail endpoint
    response = client.get("/places/palma")
    assert response.status_code == 200
    palma_detail = response.json()
    assert palma_detail["place_name"] == "Palma"
    assert "port_de_palma" in palma_detail["children"]
    
    response = client.get("/places/ibiza")
    assert response.status_code == 200
    ibiza_detail = response.json()
    assert ibiza_detail["observation_sources"] == ["REDEXT"]


def test_local_store_uses_latest_run_folder_when_available(tmp_path):
    write_run_snapshot(tmp_path, run_id="2026-05-29T0630Z", wave_max=0.5)
    write_run_snapshot(tmp_path, run_id="2026-05-29T1230Z", wave_max=0.8)
    store = EvidenceStore(tmp_path)

    assert store.latest_run("2026-05-29") == "2026-05-29T1230Z"
    assert store.route_ids("2026-05-29") == ["ibiza_palma"]
    assert store.load_snapshot("ibiza_palma", "2026-05-29")["forecast"]["wave_max_m"] == 0.8
    assert store.load_snapshot("ibiza_palma", "2026-05-29", run_id="2026-05-29T0630Z")["forecast"]["wave_max_m"] == 0.5


def test_routes_endpoint_accepts_specific_run_id(tmp_path):
    write_run_snapshot(tmp_path, run_id="2026-05-29T0630Z", wave_max=0.5)
    write_run_snapshot(tmp_path, run_id="2026-05-29T1230Z", wave_max=0.8)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/routes/ibiza_palma/evidence?date=2026-05-29&run=2026-05-29T0630Z")

    assert response.status_code == 200
    payload = response.json()
    assert payload["date"] == "2026-05-29"
    assert payload["run"] == "2026-05-29T0630Z"
    assert payload["evidence"]["forecast"]["wave_max_m"] == 0.5


def test_question_endpoint_answers_from_stored_evidence(tmp_path):
    write_snapshot(tmp_path)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/ibiza_palma/question",
        json={
            "date": "2026-05-29",
            "question": "How will the sea be this afternoon?",
            "vessel_class": "medium",
            "location_label": "Palma Marina",
            "current_time": "09:30",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["route_id"] == "ibiza_palma"
    assert payload["intent"] == "conditions_soon"
    assert payload["freshness_status"] == "current"
    assert payload["freshness_warning"] is None
    assert payload["evidence_timestamp"] == "2026-05-29T06:30Z"
    assert payload["operational_stance"]["decision"] == "Conditions look workable for the next operational window."
    assert payload["operational_stance"]["best_window"] == "during the morning"
    assert payload["operational_stance"]["confidence"] == "Medium"
    assert "Conditions look workable" in payload["answer"]
    assert "Recommendation:" in payload["answer"]
    assert "CURRENT:" in payload["answer"]
    assert "TREND:" in payload["answer"]
    assert "WINDOWS:" in payload["answer"]
    assert "COMFORT:" in payload["answer"]
    assert "WATCH OUT:" in payload["answer"]
    assert "What could change:" in payload["answer"]
    assert "Confidence:" in payload["answer"]
    assert "For this vessel size:" in payload["answer"]
    lowered = payload["answer"].lower()
    assert "safe" not in lowered
    assert "guaranteed smooth" not in lowered
    assert "no issues" not in lowered
    assert payload["evidence_used"]["hourly_points"] == 22
    assert payload["evidence_used"]["observations"] == ["canal_de_ibiza"]


def test_openapi_marks_location_question_coordinates_as_required(tmp_path):
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    openapi = client.get("/openapi.json").json()
    schema = openapi["components"]["schemas"]["LocationQuestionRequest"]
    operation = openapi["paths"]["/question"]["post"]

    assert "latitude" in schema["required"]
    assert "longitude" in schema["required"]
    assert operation["summary"] == "Location question from a shared GPS position"
    assert "must include latitude and longitude" in operation["description"].lower()


def test_question_endpoint_exposes_wave_direction_evidence(tmp_path):
    run_id = "2026-06-09T0630Z"
    route_dir = Path(tmp_path) / "2026-06-09" / "runs" / run_id / "ibiza_palma"
    route_dir.mkdir(parents=True)
    snapshot = write_snapshot_data("ibiza_palma", wave_max=1.3, created_at_utc="2026-06-09 06:30 UTC")
    snapshot["observations"]["canal_de_ibiza"]["wave_from_direction_deg"] = 82.0
    snapshot["forecast"].update(
        {
            "wave_peak_direction_deg": 74.0,
            "swell_1_height_m": 0.8,
            "swell_1_direction_deg": 45.0,
            "swell_2_height_m": 0.4,
            "swell_2_direction_deg": 110.0,
            "wind_wave_height_m": 0.6,
            "wind_wave_direction_deg": 72.0,
            "hourly": [
                {
                    "time": "08:00",
                    "time_utc": "2026-06-09 06:00 UTC",
                    "wave_m": 1.0,
                    "wave_direction_deg": 70.0,
                    "wave_sea_state": "following sea",
                },
                {
                    "time": "10:00",
                    "time_utc": "2026-06-09 08:00 UTC",
                    "wave_m": 1.3,
                    "wave_direction_deg": 74.0,
                    "wave_sea_state": "stern quartering sea",
                },
            ],
        }
    )
    (route_dir / "daily_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (Path(tmp_path) / "2026-06-09" / "latest_run.json").write_text(
        json.dumps({"run_id": run_id, "path": f"runs/{run_id}"}),
        encoding="utf-8",
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/ibiza_palma/question",
        json={
            "date": "2026-06-09",
            "run": "latest",
            "question": "Would Palma to Ibiza feel comfortable this morning?",
            "vessel_class": "medium",
            "current_date": "2026-06-09",
            "current_time": "07:30",
        },
    )

    assert response.status_code == 200
    sea_state = response.json()["evidence_used"]["sea_state"]
    assert sea_state["wave_direction_deg"]["peak"] == 74.0
    assert sea_state["wave_direction_deg"]["hourly"][:2] == [
        {
            "time": "08:00",
            "time_utc": "2026-06-09 06:00 UTC",
            "wave_direction_deg": 70.0,
            "wave_sea_state": "following sea",
        },
        {
            "time": "10:00",
            "time_utc": "2026-06-09 08:00 UTC",
            "wave_direction_deg": 74.0,
            "wave_sea_state": "stern quartering sea",
        },
    ]
    assert len(sea_state["wave_direction_deg"]["hourly"]) == 22
    assert sea_state["components"]["swell_1"]["direction_deg"] == 45.0
    assert sea_state["components"]["swell_2"]["direction_deg"] == 110.0
    assert sea_state["components"]["wind_wave"]["direction_deg"] == 72.0
    assert sea_state["observed_wave_height_m"]["canal_de_ibiza"]["observed_wave_direction_deg"] == 82.0


def test_question_endpoint_reports_passage_evidence_availability(tmp_path):
    route_dir = Path(tmp_path) / "2026-06-07" / "runs" / "2026-06-07T0630Z" / "ibiza_palma"
    route_dir.mkdir(parents=True)
    snapshot = write_snapshot_data(wave_max=1.5, created_at_utc="2026-06-07 06:30 UTC")
    snapshot["forecast"]["route_segments"] = {
        "departure_conditions": {"name": "Palma Bay offshore", "hourly": [{"time": "08:00", "wave_m": 0.5}]},
        "open_water_conditions": {"name": "Mid Palma-Ibiza", "hourly": [{"time": "10:00", "wave_m": 1.5}]},
        "arrival_conditions": {"name": "Ibiza Channel", "hourly": [{"time": "12:00", "wave_m": 1.1}]},
    }
    snapshot["forecast"]["passage_evidence"] = {
        "departure_time": "08:30",
        "vessel_speed_kn": 16,
        "priority": "comfort",
        "segments": [
            {
                "id": "open_water_conditions",
                "label": "Mid Palma-Ibiza",
                "eta": "10:15",
                "sample": {"time": "10:00", "wave_m": 1.5},
                "comfort": "moderate_to_poor",
            }
        ],
        "worst_segment": {
            "id": "open_water_conditions",
            "label": "Mid Palma-Ibiza",
            "time": "10:00",
            "wave_m": 1.5,
            "comfort": "moderate_to_poor",
        },
        "summary": "Worst expected section: Mid Palma-Ibiza near 1.5 m around 10:00.",
    }
    (route_dir / "daily_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (route_dir / "route_decision_map.png").write_bytes(b"fake-png")
    (Path(tmp_path) / "2026-06-07" / "latest_run.json").write_text(
        json.dumps({"run_id": "2026-06-07T0630Z", "path": "runs/2026-06-07T0630Z"}),
        encoding="utf-8",
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    evidence_response = client.get("/routes/ibiza_palma/evidence?date=2026-06-07&run=latest")
    question_response = client.post(
        "/routes/ibiza_palma/question",
        json={
            "date": "2026-06-07",
            "run": "latest",
            "question": "When is the best moment to leave from Palma to Ibiza today?",
            "vessel_class": "medium",
            "current_date": "2026-06-07",
            "current_time": "07:00",
        },
    )

    assert evidence_response.status_code == 200
    assert (
        evidence_response.json()["evidence"]["forecast"]["passage_evidence"]["summary"]
        == "Worst expected section: Mid Palma-Ibiza near 1.5 m around 10:00."
    )
    assert question_response.status_code == 200
    answer = question_response.json()["answer"]
    assert "Recommendation:" in answer
    assert "PASSAGE:" in answer
    evidence_used = question_response.json()["evidence_used"]
    assert evidence_used["passage_evidence"]["available"] is True
    assert evidence_used["passage_evidence"]["worst_segment"] == "Mid Palma-Ibiza"
    assert evidence_used["passage_evidence"]["departure_time"] == "08:30"


def test_question_endpoint_refreshes_stale_passage_evidence_from_route_segments(tmp_path):
    route_dir = Path(tmp_path) / "2026-06-07" / "runs" / "2026-06-07T1034Z" / "ibiza_palma"
    route_dir.mkdir(parents=True)
    snapshot = write_snapshot_data(wave_max=1.6, created_at_utc="2026-06-07 10:34 UTC")
    snapshot["forecast"]["wave_peak_time"] = "17:00"
    snapshot["forecast"]["route_segments"] = {
        "departure_conditions": {
            "name": "Palma Bay offshore",
            "hourly": [
                {"time": "09:00", "wave_m": 0.3, "wave_sea_state": "stern quartering sea"},
                {"time": "00:00", "wave_m": 0.4, "wave_sea_state": "stern quartering sea"},
            ],
        },
        "open_water_conditions": {
            "name": "Mid Palma-Ibiza",
            "hourly": [
                {"time": "11:00", "wave_m": 0.6, "wave_sea_state": "stern quartering sea"},
                {"time": "00:00", "wave_m": 0.7, "wave_sea_state": "stern quartering sea"},
            ],
        },
        "arrival_conditions": {
            "name": "Ibiza Channel",
            "hourly": [
                {"time": "12:00", "wave_m": 0.9, "wave_sea_state": "stern quartering sea"},
                {"time": "00:00", "wave_m": 0.8, "wave_sea_state": "stern quartering sea"},
            ],
        },
    }
    snapshot["forecast"]["passage_evidence"] = {
        "departure_time": "08:30",
        "vessel_speed_kn": 16,
        "priority": "comfort",
        "segments": [],
        "worst_segment": {"label": "Ibiza Channel", "time": "00:00", "wave_m": 0.8},
        "summary": "Worst expected section: Ibiza Channel near 0.8 m around 00:00.",
    }
    (route_dir / "daily_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (Path(tmp_path) / "2026-06-07" / "latest_run.json").write_text(
        json.dumps({"run_id": "2026-06-07T1034Z", "path": "runs/2026-06-07T1034Z"}),
        encoding="utf-8",
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/ibiza_palma/question",
        json={
            "date": "2026-06-07",
            "run": "latest",
            "question": "When is the best moment to leave from Palma to Ibiza today?",
            "vessel_class": "medium",
            "current_date": "2026-06-07",
            "current_time": "12:45",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "The calmer morning window has passed" in payload["answer"]
    assert payload["evidence_used"]["passage_evidence"]["worst_time"] == "12:00"


def test_question_endpoint_uses_requested_departure_time_and_priority_for_passage_evidence(tmp_path):
    route_dir = Path(tmp_path) / "2026-06-07" / "runs" / "2026-06-07T1034Z" / "ibiza_palma"
    route_dir.mkdir(parents=True)
    snapshot = write_snapshot_data(wave_max=1.6, created_at_utc="2026-06-07 10:34 UTC")
    snapshot["forecast"]["wave_peak_time"] = "17:00"
    snapshot["forecast"]["route_segments"] = {
        "departure_conditions": {
            "name": "Palma Bay offshore",
            "hourly": [{"time": "10:00", "wave_m": 0.4}, {"time": "11:00", "wave_m": 0.5}],
        },
        "open_water_conditions": {
            "name": "Mid Palma-Ibiza",
            "hourly": [{"time": "12:00", "wave_m": 0.8}, {"time": "13:00", "wave_m": 1.2}],
        },
        "arrival_conditions": {
            "name": "Ibiza Channel",
            "hourly": [{"time": "13:00", "wave_m": 1.0}, {"time": "14:00", "wave_m": 1.4}],
        },
    }
    (route_dir / "daily_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (Path(tmp_path) / "2026-06-07" / "latest_run.json").write_text(
        json.dumps({"run_id": "2026-06-07T1034Z", "path": "runs/2026-06-07T1034Z"}),
        encoding="utf-8",
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/ibiza_palma/question",
        json={
            "date": "2026-06-07",
            "run": "latest",
            "question": "If we leave at 10:00, what is the operational read?",
            "vessel_class": "medium",
            "departure_time": "10:00",
            "priority": "schedule",
            "current_date": "2026-06-07",
            "current_time": "09:30",
        },
    )

    assert response.status_code == 200
    passage = response.json()["evidence_used"]["passage_evidence"]
    assert passage["departure_time"] == "10:00"
    assert passage["priority"] == "schedule"
    assert passage["worst_time"] == "14:00"


def test_question_endpoint_uses_current_position_for_remaining_passage_evidence(tmp_path):
    route_dir = Path(tmp_path) / "2026-06-07" / "runs" / "2026-06-07T1034Z" / "ibiza_palma"
    route_dir.mkdir(parents=True)
    snapshot = write_snapshot_data(wave_max=1.6, created_at_utc="2026-06-07 10:34 UTC")
    snapshot["forecast"]["route_segments"] = {
        "departure_conditions": {"name": "Palma Bay offshore", "hourly": [{"time": "09:00", "wave_m": 0.5}]},
        "open_water_conditions": {"name": "Mid Palma-Ibiza", "hourly": [{"time": "11:00", "wave_m": 1.0}]},
        "arrival_conditions": {"name": "Ibiza Channel", "hourly": [{"time": "12:00", "wave_m": 1.3}]},
    }
    (route_dir / "daily_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (Path(tmp_path) / "2026-06-07" / "latest_run.json").write_text(
        json.dumps({"run_id": "2026-06-07T1034Z", "path": "runs/2026-06-07T1034Z"}),
        encoding="utf-8",
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/ibiza_palma/question",
        json={
            "date": "2026-06-07",
            "run": "latest",
            "question": "What is ahead of us now?",
            "vessel_class": "medium",
            "departure_time": "08:30",
            "current_latitude": 39.19,
            "current_longitude": 2.04,
            "current_date": "2026-06-07",
            "current_time": "10:30",
        },
    )

    assert response.status_code == 200
    passage = response.json()["evidence_used"]["passage_evidence"]
    assert passage["position_status"] == "on_route"
    assert passage["remaining_segments"] == ["open_water_conditions", "arrival_conditions"]
    assert passage["segment_count"] == 2
    assert passage["worst_segment"] == "Ibiza Channel"


def test_question_endpoint_warns_when_current_position_is_far_from_route(tmp_path):
    route_dir = Path(tmp_path) / "2026-06-07" / "runs" / "2026-06-07T1034Z" / "ibiza_palma"
    route_dir.mkdir(parents=True)
    snapshot = write_snapshot_data(wave_max=1.6, created_at_utc="2026-06-07 10:34 UTC")
    snapshot["forecast"]["route_segments"] = {
        "departure_conditions": {"name": "Palma Bay offshore", "hourly": [{"time": "09:00", "wave_m": 0.5}]},
        "open_water_conditions": {"name": "Mid Palma-Ibiza", "hourly": [{"time": "11:00", "wave_m": 1.0}]},
        "arrival_conditions": {"name": "Ibiza Channel", "hourly": [{"time": "12:00", "wave_m": 1.3}]},
    }
    (route_dir / "daily_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (Path(tmp_path) / "2026-06-07" / "latest_run.json").write_text(
        json.dumps({"run_id": "2026-06-07T1034Z", "path": "runs/2026-06-07T1034Z"}),
        encoding="utf-8",
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/ibiza_palma/question",
        json={
            "date": "2026-06-07",
            "run": "latest",
            "question": "What is ahead of us now?",
            "vessel_class": "medium",
            "current_latitude": 40.6,
            "current_longitude": 5.4,
            "current_date": "2026-06-07",
            "current_time": "10:30",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    warning = "Position is not close enough to the planned route; treating this as a location-based forecast instead."
    assert payload["evidence_used"]["passage_evidence"]["position_status"] == "off_route"
    assert payload["evidence_used"]["passage_evidence"]["position_warning"] == warning
    assert "Recommendation:" in payload["answer"]


def test_location_question_endpoint_answers_anchor_question_from_map_grids(tmp_path):
    write_run_snapshot(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z")
    write_map_overlay(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z", variable="wave_height")
    write_map_overlay(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z", variable="current_speed")
    write_regional_evidence(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z")
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/question",
        json={
            "date": "2026-05-31",
            "run": "latest",
            "question": "I am at this position, where should I anchor tonight?",
            "latitude": 39.45,
            "longitude": 2.1,
            "vessel_class": "small",
            "current_time": "19:00",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "location"
    assert payload["intent"] == "anchoring_guidance"
    assert payload["date"] == "2026-05-31"
    assert payload["run"] == "2026-05-31T1230Z"
    assert payload["location"]["requested_lat"] == 39.45
    assert payload["location"]["requested_lon"] == 2.1
    assert payload["environmental_evidence"]["wave_height"]["value"] == 0.9
    assert payload["environmental_evidence"]["current_speed"]["value"] == 0.9
    assert payload["regional_evidence"]["available"] is True
    assert payload["regional_evidence"]["supported_modes"] == ["route_question", "location_question", "map_inspect"]
    assert payload["regional_evidence"]["available_variables"] == ["current_speed", "wave_height"]
    assert "No seabed type" in payload["regional_evidence"]["limitations"]
    assert "Decision:" in payload["answer"]
    assert "Best window:" in payload["answer"]
    assert "Comfort:" in payload["answer"]
    assert "Risk:" in payload["answer"]
    assert "Why:" in payload["answer"]
    assert "Confidence:" in payload["answer"]
    assert "does not yet include seabed type" in payload["answer"]


def test_location_question_endpoint_marks_outside_forecast_domain(tmp_path):
    write_run_snapshot(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z")
    write_map_overlay(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z", variable="wave_height")
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/question",
        json={
            "date": "2026-05-31",
            "question": "Can I anchor here?",
            "latitude": 42.0,
            "longitude": 8.0,
            "vessel_class": "medium",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["location"]["inside_domain"] is False
    assert payload["decision"]["status"] == "manual_review"
    assert "outside the available forecast grid" in payload["answer"]


def test_question_endpoint_flags_last_night_evidence_and_avoids_repeated_window_copy(tmp_path):
    write_run_snapshot(
        tmp_path,
        date_text="2026-06-03",
        run_id="2026-06-03T1923Z",
        wave_max=1.3,
        created_at_utc="2026-06-03 19:23 UTC",
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/ibiza_palma/question",
        json={
            "date": "2026-06-03",
            "run": "2026-06-03T1923Z",
            "question": "When is the best moment to leave from Palma to Ibiza today?",
            "vessel_class": "medium",
            "location_label": "Palma",
            "current_date": "2026-06-04",
            "current_time": "10:14",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence_timestamp"] == "2026-06-03T19:23Z"
    assert payload["freshness_status"] == "last_night_run"
    assert payload["freshness_warning"] == (
        "Latest available forecast package is from last night. Confirm with the morning run before committing."
    )
    assert "Latest available forecast package is from last night" in payload["answer"]
    assert "latest available package" in payload["answer"]
    answer_lines = payload["answer"].split("\n\n")
    assert answer_lines[0].startswith("Recommendation: Palma -> Ibiza: Leave during daylight hours")
    assert any(line.startswith("CURRENT:") for line in answer_lines)
    assert any(line.startswith("WINDOWS:") for line in answer_lines)
    assert "Leave during daylight hours" in payload["answer"]


def test_question_endpoint_filters_tomorrow_question_to_tomorrow_hourly_rows(tmp_path):
    run_id = "2026-06-05T1622Z"
    route_dir = Path(tmp_path) / "2026-06-05" / "runs" / run_id / "ibiza_palma"
    route_dir.mkdir(parents=True)
    snapshot = write_snapshot_data("ibiza_palma", wave_max=1.9, created_at_utc="2026-06-05 16:23 UTC")
    snapshot["forecast"].update(
        {
            "wave_min_m": 0.5,
            "wave_max_m": 1.9,
            "wave_peak_time": "11:00",
            "current_max_kn": 0.8,
            "current_peak_time": "11:00",
            "hourly": [
                {
                    "time": "11:00",
                    "time_utc": "2026-06-05 11:00 UTC",
                    "wave_m": 1.9,
                    "current_kn": 0.8,
                    "wave_direction_deg": 59.9,
                    "wave_sea_state": "following sea",
                },
                {
                    "time": "00:00",
                    "time_utc": "2026-06-05 22:00 UTC",
                    "wave_m": 1.2,
                    "current_kn": 0.4,
                    "wave_direction_deg": 73.0,
                    "wave_sea_state": "following sea",
                },
                {
                    "time": "08:00",
                    "time_utc": "2026-06-06 06:00 UTC",
                    "wave_m": 0.8,
                    "current_kn": 0.3,
                    "wave_direction_deg": 81.0,
                    "wave_sea_state": "following sea",
                },
                {
                    "time": "10:00",
                    "time_utc": "2026-06-06 08:00 UTC",
                    "wave_m": 0.7,
                    "current_kn": 0.2,
                    "wave_direction_deg": 84.0,
                    "wave_sea_state": "following sea",
                },
            ],
        }
    )
    (route_dir / "daily_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (route_dir / "route_decision_map.png").write_bytes(b"fake-png")
    (Path(tmp_path) / "2026-06-05" / "latest_run.json").write_text(
        json.dumps({"run_id": run_id, "path": f"runs/{run_id}"}),
        encoding="utf-8",
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/ibiza_palma/question",
        json={
            "date": "2026-06-05",
            "run": "latest",
            "question": "Would Palma to Ibiza feel comfortable for a 15-24m vessel tomorrow morning?",
            "vessel_class": "medium",
            "current_date": "2026-06-05",
            "current_time": "21:00",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "Tomorrow morning looks workable" in payload["answer"]
    assert "through the morning" in payload["answer"] or "during the morning" in payload["answer"]
    assert "WINDOWS:" in payload["answer"]
    assert "1.9 m" not in payload["answer"]
    assert "1.2 m" not in payload["answer"]
    assert payload["evidence_used"]["hourly_points"] == 2
    assert payload["evidence_used"]["target_local_date"] == "2026-06-06"
    assert payload["evidence_used"]["target_period_label"] == "morning"
    assert payload["evidence_used"]["route_segments"] == []


def test_question_endpoint_leave_window_tomorrow_does_not_use_late_today_message(tmp_path):
    run_id = "2026-06-05T1622Z"
    route_dir = Path(tmp_path) / "2026-06-05" / "runs" / run_id / "ibiza_palma"
    route_dir.mkdir(parents=True)
    snapshot = write_snapshot_data("ibiza_palma", wave_max=1.9, created_at_utc="2026-06-05 16:23 UTC")
    snapshot["forecast"].update(
        {
            "wave_min_m": 0.5,
            "wave_max_m": 1.9,
            "wave_peak_time": "11:00",
            "current_max_kn": 0.8,
            "current_peak_time": "11:00",
            "hourly": [
                {
                    "time": "11:00",
                    "time_utc": "2026-06-05 11:00 UTC",
                    "wave_m": 1.9,
                    "current_kn": 0.8,
                    "wave_direction_deg": 59.9,
                    "wave_sea_state": "following sea",
                },
                {
                    "time": "00:00",
                    "time_utc": "2026-06-05 22:00 UTC",
                    "wave_m": 1.2,
                    "current_kn": 0.4,
                    "wave_direction_deg": 73.0,
                    "wave_sea_state": "following sea",
                },
                {
                    "time": "08:00",
                    "time_utc": "2026-06-06 06:00 UTC",
                    "wave_m": 0.8,
                    "current_kn": 0.3,
                    "wave_direction_deg": 81.0,
                    "wave_sea_state": "following sea",
                },
                {
                    "time": "10:00",
                    "time_utc": "2026-06-06 08:00 UTC",
                    "wave_m": 0.7,
                    "current_kn": 0.2,
                    "wave_direction_deg": 84.0,
                    "wave_sea_state": "following sea",
                },
            ],
        }
    )
    (route_dir / "daily_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (route_dir / "route_decision_map.png").write_bytes(b"fake-png")
    (Path(tmp_path) / "2026-06-05" / "latest_run.json").write_text(
        json.dumps({"run_id": run_id, "path": f"runs/{run_id}"}),
        encoding="utf-8",
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/ibiza_palma/question",
        json={
            "date": "2026-06-05",
            "run": "latest",
            "question": "When is the best moment to leave from Palma to Ibiza tomorrow?",
            "vessel_class": "medium",
            "current_date": "2026-06-05",
            "current_time": "21:15",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "today's practical daylight window has passed" not in payload["answer"].lower()
    assert "Tomorrow looks workable" in payload["answer"]
    assert "Leave before late morning" in payload["answer"]
    assert "Leave before late morning" in payload["answer"] or "leave before late morning" in payload["answer"].lower()
    assert any(line.startswith("WINDOWS:") for line in payload["answer"].split("\n\n"))
    assert "1.9 m" not in payload["answer"]
    assert payload["evidence_used"]["target_local_date"] == "2026-06-06"
    assert payload["evidence_used"]["target_period_label"] == "tomorrow"
    assert payload["evidence_used"]["hourly_points"] == 3


def test_briefing_endpoint_renders_text_from_stored_evidence(tmp_path):
    write_snapshot(tmp_path)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/routes/ibiza_palma/briefing?date=2026-05-29&format=whatsapp")

    assert response.status_code == 200
    payload = response.json()
    assert payload["route"] == "Palma -> Ibiza"
    assert "PredSea Captain's Briefing" in payload["briefing"]


def test_route_gmdss_warnings_endpoint(tmp_path):
    write_snapshot(tmp_path, route_id="cagliari_naples")
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    # Test Cagliari -> Naples route (should have Rome SAR and Cagliari Military Exercises warnings active)
    response = client.get("/routes/cagliari_naples/gmdss?max_distance=60.0")
    assert response.status_code == 200
    payload = response.json()
    assert payload["route_id"] == "cagliari_naples"
    assert payload["safety_threshold_nm"] == 60.0
    assert "disclaimer" in payload
    assert payload["alerts_count"] >= 2
    alert_ids = [a["alert_id"] for a in payload["alerts"]]
    assert "NAVTEX-CAG-221" in alert_ids  # Cagliari exercises
    assert "NAVTEX-ROM-115" in alert_ids  # Rome SAR yacht Aquarius
    assert "GMDSS SAFETY NET & NAVTEX SUPPLEMENTAL SERVICE DISCLAIMER" in payload["markdown_summary"]

    # Test with a very small threshold (should filter out these alerts)
    response_small = client.get("/routes/cagliari_naples/gmdss?max_distance=1.0")
    assert response_small.status_code == 200
    payload_small = response_small.json()
    assert payload_small["alerts_count"] == 0


def test_route_briefing_injects_gmdss(tmp_path):
    write_snapshot(tmp_path, route_id="cagliari_naples")
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/routes/cagliari_naples/briefing?date=2026-05-29&format=whatsapp")
    assert response.status_code == 200
    payload = response.json()
    # Ensure that GMDSS block is present in the rendered briefing string
    assert "GMDSS SAFETY NET & NAVTEX SUPPLEMENTAL SERVICE DISCLAIMER" in payload["briefing"]
    assert "NAVTEX-CAG-221" in payload["briefing"] or "NAVTEX-ROM-115" in payload["briefing"]


def test_position_gmdss_warnings_endpoint(tmp_path):
    write_snapshot(tmp_path, route_id="cagliari_naples")
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    # Query with Naples coordinates (should return Rome SAR alert NAVTEX-ROM-115)
    response = client.get("/warnings/gmdss?lat=40.8&lon=14.15&radius=45.0")
    assert response.status_code == 200
    payload = response.json()
    assert payload["latitude"] == 40.8
    assert payload["longitude"] == 14.15
    assert payload["safety_threshold_nm"] == 45.0
    assert payload["alerts_count"] >= 1
    alert_ids = [a["alert_id"] for a in payload["alerts"]]
    assert "NAVTEX-ROM-115" in alert_ids

    # Query with a tiny radius (should return 0 alerts)
    response_small = client.get("/warnings/gmdss?lat=40.8&lon=14.15&radius=1.0")
    assert response_small.status_code == 200
    payload_small = response_small.json()
    assert payload_small["alerts_count"] == 0


def test_gmdss_warnings_loaded_from_custom_file(tmp_path):
    # Set up custom run dir and write a custom active_gmdss_warnings.json to it
    date_text = "2026-05-29"
    run_id = "RUN_TEST"
    run_dir = tmp_path / date_text / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # Write a route snapshot as well so we can test route resolution
    write_snapshot(tmp_path, date_text=date_text, route_id="cagliari_naples", run_id=run_id)
    
    custom_warnings = [
        {
            "alert_id": "CUSTOM-ALERT-999",
            "station_name": "Ibiza Radio",
            "alert_type": "Navigational",
            "message_text": "Experimental warning at position 40.80N, 14.10E.",
            "severity": "Critical",
            "publish_time": "2026-06-26T22:00:00Z"
        }
    ]
    warnings_file = run_dir / "active_gmdss_warnings.json"
    with open(warnings_file, "w") as f:
        json.dump(custom_warnings, f)
        
    client = TestClient(create_app(EvidenceStore(tmp_path)))
    
    # Test position warnings endpoint with custom date & run parameters
    response = client.get(f"/warnings/gmdss?lat=40.8&lon=14.1&radius=50.0&date={date_text}&run={run_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["alerts_count"] == 1
    assert payload["alerts"][0]["alert_id"] == "CUSTOM-ALERT-999"
    
    # Test route warnings endpoint with custom date & run parameters
    response_route = client.get(f"/routes/cagliari_naples/gmdss?max_distance=60.0&date={date_text}&run={run_id}")
    assert response_route.status_code == 200
    payload_route = response_route.json()
    assert payload_route["alerts_count"] == 1
    assert payload_route["alerts"][0]["alert_id"] == "CUSTOM-ALERT-999"


def test_place_weather_endpoint_returns_saved_weather_payload(tmp_path):
    write_place_weather(tmp_path)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/places/ibiza/weather?date=2026-05-31&run=latest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["place_id"] == "ibiza"
    assert payload["place_name"] == "Ibiza"
    assert payload["wave_height_m"] == 0.8
    assert payload["freshness_status"] == "fresh"
    assert payload["observation"]["station_name"] == "Buoy Canal de Ibiza"


def test_locations_weather_endpoint_uses_coordinates_without_place_id(tmp_path):
    write_place_weather(tmp_path)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/locations/weather?date=2026-05-31&run=latest&latitude=38.97&longitude=1.44")

    assert response.status_code == 200
    payload = response.json()
    assert payload["place_id"] in ("ibiza", "current_position")
    if payload["place_id"] == "ibiza":
        assert payload["place_name"] == "Ibiza"
    else:
        assert payload["place_name"] == "Coordinate (38.97, 1.44)"
    assert payload["requested_latitude"] == 38.97
    assert payload["requested_longitude"] == 1.44
    assert payload["source_system"] == "place_weather"


def test_place_connection_metrics_endpoint_returns_static_pair_metrics(tmp_path):
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/places/palma/connection/portocolom")

    assert response.status_code == 200
    payload = response.json()
    assert payload["origin_place_id"] == "palma"
    assert payload["destination_place_id"] == "portocolom"
    assert payload["distance_nm"] > 0
    assert payload["typical_travel_time_minutes"] > 0
    assert payload["source_tag"] == "place_distance_table_v1"


def test_optimal_route_endpoint_returns_precomputed_route(tmp_path):
    client = TestClient(create_app(EvidenceStore(tmp_path), route_store=FakeRouteStore()))

    response = client.get("/routes/optimal/palma/ibiza?priority=comfort&vessel_class=medium")

    assert response.status_code == 200
    payload = response.json()
    assert payload["origin_place_id"] == "palma"
    assert payload["destination_place_id"] == "ibiza"
    assert payload["distance_nm"] == 46.2
    assert payload["estimated_time_h"] == 3.1
    assert payload["origin_place_name"] == "Palma"
    assert payload["destination_place_name"] == "Ibiza"


def test_places_distance_endpoint_returns_distance_and_time(tmp_path):
    client = TestClient(create_app(EvidenceStore(tmp_path), route_store=FakeRouteStore()))

    response = client.get("/places/distance?origin=palma&destination=ibiza")

    assert response.status_code == 200
    payload = response.json()
    assert payload["origin_place_id"] == "palma"
    assert payload["destination_place_id"] == "ibiza"
    assert payload["distance_nm"] == 100.0
    assert payload["estimated_time_h"] == pytest.approx(100.0 / 15.0, rel=1e-6)
    assert payload["source_tag"] == "place_distance_table_v1"


def test_places_distance_uses_graph_fallback_for_uncatalogued_pair(tmp_path, monkeypatch):
    dummy_resolver = DummyDistanceResolver()
    monkeypatch.setattr(place_registry, "PLACE_DISTANCE_RESOLVER", dummy_resolver)
    place_registry.PAIR_METRICS.clear()
    client = TestClient(create_app(EvidenceStore(tmp_path), route_store=FakeRouteStore()))

    response = client.get("/places/distance?origin=barcelona&destination=valencia")

    assert response.status_code == 200
    payload = response.json()
    assert payload["distance_nm"] == 77.7
    assert payload["estimated_time_h"] == pytest.approx(311 / 60.0, rel=1e-6)
    assert payload["source_tag"] == "graph_sea_route_v1"
    assert dummy_resolver.calls == [("barcelona", "valencia")]


def test_places_resolve_endpoint_uses_alias_file(tmp_path):
    client = TestClient(create_app(EvidenceStore(tmp_path), route_store=FakeRouteStore()))

    response = client.get("/places/resolve?query=portals")

    assert response.status_code == 200
    payload = response.json()
    assert payload["matched"] is True
    assert payload["place_id"] == "porto_portals"
    assert payload["place_name"] == "Puerto Portals"
    assert payload["type"] == "port"
    assert payload["confidence"] == "high"


@pytest.mark.parametrize(
    "query,expected_place_id",
    [
        ("eivissa", "ibiza"),
        ("mao", "mahon"),
        ("west ibiza", "west_ibiza"),
    ],
)
def test_places_resolve_endpoint_returns_catalog_entries(tmp_path, query, expected_place_id):
    client = TestClient(create_app(EvidenceStore(tmp_path), route_store=FakeRouteStore()))

    response = client.get(f"/places/resolve?query={query}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["matched"] is True
    assert payload["place_id"] == expected_place_id
    assert payload["place_name"]
    assert payload["latitude"] is not None
    assert payload["longitude"] is not None


@pytest.mark.parametrize(
    "params,expected_method",
    [
        (
            "origin=palma&destination=ibiza",
            "place_to_place",
        ),
        (
            "origin=palma&destination_latitude=38.92&destination_longitude=1.49",
            "place_to_coordinates",
        ),
        (
            "origin_latitude=39.52&origin_longitude=2.58&destination=ibiza",
            "coordinates_to_place",
        ),
        (
            "origin_latitude=39.52&origin_longitude=2.58&destination_latitude=38.92&destination_longitude=1.49",
            "coordinates_to_coordinates",
        ),
    ],
)
def test_places_distance_mixed_supports_all_combinations(tmp_path, params, expected_method):
    client = TestClient(create_app(EvidenceStore(tmp_path), route_store=FakeRouteStore()))

    response = client.get(f"/places/distance/mixed?{params}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["method"] == expected_method
    assert payload["distance_nm"] > 0
    assert payload["estimated_time_h"] > 0
    assert payload["origin"]
    assert payload["destination"]
    assert payload["source_tag"] in ("place_distance_table_v1", "graph_sea_route_v1")


def test_places_distance_coordinates_endpoint_returns_maritime_distance(tmp_path):
    client = TestClient(create_app(EvidenceStore(tmp_path), route_store=FakeRouteStore()))

    response = client.get(
        "/places/distance/coordinates?origin_latitude=39.0&origin_longitude=2.0&destination_latitude=39.5&destination_longitude=2.5"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["origin_latitude"] == 39.0
    assert payload["destination_longitude"] == 2.5
    assert payload["distance_nm"] > 0
    assert payload["typical_speed_kn"] == 15.0
    assert payload["source_tag"] == "graph_sea_route_v1"


def test_places_route_endpoint_returns_waypoints(tmp_path, monkeypatch):
    def fake_route_geometry(**kwargs):
        return {
            "origin_place_id": kwargs["origin_place_id"],
            "origin_place_name": kwargs["origin_place_name"],
            "destination_place_id": kwargs["destination_place_id"],
            "destination_place_name": kwargs["destination_place_name"],
            "distance_nm": 100.0,
            "estimated_time_h": 6.67,
            "waypoints": [
                {"lat": kwargs["origin_latitude"], "lng": kwargs["origin_longitude"]},
                {"lat": 39.2, "lng": 2.1},
                {"lat": kwargs["destination_latitude"], "lng": kwargs["destination_longitude"]},
            ],
            "computed_at_local": "2026-06-17 14:00 CEST",
            "source_tag": "graph_sea_route_v1",
        }

    def fake_checkpoints(*args, **kwargs):
        return [
            {
                "waypoint_index": 0,
                "lat": 39.2,
                "lng": 2.1,
                "eta_local": "2026-06-17 15:30 CEST",
                "distance_from_origin_nm": 28.0,
                "forecast_time_local": "2026-06-17 15:30 CEST",
                "weather": {"wave_height_m": 1.1, "current_kn": 0.5},
            }
        ]

    monkeypatch.setattr(place_registry, "coordinates_route_geometry_metrics", fake_route_geometry)
    monkeypatch.setattr("api.app.build_route_checkpoints", fake_checkpoints)
    client = TestClient(create_app(EvidenceStore(tmp_path), route_store=FakeRouteStore()))

    response = client.get("/places/route/palma/ibiza?date=2026-06-17&run=latest&departure_time=08:30")

    assert response.status_code == 200
    payload = response.json()
    assert payload["origin_place_id"] == "palma"
    assert payload["destination_place_id"] == "ibiza"
    assert payload["distance_nm"] == 100.0
    assert payload["waypoints"][0]["lat"] == 39.52
    assert payload["waypoints"][0]["lng"] == 2.58
    assert payload["checkpoints"][0]["eta_local"] == "2026-06-17 15:30 CEST"
    assert payload["checkpoints"][0]["weather"]["wave_height_m"] == 1.1
    assert payload["source_tag"] == "graph_sea_route_v1"


def test_places_route_resolves_st_tropez_and_theoule_sur_mer(tmp_path, monkeypatch):
    def fake_route_geometry(**kwargs):
        return {
            "origin_place_id": kwargs["origin_place_id"],
            "origin_place_name": kwargs["origin_place_name"],
            "destination_place_id": kwargs["destination_place_id"],
            "destination_place_name": kwargs["destination_place_name"],
            "distance_nm": 100.0,
            "estimated_time_h": 6.67,
            "waypoints": [
                {"lat": kwargs["origin_latitude"], "lng": kwargs["origin_longitude"]},
                {"lat": kwargs["destination_latitude"], "lng": kwargs["destination_longitude"]},
            ],
            "computed_at_local": "2026-06-17 14:00 CEST",
            "source_tag": "graph_sea_route_v1",
        }

    def fake_checkpoints(*args, **kwargs):
        return []

    monkeypatch.setattr(place_registry, "coordinates_route_geometry_metrics", fake_route_geometry)
    monkeypatch.setattr("api.app.build_route_checkpoints", fake_checkpoints)
    client = TestClient(create_app(EvidenceStore(tmp_path), route_store=FakeRouteStore()))

    response = client.get("/places/route/st_tropez/theoule_sur_mer?date=2026-06-17&run=latest&departure_time=08:30")
    assert response.status_code == 200
    payload = response.json()
    assert payload["origin_place_id"] == "st_tropez"
    assert payload["destination_place_id"] == "theoule_sur_mer"


def test_places_route_endpoint_uses_coordinate_overrides(tmp_path, monkeypatch):
    seen = {}

    def fake_route_geometry(**kwargs):
        seen.update(kwargs)
        return {
            "origin_place_id": kwargs["origin_place_id"],
            "origin_place_name": kwargs["origin_place_name"],
            "origin_latitude": kwargs["origin_latitude"],
            "origin_longitude": kwargs["origin_longitude"],
            "destination_place_id": kwargs["destination_place_id"],
            "destination_place_name": kwargs["destination_place_name"],
            "destination_latitude": kwargs["destination_latitude"],
            "destination_longitude": kwargs["destination_longitude"],
            "distance_nm": 99.0,
            "estimated_time_h": 6.6,
            "waypoints": [
                {"lat": kwargs["origin_latitude"], "lng": kwargs["origin_longitude"]},
                {"lat": kwargs["destination_latitude"], "lng": kwargs["destination_longitude"]},
            ],
            "computed_at_local": "2026-06-17 14:00 CEST",
            "source_tag": "graph_sea_route_v1",
        }

    monkeypatch.setattr(place_registry, "coordinates_route_geometry_metrics", fake_route_geometry)
    monkeypatch.setattr("api.app.build_route_checkpoints", lambda *args, **kwargs: [])
    client = TestClient(create_app(EvidenceStore(tmp_path), route_store=FakeRouteStore()))

    response = client.get(
        "/places/route/palma/ibiza?origin_latitude=39.0&origin_longitude=2.0&destination_latitude=38.92&destination_longitude=1.49&departure_time=09:15"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["origin_place_id"] == "palma"
    assert payload["origin_latitude"] == 39.0
    assert payload["origin_longitude"] == 2.0
    assert payload["destination_place_id"] == "ibiza"
    assert payload["destination_latitude"] == 38.92
    assert payload["destination_longitude"] == 1.49
    assert seen["origin_latitude"] == 39.0
    assert seen["origin_longitude"] == 2.0
    assert seen["destination_latitude"] == 38.92
    assert seen["destination_longitude"] == 1.49


def test_places_route_endpoint_falls_back_to_latest_weather_bundle_for_future_date(tmp_path, monkeypatch):
    write_place_weather(
        tmp_path,
        date_text="2026-06-17",
        run_id="2026-06-17T0630Z",
        place_id="palma",
    )
    (Path(tmp_path) / "2026-06-17" / "latest_run.json").write_text(
        json.dumps({"run_id": "2026-06-17T0630Z", "path": "runs/2026-06-17T0630Z"}),
        encoding="utf-8",
    )

    def fake_route_geometry(**kwargs):
        return {
            "origin_place_id": kwargs["origin_place_id"],
            "origin_place_name": kwargs["origin_place_name"],
            "destination_place_id": kwargs["destination_place_id"],
            "destination_place_name": kwargs["destination_place_name"],
            "distance_nm": 22.0,
            "estimated_time_h": 1.5,
            "waypoints": [
                {"lat": kwargs["origin_latitude"], "lng": kwargs["origin_longitude"]},
                {"lat": 39.3, "lng": 2.3},
                {"lat": kwargs["destination_latitude"], "lng": kwargs["destination_longitude"]},
            ],
            "computed_at_local": "2026-06-17 14:00 CEST",
            "source_tag": "graph_sea_route_v1",
        }

    monkeypatch.setattr(place_registry, "coordinates_route_geometry_metrics", fake_route_geometry)
    monkeypatch.setattr(
        "api.app.place_weather.resolve_place",
        lambda *args, **kwargs: {
            "requested_place_id": "current_position",
            "place_id": "palma",
            "place_name": "Palma",
            "latitude": 39.52,
            "longitude": 2.58,
            "matched": True,
            "confidence": "high",
        },
    )
    client = TestClient(create_app(EvidenceStore(tmp_path), route_store=FakeRouteStore()))

    response = client.get("/places/route/palma/ibiza?date=2026-06-18&run=latest&departure_time=08:30")

    assert response.status_code == 200
    payload = response.json()
    assert payload["checkpoints"][0]["weather"]["place_id"] == "palma"
    assert payload["checkpoints"][0]["weather"]["sample_time_local"] == "10:00"
    assert payload["checkpoints"][0]["weather"]


def test_routes_optimal_status_reports_route_store_state(tmp_path):
    client = TestClient(create_app(EvidenceStore(tmp_path), route_store=FakeRouteStore()))

    response = client.get("/routes/optimal/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["loaded_date"] == "2026-06-14"
    assert payload["route_count"] == 2


def test_route_question_includes_route_connection_metrics(tmp_path):
    write_snapshot(tmp_path, date_text="2026-05-29", route_id="ibiza_palma")
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/ibiza_palma/question",
        json={
            "date": "2026-05-29",
            "run": "latest",
            "question": "Is it good to go from Palma to Ibiza today?",
            "vessel_class": "medium",
            "current_date": "2026-05-29",
            "current_time": "09:00",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "PASSAGE:" in payload["answer"]
    assert payload["evidence_used"]["route_connection"]["distance_nm"] == 100.0
    assert payload["evidence_used"]["route_connection"]["typical_travel_time_minutes"] > 0


def test_route_question_includes_reliability_block(tmp_path):
    run_date = "2026-06-20"
    run_id = "2026-06-20T0630Z"
    write_snapshot(tmp_path, date_text=run_date, route_id="ibiza_palma", run_id=run_id)
    write_place_weather(
        tmp_path,
        run_date,
        run_id,
        "palma",
        source_label="REDEXT",
        wave_height_m=0.5,
        observed_at_utc=utc_text(20),
    )
    write_place_weather(
        tmp_path,
        run_date,
        run_id,
        "ibiza",
        source_label="REDCOS",
        wave_height_m=0.55,
        observed_at_utc=utc_text(25),
    )
    (Path(tmp_path) / run_date / "latest_run.json").write_text(
        json.dumps({"run_id": run_id, "path": f"runs/{run_id}"}),
        encoding="utf-8",
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/ibiza_palma/question",
        json={
            "date": run_date,
            "run": "latest",
            "question": "Is it good to go from Palma to Ibiza today?",
            "vessel_class": "medium",
            "current_date": run_date,
            "current_time": "09:00",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["reliability"]["evaluation_method"] == "single_model_consistency"
    assert payload["reliability"]["confidence_score"] in {"High", "Medium", "Low"}
    assert isinstance(payload["reliability"]["age_minutes"], int)


def test_route_question_uses_single_model_consistency_when_only_one_place_source(tmp_path):
    run_date = "2026-06-20"
    current_run_id = "2026-06-20T0630Z"
    previous_run_id = "2026-06-20T0530Z"
    write_snapshot(tmp_path, date_text=run_date, route_id="ibiza_palma", run_id=current_run_id)
    write_place_weather(
        tmp_path,
        run_date,
        current_run_id,
        "palma",
        source_label="REDMAR",
        wave_height_m=0.8,
        observed_at_utc=utc_text(30),
    )
    write_place_weather(
        tmp_path,
        run_date,
        previous_run_id,
        "palma",
        source_label="REDMAR",
        wave_height_m=0.84,
        observed_at_utc=utc_text(90),
    )
    (Path(tmp_path) / run_date / "latest_run.json").write_text(
        json.dumps({"run_id": current_run_id, "path": f"runs/{current_run_id}"}),
        encoding="utf-8",
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/ibiza_palma/question",
        json={
            "date": run_date,
            "run": "latest",
            "question": "Is it good to go from Palma to Ibiza today?",
            "vessel_class": "medium",
            "current_date": run_date,
            "current_time": "09:00",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["reliability"]["evaluation_method"] == "single_model_consistency"
    assert payload["reliability"]["confidence_score"] in {"High", "Medium", "Low"}
    assert isinstance(payload["reliability"]["age_minutes"], int)


def test_route_question_uses_previous_day_snapshot_when_same_day_previous_run_missing(tmp_path):
    current_date = "2026-06-20"
    previous_date = "2026-06-19"
    current_run_id = "2026-06-20T0630Z"
    previous_run_id = "2026-06-19T2030Z"
    current_snapshot = write_snapshot(
        tmp_path,
        date_text=current_date,
        route_id="ibiza_palma",
        run_id=current_run_id,
    )
    previous_snapshot = write_snapshot(
        tmp_path,
        date_text=previous_date,
        route_id="ibiza_palma",
        run_id=previous_run_id,
    )
    previous_snapshot["forecast"]["wave_max_m"] = 2.0
    current_snapshot["created_at_utc"] = utc_text(10)
    previous_snapshot["created_at_utc"] = utc_text(25)
    current_dir = Path(tmp_path) / current_date / "runs" / current_run_id / "ibiza_palma"
    previous_dir = Path(tmp_path) / previous_date / "runs" / previous_run_id / "ibiza_palma"
    (current_dir / "daily_snapshot.json").write_text(json.dumps(current_snapshot), encoding="utf-8")
    (previous_dir / "daily_snapshot.json").write_text(json.dumps(previous_snapshot), encoding="utf-8")
    (Path(tmp_path) / current_date / "latest_run.json").write_text(
        json.dumps({"run_id": current_run_id, "path": f"runs/{current_run_id}"}),
        encoding="utf-8",
    )
    (Path(tmp_path) / previous_date / "latest_run.json").write_text(
        json.dumps({"run_id": previous_run_id, "path": f"runs/{previous_run_id}"}),
        encoding="utf-8",
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/ibiza_palma/question",
        json={
            "date": current_date,
            "run": "latest",
            "question": "Is it good to go from Palma to Ibiza today?",
            "vessel_class": "medium",
            "current_date": current_date,
            "current_time": "09:00",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    reliability = payload["reliability"]
    assert reliability["evaluation_method"] == "single_model_consistency"
    assert reliability["details"]["previous_run_date"] == previous_date
    assert "Compared against the previous forecast snapshot" in reliability["reason"]


def test_route_question_penalizes_missing_route_source(tmp_path):
    current_date = "2026-06-20"
    previous_date = "2026-06-19"
    current_run_id = "2026-06-20T0630Z"
    previous_run_id = "2026-06-19T2030Z"

    current_snapshot = write_snapshot(
        tmp_path,
        date_text=current_date,
        route_id="ibiza_palma",
        run_id=current_run_id,
    )
    previous_snapshot = write_snapshot(
        tmp_path,
        date_text=previous_date,
        route_id="ibiza_palma",
        run_id=previous_run_id,
    )
    current_snapshot["created_at_utc"] = utc_text(10)
    previous_snapshot["created_at_utc"] = utc_text(25)
    current_dir = Path(tmp_path) / current_date / "runs" / current_run_id / "ibiza_palma"
    previous_dir = Path(tmp_path) / previous_date / "runs" / previous_run_id / "ibiza_palma"
    (current_dir / "daily_snapshot.json").write_text(json.dumps(current_snapshot), encoding="utf-8")
    (previous_dir / "daily_snapshot.json").write_text(json.dumps(previous_snapshot), encoding="utf-8")

    write_place_weather(
        tmp_path,
        current_date,
        current_run_id,
        "palma",
        source_label="REDMAR",
        wave_height_m=0.8,
        observed_at_utc=utc_text(30),
    )
    write_place_weather(
        tmp_path,
        current_date,
        current_run_id,
        "ibiza",
        source_label="REDEXT",
        wave_height_m=0.7,
        observed_at_utc=utc_text(28),
    )

    (Path(tmp_path) / current_date / "latest_run.json").write_text(
        json.dumps({"run_id": current_run_id, "path": f"runs/{current_run_id}"}),
        encoding="utf-8",
    )
    (Path(tmp_path) / previous_date / "latest_run.json").write_text(
        json.dumps({"run_id": previous_run_id, "path": f"runs/{previous_run_id}"}),
        encoding="utf-8",
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/ibiza_palma/question",
        json={
            "date": current_date,
            "run": "latest",
            "question": "Is it good to go from Palma to Ibiza today?",
            "vessel_class": "medium",
            "current_date": current_date,
            "current_time": "09:00",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    reliability = payload["reliability"]
    assert reliability["confidence_score"] == "Low"
    assert reliability["details"]["offline_sources"] == []
    assert reliability["reason"]


def test_route_question_uses_source_breadth_when_previous_snapshot_missing(tmp_path):
    source_summary = {
        "primary_source": "Copernicus",
        "sources": ["Copernicus", "ECMWF", "Puertos del Estado"],
        "count": 3,
        "families": ["ocean_forecast", "atmosphere", "observation"],
        "text": "Sources used: Copernicus, ECMWF, Puertos del Estado",
    }
    current_snapshot = write_snapshot(
        tmp_path,
        date_text="2026-06-21",
        route_id="ibiza_palma",
        run_id="2026-06-21T0616Z",
        source_summary=source_summary,
    )
    current_snapshot["created_at_utc"] = utc_text(15)
    current_dir = Path(tmp_path) / "2026-06-21" / "runs" / "2026-06-21T0616Z" / "ibiza_palma"
    (current_dir / "daily_snapshot.json").write_text(json.dumps(current_snapshot), encoding="utf-8")
    (Path(tmp_path) / "2026-06-21" / "latest_run.json").write_text(
        json.dumps({"run_id": "2026-06-21T0616Z", "path": "runs/2026-06-21T0616Z"}),
        encoding="utf-8",
    )
    write_place_weather(
        tmp_path,
        "2026-06-21",
        "2026-06-21T0616Z",
        "palma",
        source_label="REDMAR",
        wave_height_m=0.8,
        observed_at_utc=utc_text(20),
    )
    write_place_weather(
        tmp_path,
        "2026-06-21",
        "2026-06-21T0616Z",
        "ibiza",
        source_label="REDEXT",
        wave_height_m=0.7,
        observed_at_utc=utc_text(18),
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/ibiza_palma/question",
        json={
            "date": "2026-06-21",
            "run": "latest",
            "question": "Is it good to go from Palma to Ibiza today?",
            "vessel_class": "medium",
            "current_date": "2026-06-21",
            "current_time": "08:00",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    reliability = payload["reliability"]
    assert reliability["confidence_score"] == "Medium"
    assert reliability["details"]["source_breadth_score"] in {"Medium", "High"}
    assert payload["evidence_used"]["source_summary"]["sources"] == ["Copernicus", "ECMWF", "Puertos del Estado"]
    assert "Sources used: Copernicus, ECMWF, Puertos del Estado" in payload["answer"] or "Sources used" in payload["operational_stance"].get("why", "")


def test_route_question_uses_graph_fallback_for_uncatalogued_pair(tmp_path, monkeypatch):
    dummy_resolver = DummyDistanceResolver()
    monkeypatch.setattr(place_registry, "PLACE_DISTANCE_RESOLVER", dummy_resolver)
    place_registry.PAIR_METRICS.clear()
    write_snapshot(tmp_path, date_text="2026-05-29", route_id="palma_valencia")
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.post(
        "/routes/palma_valencia/question",
        json={
            "date": "2026-05-29",
            "run": "latest",
            "question": "Is it good to go from Palma to Valencia today?",
            "vessel_class": "medium",
            "current_date": "2026-05-29",
            "current_time": "09:00",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence_used"]["route_connection"]["distance_nm"] == 77.7
    assert dummy_resolver.calls == [("palma", "valencia")]


def test_artifact_endpoint_serves_latest_route_map(tmp_path):
    write_run_snapshot(tmp_path, run_id="2026-05-29T0630Z", wave_max=0.5)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/routes/ibiza_palma/artifacts/route_decision_map.png?date=2026-05-29&run=latest")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "public, max-age=300"
    assert response.content == b"fake-png"


def test_artifact_endpoint_rejects_non_public_artifacts(tmp_path):
    write_run_snapshot(tmp_path, run_id="2026-05-29T0630Z", wave_max=0.5)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/routes/ibiza_palma/artifacts/daily_snapshot.json?date=2026-05-29&run=latest")

    assert response.status_code == 404


class FakeGcsBlob:
    def __init__(self, name, text):
        self.name = name
        self._text = text

    def exists(self):
        return True

    def download_as_text(self, encoding="utf-8"):
        return self._text

    def download_as_bytes(self):
        if isinstance(self._text, bytes):
            return self._text
        return self._text.encode("utf-8")

    def generate_signed_url(self, version="v4", expiration=None, method="GET"):
        return f"https://signed.example/{self.name}?method={method}&version={version}"


class MissingFakeGcsBlob:
    def exists(self):
        return False


class FakeGcsBucket:
    def __init__(self, objects):
        self.objects = objects

    def blob(self, name):
        if name not in self.objects:
            return MissingFakeGcsBlob()
        return FakeGcsBlob(name, self.objects[name])


class FakeGcsIterator:
    def __init__(self, blobs, prefixes=None):
        self._blobs = blobs
        self.prefixes = prefixes or set()

    def __iter__(self):
        return iter(self._blobs)


class FakeGcsClient:
    def __init__(self, objects):
        self.objects = objects

    def bucket(self, bucket_name):
        return FakeGcsBucket(self.objects)

    def list_blobs(self, bucket_name, prefix="", delimiter=None):
        names = [name for name in self.objects if name.startswith(prefix)]
        if delimiter == "/":
            prefixes = set()
            for name in names:
                remaining = name[len(prefix) :]
                first_part = remaining.split("/", 1)[0]
                if first_part:
                    prefixes.add(f"{prefix}{first_part}/")
            return FakeGcsIterator([], prefixes=prefixes)
        return FakeGcsIterator([FakeGcsBlob(name, self.objects[name]) for name in names])


def test_gcs_evidence_store_reads_latest_snapshot_from_bucket():
    snapshot = write_snapshot_data = {
        "route": "Palma -> Ibiza",
        "route_id": "ibiza_palma",
        "forecast": {"hourly": []},
        "observations": {},
        "recommendation": {},
    }
    objects = {
        "predictions/2026-05-30/ibiza_palma/daily_snapshot.json": json.dumps({"route_id": "old"}),
        "predictions/2026-05-31/ibiza_palma/daily_snapshot.json": json.dumps(write_snapshot_data),
    }
    store = GcsEvidenceStore("predsea-daily-outputs", client=FakeGcsClient(objects))

    assert store.latest_date() == "2026-05-31"
    assert store.route_ids("2026-05-31") == ["ibiza_palma"]
    assert store.load_snapshot("ibiza_palma") == snapshot


def test_gcs_evidence_store_reads_latest_run_from_bucket():
    objects = {
        "predictions/2026-05-31/latest_run.json": json.dumps(
            {"run_id": "2026-05-31T1230Z", "path": "runs/2026-05-31T1230Z"}
        ),
        "predictions/2026-05-31/runs/2026-05-31T0630Z/ibiza_palma/daily_snapshot.json": json.dumps(
            write_snapshot_data(wave_max=0.4)
        ),
        "predictions/2026-05-31/runs/2026-05-31T1230Z/ibiza_palma/daily_snapshot.json": json.dumps(
            write_snapshot_data(wave_max=0.9)
        ),
    }
    store = GcsEvidenceStore("predsea-daily-outputs", client=FakeGcsClient(objects))

    assert store.latest_run("2026-05-31") == "2026-05-31T1230Z"
    assert store.route_ids("2026-05-31") == ["ibiza_palma"]
    assert store.load_snapshot("ibiza_palma", "2026-05-31")["forecast"]["wave_max_m"] == 0.9
    assert store.load_snapshot("ibiza_palma", "2026-05-31", run_id="2026-05-31T0630Z")["forecast"]["wave_max_m"] == 0.4


def test_media_endpoint_returns_api_and_signed_urls_for_route_artifacts():
    objects = {
        "predictions/2026-05-31/latest_run.json": json.dumps(
            {"run_id": "2026-05-31T1230Z", "path": "runs/2026-05-31T1230Z"}
        ),
        "predictions/2026-05-31/runs/2026-05-31T1230Z/ibiza_palma/daily_snapshot.json": json.dumps(
            write_snapshot_data(wave_max=0.9)
        ),
        "predictions/2026-05-31/runs/2026-05-31T1230Z/ibiza_palma/route_decision_map.png": b"map",
    }
    client = TestClient(create_app(GcsEvidenceStore("predsea-daily-outputs", client=FakeGcsClient(objects))))

    response = client.get("/routes/ibiza_palma/media?date=2026-05-31&run=latest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"] == "2026-05-31T1230Z"
    route_map = payload["artifacts"]["route_decision_map.png"]
    assert route_map["api_url"].endswith(
        "/routes/ibiza_palma/artifacts/route_decision_map.png?date=2026-05-31&run=2026-05-31T1230Z"
    )
    assert route_map["signed_url"].startswith("https://signed.example/")
    assert route_map["download_url"] == route_map["signed_url"]
    assert "predsea_whatsapp_figure.png" not in payload["artifacts"]


def test_maps_endpoint_returns_leaflet_overlay_contract(tmp_path):
    write_run_snapshot(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z")
    filename = write_map_overlay(tmp_path)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/maps?date=2026-05-31&variable=wave_height&time=14:00")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["run"] == "2026-05-31T1230Z"
    assert payload["variable"] == "wave_height"
    assert payload["time"] == "2026-05-31T14:00:00Z"
    assert payload["bounds"] == [[38.5, 1.0], [40.5, 4.5]]
    assert payload["overlay_url"].endswith(
        f"/maps/overlays/wave_height/{filename}?date=2026-05-31&run=2026-05-31T1230Z"
    )
    assert payload["leaflet"]["method"] == "L.imageOverlay"


def test_maps_endpoint_serves_wave_partition_overlay_contract(tmp_path):
    write_run_snapshot(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z")
    filename = write_map_overlay(tmp_path, variable="swell_1_height")
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/maps?date=2026-05-31&variable=swell_1_height&time=14:00")

    assert response.status_code == 200
    payload = response.json()
    assert payload["variable"] == "swell_1_height"
    assert payload["overlay_url"].endswith(
        f"/maps/overlays/swell_1_height/{filename}?date=2026-05-31&run=2026-05-31T1230Z"
    )


def test_map_overlay_endpoint_serves_overlay_png(tmp_path):
    write_run_snapshot(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z")
    filename = write_map_overlay(tmp_path)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get(f"/maps/overlays/wave_height/{filename}?date=2026-05-31&run=latest")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == b"overlay-png"


def test_map_overlay_endpoint_serves_wave_partition_png(tmp_path):
    write_run_snapshot(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z")
    filename = write_map_overlay(tmp_path, variable="wind_wave_height")
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get(f"/maps/overlays/wind_wave_height/{filename}?date=2026-05-31&run=latest")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == b"overlay-png"


def test_map_inspect_endpoint_samples_nearest_grid_point(tmp_path):
    write_run_snapshot(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z")
    write_map_overlay(tmp_path)
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get(
        "/maps/inspect?date=2026-05-31&variable=wave_height&time=14:00&lat=39.45&lon=2.1"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["run"] == "2026-05-31T1230Z"
    assert payload["time"] == "2026-05-31T14:00:00Z"
    assert payload["sampled_lat"] == 39.5
    assert payload["sampled_lon"] == 2.0
    assert payload["value"] == 0.9
    assert payload["units"] == "m"
    assert payload["inside_domain"] is True


def test_media_endpoint_download_url_falls_back_to_api_url_for_local_store(tmp_path):
    write_run_snapshot(tmp_path, date_text="2026-05-31", run_id="2026-05-31T1230Z")
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/routes/ibiza_palma/media?date=2026-05-31&run=latest")

    assert response.status_code == 200
    route_map = response.json()["artifacts"]["route_decision_map.png"]
    assert route_map["signed_url"] is None
    assert route_map["download_url"] == route_map["api_url"]


def test_health_reports_gcs_backend_when_gcs_store_is_injected():
    objects = {
        "predictions/2026-05-31/ibiza_palma/daily_snapshot.json": json.dumps(
            {
                "route": "Palma -> Ibiza",
                "route_id": "ibiza_palma",
                "forecast": {"hourly": []},
                "observations": {},
                "recommendation": {},
            }
        )
    }
    client = TestClient(create_app(GcsEvidenceStore("predsea-daily-outputs", client=FakeGcsClient(objects))))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "latest_date": "2026-05-31",
        "latest_run": None,
        "storage_backend": "gcs",
        "environment": "test",
    }


def test_warnings_endpoint_merges_sorts_and_counts_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(
        warnings_service,
        "compute_rolling_anomaly_warnings",
        lambda *args, **kwargs: (
            [
                {
                    "source": "predsea_anomaly",
                    "severity": "severe",
                    "variable": "wave_height",
                    "label": "Wave height anomaly",
                    "description": "High wave height at Ibiza Channel",
                    "value": 3.5,
                    "unit": "m",
                    "z_score": 2.9,
                    "baseline_type": "rolling",
                    "station_id": "canal_de_ibiza",
                    "station_name": "Canal de Ibiza",
                    "latitude": 38.9,
                    "longitude": 1.4,
                    "issued_at_utc": "2026-06-21T08:00:00+00:00",
                    "valid_from_utc": "2026-06-21T08:00:00Z",
                    "valid_to_utc": None,
                    "route": "ibiza_palma",
                    "aemet_event": None,
                    "aemet_area": None,
                    "extra": {},
                }
            ],
            True,
        ),
    )
    monkeypatch.setattr(
        warnings_service,
        "compute_climatological_anomaly_warnings",
        lambda *args, **kwargs: (
            [
                {
                    "source": "predsea_anomaly",
                    "severity": "moderate",
                    "variable": "air_temperature",
                    "label": "Air temperature anomaly",
                    "description": "Warmer than climatology",
                    "value": 27.2,
                    "unit": "C",
                    "z_score": 1.7,
                    "baseline_type": "climatological",
                    "station_id": "palma",
                    "station_name": "Palma",
                    "latitude": 39.56,
                    "longitude": 2.65,
                    "issued_at_utc": "2026-06-21T08:00:00+00:00",
                    "valid_from_utc": "2026-06-21T08:00:00Z",
                    "valid_to_utc": None,
                    "route": "ibiza_palma",
                    "aemet_event": None,
                    "aemet_area": None,
                    "extra": {},
                }
            ],
            True,
        ),
    )
    monkeypatch.setattr(
        warnings_service,
        "fetch_aemet_warnings",
        lambda *args, **kwargs: (
            [
                {
                    "source": "aemet_official",
                    "severity": "severe",
                    "variable": "wind_speed",
                    "label": "Aviso rojo por viento costero",
                    "description": "Strong coastal wind expected",
                    "value": None,
                    "unit": None,
                    "z_score": None,
                    "baseline_type": None,
                    "station_id": None,
                    "station_name": None,
                    "latitude": None,
                    "longitude": None,
                    "issued_at_utc": "2026-06-21T08:00:00+00:00",
                    "valid_from_utc": "2026-06-21T10:00:00+00:00",
                    "valid_to_utc": "2026-06-21T22:00:00+00:00",
                    "route": "ibiza_palma",
                    "aemet_event": "Viento costero",
                    "aemet_area": "Baleares - Costa Norte",
                    "extra": {},
                }
            ],
            True,
        ),
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/warnings/active?route=ibiza_palma")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == {
        "total": 3,
        "severe": 2,
        "moderate": 1,
        "info": 0,
        "aemet_official": 1,
        "predsea_anomaly": 2,
        "sources_available": ["predsea_anomaly", "aemet_official"],
    }
    assert payload["operational_stance"].startswith("SEVERE conditions detected")
    assert payload["warnings"][0]["source"] == "aemet_official"
    assert payload["warnings"][1]["severity"] == "severe"
    assert payload["warnings"][2]["severity"] == "moderate"


def test_warnings_endpoint_remains_200_when_all_sources_fail(tmp_path, monkeypatch):
    monkeypatch.setattr(
        warnings_service,
        "compute_rolling_anomaly_warnings",
        lambda *args, **kwargs: ([], False),
    )
    monkeypatch.setattr(
        warnings_service,
        "compute_climatological_anomaly_warnings",
        lambda *args, **kwargs: ([], False),
    )
    monkeypatch.setattr(
        warnings_service,
        "fetch_aemet_warnings",
        lambda *args, **kwargs: ([], False),
    )
    client = TestClient(create_app(EvidenceStore(tmp_path)))

    response = client.get("/warnings/active?place=palma")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["total"] == 0
    assert payload["sources_available"] == []
    assert payload["operational_stance"] == "Warning sources temporarily unavailable. Check conditions manually."


def test_aemet_cap_tar_parser_keeps_only_es_balearic_xml(monkeypatch):
    import io
    import tarfile

    monkeypatch.setenv("AEMET_API_KEY", "test-key")
    monkeypatch.setenv("PREDSEA_AEMET_WARNING_AREA_CODES", "esp")

    es_xml = """<?xml version="1.0" encoding="UTF-8"?>
<alert>
  <info>
    <language>es-ES</language>
    <event>Aviso de fenómenos costeros</event>
    <severity>Severe</severity>
    <headline>Aviso de fenómenos costeros</headline>
    <description>Viento del noreste fuerza 7 y olas de 3 metros.</description>
    <area>
      <areaDesc>Ibiza y Formentera</areaDesc>
      <geocode>
        <valueName>AEMET-Meteoalerta zona</valueName>
        <value>733104</value>
      </geocode>
    </area>
    <onset>2026-06-21T10:00:00Z</onset>
    <expires>2026-06-21T22:00:00Z</expires>
  </info>
  <info>
    <language>en-GB</language>
    <event>Coastal phenomena warning</event>
    <severity>Severe</severity>
    <headline>Coastal phenomena warning</headline>
    <description>Wind and waves.</description>
    <area>
      <areaDesc>Ibiza and Formentera</areaDesc>
      <geocode>
        <valueName>AEMET-Meteoalerta zona</valueName>
        <value>733104</value>
      </geocode>
    </area>
  </info>
</alert>
"""
    non_balearic_xml = """<?xml version="1.0" encoding="UTF-8"?>
<alert>
  <info>
    <language>es-ES</language>
    <event>Aviso de viento</event>
    <severity>Moderate</severity>
    <headline>Aviso de viento</headline>
    <description>Viento fuerte en Navarra.</description>
    <area>
      <areaDesc>Navarra</areaDesc>
      <geocode>
        <valueName>AEMET-Meteoalerta zona</valueName>
        <value>741001</value>
      </geocode>
    </area>
  </info>
</alert>
"""

    archive_buffer = io.BytesIO()
    with tarfile.open(fileobj=archive_buffer, mode="w") as archive:
        for name, content in {
            "alerts/balearic.xml": es_xml,
            "alerts/navarra.xml": non_balearic_xml,
        }.items():
            encoded = content.encode("utf-8")
            member = tarfile.TarInfo(name)
            member.size = len(encoded)
            archive.addfile(member, io.BytesIO(encoded))
    archive_bytes = archive_buffer.getvalue()

    class FakeResponse:
        def __init__(self, payload=None, content=b""):
            self._payload = payload
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_get(url, headers=None, timeout=None):
        if "avisos_cap/ultimoelaborado/area/esp" in url:
            return FakeResponse({"estado": 200, "datos": "https://aemet.example/downloads/cap.tar"})
        if url == "https://aemet.example/downloads/cap.tar":
            return FakeResponse(content=archive_bytes)
        raise AssertionError(f"Unexpected AEMET URL: {url}")

    monkeypatch.setattr(warnings_service.requests, "get", fake_get)

    warnings, available = warnings_service.fetch_aemet_warnings(generated_at_utc="2026-06-21T12:00:00+00:00")

    assert available is True
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning["source"] == "aemet_official"
    assert warning["severity"] == "severe"
    assert warning["aemet_area"] == "Ibiza y Formentera"
    assert warning["extra"]["zone_codes"] == ["733104"]


def test_briefing_summary_ignores_non_finite_observation_values():
    from briefing import build_daily_briefing_summary

    snapshot = {
        "created_at_utc": "2026-06-21 08:00 UTC",
        "forecast": {"wave_max_m": 1.2, "current_max_kn": 0.4, "hourly": []},
        "observations": {
            "canal_de_ibiza": {
                "wave_height_m": float("nan"),
                "last_sample_utc": "2026-06-21 07:30 UTC",
            }
        },
        "recommendation": {"confidence": "low"},
    }

    summary = build_daily_briefing_summary(snapshot)

    assert summary["observation_alignment"]["agreement"] == "unavailable"
    assert summary["observation_alignment"]["difference_pct"] is None
