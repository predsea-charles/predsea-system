import pytest

import socib_thredds


def test_with_retries_recovers_from_transient_oserror(monkeypatch):
    calls = []
    monkeypatch.setattr(socib_thredds.time, "sleep", lambda seconds: None)

    def operation():
        calls.append("call")
        if len(calls) == 1:
            raise OSError("temporary NetCDF I/O failure")
        return "ok"

    assert socib_thredds.with_retries("SOCIB SAPO-IB waves", operation, attempts=2, delay_seconds=0) == "ok"
    assert len(calls) == 2


def test_with_retries_raises_last_error_after_attempts(monkeypatch):
    monkeypatch.setattr(socib_thredds.time, "sleep", lambda seconds: None)

    with pytest.raises(OSError, match="still down"):
        socib_thredds.with_retries(
            "SOCIB SAPO-IB waves",
            lambda: (_ for _ in ()).throw(OSError("still down")),
            attempts=2,
            delay_seconds=0,
        )


def test_utc_naive_timestamp_converts_timezone_aware_values():
    import pandas as pd

    value = socib_thredds._utc_naive_timestamp(pd.Timestamp("2026-06-18T06:00:00+02:00"))

    assert str(value.tzinfo) == "None"
    assert value.isoformat() == "2026-06-18T04:00:00"
