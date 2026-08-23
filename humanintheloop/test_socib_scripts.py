import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timezone


class FetchDataTests(unittest.TestCase):
    @patch("fetch_data.copernicusmarine.get")
    @patch("fetch_data.copernicusmarine.subset")
    def test_balearic_forecast_uses_subset_for_bounded_downloads(self, subset, get):
        import fetch_data

        fetch_data.get_balearic_forecast(dry_run=True)

        self.assertEqual(fetch_data.PHY_ID, "cmems_mod_med_phy-cur_anfc_4.2km-2D_PT1H-m")
        self.assertEqual(fetch_data.WAV_ID, "cmems_mod_med_wav_anfc_4.2km_PT1H-i")
        self.assertEqual(subset.call_count, 2)
        get.assert_not_called()
        current_call = subset.call_args_list[0].kwargs
        wave_call = subset.call_args_list[1].kwargs

        self.assertEqual(current_call["dataset_id"], fetch_data.PHY_ID)
        self.assertEqual(current_call["variables"], ["uo", "vo"])
        self.assertEqual(current_call["output_filename"], "balearic_currents.nc")
        self.assertTrue(current_call["dry_run"])

        self.assertEqual(wave_call["dataset_id"], fetch_data.WAV_ID)
        self.assertEqual(
            wave_call["variables"],
            [
                "VHM0",
                "VMDR",
                "VHM0_SW1",
                "VMDR_SW1",
                "VHM0_SW2",
                "VMDR_SW2",
                "VHM0_WW",
                "VMDR_WW",
            ],
        )
        self.assertEqual(wave_call["output_filename"], "balearic_waves.nc")
        self.assertTrue(wave_call["dry_run"])

    @patch("fetch_data.copernicusmarine.subset")
    def test_balearic_forecast_retries_core_waves_if_partitions_unavailable(self, subset):
        import fetch_data

        subset.side_effect = [None, RuntimeError("variable not found"), None]

        fetch_data.get_balearic_forecast(dry_run=False)

        self.assertEqual(subset.call_count, 3)
        retry_call = subset.call_args_list[2].kwargs
        self.assertEqual(retry_call["dataset_id"], fetch_data.WAV_ID)
        self.assertEqual(retry_call["variables"], fetch_data.CORE_WAVE_VARIABLES)
        self.assertEqual(retry_call["output_filename"], "balearic_waves.nc")

    @patch("fetch_data.time.sleep")
    @patch("fetch_data.copernicusmarine.subset")
    def test_balearic_forecast_retries_transient_copernicus_auth_failure(self, subset, sleep):
        import fetch_data

        subset.side_effect = [RuntimeError("CouldNotConnectToAuthenticationSystem"), None, None]

        fetch_data.get_balearic_forecast(dry_run=False)

        self.assertEqual(subset.call_count, 3)
        sleep.assert_called()
        current_call = subset.call_args_list[1].kwargs
        self.assertEqual(current_call["dataset_id"], fetch_data.PHY_ID)
        self.assertEqual(current_call["variables"], ["uo", "vo"])

    @patch("fetch_data.copernicusmarine.subset")
    @patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}, clear=True)
    def test_balearic_forecast_fails_fast_in_ci_without_copernicus_credentials(self, subset):
        import fetch_data

        with self.assertRaisesRegex(RuntimeError, "COPERNICUSMARINE_SERVICE_USERNAME"):
            fetch_data.get_balearic_forecast(dry_run=False)

        subset.assert_not_called()


class MapGeneratorTests(unittest.TestCase):
    def test_map_metadata_prioritizes_oceanographic_layers(self):
        import map_generator

        metadata = map_generator.map_metadata()

        self.assertEqual(metadata["title"], "OCEANOGRAPHIC CONDITIONS MAP")
        self.assertIn("wave_height", metadata["primary_layers"])
        self.assertIn("current_vectors", metadata["primary_layers"])
        self.assertNotIn("route_reference", metadata["primary_layers"])
        self.assertEqual(metadata["route_role"], "none")
        self.assertEqual(metadata["extent"], "dynamic_route_corridor")

    def test_route_decision_map_writes_png_from_forecast_files(self):
        import numpy as np
        import xarray as xr
        from PIL import Image

        import map_generator

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            times = np.array(["2026-05-14T06:00:00", "2026-05-14T07:00:00"], dtype="datetime64[ns]")
            latitudes = [38.8, 39.2, 39.6]
            longitudes = [1.6, 2.1, 2.6]
            waves = xr.Dataset(
                {
                    "VHM0": (
                        ("time", "latitude", "longitude"),
                        np.array(
                            [
                                [[0.8, 0.9, 1.0], [1.1, 1.3, 1.2], [0.7, 0.8, 0.9]],
                                [[0.9, 1.0, 1.1], [1.2, 1.6, 1.4], [0.8, 0.9, 1.0]],
                            ]
                        ),
                    ),
                    "VMDR": (
                        ("time", "latitude", "longitude"),
                        np.full((2, 3, 3), 300.0),
                    ),
                },
                coords={"time": times, "latitude": latitudes, "longitude": longitudes},
            )
            currents = xr.Dataset(
                {
                    "uo": (("time", "latitude", "longitude"), np.full((2, 3, 3), 0.2)),
                    "vo": (("time", "latitude", "longitude"), np.full((2, 3, 3), 0.1)),
                },
                coords={"time": times, "latitude": latitudes, "longitude": longitudes},
            )
            waves_path = root / "waves.nc"
            currents_path = root / "currents.nc"
            waves.to_netcdf(waves_path)
            currents.to_netcdf(currents_path)

            route = {
                "id": "ibiza_palma",
                "name": "Palma -> Ibiza",
                "origin": {"name": "Palma", "longitude": 2.65, "latitude": 39.57},
                "destination": {"name": "Ibiza", "longitude": 1.43, "latitude": 38.91},
                "sample_points": [
                    {"name": "Palma Bay offshore", "longitude": 2.55, "latitude": 39.45},
                    {"name": "Mid Palma-Ibiza", "longitude": 2.10, "latitude": 39.20},
                    {"name": "Ibiza Channel", "longitude": 1.70, "latitude": 38.90},
                ],
            }
            snapshot = {
                "route": "Palma -> Ibiza",
                "route_id": "ibiza_palma",
                "vessel_profile": {"label": "15-24m"},
                "forecast": {
                    "wave_min_m": 0.8,
                    "wave_max_m": 1.6,
                    "wave_peak_time": "07:00",
                    "current_max_kn": 0.4,
                    "current_peak_time": "07:00",
                },
                "recommendation": {
                    "vessel_severity": "caution",
                    "vessel_advice": "caution for vessels 15-24m",
                    "confidence": "medium",
                },
            }

            called = {"route": False}
            original_render_matplotlib_map = map_generator.render_matplotlib_map

            def wrapped_render_matplotlib_map(*args, **kwargs):
                called["route"] = True
                return original_render_matplotlib_map(*args, **kwargs)

            map_generator.render_matplotlib_map = wrapped_render_matplotlib_map

            output = root / "route_decision_map.png"
            try:
                result = map_generator.generate_route_decision_map(
                    waves_path,
                    currents_path,
                    route,
                    snapshot,
                    output,
                )
            finally:
                map_generator.render_matplotlib_map = original_render_matplotlib_map

            self.assertEqual(result, output)
            self.assertTrue(output.exists())
            self.assertTrue(called["route"])
            with Image.open(output) as image:
                self.assertEqual(image.size, (1440, 1800))


class SocibFetcherTests(unittest.TestCase):
    def test_build_headers_uses_socib_api_key_header_without_json_accept(self):
        import socib_fetcher

        headers = socib_fetcher.build_headers("abc123")

        self.assertEqual(headers["apikey"], "abc123")
        self.assertNotIn("Authorization", headers)
        self.assertNotEqual(headers.get("Accept"), "application/json")


class SocibPublicTests(unittest.TestCase):
    def test_public_urls_use_data_discovery_not_broken_data_catalog_latest_api(self):
        import socib_public

        urls = [socib_public.PUBLIC_URL]

        self.assertTrue(all("DataDiscovery" in url for url in urls))
        self.assertTrue(all("data-catalog/api/instruments" not in url for url in urls))

    def test_fetch_public_platforms_retries_transient_timeout(self):
        from unittest.mock import Mock
        import requests
        import socib_public

        session = Mock()
        first = requests.exceptions.Timeout("SOCIB slow")
        second = Mock(status_code=200)
        second.json.return_value = [{"id": 146}]
        session.get.side_effect = [first, second]

        payload = socib_public.fetch_public_platforms(
            session=session,
            timeout=60,
            max_retries=2,
            sleep=lambda seconds: None,
        )

        self.assertEqual(payload, [{"id": 146}])
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(session.get.call_args.kwargs["timeout"], 60)

    def test_fetch_public_observations_returns_empty_when_socib_stays_unavailable(self):
        from unittest.mock import Mock
        import requests
        import socib_public

        session = Mock()
        session.get.side_effect = requests.exceptions.Timeout("SOCIB unavailable")

        observations = socib_public.fetch_public_observations(
            session=session,
            max_retries=2,
            sleep=lambda seconds: None,
        )

        self.assertEqual(observations, {})


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
                            {
                                "standardName": "sea_surface_wave_significant_height",
                                "lastSampleValue": "0.75 m",
                                "lastValue": 0.75,
                            },
                            {
                                "standardName": "sea_water_temperature",
                                "lastSampleValue": "18.88 C",
                                "lastValue": 18.88,
                            },
                        ]
                    }
                ],
            }
        ]

        observations = socib_public.extract_public_observations(
            payload,
            now=datetime(2026, 5, 9, 7, 0, tzinfo=timezone.utc),
        )

        canal = observations["canal_de_ibiza"]
        self.assertEqual(canal["name"], "Buoy Canal de Ibiza")
        self.assertEqual(canal["wave_height_m"], 0.75)
        self.assertEqual(canal["water_temp_c"], 18.88)
        self.assertEqual(canal["last_sample_utc"], "2026-05-09 06:30 UTC")

    def test_extract_public_observations_includes_bahia_de_palma_wave_buoy(self):
        import socib_public

        payload = [
            {
                "id": 143,
                "name": "Buoy Bahia de Palma",
                "lastTimeSampleReceived": 1778308200,
                "jsonInstrumentList": [
                    {
                        "jsonVariableList": [
                            {
                                "standardName": "sea_surface_wave_significant_height",
                                "lastSampleValue": "0.38 m",
                                "lastValue": 0.38,
                            }
                        ]
                    }
                ],
            }
        ]

        observations = socib_public.extract_public_observations(
            payload,
            now=datetime(2026, 5, 9, 7, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(observations["bahia_de_palma"]["wave_height_m"], 0.38)

    def test_extract_public_observations_includes_wave_direction_when_numeric(self):
        import socib_public

        payload = [
            {
                "id": 146,
                "name": "Buoy Canal de Ibiza",
                "lastTimeSampleReceived": 1778308200,
                "jsonInstrumentList": [
                    {
                        "jsonVariableList": [
                            {
                                "standardName": "sea_surface_wave_from_direction",
                                "lastSampleValue": "64.7 degree",
                                "lastValue": 64.7,
                            }
                        ]
                    }
                ],
            }
        ]

        observations = socib_public.extract_public_observations(
            payload,
            now=datetime(2026, 5, 9, 7, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(observations["canal_de_ibiza"]["wave_from_direction_deg"], 64.7)

    def test_extract_public_observations_excludes_stale_platforms(self):
        import socib_public

        payload = [
            {
                "id": 512,
                "name": "Buoy Porto Colom",
                "lastTimeSampleReceived": 1775041200,
                "jsonInstrumentList": [
                    {
                        "jsonVariableList": [
                            {
                                "standardName": "sea_surface_wave_significant_height",
                                "lastSampleValue": "0.40 m",
                                "lastValue": 0.40,
                            }
                        ]
                    }
                ],
            }
        ]

        observations = socib_public.extract_public_observations(
            payload,
            now=datetime(2026, 5, 9, 7, 0, tzinfo=timezone.utc),
        )

        self.assertNotIn("porto_colom", observations)

    def test_station_key_from_names_recognizes_western_mediterranean_sites(self):
        import socib_api

        self.assertEqual(socib_api.station_key_from_names(platform={"name": "Barcelona"}), "barcelona")
        self.assertEqual(socib_api.station_key_from_names(platform={"name": "Valencia buoy"}), "valencia")
        self.assertEqual(socib_api.station_key_from_names(platform={"name": "Port de Sóller"}), "soller")


class RouteAnalysisTests(unittest.TestCase):
    def test_load_routes_includes_initial_platform_routes(self):
        import route_analysis

        routes = route_analysis.load_routes()

        expected_subset = [
            "addaia_fornells",
            "addaia_mahon",
            "alcudia_ciutadella",
            "alcudia_fornells",
            "alcudia_palma",
            "andratx_ibiza",
            "andratx_san_antonio",
            "barcelona_cagliari",
            "barcelona_genoa",
            "barcelona_marseille",
            "barcelona_palamos",
            "barcelona_tarragona",
            "cabrera_ibiza",
            "cagliari_naples",
            "ciutadella_fornells",
            "formentera_palma",
            "fornells_mahon",
            "cagliari_genoa",
            "genoa_marseille",
            "genoa_toulon",
            "cagliari_ibiza",
            "formentera_ibiza",
            "ibiza_mahon",
            "ibiza_san_antonio",
            "ibiza_soller",
            "cagliari_marseille",
            "marseille_palma",
            "marseille_toulon",
            "barcelona_montpellier",
            "genoa_montpellier",
            "marseille_montpellier",
            "montpellier_palma",
            "marseille_naples",
            "naples_palermo",
            "alcudia_palma",
            "barcelona_palma",
            "cabrera_palma",
            "cagliari_palma",
            "ciutadella_palma",
            "ibiza_palma",
            "mahon_palma",
            "palma_san_antonio",
            "palma_soller",
            "palma_tarragona",
            "palma_valencia",
            "palma_san_antonio",
            "palma_soller",
            "palma_tarragona",
            "tarragona_valencia",
            "cagliari_toulon",
            "palma_toulon",
        ]
        for route_id in expected_subset:
            self.assertIn(route_id, routes)

        self.assertEqual(routes["ibiza_palma"]["name"], "Palma -> Ibiza")
        self.assertEqual(routes["alcudia_ciutadella"]["destination"]["name"], "Ciutadella")
        self.assertGreaterEqual(len(routes["alcudia_ciutadella"]["sample_points"]), 3)
        self.assertEqual(routes["cabrera_palma"]["validation"]["truth_source"], "bahia_de_palma")
        self.assertIsNone(routes["alcudia_ciutadella"]["validation"]["truth_source"])
        self.assertEqual(routes["barcelona_palma"]["destination"]["name"], "Barcelona")
        self.assertEqual(routes["palma_valencia"]["destination"]["name"], "Valencia")
        self.assertEqual(routes["ciutadella_palma"]["destination"]["name"], "Ciutadella")
        self.assertEqual(routes["mahon_palma"]["destination"]["name"], "Mahon")
        self.assertEqual(routes["ibiza_mahon"]["destination"]["name"], "Mahon")
        self.assertEqual(routes["andratx_ibiza"]["id"], "andratx_ibiza")
        self.assertEqual(routes["ciutadella_fornells"]["destination"]["name"], "Cala Fornells")

    def test_load_route_rejects_unknown_route_id(self):
        import route_analysis

        with self.assertRaises(ValueError):
            route_analysis.load_route("mallorca_mars")

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

        route = route_analysis.load_route("ibiza_palma")
        snapshot = route_analysis.build_route_snapshot(observations, forecast, route=route, vessel_class="medium")

        self.assertEqual(snapshot["route"], "Palma -> Ibiza")
        self.assertEqual(snapshot["route_id"], "ibiza_palma")
        self.assertEqual(snapshot["vessel_class"], "medium")
        self.assertEqual(snapshot["recommendation"]["best_window"], "before midday")
        self.assertEqual(snapshot["recommendation"]["confidence"], "medium")
        self.assertIn("waves build", snapshot["recommendation"]["watch_out"])

    def test_vessel_class_changes_recommendation_severity(self):
        import route_analysis

        route = route_analysis.load_route("alcudia_ciutadella")
        forecast = {
            "wave_min_m": 1.1,
            "wave_max_m": 1.9,
            "wave_peak_time": "15:00",
            "current_max_kn": 0.8,
            "current_peak_time": "16:00",
        }

        small = route_analysis.build_route_snapshot({}, forecast, route=route, vessel_class="small")
        large = route_analysis.build_route_snapshot({}, forecast, route=route, vessel_class="large")

        self.assertEqual(small["recommendation"]["vessel_severity"], "restricted")
        self.assertEqual(large["recommendation"]["vessel_severity"], "manageable")
        self.assertIn("under 15m", small["recommendation"]["vessel_advice"])
        self.assertIn("larger vessels", large["recommendation"]["vessel_advice"])


class BriefingRendererTests(unittest.TestCase):
    def test_renderers_include_route_advice_and_confidence(self):
        import briefing_renderers

        snapshot = {
            "route": "Mallorca -> Ibiza",
            "created_at_utc": "2026-05-09 07:30 UTC",
            "source_summary": {
                "primary_source": "Copernicus",
                "sources": ["Copernicus", "ECMWF", "Puertos del Estado"],
                "count": 3,
                "families": ["ocean_forecast", "atmosphere", "observation"],
                "text": "Sources used: Copernicus, ECMWF, Puertos del Estado",
            },
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
        self.assertIn("Confidence: Medium", screenshot)
        self.assertIn("Sources used: Copernicus, ECMWF, Puertos del Estado", linkedin)
        self.assertIn("Sources used: Copernicus, ECMWF, Puertos del Estado", whatsapp)
        self.assertIn("Sources used: Copernicus, ECMWF, Puertos del Estado", screenshot)
        self.assertIn("Captain:", screenshot)
        self.assertIn("PredSea:", screenshot)
        self.assertIn("Captain: [Shared live location]", screenshot)
        self.assertIn("Captain: Mallorca -> Ibiza today. Best time to leave?", screenshot)
        self.assertIn("PredSea: Go earlier.", screenshot)
        self.assertIn("peaks near 1.6 m", screenshot)
        self.assertNotRegex(screenshot, r"\b\d{1,2}:\d{2}\b")


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
            "recommendation": {
                "best_window": "before midday",
                "watch_out": "waves build",
                "confidence": "medium",
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            briefing.write_outputs(snapshot, output_dir=tmp)
            root = Path(tmp)

            self.assertEqual(json.loads((root / "daily_snapshot.json").read_text())["route"], "Mallorca -> Ibiza")
            self.assertEqual(
                json.loads((root / "daily_briefing.json").read_text())["summary_type"],
                "daily_marine_briefing",
            )

    def test_route_output_dir_uses_route_id(self):
        import tempfile
        from pathlib import Path
        import briefing

        route = {"id": "alcudia_ciutadella", "name": "Alcudia -> Ciutadella"}

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = briefing.route_output_dir(tmp, route)

            self.assertEqual(output_dir, Path(tmp) / "routes" / "alcudia_ciutadella")

    def test_write_outputs_with_question_creates_decision_answer(self):
        import tempfile
        from pathlib import Path
        import briefing

        snapshot = {
            "route": "Mallorca -> Ibiza",
            "created_at_utc": "2026-05-09 07:30 UTC",
            "observations": {"canal_de_ibiza": {"wave_height_m": 0.75, "water_temp_c": 18.88}},
            "forecast": {"wave_max_m": 1.6, "wave_peak_time": "15:00"},
            "recommendation": {
                "best_window": "before midday",
                "watch_out": "waves build",
                "confidence": "medium",
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            briefing.write_outputs(
                snapshot,
                output_dir=tmp,
                question="Is it safe to stay here?",
                location_label="Palma Marina",
                current_time="12:20",
            )
            root = Path(tmp)

            answer = (root / "decision_answer.txt").read_text()

            self.assertIn("Stay only if you are sheltered", answer)
            self.assertIn("Recommendation:", answer)

    def test_write_outputs_with_afternoon_question_does_not_recommend_past_morning_window(self):
        import tempfile
        from pathlib import Path
        import briefing

        snapshot = {
            "route": "Mallorca -> Ibiza",
            "forecast": {"wave_max_m": 1.6, "wave_peak_time": "14:00"},
            "recommendation": {
                "best_window": "before midday",
                "watch_out": "waves build toward 1.6 m around 14:00",
                "confidence": "medium",
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            briefing.write_outputs(
                snapshot,
                output_dir=tmp,
                question="I want to leave this afternoon. Is there a calm window?",
                current_time="12:20",
            )
            answer = (Path(tmp) / "decision_answer.txt").read_text()

            self.assertIn("calmer morning window has passed", answer)
            self.assertIn("Recommendation:", answer)
            self.assertNotRegex(answer, r"\b\d{1,2}:\d{2}\b")

    def test_write_outputs_with_morning_current_time_keeps_morning_window_actionable(self):
        import tempfile
        from pathlib import Path
        import briefing

        snapshot = {
            "route": "Mallorca -> Ibiza",
            "forecast": {"wave_max_m": 1.6, "wave_peak_time": "14:00"},
            "recommendation": {
                "best_window": "morning to early afternoon",
                "watch_out": "forecast peak near 1.6 m around 14:00",
                "confidence": "medium",
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            briefing.write_outputs(
                snapshot,
                output_dir=tmp,
                question="I want to leave this afternoon. Is there a calm window?",
                current_time="09:30",
            )
            answer = (Path(tmp) / "decision_answer.txt").read_text()

            self.assertIn("Leave morning to early afternoon", answer)
            self.assertIn("Recommendation:", answer)
            self.assertNotIn("has passed", answer)
            self.assertNotRegex(answer, r"\b\d{1,2}:\d{2}\b")


class ForecastFallbackTests(unittest.TestCase):
    def test_forecast_summary_fallback_keeps_briefing_available(self):
        import route_analysis

        summary = route_analysis.default_forecast_summary()

        self.assertEqual(summary["wave_peak_time"], "N/A")
        self.assertIsNone(summary["wave_max_m"])
        self.assertIsNone(summary["current_max_kn"])


class ForecastSummaryTests(unittest.TestCase):
    def test_summarize_forecast_series_reports_wave_and_current_peaks(self):
        import route_analysis

        summary = route_analysis.summarize_forecast_series(
            times=["09:00", "15:00"],
            wave_heights_m=[0.7, 1.6],
            current_speeds_mps=[0.2, 0.7],
        )

        self.assertEqual(summary["wave_min_m"], 0.7)
        self.assertEqual(summary["wave_max_m"], 1.6)
        self.assertEqual(summary["wave_peak_time"], "15:00")
        self.assertEqual(summary["current_peak_time"], "15:00")
        self.assertAlmostEqual(summary["current_max_kn"], 1.4)
        self.assertEqual(
            summary["hourly"],
            [
                {"time": "09:00", "wave_m": 0.7, "current_mps": 0.2, "current_kn": 0.4},
                {"time": "15:00", "wave_m": 1.6, "current_mps": 0.7, "current_kn": 1.4},
            ],
        )

    def test_summarize_route_points_uses_exposed_route_max_not_box_average(self):
        import route_analysis

        summary = route_analysis.summarize_route_point_series(
            times=["17:00"],
            wave_points_by_time=[[1.2, 1.8, 1.7]],
            current_points_by_time=[[0.1, 0.3, 0.2]],
        )

        self.assertEqual(summary["wave_max_m"], 1.8)
        self.assertEqual(summary["hourly"][0]["wave_m"], 1.8)
        self.assertEqual(summary["hourly"][0]["current_kn"], 0.6)
        self.assertEqual(summary["sampling_method"], "route_exposed_max")

    def test_summarize_route_points_keeps_wave_direction_at_exposed_point(self):
        import route_analysis

        summary = route_analysis.summarize_route_point_series(
            times=["15:00"],
            wave_points_by_time=[[1.2, 1.8, 1.7]],
            current_points_by_time=[[0.1, 0.3, 0.2]],
            wave_direction_points_by_time=[[20.0, 315.0, 280.0]],
            current_direction_points_by_time=[[10.0, 80.0, 120.0]],
        )

        self.assertEqual(summary["wave_peak_direction_deg"], 315.0)
        self.assertEqual(summary["hourly"][0]["wave_direction_deg"], 315.0)
        self.assertEqual(summary["hourly"][0]["current_direction_deg"], 80.0)
        self.assertEqual(summary["hourly"][0]["current_mps"], 0.3)

    def test_summarize_route_points_keeps_wave_partitions_at_exposed_point(self):
        import route_analysis

        route = {
            "origin": {"longitude": 2.0, "latitude": 0.0},
            "destination": {"longitude": 3.0, "latitude": 0.0},
        }
        summary = route_analysis.summarize_route_point_series(
            times=["15:00"],
            wave_points_by_time=[[1.2, 1.8, 1.7]],
            current_points_by_time=[[0.1, 0.3, 0.2]],
            wave_direction_points_by_time=[[20.0, 90.0, 280.0]],
            component_points_by_time={
                "swell_1": {
                    "height": [[0.4, 1.1, 0.9]],
                    "direction": [[30.0, 90.0, 290.0]],
                },
                "swell_2": {
                    "height": [[0.2, 0.5, 0.3]],
                    "direction": [[210.0, 180.0, 160.0]],
                },
                "wind_wave": {
                    "height": [[0.3, 0.7, 0.6]],
                    "direction": [[80.0, 100.0, 110.0]],
                },
            },
            route=route,
        )

        self.assertEqual(summary["route_bearing_deg"], 90.0)
        self.assertEqual(summary["wave_peak_sea_state"], "head sea")
        self.assertEqual(summary["wave_peak_relative_angle_deg"], 0.0)
        self.assertEqual(summary["swell_1_height_m"], 1.1)
        self.assertEqual(summary["swell_1_direction_deg"], 90.0)
        self.assertEqual(summary["swell_2_height_m"], 0.5)
        self.assertEqual(summary["swell_2_direction_deg"], 180.0)
        self.assertEqual(summary["wind_wave_height_m"], 0.7)
        self.assertEqual(summary["wind_wave_direction_deg"], 100.0)
        self.assertEqual(summary["hourly"][0]["swell_1_height_m"], 1.1)
        self.assertEqual(summary["hourly"][0]["swell_1_direction_deg"], 90.0)
        self.assertEqual(summary["hourly"][0]["wave_sea_state"], "head sea")

    def test_relative_sea_state_classifies_route_angle(self):
        import route_analysis

        self.assertEqual(route_analysis.relative_sea_state(90, 90)["label"], "head sea")
        self.assertEqual(route_analysis.relative_sea_state(270, 90)["label"], "following sea")
        self.assertEqual(route_analysis.relative_sea_state(0, 90)["label"], "beam sea")
        self.assertEqual(route_analysis.relative_sea_state(45, 90)["label"], "bow quartering sea")
        self.assertEqual(route_analysis.relative_sea_state(135, 90)["label"], "bow quartering sea")
        self.assertEqual(route_analysis.relative_sea_state(225, 90)["label"], "stern quartering sea")

    def test_route_points_are_read_from_supplied_route(self):
        import route_analysis

        route = {
            "id": "test_route",
            "sample_points": [
                {"name": "A", "longitude": 1.0, "latitude": 2.0},
                {"name": "B", "longitude": 3.0, "latitude": 4.0},
            ],
        }

        points = route_analysis.route_sample_points(route)

        self.assertEqual(
            points,
            [
                {"name": "A", "longitude": 1.0, "latitude": 2.0},
                {"name": "B", "longitude": 3.0, "latitude": 4.0},
            ],
        )


class DecisionEngineTests(unittest.TestCase):
    def test_classify_question_detects_decision_intents(self):
        import decision_engine

        self.assertEqual(decision_engine.classify_question("Is it safe to stay here tonight?"), "location_safety")
        self.assertEqual(decision_engine.classify_question("Can I save fuel by using another route to Ibiza?"), "fuel_efficiency")
        self.assertEqual(decision_engine.classify_question("What is the best time to leave Palma?"), "leave_window")
        self.assertEqual(decision_engine.classify_question("How will the sea be here in 4 hours?"), "conditions_soon")
        self.assertEqual(decision_engine.classify_question("Can I cross Palma to Ibiza tonight?"), "route_timing")

    def test_route_timing_answers_distinguish_tonight_from_tomorrow(self):
        import decision_engine

        snapshot = {
            "route": "Palma -> Ibiza",
            "vessel_profile": {"label": "15-24m", "manageable_m": 1.5, "restricted_m": 2.2},
            "forecast": {
                "wave_max_m": 0.5,
                "wave_peak_time": "15:00",
                "current_max_kn": 0.3,
                "hourly": [
                    {"time": "21:00", "wave_m": 0.3, "current_kn": 0.1},
                    {"time": "09:00", "wave_m": 0.4, "current_kn": 0.2},
                ],
            },
            "recommendation": {
                "best_window": "most daylight windows look manageable",
                "watch_out": "no major wave build-up in the 24h forecast",
                "confidence": "medium",
                "vessel_advice": "manageable for vessels 15-24m",
            },
        }

        tonight = decision_engine.answer_question(
            "Can I cross Palma to Ibiza tonight?",
            snapshot,
            current_time="21:30",
        )
        tomorrow = decision_engine.answer_question(
            "Can I cross Palma to Ibiza tomorrow?",
            snapshot,
            current_time="21:30",
        )

        self.assertEqual(tonight["intent"], "route_timing")
        self.assertIn("night crossing", tonight["answer"])
        self.assertIn("Tonight", tonight["answer"])
        self.assertIn("Tomorrow", tomorrow["answer"])
        self.assertIn("Tomorrow morning looks workable", tomorrow["answer"])
        self.assertNotEqual(tonight["answer"], tomorrow["answer"])

    def test_late_best_time_question_defers_to_tomorrow_planning(self):
        import decision_engine

        snapshot = {
            "route": "Palma -> Ibiza",
            "forecast": {"wave_max_m": 0.4, "wave_peak_time": "15:00", "current_max_kn": 0.2},
            "recommendation": {
                "best_window": "most daylight windows look manageable",
                "watch_out": "no major wave build-up in the 24h forecast",
                "confidence": "medium",
            },
        }

        decision = decision_engine.answer_question(
            "What is the best time to leave Palma for Ibiza today?",
            snapshot,
            current_time="22:00",
        )

        self.assertEqual(decision["intent"], "leave_window")
        self.assertIn("practical daylight window has passed", decision["answer"])
        self.assertIn("tomorrow morning", decision["answer"])

    def test_answer_question_uses_captain_facing_operational_tone(self):
        import decision_engine

        snapshot = {
            "route": "Mallorca -> Ibiza",
            "forecast": {"wave_max_m": 1.6, "wave_peak_time": "14:00", "current_max_kn": 0.5},
            "recommendation": {
                "best_window": "before midday",
                "watch_out": "waves build toward 1.6 m around 14:00",
                "confidence": "medium",
            },
        }

        decision = decision_engine.answer_question(
            "I want to leave this afternoon. Is there a calm window?",
            snapshot,
            location_label="Palma Marina",
            current_time="12:20",
        )

        self.assertEqual(decision["intent"], "leave_window")
        self.assertIn("calmer morning window has passed", decision["answer"])
        self.assertIn("avoid timing your departure near the forecast peak", decision["answer"])
        self.assertIn("Recommendation:", decision["answer"])
        self.assertNotIn("Reason:", decision["answer"])
        self.assertIn("Confidence: Medium", decision["answer"])

    def test_afternoon_question_reframes_morning_to_early_afternoon_window(self):
        import decision_engine

        snapshot = {
            "route": "Mallorca -> Ibiza",
            "forecast": {"wave_max_m": 1.6, "wave_peak_time": "14:00"},
            "recommendation": {
                "best_window": "morning to early afternoon",
                "watch_out": "forecast peak near 1.6 m around 14:00",
                "confidence": "medium",
            },
        }

        decision = decision_engine.answer_question(
            "I want to leave this afternoon. Is there a calm window?",
            snapshot,
            current_time="12:20",
        )

        self.assertIn("roughest daylight hours period", decision["answer"])
        self.assertIn("Recommendation:", decision["answer"])

    def test_requested_time_question_compares_against_forecast_curve(self):
        import decision_engine

        snapshot = {
            "route": "Mallorca -> Ibiza",
            "forecast": {
                "wave_max_m": 1.6,
                "wave_peak_time": "14:00",
                "hourly": [
                    {"time": "14:00", "wave_m": 1.6, "current_kn": 0.4},
                    {"time": "17:00", "wave_m": 1.2, "current_kn": 0.3},
                ],
            },
            "recommendation": {
                "best_window": "morning to early afternoon",
                "watch_out": "forecast peak near 1.6 m around 14:00",
                "confidence": "medium",
            },
        }

        decision = decision_engine.answer_question(
            "Can I leave at 17:00?",
            snapshot,
            current_time="12:20",
        )

        self.assertIn("17:00 LT looks better than the 14:00 LT peak", decision["answer"])
        self.assertEqual(decision["forecast_context"]["hourly"][1]["wave_m"], 1.2)

    def test_agent_does_not_recommend_forecast_peak_as_best_departure(self):
        import decision_engine

        snapshot = {
            "route": "Palma -> Ibiza",
            "vessel_profile": {"label": "15-24m", "manageable_m": 1.5, "restricted_m": 2.2},
            "forecast": {
                "wave_max_m": 1.6,
                "wave_peak_time": "08:00",
                "wave_peak_direction_deg": 60,
                "hourly": [
                    {"time": "08:00", "wave_m": 1.6, "wave_direction_deg": 60},
                    {"time": "11:00", "wave_m": 1.2, "wave_direction_deg": 65},
                ],
            },
            "recommendation": {
                "best_window": "morning to early afternoon",
                "watch_out": "forecast peak near 1.6 m around 08:00",
                "confidence": "medium",
                "vessel_advice": "caution for vessels 15-24m; use the best weather window",
            },
        }

        decision = decision_engine.answer_question(
            "What is the best time to leave Palma to Ibiza?",
            snapshot,
            current_time="07:00",
        )

        self.assertIn("roughest early morning period", decision["answer"])
        self.assertTrue(
            "leave through the morning" in decision["answer"].lower()
            or "leave before late morning" in decision["answer"].lower()
            or "leave overnight" in decision["answer"].lower()
        )
        self.assertEqual(decision["forecast_context"]["wave_max_m"], 1.6)
        self.assertEqual(decision["forecast_context"]["wave_peak_direction_deg"], 60)
        self.assertNotIn("leave morning to early afternoon", decision["answer"])

    def test_best_departure_window_does_not_recommend_past_time(self):
        import decision_engine

        snapshot = {
            "route": "Palma -> Ibiza",
            "vessel_profile": {"label": "15-24m", "manageable_m": 1.5, "restricted_m": 2.2},
            "forecast": {
                "wave_max_m": 1.6,
                "wave_peak_time": "08:00",
                "wave_peak_direction_deg": 60,
                "hourly": [
                    {"time": "05:00", "wave_m": 0.7, "wave_direction_deg": 55},
                    {"time": "08:00", "wave_m": 1.6, "wave_direction_deg": 60},
                    {"time": "11:00", "wave_m": 1.2, "wave_direction_deg": 65},
                ],
            },
            "recommendation": {
                "best_window": "morning to early afternoon",
                "watch_out": "forecast peak near 1.6 m around 08:00",
                "confidence": "medium",
                "vessel_advice": "caution for vessels 15-24m; use the best weather window",
            },
        }

        decision = decision_engine.answer_question(
            "What is the best time to leave Palma to Ibiza?",
            snapshot,
            current_time="07:00",
        )

        self.assertIn("Recommendation:", decision["answer"])
        self.assertIn("WINDOWS:", decision["answer"])
        self.assertIn("COMFORT:", decision["answer"])
        self.assertIn("TREND:", decision["answer"])
        self.assertIn("What could change:", decision["answer"])
        self.assertIn("Confidence:", decision["answer"])
        self.assertTrue(
            "leave through the morning" in decision["answer"].lower()
            or "leave before late morning" in decision["answer"].lower()
            or "leave overnight" in decision["answer"].lower()
        )
        self.assertNotIn("05:00", decision["answer"])

    def test_agent_includes_wave_components_and_route_relative_sea_state(self):
        import decision_engine

        snapshot = {
            "route": "Palma -> Ibiza",
            "vessel_profile": {"label": "15-24m", "manageable_m": 1.5, "restricted_m": 2.2},
            "forecast": {
                "wave_max_m": 1.6,
                "wave_peak_time": "08:00",
                "wave_peak_direction_deg": 68,
                "wave_peak_sea_state": "head sea",
                "swell_1_height_m": 1.0,
                "swell_1_direction_deg": 70,
                "swell_2_height_m": 0.4,
                "swell_2_direction_deg": 210,
                "wind_wave_height_m": 0.7,
                "wind_wave_direction_deg": 75,
                "hourly": [
                    {"time": "07:00", "wave_m": 0.8, "wave_direction_deg": 65, "wave_sea_state": "head sea"},
                    {"time": "08:00", "wave_m": 1.6, "wave_direction_deg": 68, "wave_sea_state": "head sea"},
                    {"time": "11:00", "wave_m": 1.2, "wave_direction_deg": 70, "wave_sea_state": "head sea"},
                ],
            },
            "recommendation": {
                "best_window": "morning to early afternoon",
                "watch_out": "forecast peak near 1.6 m around 08:00",
                "confidence": "medium",
                "vessel_advice": "caution for vessels 15-24m; use the best weather window",
            },
        }

        decision = decision_engine.answer_question(
            "What is the best time to leave Palma to Ibiza?",
            snapshot,
            current_time="07:00",
        )

        self.assertIn("head sea", decision["answer"])
        self.assertIn("Primary swell 1.0 m from 70", decision["answer"])
        self.assertIn("secondary swell 0.4 m from 210", decision["answer"])
        self.assertIn("wind wave 0.7 m from 75", decision["answer"])
        self.assertNotIn("components are not available", decision["answer"])

    def test_conditions_soon_does_not_warn_when_peak_is_calm(self):
        import decision_engine

        snapshot = {
            "route": "Palma -> Ibiza",
            "vessel_profile": {"label": "15-24m", "manageable_m": 1.5, "restricted_m": 2.2},
            "forecast": {"wave_max_m": 0.5, "wave_peak_time": "08:00", "current_max_kn": 0.3},
            "recommendation": {
                "best_window": "most daylight windows look manageable",
                "watch_out": "no major wave build-up in the 24h forecast",
                "confidence": "medium",
                "vessel_advice": "manageable for vessels 15-24m",
            },
        }

        decision = decision_engine.answer_question(
            "How will the sea be this afternoon?",
            snapshot,
            current_time="09:30",
        )

        self.assertIn("Conditions look workable", decision["answer"])
        self.assertEqual(decision["forecast_context"]["wave_max_m"], 0.5)
        self.assertIn("For this vessel size:", decision["answer"])
        self.assertIn("15-24m", decision["answer"])
        self.assertNotIn("expect conditions to worsen", decision["answer"])

    def test_answer_question_includes_vessel_class_context(self):
        import decision_engine

        snapshot = {
            "route": "Alcudia -> Ciutadella",
            "vessel_class": "small",
            "forecast": {"wave_max_m": 1.9, "wave_peak_time": "15:00"},
            "recommendation": {
                "best_window": "avoid the exposed peak window",
                "watch_out": "forecast peak near 1.9 m around 15:00",
                "confidence": "medium",
                "vessel_advice": "restricted for vessels under 15m",
            },
        }

        decision = decision_engine.answer_question(
            "Can I leave at 15:00?",
            snapshot,
            current_time="09:30",
        )

        self.assertIn("For this vessel size:", decision["answer"])
        self.assertIn("restricted for vessels under 15m", decision["answer"])

    def test_answer_question_handles_missing_vessel_and_component_information(self):
        import decision_engine

        snapshot = {
            "route": "Palma -> Ibiza",
            "forecast": {
                "wave_max_m": 1.3,
                "wave_peak_time": "14:00",
                "wave_peak_direction_deg": 90,
                "hourly": [{"time": "09:00", "wave_m": 1.0}],
            },
            "recommendation": {
                "best_window": "morning",
                "watch_out": "forecast peak near 1.3 m around 14:00",
                "confidence": "medium",
            },
        }

        decision = decision_engine.answer_question(
            "Would Palma to Ibiza feel comfortable tomorrow morning?",
            snapshot,
            current_time="21:30",
        )

        self.assertIn("Recommendation:", decision["answer"])
        self.assertIn("COMFORT:", decision["answer"])
        self.assertIn("For this vessel size: vessel size was not provided", decision["answer"])
        self.assertIn("What could change:", decision["answer"])
        self.assertIn("swell and wind-wave partition data changes the comfort read", decision["answer"])
        self.assertIn("Evidence note:", decision["answer"])

    def test_tomorrow_question_filters_hourly_forecast_to_tomorrow_local_date(self):
        import decision_engine

        snapshot = {
            "route": "Palma -> Ibiza",
            "vessel_class": "medium",
            "vessel_profile": {"label": "15-24m", "manageable_m": 1.5, "restricted_m": 2.2},
            "forecast": {
                "wave_min_m": 0.5,
                "wave_max_m": 1.9,
                "wave_peak_time": "11:00",
                "current_max_kn": 0.8,
                "current_peak_time": "11:00",
                "route_segments": {
                    "worst_segment": {
                        "name": "Ibiza Channel",
                        "max_wave_m": 1.9,
                        "peak_time": "11:00",
                        "sea_state": "following sea",
                    }
                },
                "hourly": [
                    {
                        "time": "11:00",
                        "time_utc": "2026-06-05 11:00 UTC",
                        "wave_m": 1.9,
                        "current_kn": 0.8,
                        "wave_direction_deg": 59.9,
                        "wave_sea_state": "following sea",
                        "swell_1_height_m": 0.9,
                        "swell_1_direction_deg": 8.0,
                        "swell_2_height_m": 0.7,
                        "swell_2_direction_deg": 28.0,
                        "wind_wave_height_m": 1.5,
                        "wind_wave_direction_deg": 82.0,
                    },
                    {
                        "time": "00:00",
                        "time_utc": "2026-06-05 22:00 UTC",
                        "wave_m": 1.2,
                        "current_kn": 0.4,
                        "wave_direction_deg": 73.0,
                        "wave_sea_state": "following sea",
                        "swell_1_height_m": 0.9,
                        "swell_1_direction_deg": 73.0,
                        "swell_2_height_m": 0.7,
                        "swell_2_direction_deg": 45.0,
                        "wind_wave_height_m": 0.5,
                        "wind_wave_direction_deg": 100.0,
                    },
                    {
                        "time": "08:00",
                        "time_utc": "2026-06-06 06:00 UTC",
                        "wave_m": 0.8,
                        "current_kn": 0.3,
                        "wave_direction_deg": 81.0,
                        "wave_sea_state": "following sea",
                        "swell_1_height_m": 0.6,
                        "swell_1_direction_deg": 80.0,
                        "swell_2_height_m": 0.5,
                        "swell_2_direction_deg": 50.0,
                        "wind_wave_height_m": 0.0,
                        "wind_wave_direction_deg": 100.0,
                    },
                    {
                        "time": "10:00",
                        "time_utc": "2026-06-06 08:00 UTC",
                        "wave_m": 0.7,
                        "current_kn": 0.2,
                        "wave_direction_deg": 84.0,
                        "wave_sea_state": "following sea",
                        "swell_1_height_m": 0.5,
                        "swell_1_direction_deg": 85.0,
                        "swell_2_height_m": 0.4,
                        "swell_2_direction_deg": 52.0,
                        "wind_wave_height_m": 0.1,
                        "wind_wave_direction_deg": 102.0,
                    },
                ],
            },
            "recommendation": {
                "best_window": "lower sea-state window",
                "watch_out": "forecast peak near 1.9 m around 11:00",
                "confidence": "medium",
                "vessel_advice": "manageable for vessels 15-24m",
            },
        }

        decision = decision_engine.answer_question(
            "Would Palma to Ibiza feel comfortable for a 15-24m vessel tomorrow morning?",
            snapshot,
            current_time="21:00",
            current_date="2026-06-05",
        )

        self.assertIn("Tomorrow morning looks workable", decision["answer"])
        self.assertTrue(any(row["wave_m"] == 0.8 for row in decision["forecast_context"]["hourly"]))
        self.assertTrue(
            "through the morning" in decision["answer"]
            or "during daylight hours" in decision["answer"]
            or "overnight" in decision["answer"]
        )
        self.assertNotIn("1.9 m", decision["answer"])
        self.assertNotIn("1.2 m", decision["answer"])
        self.assertNotIn("Ibiza Channel", decision["answer"])
        self.assertNotIn("Worst route segment", decision["answer"])

    def test_render_decision_screenshot_script_uses_shared_location_and_question(self):
        import decision_engine

        decision = {
            "intent": "location_safety",
            "question": "Is it safe to stay here?",
            "answer": "Stay only if you are sheltered.\nWaves build.\nConfidence: Medium.",
        }

        script = decision_engine.render_decision_screenshot_script(decision)

        self.assertIn("Captain: [Shared live location]", script)
        self.assertIn("Captain: Is it safe to stay here?", script)
        self.assertIn("PredSea: Stay only if you are sheltered.", script)


class ChatFigureTests(unittest.TestCase):
    def test_parse_script_marks_shared_location_message(self):
        import chat_figure

        messages, _ = chat_figure.parse_script("Captain: [Shared live location]\nPredSea: Got it.")

        self.assertTrue(messages[0]["is_location"])

    def test_emphasize_message_marks_key_route_values(self):
        import chat_figure

        segments = chat_figure.emphasize_message("Best window looks before midday and waves reach 1.6 m.")

        self.assertIn(("before midday", True), segments)
        self.assertIn(("1.6 m", True), segments)

    def test_generate_chat_figure_writes_png_from_script_and_logo(self):
        import tempfile
        from pathlib import Path
        from PIL import Image
        import chat_figure

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script_path = root / "script.txt"
            logo_path = root / "logo.png"
            output_path = root / "chat.png"
            script_path.write_text(
                "\n".join(
                    [
                        "Illustrative WhatsApp screenshot script",
                        "Captain: How is the sea looking for Palma to Ibiza today?",
                        "PredSea: Best window looks before midday.",
                        "PredSea: Confidence: Medium.",
                        "Caption note: illustrative product example.",
                    ]
                ),
                encoding="utf-8",
            )
            Image.new("RGB", (128, 128), "#00d7df").save(logo_path)

            result = chat_figure.generate_chat_figure(script_path, logo_path, output_path)

            self.assertEqual(Path(result), output_path)
            self.assertTrue(output_path.exists())
            with Image.open(output_path) as image:
                self.assertEqual(image.size, (1440, 1800))


class ValidationEngineTests(unittest.TestCase):
    def test_validate_route_snapshot_compares_predicted_wave_to_observed_buoy(self):
        import validation_engine

        snapshot = {
            "route": "Palma -> Ibiza",
            "route_id": "ibiza_palma",
            "forecast": {
                "wave_peak_time": "15:00",
                "hourly": [
                    {"time": "14:00", "wave_m": 1.3},
                    {"time": "15:00", "wave_m": 1.6},
                ],
            },
        }
        observations = {
            "canal_de_ibiza": {
                "name": "Buoy Canal de Ibiza",
                "wave_height_m": 1.5,
                "last_sample_utc": "2026-05-10 15:00 UTC",
            }
        }

        result = validation_engine.validate_route_snapshot(snapshot, observations)

        self.assertEqual(result["route_id"], "ibiza_palma")
        self.assertEqual(result["truth_source"], "canal_de_ibiza")
        self.assertEqual(result["target_time"], "15:00")
        self.assertEqual(result["predsea_wave_m"], 1.6)
        self.assertEqual(result["observed_wave_m"], 1.5)
        self.assertEqual(result["predsea_error_delta_m"], 0.1)
        self.assertEqual(result["validation_status"], "validated")

    def test_validate_route_snapshot_uses_route_specific_truth_source(self):
        import validation_engine

        snapshot = {
            "route": "Palma -> Cabrera",
            "route_id": "cabrera_palma",
            "forecast": {"wave_peak_time": "12:00", "hourly": [{"time": "12:00", "wave_m": 0.7}]},
        }
        observations = {
            "canal_de_ibiza": {"name": "Buoy Canal de Ibiza", "wave_height_m": 1.5},
            "bahia_de_palma": {"name": "Buoy Bahia de Palma", "wave_height_m": 0.4},
        }

        result = validation_engine.validate_route_snapshot(snapshot, observations)

        self.assertEqual(result["truth_source"], "bahia_de_palma")
        self.assertEqual(result["truth_source_name"], "Buoy Bahia de Palma")
        self.assertEqual(result["predsea_error_delta_m"], 0.3)

    def test_validate_route_without_suitable_truth_source_does_not_use_wrong_buoy(self):
        import validation_engine

        snapshot = {
            "route": "Alcudia -> Ciutadella",
            "route_id": "alcudia_ciutadella",
            "forecast": {"wave_peak_time": "12:00", "hourly": [{"time": "12:00", "wave_m": 1.8}]},
        }
        observations = {
            "canal_de_ibiza": {"name": "Buoy Canal de Ibiza", "wave_height_m": 1.5},
            "bahia_de_palma": {"name": "Buoy Bahia de Palma", "wave_height_m": 0.4},
        }

        result = validation_engine.validate_route_snapshot(snapshot, observations)

        self.assertIsNone(result["truth_source"])
        self.assertIsNone(result["observed_wave_m"])
        self.assertEqual(result["validation_status"], "no_suitable_truth_source")
        self.assertIn("No suitable SOCIB wave buoy", result["marketing_reason"])

    def test_marketing_win_requires_baseline_and_lower_error(self):
        import validation_engine

        result = validation_engine.evaluate_marketing_win(
            predsea_wave_m=1.6,
            baseline_wave_m=1.1,
            observed_wave_m=1.5,
        )

        self.assertTrue(result["marketing_win"])
        self.assertEqual(result["baseline_error_delta_m"], 0.4)
        self.assertIn("PredSea error 0.1 m vs baseline error 0.4 m", result["reason"])

    def test_marketing_win_is_not_claimed_without_baseline(self):
        import validation_engine

        result = validation_engine.evaluate_marketing_win(
            predsea_wave_m=1.6,
            baseline_wave_m=None,
            observed_wave_m=1.5,
        )

        self.assertFalse(result["marketing_win"])
        self.assertIsNone(result["baseline_error_delta_m"])
        self.assertIn("No baseline forecast", result["reason"])

    def test_write_validation_outputs_creates_report_and_marketing_log(self):
        import json
        import tempfile
        from pathlib import Path
        import validation_engine

        validations = [
            {
                "route_id": "ibiza_palma",
                "route": "Palma -> Ibiza",
                "validation_status": "validated",
                "marketing_win": True,
                "marketing_reason": "PredSea error 0.1 m vs baseline error 0.4 m",
            }
        ]

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = validation_engine.write_validation_outputs(validations, root_dir=tmp, run_date="2026-05-10")

            root = Path(output_dir)
            report = json.loads((root / "validation_report.json").read_text())
            wins = (root / "marketing_wins.txt").read_text()

            self.assertEqual(report[0]["route_id"], "ibiza_palma")
            self.assertIn("Palma -> Ibiza", wins)
            self.assertIn("PredSea error 0.1 m", wins)

    def test_daily_forecast_series_stops_when_forecast_wraps_to_next_day(self):
        import validation_engine

        snapshot = {
            "forecast": {
                "hourly": [
                    {"time": "21:00", "wave_m": 1.5},
                    {"time": "22:00", "wave_m": 1.4},
                    {"time": "23:00", "wave_m": 1.2},
                    {"time": "00:00", "wave_m": 1.1},
                ]
            }
        }

        series = validation_engine.daily_forecast_series(snapshot)

        self.assertEqual(
            series,
            [
                {"time": "21:00", "forecast_wave_m": 1.5},
                {"time": "22:00", "forecast_wave_m": 1.4},
                {"time": "23:00", "forecast_wave_m": 1.2},
            ],
        )

    def test_align_time_series_matches_forecast_and_observed_values_by_time(self):
        import validation_engine

        forecast_series = [
            {"time": "14:00", "forecast_wave_m": 1.8},
            {"time": "15:00", "forecast_wave_m": 1.9},
        ]
        observation_series = [
            {"time": "14:00", "observed_wave_m": 1.24},
            {"time": "15:00", "observed_wave_m": 1.31},
        ]

        aligned = validation_engine.align_time_series(forecast_series, observation_series)

        self.assertEqual(aligned[0]["error_delta_m"], 0.6)
        self.assertEqual(aligned[1]["error_delta_m"], 0.6)
        self.assertEqual(validation_engine.mean_absolute_error(aligned), 0.6)

    def test_render_time_series_png_writes_chart(self):
        import tempfile
        from pathlib import Path
        from PIL import Image
        import validation_engine

        aligned = [
            {"time": "14:00", "forecast_wave_m": 1.8, "observed_wave_m": 1.24, "error_delta_m": 0.6},
            {"time": "15:00", "forecast_wave_m": 1.9, "observed_wave_m": 1.31, "error_delta_m": 0.6},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "chart.png"
            validation_engine.render_time_series_png(aligned, "Palma -> Ibiza", output)

            self.assertTrue(output.exists())
            with Image.open(output) as image:
                self.assertEqual(image.size, (1200, 700))

    def test_align_direction_vectors_uses_circular_error_without_line_chart(self):
        import validation_engine

        forecast_series = [{"time": "12:00", "forecast_direction_deg": 350.0}]
        observation_series = [{"time": "12:00", "observed_direction_deg": 10.0}]

        aligned = validation_engine.align_direction_vectors(forecast_series, observation_series)

        self.assertEqual(aligned[0]["direction_error_deg"], 20.0)

    def test_render_direction_vector_png_writes_arrow_chart(self):
        import tempfile
        from pathlib import Path
        from PIL import Image
        import validation_engine

        aligned = [
            {"time": "14:00", "forecast_direction_deg": 310.0, "observed_direction_deg": 300.0, "direction_error_deg": 10.0},
            {"time": "15:00", "forecast_direction_deg": 320.0, "observed_direction_deg": 330.0, "direction_error_deg": 10.0},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "vectors.png"
            validation_engine.render_direction_vector_png(aligned, "Palma -> Ibiza", output)

            self.assertTrue(output.exists())
            with Image.open(output) as image:
                self.assertEqual(image.size, (1200, 700))

    def test_align_current_speed_series_matches_scalar_values(self):
        import validation_engine

        forecast_series = [{"time": "12:00", "forecast_current_mps": 0.30}]
        observation_series = [{"time": "12:00", "observed_current_mps": 0.42}]

        aligned = validation_engine.align_current_speed_series(forecast_series, observation_series)

        self.assertEqual(aligned[0]["error_delta_mps"], 0.12)

    def test_current_validation_source_is_configured_for_menorca_channel(self):
        import validation_engine

        source = validation_engine.current_validation_source("alcudia_ciutadella")

        self.assertEqual(source["truth_source"], "ciutadella")
        self.assertEqual(source["socib_speed_variable_id"], 90776)
        self.assertEqual(source["socib_direction_variable_id"], 90763)


if __name__ == "__main__":
    unittest.main()
