"""Tests for observation ingestion orchestrator."""

import sys
import types
import pytest

import ingest_observations


@pytest.fixture(autouse=True)
def mock_copernicus_default(monkeypatch):
    monkeypatch.setattr(
        ingest_observations.fetch_copernicus_insitu,
        "fetch_copernicus_insitu_bundle",
        lambda dry_run=False: {"observations": {}, "stations": [], "errors": {}}
    )


def test_fetch_all_observations_returns_puertos_first_bundle(monkeypatch):
    monkeypatch.delenv("PREDSEA_ENABLE_PUERTOS_OBSERVATIONS", raising=False)
    monkeypatch.delenv("PREDSEA_ENABLE_EMODNET_OBSERVATIONS", raising=False)
    monkeypatch.delenv("PREDSEA_ENABLE_PORTUS_OBSERVATIONS", raising=False)
    monkeypatch.delenv("PREDSEA_ENABLE_SOCIB_OBSERVATIONS", raising=False)

    puertos_result = {
        "observations": {"puertos_mallorca": {"wave_height_m": 0.8}},
        "measurements": {"puertos_mallorca": [{"raw_key": "wave_height_m", "value": 0.8}]},
        "errors": {},
        "catalog_stations": [{"station_id": "puertos_mallorca"}],
    }
    portus_result = {
        "observations": {"portus_ibiza": {"wave_height_m": 0.4}},
        "predictions": {},
        "errors": {},
    }

    monkeypatch.setitem(
        sys.modules,
        "fetch_puertos_estado",
        types.SimpleNamespace(fetch_balearic_observations=lambda dry_run=False: puertos_result),
    )
    monkeypatch.setattr(
        ingest_observations.fetch_portus,
        "fetch_portus_bundle",
        lambda dry_run=False: portus_result,
    )
    monkeypatch.setattr(
        ingest_observations.fetch_emodnet,
        "fetch_emodnet_bundle",
        lambda dry_run=False: {"observations": {}, "stations": [], "errors": {}},
    )
    monkeypatch.setattr(
        ingest_observations.socib_public,
        "fetch_public_observations",
        lambda *args, **kwargs: {},
    )

    result = ingest_observations.fetch_all_observations(include_puertos=True, include_portus=True)
    assert "observations" in result
    assert result["ground_truth_lineage"]["source"] == "puertos_del_estado_and_puertos_portus"
    assert "puertos_puertos_mallorca" in result["observations"]
    assert "portus_ibiza" in result["observations"]
    assert "socib" not in result["errors"]


def test_puertos_enabled_by_default(monkeypatch):
    monkeypatch.delenv("PREDSEA_ENABLE_PUERTOS_OBSERVATIONS", raising=False)
    assert ingest_observations._puertos_enabled()


def test_puertos_enabled_by_env_var(monkeypatch):
    monkeypatch.setenv("PREDSEA_ENABLE_PUERTOS_OBSERVATIONS", "1")
    assert ingest_observations._puertos_enabled()


def test_puertos_can_be_disabled_explicitly(monkeypatch):
    monkeypatch.setenv("PREDSEA_ENABLE_PUERTOS_OBSERVATIONS", "0")
    assert not ingest_observations._puertos_enabled()


def test_portus_enabled_by_default(monkeypatch):
    monkeypatch.delenv("PREDSEA_ENABLE_PORTUS_OBSERVATIONS", raising=False)
    assert ingest_observations._portus_enabled()


def test_emodnet_enabled_by_default(monkeypatch):
    monkeypatch.delenv("PREDSEA_ENABLE_EMODNET_OBSERVATIONS", raising=False)
    assert ingest_observations._emodnet_enabled()


def test_fetch_all_observations_merges_emodnet_bundle(monkeypatch):
    monkeypatch.setenv("PREDSEA_ENABLE_EMODNET_OBSERVATIONS", "1")
    monkeypatch.setenv("PREDSEA_ENABLE_PUERTOS_OBSERVATIONS", "0")
    monkeypatch.setenv("PREDSEA_ENABLE_PORTUS_OBSERVATIONS", "0")
    monkeypatch.setenv("PREDSEA_ENABLE_SOCIB_OBSERVATIONS", "0")

    emodnet_result = {
        "observations": {
            "emodnet_bilbao": {
                "provider": "emodnet_physics",
                "source_system": "emodnet_physics",
                "source_label": "EMODNET_PHYSICS",
                "station_id": "emodnet_bilbao",
                "station_name": "Bilbao",
                "network": "emodnet_physics",
                "station_kind": "platform",
                "latitude": 43.4,
                "longitude": -3.0,
                "measurements": [
                    {
                        "raw_key": "wave_height_m",
                        "source_field": "VTDH",
                        "variable": "wave_height",
                        "value": 1.2,
                        "units": "m",
                        "observed_at_utc": "2026-06-18T12:00:00Z",
                        "sample_time_utc": "2026-06-18T12:00:00Z",
                        "source_time_coordinate_utc": "2026-06-18T12:00:00Z",
                    }
                ],
            }
        },
        "stations": [{"station_id": "emodnet_bilbao", "station_name": "Bilbao"}],
        "errors": {},
    }

    monkeypatch.setattr(
        ingest_observations.fetch_emodnet,
        "fetch_emodnet_bundle",
        lambda dry_run=False: emodnet_result,
    )
    monkeypatch.setitem(
        sys.modules,
        "fetch_puertos_estado",
        types.SimpleNamespace(
            fetch_balearic_observations=lambda dry_run=False: {
                "observations": {},
                "measurements": {},
                "errors": {},
                "catalog_stations": [],
            }
        ),
    )

    result = ingest_observations.fetch_all_observations(include_puertos=True, include_emodnet=True, include_portus=False)
    assert "emodnet_bilbao" in result["observations"]
    assert result["ground_truth_lineage"]["source"] == "emodnet_physics"
    assert result["ground_truth_lineage"]["status"] == "matched_successfully"
    assert result["station_metadata"][0]["station_id"] == "emodnet_bilbao"


def test_ground_truth_lineage_with_both_sources():
    observations = {"canal_de_ibiza": {}, "puertos_mahon": {}}
    lineage = ingest_observations._build_ground_truth_lineage(
        observations,
        ["puertos_del_estado", "puertos_portus"],
        {},
    )
    assert lineage["source"] == "puertos_del_estado_and_puertos_portus"
    assert lineage["status"] == "matched_successfully"
    assert lineage["station_count"] == 2


def test_ground_truth_lineage_puertos_only():
    lineage = ingest_observations._build_ground_truth_lineage(
        {"canal_de_ibiza": {}},
        ["puertos_del_estado"],
        {},
    )
    assert lineage["source"] == "puertos_del_estado"
    assert lineage["status"] == "matched_successfully"


def test_ground_truth_lineage_empty():
    lineage = ingest_observations._build_ground_truth_lineage({}, [], {})
    assert lineage["source"] is None
    assert lineage["status"] == "unavailable"


def test_socib_enabled_by_default(monkeypatch):
    monkeypatch.delenv("PREDSEA_ENABLE_SOCIB_OBSERVATIONS", raising=False)
    assert ingest_observations._socib_enabled()


def test_socib_enabled_by_env_var(monkeypatch):
    monkeypatch.setenv("PREDSEA_ENABLE_SOCIB_OBSERVATIONS", "1")
    assert ingest_observations._socib_enabled()


def test_socib_can_be_disabled_explicitly(monkeypatch):
    monkeypatch.setenv("PREDSEA_ENABLE_SOCIB_OBSERVATIONS", "0")
    assert not ingest_observations._socib_enabled()


def test_fetch_all_observations_merges_socib(monkeypatch):
    monkeypatch.setenv("PREDSEA_ENABLE_SOCIB_OBSERVATIONS", "1")
    monkeypatch.setenv("PREDSEA_ENABLE_PUERTOS_OBSERVATIONS", "0")
    monkeypatch.setenv("PREDSEA_ENABLE_EMODNET_OBSERVATIONS", "0")
    monkeypatch.setenv("PREDSEA_ENABLE_PORTUS_OBSERVATIONS", "0")

    mock_socib_data = {
        "canal_de_ibiza": {
            "name": "Canal de Ibiza Buoy",
            "last_sample_utc": "2026-06-27 10:00 UTC",
            "wave_height_m": 0.34,
            "water_temp_c": 25.14,
        }
    }
    monkeypatch.setattr(
        ingest_observations.socib_public,
        "fetch_public_observations",
        lambda *args, **kwargs: mock_socib_data,
    )

    result = ingest_observations.fetch_all_observations(
        include_puertos=False,
        include_emodnet=False,
        include_portus=False,
        include_socib=True,
    )
    assert "canal_de_ibiza" in result["observations"]
    assert result["observations"]["canal_de_ibiza"]["wave_height_m"] == 0.34
    assert result["ground_truth_lineage"]["source"] == "socib_public"
    assert result["ground_truth_lineage"]["status"] == "matched_successfully"


def test_fetch_all_observations_handles_socib_failure_gracefully(monkeypatch):
    monkeypatch.setenv("PREDSEA_ENABLE_SOCIB_OBSERVATIONS", "1")
    monkeypatch.setenv("PREDSEA_ENABLE_PUERTOS_OBSERVATIONS", "0")
    monkeypatch.setenv("PREDSEA_ENABLE_EMODNET_OBSERVATIONS", "0")
    monkeypatch.setenv("PREDSEA_ENABLE_PORTUS_OBSERVATIONS", "0")

    def raise_error(*args, **kwargs):
        raise ValueError("API error simulator")

    monkeypatch.setattr(
        ingest_observations.socib_public,
        "fetch_public_observations",
        raise_error,
    )

    result = ingest_observations.fetch_all_observations(
        include_puertos=False,
        include_emodnet=False,
        include_portus=False,
        include_socib=True,
    )
    assert "socib_public" in result["errors"]
    assert "API error simulator" in result["errors"]["socib_public"]
    assert result["ground_truth_lineage"]["source"] is None
    assert result["ground_truth_lineage"]["status"] == "unavailable"


def test_copernicus_enabled_by_default(monkeypatch):
    monkeypatch.delenv("PREDSEA_ENABLE_COPERNICUS_OBSERVATIONS", raising=False)
    assert ingest_observations._copernicus_enabled()


def test_copernicus_enabled_by_env_var(monkeypatch):
    monkeypatch.setenv("PREDSEA_ENABLE_COPERNICUS_OBSERVATIONS", "1")
    assert ingest_observations._copernicus_enabled()


def test_copernicus_can_be_disabled_explicitly(monkeypatch):
    monkeypatch.setenv("PREDSEA_ENABLE_COPERNICUS_OBSERVATIONS", "0")
    assert not ingest_observations._copernicus_enabled()


def test_fetch_all_observations_merges_copernicus(monkeypatch):
    # Disable the mock_copernicus_default autouse mock by overriding it
    monkeypatch.setenv("PREDSEA_ENABLE_COPERNICUS_OBSERVATIONS", "1")
    monkeypatch.setenv("PREDSEA_ENABLE_PUERTOS_OBSERVATIONS", "0")
    monkeypatch.setenv("PREDSEA_ENABLE_EMODNET_OBSERVATIONS", "0")
    monkeypatch.setenv("PREDSEA_ENABLE_PORTUS_OBSERVATIONS", "0")
    monkeypatch.setenv("PREDSEA_ENABLE_SOCIB_OBSERVATIONS", "0")

    copernicus_result = {
        "observations": {
            "copernicus_insitu_6100196": {
                "provider": "copernicus_insitu",
                "source_system": "copernicus_insitu",
                "source_label": "Copernicus In-Situ",
                "station_id": "copernicus_insitu_6100196",
                "station_name": "6100196",
                "network": "copernicus_insitu",
                "station_kind": "platform",
                "latitude": 42.1,
                "longitude": 4.5,
                "water_temp_c": 19.5,
                "measurements": [
                    {
                        "raw_key": "water_temp_c",
                        "source_field": "TEMP",
                        "variable": "water_temperature",
                        "value": 19.5,
                        "units": "celsius",
                        "observed_at_utc": "2026-07-08T12:00:00Z",
                        "sample_time_utc": "2026-07-08T12:00:00Z",
                        "source_time_coordinate_utc": "2026-07-08T12:00:00Z",
                    }
                ],
            }
        },
        "stations": [{"station_id": "copernicus_insitu_6100196", "station_name": "6100196"}],
        "errors": {},
    }

    monkeypatch.setattr(
        ingest_observations.fetch_copernicus_insitu,
        "fetch_copernicus_insitu_bundle",
        lambda dry_run=False: copernicus_result,
    )

    result = ingest_observations.fetch_all_observations(
        include_puertos=False,
        include_emodnet=False,
        include_portus=False,
        include_socib=False,
        include_copernicus=True,
    )
    assert "copernicus_insitu_6100196" in result["observations"]
    assert result["observations"]["copernicus_insitu_6100196"]["water_temp_c"] == 19.5
    assert result["ground_truth_lineage"]["source"] == "copernicus_insitu"
    assert result["ground_truth_lineage"]["status"] == "matched_successfully"


