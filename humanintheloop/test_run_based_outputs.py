import importlib.util
import json
from pathlib import Path


def load_script_module(path):
    spec = importlib.util.spec_from_file_location(Path(path).stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_daily_generator_writes_manifest_and_latest_run_pointer(tmp_path):
    generator = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_briefing.py")
    run_id = "2026-05-31T0630Z"
    day_dir = tmp_path / "2026-05-31"
    run_dir = day_dir / "runs" / run_id
    run_dir.mkdir(parents=True)

    generator.write_manifest(
        run_dir,
        "2026-05-31",
        run_id,
        ["ibiza_palma"],
        "medium",
        publication_phase="preliminary",
        wrf_status="running",
    )
    generator.write_latest_run(
        day_dir,
        "2026-05-31",
        run_id,
        ["ibiza_palma"],
        "medium",
        publication_phase="preliminary",
        wrf_status="running",
    )

    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    latest = json.loads((day_dir / "latest_run.json").read_text(encoding="utf-8"))

    assert manifest["run_date"] == "2026-05-31"
    assert manifest["run_id"] == run_id
    assert latest["run_id"] == run_id
    assert latest["path"] == f"runs/{run_id}"
    assert manifest["publication_phase"] == "preliminary"
    assert manifest["wrf_status"] == "running"
    assert latest["publication_phase"] == "preliminary"


def test_daily_generator_writes_validation_manifest_pointer(tmp_path):
    generator = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_briefing.py")
    run_id = "2026-05-31T0630Z"
    day_dir = tmp_path / "2026-05-31"
    run_dir = day_dir / "runs" / run_id
    run_dir.mkdir(parents=True)
    validation_summary = {
        "observation_rows": 3,
        "forecast_rows": 120,
        "matched_rows": 2,
        "matched_variables": {"wave_height": 2},
    }
    validation_entry = generator.validation_manifest_entry(validation_summary)

    generator.write_manifest(
        run_dir,
        "2026-05-31",
        run_id,
        ["ibiza_palma"],
        "medium",
        validation=validation_entry,
    )
    generator.write_latest_run(
        day_dir,
        "2026-05-31",
        run_id,
        ["ibiza_palma"],
        "medium",
        validation=validation_entry,
    )

    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    latest = json.loads((day_dir / "latest_run.json").read_text(encoding="utf-8"))

    assert manifest["validation"]["path"] == "validation/validation_summary.json"
    assert manifest["validation"]["matched_rows"] == 2
    assert latest["validation"]["forecast_index_path"] == "validation/forecast_index.jsonl"
    assert manifest["validation"]["station_metadata_path"] == "validation/station_metadata.jsonl"


def test_web_demo_exporter_uses_latest_run_folder(tmp_path):
    exporter = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "export_web_demo_bundle.py")
    run_id = "2026-05-31T0630Z"
    run_dir = tmp_path / "outputs" / "2026-05-31" / "runs" / run_id
    route_dir = run_dir / "ibiza_palma"
    route_dir.mkdir(parents=True)
    (tmp_path / "outputs" / "2026-05-31" / "latest_run.json").write_text(
        json.dumps({"run_id": run_id, "path": f"runs/{run_id}"}),
        encoding="utf-8",
    )
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"run_date": "2026-05-31", "run_id": run_id, "routes": ["ibiza_palma"]}),
        encoding="utf-8",
    )
    for name in exporter.ROUTE_ARTIFACTS:
        (route_dir / name).write_text("demo", encoding="utf-8")

    result = exporter.export_web_demo_bundle(
        tmp_path / "outputs",
        tmp_path / "web-demo",
        featured_route="ibiza_palma",
    )

    manifest = json.loads((tmp_path / "web-demo" / "demo_manifest.json").read_text(encoding="utf-8"))
    assert result.run_date == "2026-05-31"
    assert manifest["run_id"] == run_id
    assert (tmp_path / "web-demo" / "latest.json").exists()


def test_daily_generator_requests_all_registered_leaflet_overlay_variables(tmp_path, monkeypatch):
    generator = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_briefing.py")
    requested = {}

    class OverlayGenerator:
        VARIABLES = {
            "wave_height": {},
            "current_speed": {},
            "swell_1_height": {},
            "swell_1_direction": {},
            "swell_2_height": {},
            "swell_2_direction": {},
            "wind_wave_height": {},
            "wind_wave_direction": {},
        }

        @staticmethod
        def generate_leaflet_overlays(waves_path, currents_path, run_dir, variables):
            requested["variables"] = variables
            return {}

    monkeypatch.setattr(generator, "load_leaflet_overlay_generator", lambda: OverlayGenerator)

    generator.maybe_generate_leaflet_overlays(
        tmp_path / "run",
        tmp_path / "waves.nc",
        tmp_path / "currents.nc",
    )

    assert requested["variables"] == sorted(OverlayGenerator.VARIABLES)


def test_daily_generator_route_precompute_uses_absolute_paths(tmp_path, monkeypatch):
    generator = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_briefing.py")
    waves = tmp_path / "copernicus" / "balearic_waves.nc"
    currents = tmp_path / "copernicus" / "balearic_currents.nc"
    waves.parent.mkdir(parents=True)
    waves.write_text("waves", encoding="utf-8")
    currents.write_text("currents", encoding="utf-8")

    captured = {}

    class Completed:
        stdout = ""
        stderr = ""
        returncode = 0

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs.get("cwd")
        return Completed()

    monkeypatch.setattr(generator.subprocess, "run", fake_run)

    generator.run_route_precompute(waves, currents, "2026-06-18", "2026-06-17T2345Z")

    assert Path(captured["command"][3]).is_absolute()
    assert Path(captured["command"][5]).is_absolute()
    assert captured["cwd"] == generator.PROJECT_ROOT


def test_daily_generator_route_precompute_preserves_gcs_uris(tmp_path, monkeypatch):
    generator = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_briefing.py")
    captured = {}

    class Completed:
        stdout = ""
        stderr = ""
        returncode = 0

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs.get("cwd")
        return Completed()

    monkeypatch.setattr(generator.subprocess, "run", fake_run)

    generator.run_route_precompute(
        "gs://predsea-daily-outputs/copernicus/waves_latest.nc",
        "gs://predsea-daily-outputs/copernicus/currents_latest.nc",
        "2026-06-18",
        "2026-06-18T1922Z",
    )

    assert captured["command"][3] == "gs://predsea-daily-outputs/copernicus/waves_latest.nc"
    assert captured["command"][5] == "gs://predsea-daily-outputs/copernicus/currents_latest.nc"
    assert captured["cwd"] == generator.PROJECT_ROOT


def test_write_bigquery_export_diagnostics_persists_reason_and_traceback(tmp_path):
    generator = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_briefing.py")
    result = {
        "status": "error",
        "reason": "boom",
        "traceback": "Traceback (most recent call last): ...",
        "project_id": "predsea-api",
        "dataset_id": "predsea_validation",
        "table_id": "evidence_rows",
        "observation_rows": 12,
        "forecast_rows": 34,
        "exported_rows": 46,
        "failed_rows": 0,
        "error_messages": [],
        "failed_row_samples": [],
        "insert_errors": [],
        "response_status": 500,
        "response_body": {"error": "boom"},
    }

    diagnostics = generator.write_bigquery_export_diagnostics(tmp_path / "run", "bigquery_export", result)

    path = tmp_path / "run" / "validation" / "bigquery_export_bigquery_diagnostics.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert diagnostics["reason"] == "boom"
    assert diagnostics["traceback"].startswith("Traceback")
    assert payload["observation_rows"] == 12
    assert payload["forecast_rows"] == 34
    assert payload["reason"] == "boom"
    assert payload["traceback"].startswith("Traceback")


def test_daily_generator_cached_forecast_source_requires_matching_run_date(tmp_path):
    generator = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_briefing.py")
    cache_dir = tmp_path / "copernicus"
    cache_dir.mkdir(parents=True)
    (cache_dir / "balearic_waves.nc").write_text("waves", encoding="utf-8")
    (cache_dir / "balearic_currents.nc").write_text("currents", encoding="utf-8")
    (cache_dir / "forecast_source.json").write_text(
        json.dumps(
            {
                "id": "copernicus",
                "label": "Copernicus Marine Mediterranean forecast",
                "available": True,
                "forecast_source_status": "live",
                "forecast_run_date": "2026-06-18",
                "waves_path": str(cache_dir / "balearic_waves.nc"),
                "currents_path": str(cache_dir / "balearic_currents.nc"),
            }
        ),
        encoding="utf-8",
    )

    source = generator.cached_forecast_source(
        type("FetchData", (), {"OUTPUT_DIR": str(tmp_path)}),
        run_date="2026-06-18",
    )

    assert source is not None
    assert source["forecast_source_status"] == "cached"
    assert source["forecast_run_date"] == "2026-06-18"
    assert source["metadata"]["manifest_path"].endswith("forecast_source.json")


def test_publish_latest_copernicus_files_resolves_relative_paths_from_humanintheloop(tmp_path, monkeypatch):
    generator = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_briefing.py")
    human_root = tmp_path / "humanintheloop"
    cache_dir = human_root / "mvp_data" / "copernicus"
    cache_dir.mkdir(parents=True)
    waves = cache_dir / "balearic_waves.nc"
    currents = cache_dir / "balearic_currents.nc"
    waves.write_text("waves", encoding="utf-8")
    currents.write_text("currents", encoding="utf-8")
    uploaded = []

    monkeypatch.setattr(generator, "HUMANINTHELOOP_DIR", human_root)
    monkeypatch.setattr(generator, "upload_file_to_gcs", lambda local_path, gcs_uri: uploaded.append((str(local_path), gcs_uri)))

    result = generator.publish_latest_copernicus_files(
        {
            "waves_path": "mvp_data/copernicus/balearic_waves.nc",
            "currents_path": "mvp_data/copernicus/balearic_currents.nc",
            "forecast_run_date": "2026-06-18",
        },
        run_date="2026-06-18",
    )

    assert uploaded[0][0] == str(waves.resolve())
    assert uploaded[1][0] == str(currents.resolve())
    assert result["waves_path"].startswith("gs://") or result["waves_path"].endswith("balearic_waves.nc")


def test_publish_latest_copernicus_files_skips_hybrid_predsea_source(monkeypatch):
    generator = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_briefing.py")
    uploads = []
    monkeypatch.setattr(
        generator,
        "upload_file_to_gcs",
        lambda local_path, gcs_uri: uploads.append((str(local_path), gcs_uri)),
    )

    result = generator.publish_latest_copernicus_files(
        {
            "id": "predsea_swan",
            "wave_provider": "predsea_swan",
            "current_provider": "copernicus",
            "waves_path": "/tmp/predsea_waves.nc",
            "currents_path": "/tmp/predsea_ocean.nc",
        },
        run_date="2026-07-20",
    )

    assert result == {}
    assert uploads == []


def test_daily_generator_atmospheric_context_is_disabled_by_default(monkeypatch):
    generator = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_briefing.py")
    monkeypatch.delenv("PREDSEA_ENABLE_ATMOSPHERIC_INGESTION", raising=False)

    context = generator.fetch_atmospheric_context(None, Path("/tmp/predsea-run"))

    assert context["enabled"] is False
    assert context["wind_lineage"]["status"] == "not_configured"


def test_daily_generator_snapshot_lineage_includes_wind_ocean_and_ground_truth():
    generator = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_briefing.py")
    snapshot = {}
    source = {"id": "copernicus", "label": "Copernicus Marine Mediterranean forecast"}
    atmospheric_context = {
        "wind_lineage": {
            "source": "ecmwf_open_data",
            "resolution_km": 9.0,
            "status": "active",
            "tier": 3,
        }
    }
    observations = {"canal_de_ibiza": {"wave_height_m": 0.8}}

    generator.annotate_snapshot_with_lineage(snapshot, source, atmospheric_context, observations)

    assert snapshot["data_lineage"] == {
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
    }


def test_daily_generator_fetches_atmospheric_context_when_enabled(monkeypatch, tmp_path):
    generator = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_briefing.py")
    monkeypatch.setenv("PREDSEA_ENABLE_ATMOSPHERIC_INGESTION", "1")

    class IngestAtmosphere:
        @staticmethod
        def run_atmospheric_ingestion(output_dir, dry_run=False):
            return {
                "wind_result": {"available": True, "source": "meteo_france_arome"},
                "wind_lineage": {
                    "source": "meteo_france_arome",
                    "resolution_km": 1.3,
                    "status": "active",
                    "tier": 1,
                },
                "fetchers_configured": ["meteo_france_arome", "ecmwf_open_data"],
            }

    context = generator.fetch_atmospheric_context(
        type("Modules", (), {"ingest_atmosphere": IngestAtmosphere}),
        tmp_path / "run",
    )

    assert context["enabled"] is True
    assert context["wind_result"]["source"] == "meteo_france_arome"
    assert context["wind_lineage"]["resolution_km"] == 1.3


def test_daily_generator_writes_place_weather_outputs(tmp_path, monkeypatch):
    generator = load_script_module(Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_briefing.py")
    monkeypatch.setattr(generator, "safe_load_observations", lambda briefing: {})
    monkeypatch.setattr(generator, "fetch_forecast_sources", lambda modules, run_dir: [
        {
            "id": "copernicus",
            "label": "Copernicus Marine Mediterranean forecast",
            "available": True,
            "preferred": True,
            "waves_path": str(tmp_path / "balearic_waves.nc"),
            "currents_path": str(tmp_path / "balearic_currents.nc"),
        }
    ])
    monkeypatch.setattr(generator, "preferred_forecast_source", lambda sources: sources[0])
    monkeypatch.setattr(generator, "validate_route_artifacts", lambda *args, **kwargs: None)
    monkeypatch.setattr(generator, "maybe_generate_leaflet_overlays", lambda *args, **kwargs: None)
    monkeypatch.setattr(generator, "maybe_generate_route_map", lambda *args, **kwargs: None)
    def fake_copy_preferred_route_artifacts(source_route_dir, preferred_route_dir):
        preferred_route_dir.mkdir(parents=True, exist_ok=True)
        for name in ("daily_snapshot.json", "evidence.json"):
            (preferred_route_dir / name).write_text((Path(source_route_dir) / name).read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.setattr(generator, "copy_preferred_route_artifacts", fake_copy_preferred_route_artifacts)

    def fake_generate_route_artifacts_for_source(
        modules,
        source,
        source_root_dir,
        selected_route_ids,
        routes,
        observations,
        vessel_class,
        question,
        location_label,
        current_time,
        skip_maps,
        atmospheric_context=None,
        source_inventory=None,
    ):
        generated = {}
        for route_id in selected_route_ids:
            route_dir = Path(source_root_dir) / route_id
            route_dir.mkdir(parents=True, exist_ok=True)
            (route_dir / "daily_snapshot.json").write_text(json.dumps({"route_id": route_id}), encoding="utf-8")
            (route_dir / "evidence.json").write_text(json.dumps({"route_id": route_id}), encoding="utf-8")
            generated[route_id] = route_dir
        return generated

    monkeypatch.setattr(generator, "generate_route_artifacts_for_source", fake_generate_route_artifacts_for_source)

    def fake_write_place_weather_outputs(*args, **kwargs):
        run_dir = Path(args[0])
        place_dir = run_dir / "places" / "ibiza"
        place_dir.mkdir(parents=True, exist_ok=True)
        (place_dir / "weather.json").write_text(json.dumps({"place_id": "ibiza"}), encoding="utf-8")
        return {"ibiza": place_dir / "weather.json"}

    def unexpected_bigquery_export(*args, **kwargs):
        raise AssertionError("BigQuery export must not run on the critical publication path")

    monkeypatch.setattr(generator, "load_mvp_modules", lambda: type("Modules", (), {
        "briefing": type("Briefing", (), {"load_observations": staticmethod(lambda: {})}),
        "bigquery_export": type("BQ", (), {"export_validation_archive_to_bigquery": staticmethod(unexpected_bigquery_export)}),
        "fetch_data": type("FetchData", (), {"OUTPUT_DIR": str(tmp_path), "get_balearic_forecast": staticmethod(lambda dry_run=False: None)}),
        "forecast_sources": type("ForecastSources", (), {
            "fetch_available_forecasts": staticmethod(lambda fetch_data, output_dir=None, dry_run=False: [{
                "id": "copernicus",
                "label": "Copernicus Marine Mediterranean forecast",
                "available": True,
                "preferred": True,
                "waves_path": str(tmp_path / "balearic_waves.nc"),
                "currents_path": str(tmp_path / "balearic_currents.nc"),
            }]),
            "source_manifest_entry": staticmethod(lambda source: source),
        }),
        "ingest_atmosphere": type("Atmosphere", (), {"run_atmospheric_ingestion": staticmethod(lambda output_dir=None, dry_run=False: {"wind_result": {"available": False}, "wind_lineage": {"status": "not_configured"}})}),
        "map_generator": object(),
        "route_analysis": __import__("route_analysis"),
        "validation_archive": type("ValidationArchive", (), {"write_validation_archive": staticmethod(lambda *args, **kwargs: {"observation_rows": 0, "forecast_rows": 0, "matched_rows": 0, "matched_variables": {}})}),
        "place_weather": type("PlaceWeather", (), {
            "available_place_ids": staticmethod(lambda: ["ibiza"]),
            "write_place_weather_outputs": staticmethod(fake_write_place_weather_outputs),
        }),
    }))

    result = generator.generate_daily_briefings(
        output_root=tmp_path / "outputs",
        run_date="2026-06-12",
        run_id="2026-06-12T0750Z",
        route_ids=["ibiza_palma"],
        skip_maps=True,
        skip_bigquery=True,
    )

    assert (result.output_dir / "places" / "ibiza" / "weather.json").exists()
