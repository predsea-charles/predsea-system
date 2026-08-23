import unittest
from datetime import datetime
import gmdss_aggregator


class TestGMDSSAggregator(unittest.TestCase):

    def setUp(self):
        gmdss_aggregator.active_warnings_db = []

    def test_haversine_distance(self):
        # Distance from Palma to Ibiza is approx 70 nautical miles
        dist = gmdss_aggregator.haversine_distance(39.5696, 2.6502, 38.9089, 1.435)
        self.assertAlmostEqual(dist, 70.0, delta=5.0)

    def test_coordinate_parsing_format_1(self):
        # Format: DD-MMN DDD-MME
        alert = gmdss_aggregator.GMDSSAlert(
            alert_id="TEST-1",
            station_name="Test Station",
            alert_type="Navigational",
            message_text="Alert active near 39-45N 003-10E"
        )
        self.assertIsNotNone(alert.coordinates)
        self.assertAlmostEqual(alert.coordinates[0], 39.75, places=2)
        self.assertAlmostEqual(alert.coordinates[1], 3.167, places=2)

    def test_coordinate_parsing_format_2(self):
        # Format: Decimal degrees
        alert = gmdss_aggregator.GMDSSAlert(
            alert_id="TEST-2",
            station_name="Test Station",
            alert_type="Meteorological",
            message_text="Rough seas building near 40.84N, 14.25E in the morning."
        )
        self.assertIsNotNone(alert.coordinates)
        self.assertAlmostEqual(alert.coordinates[0], 40.84, places=2)
        self.assertAlmostEqual(alert.coordinates[1], 14.25, places=2)

    def test_coordinate_parsing_format_3(self):
        # Format: Whole degrees
        alert = gmdss_aggregator.GMDSSAlert(
            alert_id="TEST-3",
            station_name="Test Station",
            alert_type="SAR",
            message_text="Distress vessel reported at 38N 013E"
        )
        self.assertIsNotNone(alert.coordinates)
        self.assertAlmostEqual(alert.coordinates[0], 38.0, places=2)
        self.assertAlmostEqual(alert.coordinates[1], 13.0, places=2)

    def test_filter_alerts_by_position(self):
        # Active Rome distress report (ROM-115) is at 40.80N, 14.10E
        # A vessel at Naples (40.84N, 14.25E) is very close (~7 NM)
        alerts = gmdss_aggregator.filter_alerts_by_position(40.84, 14.25, max_distance_nm=15.0)
        self.assertGreaterEqual(len(alerts), 1)
        alert_ids = [a[0].alert_id for a in alerts]
        self.assertIn("NAVTEX-ROM-115", alert_ids)

    def test_filter_alerts_by_route(self):
        # Route: Cagliari -> Naples has a sample point near Naples approach: (40.72, 14.05)
        # Rome SAR warning (NAVTEX-ROM-115) is at 40.80N, 14.10E (~5 NM)
        sample_points = [
            {"latitude": 39.15, "longitude": 9.40},
            {"latitude": 40.00, "longitude": 11.80},
            {"latitude": 40.72, "longitude": 14.05}
        ]
        alerts = gmdss_aggregator.filter_alerts_by_route(sample_points, max_distance_nm=20.0)
        self.assertGreaterEqual(len(alerts), 1)
        alert_ids = [a[0].alert_id for a in alerts]
        self.assertIn("NAVTEX-ROM-115", alert_ids)

    def test_render_markdown_summary(self):
        # Ensure the rendered summary contains the GMDSS legal disclaimer and heading
        alerts = gmdss_aggregator.filter_alerts_by_position(40.84, 14.25, max_distance_nm=10.0)
        summary = gmdss_aggregator.render_markdown_summary(alerts)
        self.assertIn("GMDSS SAFETY NET & NAVTEX SUPPLEMENTAL SERVICE DISCLAIMER", summary)
        self.assertIn("Geolocated GMDSS & NAVTEX Advisories", summary)
        self.assertIn("NAVTEX-ROM-115", summary)

    def test_load_save_warnings_file(self):
        import tempfile
        from pathlib import Path
        
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_file = Path(tmpdir) / "test_warnings.json"
            
            # Create a couple of custom alerts
            custom_alerts = [
                gmdss_aggregator.GMDSSAlert(
                    alert_id="CUSTOM-1",
                    station_name="Test Station 1",
                    alert_type="Navigational",
                    message_text="Alert active near 39N 003E",
                    severity="Warning",
                    publish_time="2026-06-26T12:00:00Z"
                ),
                gmdss_aggregator.GMDSSAlert(
                    alert_id="CUSTOM-2",
                    station_name="Test Station 2",
                    alert_type="SAR",
                    message_text="Distress near 40N 014E",
                    severity="Critical",
                    publish_time="2026-06-26T13:00:00Z"
                )
            ]
            
            # Save them
            gmdss_aggregator.save_warnings_to_file(custom_alerts, temp_file)
            self.assertTrue(temp_file.exists())
            
            # Load them back
            loaded_alerts = gmdss_aggregator.load_warnings_from_file(temp_file)
            self.assertEqual(len(loaded_alerts), 2)
            self.assertEqual(loaded_alerts[0].alert_id, "CUSTOM-1")
            self.assertEqual(loaded_alerts[1].alert_id, "CUSTOM-2")
            self.assertEqual(loaded_alerts[0].station_name, "Test Station 1")
            self.assertEqual(loaded_alerts[1].severity, "Critical")
            self.assertEqual(loaded_alerts[0].publish_time, "2026-06-26T12:00:00Z")
            self.assertIsNotNone(loaded_alerts[0].coordinates)
            self.assertAlmostEqual(loaded_alerts[0].coordinates[0], 39.0)
            self.assertAlmostEqual(loaded_alerts[0].coordinates[1], 3.0)

    def test_load_warnings_file_fallback(self):
        # File doesn't exist - should fallback to mock warnings database
        loaded = gmdss_aggregator.load_warnings_from_file("non_existent_file_path.json")
        self.assertGreater(len(loaded), 0)
        self.assertEqual(loaded[0].alert_id, gmdss_aggregator.MOCK_WARNINGS_DATABASE[0].alert_id)
        
        # Corrupt file - should fallback to mock warnings database
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmpdir:
            corrupt_file = Path(tmpdir) / "corrupt.json"
            with open(corrupt_file, "w") as f:
                f.write("{invalid-json")
            loaded_corrupt = gmdss_aggregator.load_warnings_from_file(corrupt_file)
            self.assertGreater(len(loaded_corrupt), 0)


if __name__ == "__main__":
    unittest.main()
