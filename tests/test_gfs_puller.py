from datetime import datetime, timezone
from pathlib import Path

from ingestion.gfs_puller import (
    WESTERN_MEDITERRANEAN_BBOX,
    GfsPullConfig,
    build_s3_prefix,
    choose_latest_cycle,
    download_latest_cycle,
    ensure_wgrib2_available,
    find_latest_available_config,
    format_cycle,
    grib_filter_expression,
    list_grib_keys,
)


def test_choose_latest_cycle_uses_completed_six_hour_cycle():
    assert choose_latest_cycle(datetime(2026, 5, 4, 1, 30, tzinfo=timezone.utc)) == "00"
    assert choose_latest_cycle(datetime(2026, 5, 4, 7, 0, tzinfo=timezone.utc)) == "06"
    assert choose_latest_cycle(datetime(2026, 5, 4, 13, 0, tzinfo=timezone.utc)) == "12"
    assert choose_latest_cycle(datetime(2026, 5, 4, 23, 59, tzinfo=timezone.utc)) == "18"


def test_format_cycle_and_s3_prefix_match_noaa_gfs_layout():
    run_time = datetime(2026, 5, 4, 13, 0, tzinfo=timezone.utc)

    assert format_cycle(run_time, "12") == "gfs.20260504/12/atmos"
    assert build_s3_prefix(run_time, "12") == "gfs.20260504/12/atmos/"


def test_list_grib_keys_filters_025_degree_grib2_files():
    class FakePaginator:
        def paginate(self, Bucket, Prefix):
            assert Bucket == "noaa-gfs-bdp-pds"
            assert Prefix == "gfs.20260504/12/atmos/"
            return [
                {
                    "Contents": [
                        {"Key": "gfs.20260504/12/atmos/gfs.t12z.pgrb2.0p25.f000"},
                        {"Key": "gfs.20260504/12/atmos/gfs.t12z.pgrb2.0p25.f003.idx"},
                        {"Key": "gfs.20260504/12/atmos/gfs.t12z.pgrb2.1p00.f000"},
                        {"Key": "gfs.20260504/12/atmos/gfs.t12z.pgrb2.0p25.f003"},
                    ]
                }
            ]

    class FakeClient:
        def get_paginator(self, name):
            assert name == "list_objects_v2"
            return FakePaginator()

    config = GfsPullConfig(run_date=datetime(2026, 5, 4, 13, tzinfo=timezone.utc), cycle="12")

    assert list_grib_keys(FakeClient(), config) == [
        "gfs.20260504/12/atmos/gfs.t12z.pgrb2.0p25.f000",
        "gfs.20260504/12/atmos/gfs.t12z.pgrb2.0p25.f003",
    ]


def test_find_latest_available_config_walks_back_to_available_cycle(monkeypatch):
    attempts = []

    def fake_list_grib_keys(s3_client, config):
        attempts.append((config.run_date.strftime("%Y%m%d"), config.cycle))
        if config.cycle == "06":
            return ["gfs.20260504/06/atmos/gfs.t06z.pgrb2.0p25.f000"]
        return []

    monkeypatch.setattr("ingestion.gfs_puller.list_grib_keys", fake_list_grib_keys)

    config, keys = find_latest_available_config(
        s3_client=object(),
        now=datetime(2026, 5, 4, 13, tzinfo=timezone.utc),
        output_dir=Path("data/gfs"),
    )

    assert attempts[:2] == [("20260504", "12"), ("20260504", "06")]
    assert config.cycle == "06"
    assert keys == ["gfs.20260504/06/atmos/gfs.t06z.pgrb2.0p25.f000"]


def test_grib_filter_expression_describes_western_mediterranean_bbox():
    expression = grib_filter_expression(WESTERN_MEDITERRANEAN_BBOX)

    assert "lon>=-6.0" in expression
    assert "lon<=10.0" in expression
    assert "lat>=34.0" in expression
    assert "lat<=45.5" in expression


def test_config_uses_partitioned_output_directory(tmp_path):
    config = GfsPullConfig(
        run_date=datetime(2026, 5, 4, 13, tzinfo=timezone.utc),
        cycle="12",
        output_dir=tmp_path,
    )

    assert config.cycle_output_dir == Path(tmp_path) / "gfs.20260504" / "12"


def test_download_latest_cycle_dry_run_prints_available_keys(monkeypatch, capsys, tmp_path):
    config = GfsPullConfig(
        run_date=datetime(2026, 5, 4, 13, tzinfo=timezone.utc),
        cycle="12",
        output_dir=tmp_path,
    )
    keys = [
        "gfs.20260504/12/atmos/gfs.t12z.pgrb2.0p25.f000",
        "gfs.20260504/12/atmos/gfs.t12z.pgrb2.0p25.f003",
    ]
    monkeypatch.setattr("ingestion.gfs_puller.make_s3_client", lambda: object())
    monkeypatch.setattr("ingestion.gfs_puller.find_latest_available_config", lambda **kwargs: (config, keys))

    result = download_latest_cycle(output_dir=tmp_path, dry_run=True, max_files=1)

    assert result == []
    assert capsys.readouterr().out == "gfs.20260504/12/atmos/gfs.t12z.pgrb2.0p25.f000\n"


def test_ensure_wgrib2_available_raises_clear_error(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)

    try:
        ensure_wgrib2_available()
    except RuntimeError as exc:
        assert "wgrib2 is required" in str(exc)
    else:
        raise AssertionError("Expected missing wgrib2 to raise RuntimeError")
