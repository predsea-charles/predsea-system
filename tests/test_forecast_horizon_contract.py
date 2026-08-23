from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_vm_startup_uses_forecast_metadata_for_model_end_date():
    startup = (ROOT / "scripts" / "vm_startup.sh").read_text()

    assert "attributes/forecast-hours" in startup
    assert '-e END_DATE="${END_DATE}"' in startup
    assert 'END_DATE="$(date -d "${RUN_DATE} + 1 day"' not in startup


def test_vm_success_requires_complete_hourly_d02_coverage():
    startup = (ROOT / "scripts" / "vm_startup.sh").read_text()

    assert "EXPECTED_WRF_TIMESTAMPS=$((FORECAST_HOURS + 1))" in startup
    assert 'WRF_DOMAIN="d02"' in startup
    assert 'exit 99' in startup
