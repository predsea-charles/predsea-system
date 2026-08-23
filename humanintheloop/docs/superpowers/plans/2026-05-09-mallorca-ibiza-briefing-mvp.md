# Mallorca-Ibiza Briefing MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a command-line MVP that generates a route snapshot plus LinkedIn, WhatsApp, and WhatsApp-screenshot-script briefings for Mallorca to Ibiza.

**Architecture:** Keep the prototype small and file-based. Existing fetchers provide SOCIB observations and Copernicus NetCDF files; a new route analysis module normalizes those into a snapshot; a new renderer turns the snapshot into text artifacts. `briefing.py` orchestrates the flow.

**Tech Stack:** Python 3.13, `unittest`, `requests`, `copernicusmarine`, optional `xarray` for NetCDF analysis when available.

---

## Implementation Status

Status: implemented locally and extended beyond the original briefing-only plan.

Completed:

- `briefing.py` command-line orchestration.
- `socib_public.py` structured SOCIB observation extraction.
- `fetch_data.py` Copernicus subset downloads.
- `route_analysis.py` route snapshot creation.
- `briefing_renderers.py` LinkedIn/WhatsApp text output.
- `decision_engine.py` rule-based captain question answering.
- `chat_figure.py` WhatsApp/Telegram-style PNG generation.
- `test_socib_scripts.py` local unittest coverage.

Important updates after the original plan:

- The forecast decision source no longer uses a broad Balearic box average.
- The route engine samples representative Palma-Ibiza water points and uses the
  exposed-route maximum per hour.
- `daily_snapshot.json` includes hourly route values for requested-time answers.
- `briefing.py --question` can answer captain questions directly.
- `briefing.py --current-time` can force demo timing for LinkedIn examples.
- The screenshot script and PNG now support simulated shared-location cards.

Remaining work from the product roadmap:

- Add a route catalog and configurable route corridor sampling.
- Split data refresh from on-demand question answering.
- Add LLM-backed query/context extraction.
- Add SOCIB WMOP/SAPO where they improve local forecasts.
- Add real WhatsApp/GPS integration later.

## File Structure

- Create `briefing.py`: command-line orchestration; writes all MVP artifacts.
- Create `route_analysis.py`: pure snapshot-building and recommendation logic; safe fallbacks when forecast files or `xarray` are unavailable.
- Create `briefing_renderers.py`: pure text renderers for LinkedIn, private WhatsApp, and screenshot-script outputs.
- Modify `socib_public.py`: expose structured SOCIB observations through a reusable function while preserving CLI printing.
- Modify `test_socib_scripts.py`: add focused unittest coverage for structured observations, snapshot generation, renderers, and `briefing.py` artifact writing.

## Task 1: Structured SOCIB Observations

**Files:**
- Modify: `socib_public.py`
- Modify: `test_socib_scripts.py`

- [ ] **Step 1: Write failing test for structured public observations**

Add this test to `test_socib_scripts.py`:

```python
class SocibPublicStructuredTests(unittest.TestCase):
    def test_extract_public_observations_returns_route_ready_values(self):
        import socib_public

        payload = [
            {
                "id": 146,
                "name": "Buoy Canal de Ibiza",
                "lastTimeSampleReceived": 1778308200,
                "jsonInstrumentList": [
                    {
                        "jsonVariableList": [
                            {"standardName": "sea_surface_wave_significant_height", "lastSampleValue": "0.75 m", "lastValue": 0.75},
                            {"standardName": "sea_water_temperature", "lastSampleValue": "18.88 C", "lastValue": 18.88},
                        ]
                    }
                ],
            }
        ]

        observations = socib_public.extract_public_observations(payload)

        canal = observations["canal_de_ibiza"]
        self.assertEqual(canal["name"], "Buoy Canal de Ibiza")
        self.assertEqual(canal["wave_height_m"], 0.75)
        self.assertEqual(canal["water_temp_c"], 18.88)
        self.assertEqual(canal["last_sample_utc"], "2026-05-09 06:30 UTC")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
./.venv/bin/python -m unittest test_socib_scripts.SocibPublicStructuredTests
```

Expected: FAIL with `AttributeError: module 'socib_public' has no attribute 'extract_public_observations'`.

- [ ] **Step 3: Implement structured extraction**

Add to `socib_public.py`:

```python
OBSERVATION_KEYS = {
    146: "canal_de_ibiza",
    14: "pollensa",
}

NUMERIC_VARIABLES = {
    "sea_surface_wave_significant_height": "wave_height_m",
    "sea_water_temperature": "water_temp_c",
    "sea_water_practical_salinity": "salinity_psu",
    "air_pressure": "air_pressure_hpa",
    "air_pressure_at_sea_level": "sea_level_pressure_hpa",
}


def extract_public_observations(platforms):
    observations = {}
    for platform in platforms:
        platform_id = platform.get("id")
        key = OBSERVATION_KEYS.get(platform_id)
        if not key:
            continue

        record = {
            "name": platform.get("name", "N/A"),
            "last_sample_utc": format_timestamp(platform.get("lastTimeSampleReceived")),
        }
        for instrument in platform.get("jsonInstrumentList", []):
            for variable in instrument.get("jsonVariableList", []):
                output_key = NUMERIC_VARIABLES.get(variable.get("standardName"))
                if output_key:
                    record[output_key] = variable.get("lastValue")
        observations[key] = record
    return observations
```

Update `get_public_data()` to call `extract_public_observations(response.json())` before printing.

- [ ] **Step 4: Run tests**

Run:

```bash
./.venv/bin/python -m unittest test_socib_scripts.py
```

Expected: all tests pass.

## Task 2: Snapshot Logic

**Files:**
- Create: `route_analysis.py`
- Modify: `test_socib_scripts.py`

- [ ] **Step 1: Write failing snapshot test**

Add this test:

```python
class RouteAnalysisTests(unittest.TestCase):
    def test_build_snapshot_recommends_early_window_when_waves_build(self):
        import route_analysis

        observations = {
            "canal_de_ibiza": {
                "name": "Buoy Canal de Ibiza",
                "last_sample_utc": "2026-05-09 06:30 UTC",
                "wave_height_m": 0.75,
                "water_temp_c": 18.88,
            }
        }
        forecast = {
            "wave_min_m": 0.7,
            "wave_max_m": 1.6,
            "wave_peak_time": "15:00",
            "current_max_kn": 1.3,
            "current_peak_time": "16:00",
        }

        snapshot = route_analysis.build_route_snapshot(observations, forecast)

        self.assertEqual(snapshot["route"], "Mallorca -> Ibiza")
        self.assertEqual(snapshot["recommendation"]["best_window"], "before midday")
        self.assertEqual(snapshot["recommendation"]["confidence"], "medium")
        self.assertIn("waves build", snapshot["recommendation"]["watch_out"])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
./.venv/bin/python -m unittest test_socib_scripts.RouteAnalysisTests
```

Expected: FAIL with `ModuleNotFoundError: No module named 'route_analysis'`.

- [ ] **Step 3: Implement `route_analysis.py`**

Create `route_analysis.py`:

```python
from datetime import datetime, timezone


ROUTE_NAME = "Mallorca -> Ibiza"


def build_route_snapshot(observations, forecast=None):
    forecast = forecast or {}
    canal = observations.get("canal_de_ibiza", {})
    wave_now = canal.get("wave_height_m")
    wave_max = forecast.get("wave_max_m")
    wave_min = forecast.get("wave_min_m")
    wave_peak_time = forecast.get("wave_peak_time", "later today")
    current_max = forecast.get("current_max_kn")
    current_peak_time = forecast.get("current_peak_time", "later today")

    recommendation = recommend_window(wave_now, wave_min, wave_max, wave_peak_time, current_max, current_peak_time)

    return {
        "route": ROUTE_NAME,
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "observations": observations,
        "forecast": forecast,
        "recommendation": recommendation,
    }


def recommend_window(wave_now, wave_min, wave_max, wave_peak_time, current_max, current_peak_time):
    if wave_max is None:
        return {
            "best_window": "check manually",
            "watch_out": "forecast layer unavailable",
            "confidence": "low",
        }

    wave_build = wave_now is not None and wave_max - wave_now >= 0.5
    strong_current = current_max is not None and current_max >= 1.0

    if wave_build:
        best_window = "before midday"
        watch_out = f"waves build toward {wave_max:.1f} m around {wave_peak_time}"
    elif wave_max <= 1.0:
        best_window = "most daylight windows look manageable"
        watch_out = "no major wave build-up in the 24h forecast"
    else:
        best_window = "morning to early afternoon"
        watch_out = f"forecast peak near {wave_max:.1f} m around {wave_peak_time}"

    if strong_current:
        watch_out = f"{watch_out}; current may reach {current_max:.1f} kn around {current_peak_time}"

    confidence = "medium" if wave_now is not None else "low"
    return {
        "best_window": best_window,
        "watch_out": watch_out,
        "confidence": confidence,
    }
```

- [ ] **Step 4: Run tests**

Run:

```bash
./.venv/bin/python -m unittest test_socib_scripts.py
```

Expected: all tests pass.

## Task 3: Text Renderers

**Files:**
- Create: `briefing_renderers.py`
- Modify: `test_socib_scripts.py`

- [ ] **Step 1: Write failing renderer test**

Add this test:

```python
class BriefingRendererTests(unittest.TestCase):
    def test_renderers_include_route_advice_and_confidence(self):
        import briefing_renderers

        snapshot = {
            "route": "Mallorca -> Ibiza",
            "created_at_utc": "2026-05-09 07:30 UTC",
            "observations": {
                "canal_de_ibiza": {
                    "name": "Buoy Canal de Ibiza",
                    "last_sample_utc": "2026-05-09 06:30 UTC",
                    "wave_height_m": 0.75,
                    "water_temp_c": 18.88,
                }
            },
            "forecast": {"wave_max_m": 1.6, "wave_peak_time": "15:00", "current_max_kn": 1.3},
            "recommendation": {
                "best_window": "before midday",
                "watch_out": "waves build toward 1.6 m around 15:00",
                "confidence": "medium",
            },
        }

        linkedin = briefing_renderers.render_linkedin(snapshot)
        whatsapp = briefing_renderers.render_whatsapp(snapshot)
        screenshot = briefing_renderers.render_whatsapp_screenshot_script(snapshot)

        self.assertIn("Mallorca -> Ibiza", linkedin)
        self.assertIn("before midday", whatsapp)
        self.assertIn("Confidence: medium", screenshot)
        self.assertIn("Captain:", screenshot)
        self.assertIn("PredSea:", screenshot)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
./.venv/bin/python -m unittest test_socib_scripts.BriefingRendererTests
```

Expected: FAIL with `ModuleNotFoundError: No module named 'briefing_renderers'`.

- [ ] **Step 3: Implement `briefing_renderers.py`**

Create `briefing_renderers.py`:

```python
def _canal(snapshot):
    return snapshot.get("observations", {}).get("canal_de_ibiza", {})


def _recommendation(snapshot):
    return snapshot.get("recommendation", {})


def _forecast(snapshot):
    return snapshot.get("forecast", {})


def render_linkedin(snapshot):
    canal = _canal(snapshot)
    rec = _recommendation(snapshot)
    forecast = _forecast(snapshot)
    return "\n".join([
        f"PredSea Balearic Briefing | {snapshot['route']}",
        "",
        f"Now: {canal.get('name', 'SOCIB buoy')} reports {canal.get('wave_height_m', 'N/A')} m significant wave height and {canal.get('water_temp_c', 'N/A')} C water.",
        f"Next 24h: forecast wave peak near {forecast.get('wave_max_m', 'N/A')} m around {forecast.get('wave_peak_time', 'N/A')}.",
        f"Captain's read: best crossing window is {rec.get('best_window', 'check manually')}.",
        f"Watch-out: {rec.get('watch_out', 'conditions require manual review')}.",
        f"Confidence: {rec.get('confidence', 'low')}.",
        "",
        "Illustrative route intelligence example, based on public marine data.",
    ])


def render_whatsapp(snapshot):
    canal = _canal(snapshot)
    rec = _recommendation(snapshot)
    forecast = _forecast(snapshot)
    return "\n".join([
        "PredSea Captain's Briefing",
        f"Route: {snapshot['route']}",
        f"Now: {canal.get('wave_height_m', 'N/A')} m waves, water {canal.get('water_temp_c', 'N/A')} C.",
        f"Next 24h: peak near {forecast.get('wave_max_m', 'N/A')} m around {forecast.get('wave_peak_time', 'N/A')}.",
        f"Best window: {rec.get('best_window', 'check manually')}.",
        f"Watch-out: {rec.get('watch_out', 'conditions require manual review')}.",
        f"Confidence: {rec.get('confidence', 'low')}.",
    ])


def render_whatsapp_screenshot_script(snapshot):
    rec = _recommendation(snapshot)
    return "\n".join([
        "Illustrative WhatsApp screenshot script",
        "Captain: How is the sea looking for Palma to Ibiza today?",
        f"PredSea: For {snapshot['route']}, the best window looks {rec.get('best_window', 'check manually')}.",
        f"PredSea: Watch-out: {rec.get('watch_out', 'conditions require manual review')}.",
        f"PredSea: Confidence: {rec.get('confidence', 'low')}.",
        "Caption note: illustrative product example based on public marine data.",
    ])
```

- [ ] **Step 4: Run tests**

Run:

```bash
./.venv/bin/python -m unittest test_socib_scripts.py
```

Expected: all tests pass.

## Task 4: Command-Line Orchestrator

**Files:**
- Create: `briefing.py`
- Modify: `test_socib_scripts.py`

- [ ] **Step 1: Write failing artifact test**

Add this test:

```python
class BriefingCliTests(unittest.TestCase):
    def test_write_outputs_creates_snapshot_and_text_artifacts(self):
        import json
        import tempfile
        from pathlib import Path
        import briefing

        snapshot = {
            "route": "Mallorca -> Ibiza",
            "created_at_utc": "2026-05-09 07:30 UTC",
            "observations": {"canal_de_ibiza": {"wave_height_m": 0.75, "water_temp_c": 18.88}},
            "forecast": {"wave_max_m": 1.6, "wave_peak_time": "15:00"},
            "recommendation": {"best_window": "before midday", "watch_out": "waves build", "confidence": "medium"},
        }

        with tempfile.TemporaryDirectory() as tmp:
            briefing.write_outputs(snapshot, output_dir=tmp)
            root = Path(tmp)

            self.assertEqual(json.loads((root / "daily_snapshot.json").read_text())["route"], "Mallorca -> Ibiza")
            self.assertIn("PredSea", (root / "briefing_linkedin.txt").read_text())
            self.assertIn("Best window", (root / "briefing_whatsapp.txt").read_text())
            self.assertIn("Captain:", (root / "briefing_whatsapp_screenshot_script.txt").read_text())
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
./.venv/bin/python -m unittest test_socib_scripts.BriefingCliTests
```

Expected: FAIL with `ModuleNotFoundError: No module named 'briefing'`.

- [ ] **Step 3: Implement `briefing.py`**

Create `briefing.py`:

```python
import json
from pathlib import Path

import briefing_renderers
import route_analysis
import socib_public
import fetch_data


OUTPUT_DIR = Path("mvp_data")


def load_observations():
    response = socib_public.requests.get(socib_public.PUBLIC_URL, timeout=30)
    response.raise_for_status()
    return socib_public.extract_public_observations(response.json())


def build_forecast_summary():
    fetch_data.get_balearic_forecast(dry_run=False)
    return {
        "wave_min_m": None,
        "wave_max_m": None,
        "wave_peak_time": "N/A",
        "current_max_kn": None,
        "current_peak_time": "N/A",
    }


def write_outputs(snapshot, output_dir=OUTPUT_DIR):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / "daily_snapshot.json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    (output_path / "briefing_linkedin.txt").write_text(briefing_renderers.render_linkedin(snapshot), encoding="utf-8")
    (output_path / "briefing_whatsapp.txt").write_text(briefing_renderers.render_whatsapp(snapshot), encoding="utf-8")
    (output_path / "briefing_whatsapp_screenshot_script.txt").write_text(briefing_renderers.render_whatsapp_screenshot_script(snapshot), encoding="utf-8")


def main():
    observations = load_observations()
    forecast = build_forecast_summary()
    snapshot = route_analysis.build_route_snapshot(observations, forecast)
    write_outputs(snapshot)
    print("Wrote PredSea briefing artifacts to mvp_data/")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

Run:

```bash
./.venv/bin/python -m unittest test_socib_scripts.py
```

Expected: all tests pass.

## Task 5: Forecast Extraction With Safe Fallback

**Files:**
- Modify: `route_analysis.py`
- Modify: `briefing.py`
- Modify: `test_socib_scripts.py`

- [ ] **Step 1: Write failing test for fallback forecast summary**

Add this test:

```python
class ForecastFallbackTests(unittest.TestCase):
    def test_forecast_summary_fallback_keeps_briefing_available(self):
        import route_analysis

        summary = route_analysis.default_forecast_summary()

        self.assertEqual(summary["wave_peak_time"], "N/A")
        self.assertIsNone(summary["wave_max_m"])
        self.assertIsNone(summary["current_max_kn"])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
./.venv/bin/python -m unittest test_socib_scripts.ForecastFallbackTests
```

Expected: FAIL with `AttributeError: module 'route_analysis' has no attribute 'default_forecast_summary'`.

- [ ] **Step 3: Implement fallback helper and use it**

Add to `route_analysis.py`:

```python
def default_forecast_summary():
    return {
        "wave_min_m": None,
        "wave_max_m": None,
        "wave_peak_time": "N/A",
        "current_max_kn": None,
        "current_peak_time": "N/A",
    }
```

Update `briefing.py`:

```python
def build_forecast_summary():
    fetch_data.get_balearic_forecast(dry_run=False)
    return route_analysis.default_forecast_summary()
```

- [ ] **Step 4: Run tests and CLI**

Run:

```bash
./.venv/bin/python -m unittest test_socib_scripts.py
./.venv/bin/python briefing.py
```

Expected: tests pass, and CLI writes the four artifacts into `mvp_data/`.

## Task 6: Final Verification

**Files:**
- Verify only.

- [ ] **Step 1: Run full unit tests**

Run:

```bash
./.venv/bin/python -m unittest test_socib_scripts.py
```

Expected: all tests pass.

- [ ] **Step 2: Run end-to-end briefing generation**

Run:

```bash
./.venv/bin/python briefing.py
```

Expected: command exits 0 and writes:

```text
mvp_data/daily_snapshot.json
mvp_data/briefing_linkedin.txt
mvp_data/briefing_whatsapp.txt
mvp_data/briefing_whatsapp_screenshot_script.txt
```

- [ ] **Step 3: Inspect artifact contents**

Run:

```bash
sed -n '1,160p' mvp_data/briefing_linkedin.txt
sed -n '1,160p' mvp_data/briefing_whatsapp.txt
sed -n '1,160p' mvp_data/briefing_whatsapp_screenshot_script.txt
```

Expected: each artifact mentions Mallorca-Ibiza, current conditions, advice, and confidence.

- [ ] **Step 4: Commit implementation**

Run:

```bash
git add humanintheloop/briefing.py humanintheloop/route_analysis.py humanintheloop/briefing_renderers.py humanintheloop/socib_public.py humanintheloop/test_socib_scripts.py humanintheloop/docs/superpowers/plans/2026-05-09-mallorca-ibiza-briefing-mvp.md
git commit -m "Build Mallorca-Ibiza briefing MVP"
```
