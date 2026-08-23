import pandas as pd
import pytest
import xarray as xr


def test_latest_valid_sample_returns_latest_sample_even_if_future():
    from predsea.connectors.puertos_del_estado.normalize_observations import latest_valid_sample_from_dataarray

    ds = xr.Dataset(
        {
            "VHM0": ("time", [0.1, -9999.0, 0.4]),
            "VHM0_QC": ("time", [1, 9, 1]),
        },
        coords={
            "time": pd.to_datetime(
                [
                    "2026-06-15T06:00:00Z",
                    "2026-06-15T12:00:00Z",
                    "2026-06-16T23:59:59Z",
                ],
                utc=True,
            ),
        },
    )

    sample = latest_valid_sample_from_dataarray(
        ds["VHM0"],
        qc_da=ds["VHM0_QC"],
        fill_values={-9999.0},
        now_utc="2026-06-15T13:00:00Z",
    )

    assert sample is not None
    assert sample["value"] == 0.4
    assert sample["source_time_coordinate_utc"] == "2026-06-16T23:59:59Z"
    assert sample["observed_at_utc"] == "2026-06-16T23:59:59Z"
    assert sample["freshness_status"] == "future"
    assert sample["is_future_timestamp"] is True


def test_hfradar_parser_emits_current_components():
    import pandas as pd
    import xarray as xr

    from predsea.connectors.puertos_del_estado.hfradar_connector import parse_station_dataset

    ds = xr.Dataset(
        {
            "u": ("time", [0.2, 0.4]),
            "v": ("time", [0.1, 0.3]),
            "stdu": ("time", [0.01, 0.02]),
            "stdv": ("time", [0.01, 0.02]),
            "cov": ("time", [0.8, 0.9]),
        },
        coords={
            "time": pd.to_datetime(["2026-06-15T10:00:00Z", "2026-06-15T11:00:00Z"], utc=True),
        },
    )
    station = {
        "station_id": "puertos_delta_del_ebro",
        "station_name": "Delta del Ebro",
        "catalog_id": "radar_local_deltaebro",
        "catalog_url": "https://opendap.puertos.es/thredds/catalog/radar_local_deltaebro/catalog.xml",
        "network": "hfradar",
        "latitude": 40.0,
        "longitude": 1.0,
    }

    records = parse_station_dataset(ds, station, dataset_url="https://example.test/radar.nc")
    variables = {record["variable"] for record in records}
    assert {"current_u", "current_v"}.issubset(variables)
    current_u_samples = [record for record in records if record["variable"] == "current_u"]
    assert [record["sample_time_utc"] for record in current_u_samples] == [
        "2026-06-15T10:00:00Z",
        "2026-06-15T11:00:00Z",
    ]
    assert all(record["source_label"] == "HF_RADAR" for record in current_u_samples)
    assert all(record["observed_at_utc"] == record["sample_time_utc"] for record in current_u_samples)
    assert all(record["qc_flag"] is None for record in current_u_samples)
    assert all(record["is_qc_good"] is None for record in current_u_samples)


def test_hfradar_parser_returns_empty_list_when_component_missing():
    import pandas as pd
    import xarray as xr

    from predsea.connectors.puertos_del_estado.hfradar_connector import parse_station_dataset

    ds = xr.Dataset(
        {
            "u": ("time", [0.2, 0.4]),
            "stdu": ("time", [0.01, 0.02]),
        },
        coords={
            "time": pd.to_datetime(["2026-06-15T10:00:00Z", "2026-06-15T11:00:00Z"], utc=True),
        },
    )
    station = {
        "station_id": "puertos_delta_del_ebro",
        "station_name": "Delta del Ebro",
        "catalog_id": "radar_local_deltaebro",
        "catalog_url": "https://opendap.puertos.es/thredds/catalog/radar_local_deltaebro/catalog.xml",
        "network": "hfradar",
        "latitude": 40.0,
        "longitude": 1.0,
    }

    records = parse_station_dataset(ds, station, dataset_url="https://example.test/radar.nc")
    assert records == []


def test_station_catalog_discovers_hfradar_network(monkeypatch):
    from predsea.connectors.puertos_del_estado import station_catalog

    monkeypatch.setattr(
        station_catalog,
        "_discover_root_catalog_refs",
        lambda **kwargs: [
            {
                "name": "Delta del Ebro",
                "href": "/thredds/catalog/radar_local_deltaebro/catalog.xml",
                "catalog_url": "https://opendap.puertos.es/thredds/catalog/radar_local_deltaebro/catalog.xml",
            }
        ],
    )

    def fake_catalogs_for_device(device, **kwargs):
        if device != "radar":
            return []
        return [
            {
                "Name": "Delta del Ebro",
                "Xlink": "/thredds/catalog/radar_local_deltaebro/catalog.xml",
                "portusLink": None,
                "categories": {"dataType": "measure", "variable": "currents", "device": "radar"},
                "variablesInfo": [{"name": "u"}],
                "bounds": [{"limN": 41.2330017, "limS": 39.5849991, "limE": 2.07800007, "limW": 0.064000003}],
                "coords": None,
                "dateFrom": "2013-12-01T08:46:38.519+00:00",
                "dateTo": "2026-06-01T08:46:37.975+00:00",
                "isPoint": False,
                "availableMean": None,
                "hourStep": 1,
                "netcdf4": False,
                "catalogRefID": "radar_local_deltaebro",
            }
        ]

    monkeypatch.setattr(station_catalog, "_portuscopia_catalogs_for_device", fake_catalogs_for_device)

    stations = station_catalog.discover_station_catalogs()
    radar = next(station for station in stations if station["network"] == "hfradar")
    assert radar["source_label"] == "HF_RADAR"
    assert radar["station_id"] == "puertos_delta_del_ebro"


def test_discover_latest_dataset_url_ignores_hidden_dataset_refs(monkeypatch):
    from predsea.connectors.puertos_del_estado import station_catalog

    xml = """
    <catalog xmlns="http://www.unidata.ucar.edu/namespaces/thredds/InvCatalog/v1.0">
      <dataset name=".DS_Store" urlPath="._junk.nc"/>
      <dataset name="Hidden" urlPath="__MACOSX/._bad.nc"/>
      <dataset name="Valid" urlPath="wave_local_a12a/HW-2026060900-B2026060900-HC.nc"/>
    </catalog>
    """

    monkeypatch.setattr(
        station_catalog,
        "fetch_text",
        lambda *args, **kwargs: {"text": xml},
    )

    url = station_catalog.discover_latest_dataset_url("https://example.test/catalog.xml")
    assert url == "https://opendap.puertos.es/thredds/dodsC/wave_local_a12a/HW-2026060900-B2026060900-HC.nc"


def test_discover_observation_stations_skips_timeouts(monkeypatch):
    from requests.exceptions import ReadTimeout

    from predsea.connectors.puertos_del_estado import station_catalog

    monkeypatch.setattr(
        station_catalog,
        "discover_station_catalogs",
        lambda **kwargs: [
            {
                "station_id": "puertos_bad",
                "station_name": "Bad Station",
                "station_key": "bad_station",
                "catalog_url": "https://example.test/bad/catalog.xml",
                "network": "redext",
                "source_label": "REDEXT",
            },
            {
                "station_id": "puertos_good",
                "station_name": "Good Station",
                "station_key": "good_station",
                "catalog_url": "https://example.test/good/catalog.xml",
                "network": "redext",
                "source_label": "REDEXT",
            },
        ],
    )

    def fake_latest_dataset_url(catalog_url, **kwargs):
        if "bad" in catalog_url:
            raise ReadTimeout("timed out")
        return "https://example.test/good/dataset.nc4"

    monkeypatch.setattr(station_catalog, "discover_latest_dataset_url", fake_latest_dataset_url)

    stations = station_catalog.discover_observation_stations()
    assert len(stations) == 1
    assert stations[0]["station_id"] == "puertos_good"
    assert stations[0]["latest_dataset_url"] == "https://example.test/good/dataset.nc4"
