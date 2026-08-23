import json

import forecast_sources


class FakeFetchData:
    OUTPUT_DIR = "/tmp/predsea-test-output"


def test_configured_forecast_sources_default_to_copernicus_only(monkeypatch):
    monkeypatch.delenv("PREDSEA_BYPASS_COPERNICUS", raising=False)
    assert forecast_sources.configured_source_ids() == ["copernicus"]


def test_fetch_available_forecasts_calls_configured_sources_without_scoping_error(monkeypatch, tmp_path):
    monkeypatch.delenv("PREDSEA_BYPASS_COPERNICUS", raising=False)
    result = forecast_sources.fetch_available_forecasts(
        FakeFetchData,
        output_dir=tmp_path,
        dry_run=True,
    )

    assert [source["id"] for source in result] == ["copernicus"]
    assert result[0]["available"] is True


def test_fetch_source_via_subprocess_threads_forecast_run_date(monkeypatch, tmp_path):
    captured = {}

    class Completed:
        stdout = ""
        stderr = ""
        returncode = 0

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs.get("cwd")
        (tmp_path / "forecast_source.json").write_text(
            json.dumps(
                {
                    "id": "copernicus",
                    "label": "Copernicus Marine Mediterranean forecast",
                    "available": True,
                    "forecast_source_status": "live",
                    "forecast_run_date": "2026-06-18",
                    "waves_path": str(tmp_path / "balearic_waves.nc"),
                    "currents_path": str(tmp_path / "balearic_currents.nc"),
                }
            ),
            encoding="utf-8",
        )
        return Completed()

    monkeypatch.setattr(forecast_sources.subprocess, "run", fake_run)

    result = forecast_sources.fetch_source_via_subprocess(
        "copernicus",
        tmp_path,
        timeout_seconds=30,
        dry_run=False,
        forecast_run_date="2026-06-18",
    )

    assert "--forecast-run-date" in captured["command"]
    assert "2026-06-18" in captured["command"]
    assert captured["cwd"] == forecast_sources.Path(forecast_sources.__file__).resolve().parent
    assert result["forecast_run_date"] == "2026-06-18"
    assert result["forecast_source_status"] == "live"
