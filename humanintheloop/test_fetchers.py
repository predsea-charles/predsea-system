"""Tests for Phase 2 atmospheric fetchers.

Tests the fetcher modules for Météo-France AROME, AEMET HARMONIE-AROME,
and ECMWF Open Data using mocked HTTP responses.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

import ingest_atmosphere


# ---- Météo-France AROME ----

def test_meteo_france_fetcher_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("METEO_FRANCE_API_KEY", raising=False)
    import fetch_meteo_france

    with pytest.raises(RuntimeError, match="METEO_FRANCE_API_KEY"):
        fetch_meteo_france.fetch_arome_wind()


def test_meteo_france_fetcher_dry_run_returns_available(monkeypatch, tmp_path):
    monkeypatch.setenv("METEO_FRANCE_API_KEY", "test-key")
    import fetch_meteo_france

    result = fetch_meteo_france.fetch_arome_wind(output_dir=tmp_path, dry_run=True)
    assert result["available"] is True
    assert result["source"] == "meteo_france_arome"
    assert result["resolution_km"] == 1.3
    assert result["dry_run"] is True


def test_meteo_france_make_fetcher_integrates_with_tier_selector(monkeypatch, tmp_path):
    monkeypatch.setenv("METEO_FRANCE_API_KEY", "test-key")
    import fetch_meteo_france

    fetcher = fetch_meteo_france.make_fetcher(output_dir=tmp_path, dry_run=True)
    fetchers = {"meteo_france_arome": fetcher}
    result = ingest_atmosphere.select_wind_forecast(fetchers)
    assert result["available"] is True
    assert result["source"] == "meteo_france_arome"
    assert result["tier"] == 1


# ---- AEMET HARMONIE-AROME ----

def test_aemet_fetcher_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("AEMET_API_KEY", raising=False)
    import fetch_aemet

    with pytest.raises(RuntimeError, match="AEMET_API_KEY"):
        fetch_aemet.fetch_harmonie_wind()


def test_aemet_fetcher_dry_run_returns_available(monkeypatch, tmp_path):
    monkeypatch.setenv("AEMET_API_KEY", "test-key")
    import fetch_aemet

    result = fetch_aemet.fetch_harmonie_wind(output_dir=tmp_path, dry_run=True)
    assert result["available"] is True
    assert result["source"] == "aemet_harmonie_arome"
    assert result["resolution_km"] == 2.5
    assert result["dry_run"] is True


def test_aemet_make_fetcher_integrates_with_tier_selector(monkeypatch, tmp_path):
    monkeypatch.setenv("AEMET_API_KEY", "test-key")
    import fetch_aemet

    fetcher = fetch_aemet.make_fetcher(output_dir=tmp_path, dry_run=True)
    fetchers = {"aemet_harmonie_arome": fetcher}
    result = ingest_atmosphere.select_wind_forecast(fetchers)
    assert result["available"] is True
    assert result["source"] == "aemet_harmonie_arome"
    assert result["tier"] == 2


# ---- ECMWF Open Data ----

def test_ecmwf_fetcher_dry_run_returns_available(tmp_path):
    import fetch_ecmwf

    result = fetch_ecmwf.fetch_ecmwf_wind(output_dir=tmp_path, dry_run=True)
    assert result["available"] is True
    assert result["source"] == "ecmwf_open_data"
    assert result["resolution_km"] == 9.0
    assert result["dry_run"] is True


def test_ecmwf_make_fetcher_integrates_with_tier_selector(tmp_path):
    import fetch_ecmwf

    fetcher = fetch_ecmwf.make_fetcher(output_dir=tmp_path, dry_run=True)
    fetchers = {"ecmwf_open_data": fetcher}
    result = ingest_atmosphere.select_wind_forecast(fetchers)
    assert result["available"] is True
    assert result["source"] == "ecmwf_open_data"
    assert result["tier"] == 3


# ---- Tier selection with real fetchers ----

def test_build_fetchers_includes_ecmwf_by_default(monkeypatch):
    monkeypatch.delenv("METEO_FRANCE_API_KEY", raising=False)
    monkeypatch.delenv("AEMET_API_KEY", raising=False)
    fetchers = ingest_atmosphere.build_fetchers(dry_run=True)
    assert "ecmwf_open_data" in fetchers
    assert "meteo_france_arome" not in fetchers
    assert "aemet_harmonie_arome" not in fetchers


def test_build_fetchers_includes_all_when_keys_present(monkeypatch):
    monkeypatch.setenv("METEO_FRANCE_API_KEY", "test")
    monkeypatch.setenv("AEMET_API_KEY", "test")
    fetchers = ingest_atmosphere.build_fetchers(dry_run=True)
    assert "meteo_france_arome" in fetchers
    assert "aemet_harmonie_arome" in fetchers
    assert "ecmwf_open_data" in fetchers


def test_full_tier_fallback_to_ecmwf_when_no_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv("METEO_FRANCE_API_KEY", raising=False)
    monkeypatch.delenv("AEMET_API_KEY", raising=False)
    result = ingest_atmosphere.run_atmospheric_ingestion(
        output_dir=str(tmp_path), dry_run=True,
    )
    wind = result["wind_result"]
    assert wind["available"] is True
    assert wind["source"] == "ecmwf_open_data"
    assert result["wind_lineage"]["status"] == "active"
    assert result["wind_lineage"]["tier"] == 3


def test_full_tier_selects_arome_when_key_present(monkeypatch, tmp_path):
    monkeypatch.setenv("METEO_FRANCE_API_KEY", "test")
    monkeypatch.delenv("AEMET_API_KEY", raising=False)
    result = ingest_atmosphere.run_atmospheric_ingestion(
        output_dir=str(tmp_path), dry_run=True,
    )
    wind = result["wind_result"]
    assert wind["available"] is True
    assert wind["source"] == "meteo_france_arome"
    assert result["wind_lineage"]["tier"] == 1


# ---- ECMWF resolution fix ----

def test_ecmwf_provider_resolution_is_9km():
    ecmwf_provider = next(
        p for p in ingest_atmosphere.ATMOSPHERIC_PROVIDERS
        if p["id"] == "ecmwf_open_data"
    )
    assert ecmwf_provider["resolution_km"] == 9.0
