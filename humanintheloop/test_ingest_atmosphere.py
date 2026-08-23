import ingest_atmosphere


def successful_fetcher(provider_id):
    def fetcher(provider):
        if provider["id"] != provider_id:
            raise RuntimeError(f"{provider['id']} unavailable")
        return {
            "available": True,
            "source": provider["id"],
            "resolution_km": provider["resolution_km"],
            "dataset_path": f"/tmp/{provider['id']}.grib2",
        }

    return fetcher


def test_select_wind_forecast_prefers_meteo_france_arome():
    result = ingest_atmosphere.select_wind_forecast(
        {
            "meteo_france_arome": successful_fetcher("meteo_france_arome"),
            "aemet_harmonie_arome": successful_fetcher("aemet_harmonie_arome"),
            "ecmwf_open_data": successful_fetcher("ecmwf_open_data"),
        }
    )

    assert result["available"] is True
    assert result["source"] == "meteo_france_arome"
    assert result["resolution_km"] == 1.3
    assert result["bbox"] == ingest_atmosphere.BALEARIC_BBOX


def test_select_wind_forecast_falls_back_to_aemet_then_ecmwf():
    aemet_result = ingest_atmosphere.select_wind_forecast(
        {
            "aemet_harmonie_arome": successful_fetcher("aemet_harmonie_arome"),
            "ecmwf_open_data": successful_fetcher("ecmwf_open_data"),
        }
    )
    ecmwf_result = ingest_atmosphere.select_wind_forecast(
        {"ecmwf_open_data": successful_fetcher("ecmwf_open_data")}
    )

    assert aemet_result["source"] == "aemet_harmonie_arome"
    assert aemet_result["resolution_km"] == 2.5
    assert ecmwf_result["source"] == "ecmwf_open_data"
    assert ecmwf_result["resolution_km"] == 9.0


def test_select_wind_forecast_returns_unavailable_lineage_when_all_fail():
    result = ingest_atmosphere.select_wind_forecast({})
    lineage = ingest_atmosphere.lineage_for_wind_result(result)

    assert result["available"] is False
    assert result["source"] is None
    assert "meteo_france_arome" in result["errors"]
    assert lineage == {
        "source": None,
        "resolution_km": None,
        "status": "unavailable",
        "tier": None,
    }


def test_lineage_for_active_arome_wind_result():
    result = ingest_atmosphere.select_wind_forecast(
        {"meteo_france_arome": successful_fetcher("meteo_france_arome")}
    )

    assert ingest_atmosphere.lineage_for_wind_result(result) == {
        "source": "meteo_france_arome",
        "resolution_km": 1.3,
        "status": "active",
        "tier": 1,
    }
