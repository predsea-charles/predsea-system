from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import fetch_ecmwf_forcing


class FakeEccodes:
    def __init__(self, messages):
        self.messages = messages
        self.index = 0

    def codes_grib_new_from_file(self, file_obj):
        if self.index >= len(self.messages):
            return None
        message = self.messages[self.index]
        self.index += 1
        return message

    @staticmethod
    def codes_get(message, key):
        return message[key]

    @staticmethod
    def codes_release(message):
        return None


class FakeWritableEccodes(FakeEccodes):
    def __init__(self, messages):
        super().__init__(messages)
        self.written = []

    @staticmethod
    def codes_set(message, key, value):
        message[key] = value

    def codes_write(self, message, file_obj):
        self.written.append(dict(message))
        file_obj.write(b"GRIB")


class FakePayloadEccodes(FakeEccodes):
    @staticmethod
    def codes_get_values(message):
        if "error" in message:
            raise RuntimeError(message["error"])
        return message["values"]


def test_skip_if_exists_validates_forecast_metadata(monkeypatch, tmp_path):
    """Cached valid-time files must not bypass the WPS metadata check."""
    monkeypatch.setattr(
        fetch_ecmwf_forcing,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "run_date": "2026-07-14",
                "run_time": 0,
                "lead_hours": 3,
                "output_dir": tmp_path,
                "gcs_bucket": "",
                "dry_run": False,
                "skip_if_exists": True,
            },
        )(),
    )
    for kind in ("pl", "sfc"):
        (tmp_path / f"ecmwf_{kind}_2026-07-14_00Z.grib2").write_bytes(b"stale")

    monkeypatch.setattr(fetch_ecmwf_forcing, "validate_forcing_files", lambda *args: None)
    metadata_checks = []

    def reject_stale(path, *args):
        metadata_checks.append(path.name)
        raise RuntimeError("step-zero metadata")

    monkeypatch.setattr(fetch_ecmwf_forcing, "validate_forecast_metadata", reject_stale)

    def stop_after_cache_rejection(**kwargs):
        assert not (tmp_path / "ecmwf_pl_2026-07-14_00Z.grib2").exists()
        assert not (tmp_path / "ecmwf_sfc_2026-07-14_00Z.grib2").exists()
        raise RuntimeError("stop test")

    monkeypatch.setattr(fetch_ecmwf_forcing, "fetch_ecmwf_data", stop_after_cache_rejection)

    with pytest.raises(SystemExit):
        fetch_ecmwf_forcing.main()

    assert metadata_checks == ["ecmwf_pl_2026-07-14_00Z.grib2"]


def test_validate_forecast_metadata_accepts_cycle_and_forecast_leads(
    monkeypatch, tmp_path
):
    path = tmp_path / "forcing.grib2"
    path.write_bytes(b"grib")
    fake = FakeEccodes(
        [
            {
                "dataDate": 20260714,
                "dataTime": 0,
                "validityDate": 20260714,
                "validityTime": 0,
                "forecastTime": 0,
            },
            {
                "dataDate": 20260714,
                "dataTime": 0,
                "validityDate": 20260714,
                "validityTime": 300,
                "forecastTime": 3,
            },
        ]
    )
    monkeypatch.setattr(fetch_ecmwf_forcing, "eccodes", fake)

    fetch_ecmwf_forcing.validate_forecast_metadata(path, "2026-07-14", 0, [0, 3])


def test_validate_forecast_metadata_rejects_rewritten_step_zero_messages(
    monkeypatch, tmp_path
):
    path = tmp_path / "forcing.grib2"
    path.write_bytes(b"grib")
    fake = FakeEccodes(
        [
            {
                "dataDate": 20260714,
                "dataTime": 300,
                "validityDate": 20260714,
                "validityTime": 300,
                "forecastTime": 0,
            }
        ]
    )
    monkeypatch.setattr(fetch_ecmwf_forcing, "eccodes", fake)

    with pytest.raises(RuntimeError, match="preserve the ECMWF cycle reference"):
        fetch_ecmwf_forcing.validate_forecast_metadata(path, "2026-07-14", 0, [0, 3])


def test_normalize_soil_metadata_for_wps_maps_indices_to_physical_depths(
    monkeypatch, tmp_path
):
    path = tmp_path / "surface.grib2"
    path.write_bytes(b"source")
    messages = []
    for short_name in ("sot", "vsw"):
        for level in range(1, 5):
            messages.append(
                {
                    "shortName": short_name,
                    "level": level,
                    "typeOfFirstFixedSurface": 151,
                    "typeOfSecondFixedSurface": 151,
                }
            )
    fake = FakeWritableEccodes(messages)
    monkeypatch.setattr(fetch_ecmwf_forcing, "eccodes", fake)

    fetch_ecmwf_forcing.normalize_soil_metadata_for_wps(path)

    assert len(fake.written) == 8
    for message in fake.written:
        lower_cm, upper_cm = fetch_ecmwf_forcing.SOIL_LAYER_BOUNDS_CM[
            message["level"]
        ]
        assert message["typeOfFirstFixedSurface"] == 106
        assert message["typeOfSecondFixedSurface"] == 106
        assert message["scaleFactorOfFirstFixedSurface"] == 2
        assert message["scaledValueOfFirstFixedSurface"] == lower_cm
        assert message["scaleFactorOfSecondFixedSurface"] == 2
        assert message["scaledValueOfSecondFixedSurface"] == upper_cm


def test_normalize_soil_metadata_for_wps_rejects_incomplete_layers(
    monkeypatch, tmp_path
):
    path = tmp_path / "surface.grib2"
    path.write_bytes(b"source")
    fake = FakeWritableEccodes([{"shortName": "sot", "level": 1}])
    monkeypatch.setattr(fetch_ecmwf_forcing, "eccodes", fake)

    with pytest.raises(RuntimeError, match="missing required ECMWF soil layers"):
        fetch_ecmwf_forcing.normalize_soil_metadata_for_wps(path)


def test_repack_cli_forces_value_reencoding(monkeypatch, tmp_path):
    path = tmp_path / "forcing.grib2"
    path.write_bytes(b"ccsds")
    observed_commands = []

    def fake_run(command, **kwargs):
        observed_commands.append(command)
        Path(command[-1]).write_bytes(b"simple")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    fetch_ecmwf_forcing.repack_grib_file(path)

    assert observed_commands[0][0:4] == [
        "grib_set",
        "-r",
        "-s",
        "packingType=grid_simple",
    ]
    assert path.read_bytes() == b"simple"


def test_validate_decodable_grib_payload_reads_every_message(monkeypatch, tmp_path):
    path = tmp_path / "forcing.grib2"
    path.write_bytes(b"grib")
    fake = FakePayloadEccodes([{"values": [1.0]}, {"values": [2.0, 3.0]}])
    monkeypatch.setattr(fetch_ecmwf_forcing, "eccodes", fake)

    fetch_ecmwf_forcing.validate_decodable_grib_payload(path)

    assert fake.index == 2


def test_validate_decodable_grib_payload_rejects_corruption(monkeypatch, tmp_path):
    path = tmp_path / "forcing.grib2"
    path.write_bytes(b"grib")
    fake = FakePayloadEccodes([{"error": "data section size mismatch"}])
    monkeypatch.setattr(fetch_ecmwf_forcing, "eccodes", fake)

    with pytest.raises(RuntimeError, match="undecodable GRIB payload"):
        fetch_ecmwf_forcing.validate_decodable_grib_payload(path)
