import pandas as pd


def test_parse_dataset_frame_emits_measurements_and_station_metadata():
    from predsea.connectors.emodnet_physics.etl import parse_dataset_frame

    frame = pd.DataFrame(
        [
            {
                "PLATFORMCODE": "Bilbao",
                "SOURCE": "emodnet",
                "SENSOR": "",
                "time": "2026-06-18T12:00:00Z",
                "TIME_QC": 1,
                "depth": 0.0,
                "DEPTH_QC": 1,
                "latitude": 43.4,
                "longitude": -3.0,
                "POSITION_QC": 1,
                "VTDH": 1.2,
                "VTDH_QC": 1,
                "VTDH_DM": "",
                "url_metadata": "https://example.test/metadata",
                "qc_entity": 0,
            }
        ]
    )

    parsed = parse_dataset_frame(
        "ERD_EP_TS_VTDH_NRT",
        frame,
        query_url="https://data-erddap.emodnet-physics.eu/erddap/tabledap/ERD_EP_TS_VTDH_NRT.csv?..."
    )

    observations = parsed["observations"]
    assert "emodnet_bilbao" in observations
    record = observations["emodnet_bilbao"]
    assert record["provider"] == "emodnet_physics"
    assert record["network"] == "emodnet_physics"
    assert record["measurements"][0]["variable"] == "wave_height"
    assert record["measurements"][0]["raw_key"] == "wave_height_m"
    assert record["measurements"][0]["value"] == 1.2
    assert record["measurements"][0]["units"] == "m"
    assert record["measurements"][0]["observed_at_utc"] == "2026-06-18T12:00:00Z"
    assert parsed["stations"][0]["station_id"] == "emodnet_bilbao"
    assert parsed["stations"][0]["variables_supported"] == ["wave_height"]


def test_parse_dataset_frame_filters_out_of_bounds_coordinates():
    from predsea.connectors.emodnet_physics.etl import parse_dataset_frame

    frame = pd.DataFrame(
        [
            {
                "PLATFORMCODE": "InBounds",
                "SOURCE": "emodnet",
                "SENSOR": "",
                "time": "2026-06-18T12:00:00Z",
                "TIME_QC": 1,
                "depth": 0.0,
                "DEPTH_QC": 1,
                "latitude": 40.0,
                "longitude": 10.0,
                "POSITION_QC": 1,
                "VTDH": 1.2,
                "VTDH_QC": 1,
                "VTDH_DM": "",
                "url_metadata": "https://example.test/metadata",
                "qc_entity": 0,
            },
            {
                "PLATFORMCODE": "OutOfBounds",
                "SOURCE": "emodnet",
                "SENSOR": "",
                "time": "2026-06-18T12:00:00Z",
                "TIME_QC": 1,
                "depth": 0.0,
                "DEPTH_QC": 1,
                "latitude": 10.0,  # out of bounds
                "longitude": 10.0,
                "POSITION_QC": 1,
                "VTDH": 2.0,
                "VTDH_QC": 1,
                "VTDH_DM": "",
                "url_metadata": "https://example.test/metadata",
                "qc_entity": 0,
            }
        ]
    )

    parsed = parse_dataset_frame(
        "ERD_EP_TS_VTDH_NRT",
        frame,
        query_url="https://data-erddap.emodnet-physics.eu/erddap/tabledap/ERD_EP_TS_VTDH_NRT.csv?..."
    )

    observations = parsed["observations"]
    assert "emodnet_inbounds" in observations
    assert "emodnet_outofbounds" not in observations
