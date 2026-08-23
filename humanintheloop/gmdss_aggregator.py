import math
import re
import json
from pathlib import Path
from datetime import datetime

# Earth's radius in nautical miles
EARTH_RADIUS_NM = 3440.065

# High-visibility GMDSS / SafetyNET legal disclaimer
GMDSS_DISCLAIMER = (
    "========================================================================\n"
    "⚠️  GMDSS SAFETY NET & NAVTEX SUPPLEMENTAL SERVICE DISCLAIMER\n"
    "========================================================================\n"
    "This safety feed is an experimental web-aggregated secondary resource.\n"
    "Web-scraped marine broadcasts may be subject to lag, transmission gaps,\n"
    "or geographic parsing errors.\n\n"
    "CRITICAL REQUIREMENT: This feed MUST NOT be used as a primary source for\n"
    "navigation or passage planning. The vessel's crew is legally required to\n"
    "verify all active navigational warnings and meteorological notices on\n"
    "their GMDSS-certified onboard hardware (physical Inmarsat C receiver, COSPAS-\n"
    "SARSAT, and active local NAVTEX/VHF receivers) prior to departure.\n"
    "========================================================================"
)


class GMDSSAlert:
    def __init__(self, alert_id, station_name, alert_type, message_text, severity="Warning", publish_time=None):
        self.alert_id = alert_id
        self.station_name = station_name
        self.alert_type = alert_type  # "Navigational", "Meteorological", "SAR"
        self.message_text = message_text
        self.severity = severity  # "Critical", "Warning", "Advisory"
        self.publish_time = publish_time or datetime.utcnow().isoformat() + "Z"
        self.coordinates = self._parse_coordinates(message_text)

    def _parse_coordinates(self, text):
        """
        Regex to parse coordinates from unstructured warning text.
        Supports standard NAVTEX formats:
        - 39-45N 003-10E
        - 40.84N, 14.25E
        - 38N 013E
        """
        # Format 1: DD-MMN DDD-MME
        pattern1 = r"\b(\d{2})-(\d{2})N\s+0?(\d{2,3})-(\d{2})E\b"
        match1 = re.search(pattern1, text)
        if match1:
            lat_deg, lat_min = map(float, match1.groups()[:2])
            lon_deg, lon_min = map(float, match1.groups()[2:])
            return (lat_deg + lat_min / 60.0, lon_deg + lon_min / 60.0)

        # Format 2: Decimal degrees (e.g., 40.84N 14.25E or 40.84N, 14.25E)
        pattern2 = r"\b(\d{2}\.\d+)\s*N,?\s+0?(\d{1,3}\.\d+)\s*E\b"
        match2 = re.search(pattern2, text)
        if match2:
            return (float(match2.group(1)), float(match2.group(2)))

        # Format 3: Simple whole degrees (e.g. 38N 013E)
        pattern3 = r"\b(\d{2})\s*N\s+0?(\d{2,3})\s*E\b"
        match3 = re.search(pattern3, text)
        if match3:
            return (float(match3.group(1)), float(match3.group(2)))

        return None


def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the geodesic distance between two points in nautical miles.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2.0) ** 2

    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_NM * c


# Active GMDSS Warnings Database representing Mediterranean stations
MOCK_WARNINGS_DATABASE = [
    GMDSSAlert(
        alert_id="NAVAREA-III-104-26",
        station_name="Cabo de la Nao (Spain)",
        alert_type="Navigational",
        message_text=(
            "NAVAREA III WARNING 104/26.\n"
            "BALEARIC SEA. DRIFTING CONTAINER reported in position 39-45N 003-10E.\n"
            "Partially submerged 40ft blue container. Danger to navigation. Vessels in vicinity keep sharp lookout."
        ),
        severity="Critical"
    ),
    GMDSSAlert(
        alert_id="NAVTEX-LG-802",
        station_name="La Garde (France)",
        alert_type="Meteorological",
        message_text=(
            "GULF OF LION. GALE WARNING.\n"
            "Mistral wind force 8 to 9 (35 to 45 knots) forecast in northern sector of Gulf of Lion.\n"
            "Seas building to rough or very rough (4.0m to 5.0m significant wave height) near 42-30N 005-40E.\n"
            "Smaller vessels should seek shelter or adapt routing."
        ),
        severity="Warning"
    ),
    GMDSSAlert(
        alert_id="NAVTEX-CAG-221",
        station_name="Cagliari (Sardinia)",
        alert_type="Navigational",
        message_text=(
            "TYRRHENIAN SEA. MILITARY ROCKET FIRING EXERCISES.\n"
            "Exclusion zone established inside area bounded by: 39-10N 009-30E to 39-25N 009-50E.\n"
            "All vessels prohibited from entering or traversing active sector. Watch VHF Ch 16 for updates."
        ),
        severity="Critical"
    ),
    GMDSSAlert(
        alert_id="NAVTEX-AUG-340",
        station_name="Augusta (Sicily)",
        alert_type="Navigational",
        message_text=(
            "STRAIT OF MESSINA. DREDGING OPERATIONS.\n"
            "Dredging vessel 'VENEZIA' in operations near Messina approach 38-12N 015-33E.\n"
            "Keep safe distance of 500 meters. Pass with caution."
        ),
        severity="Advisory"
    ),
    GMDSSAlert(
        alert_id="NAVTEX-ROM-115",
        station_name="Rome (Italy)",
        alert_type="SAR",
        message_text=(
            "TYRRHENIAN SEA. SEARCH AND RESCUE OPERATIONS.\n"
            "Vessel in distress reported near Naples coastal approach 40.80N, 14.10E.\n"
            "Sailing yacht 'AQUARIUS' taking on water. Helicopter SAR operations active.\n"
            "All vessels in vicinity keep sharp radio watch on VHF 16 and assist if able."
        ),
        severity="Critical"
    ),
    GMDSSAlert(
        alert_id="NAVTEX-ROM-116",
        station_name="Rome (Italy)",
        alert_type="Navigational",
        message_text=(
            "TYRRHENIAN SEA. SCIENTIFIC BUOY MOORED.\n"
            "Oceanographic measurement buoy moored in position 40-50N 014-12E.\n"
            "Vessels keep safe distance of 0.5 miles. Yellow flashing light."
        ),
        severity="Advisory"
    ),
    GMDSSAlert(
        alert_id="NAVTEX-PAL-090",
        station_name="Palma (Balearics)",
        alert_type="Navigational",
        message_text=(
            "MALLORCA. LIGHTHOUSE OUT OF SERVICE.\n"
            "Cabo Blanco Lighthouse (39-21N 002-47E) reported out of service temporarily.\n"
            "Exercise caution during night transits."
        ),
        severity="Advisory"
    )
]
 
# Path to the active GMDSS warnings JSON file
GMDSS_DATA_DIR = Path(__file__).resolve().parent / "mvp_data"
ACTIVE_GMDSS_WARNINGS_FILE = GMDSS_DATA_DIR / "active_gmdss_warnings.json"

# In-memory cache for active warnings
active_warnings_db = []


def load_warnings_from_file(filepath=None):
    """
    Load active GMDSS warnings from a JSON file.
    Falls back to MOCK_WARNINGS_DATABASE if the file does not exist or fails to parse.
    """
    global active_warnings_db
    if filepath is None:
        filepath = ACTIVE_GMDSS_WARNINGS_FILE

    filepath = Path(filepath)
    if filepath.exists():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            loaded = []
            for item in data:
                alert = GMDSSAlert(
                    alert_id=item["alert_id"],
                    station_name=item["station_name"],
                    alert_type=item["alert_type"],
                    message_text=item["message_text"],
                    severity=item.get("severity", "Warning"),
                    publish_time=item.get("publish_time"),
                )
                loaded.append(alert)
            active_warnings_db = loaded
            return active_warnings_db
        except Exception as error:
            print(f"Error loading GMDSS warnings from file {filepath}: {error}. Falling back to default mock data.", flush=True)

    # Fallback/Default mock data
    active_warnings_db = list(MOCK_WARNINGS_DATABASE)
    return active_warnings_db


def save_warnings_to_file(alerts, filepath=None):
    """
    Save GMDSS warnings to a JSON file.
    """
    if filepath is None:
        filepath = ACTIVE_GMDSS_WARNINGS_FILE

    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    serialized = []
    for alert in alerts:
        serialized.append({
            "alert_id": alert.alert_id,
            "station_name": alert.station_name,
            "alert_type": alert.alert_type,
            "message_text": alert.message_text,
            "severity": alert.severity,
            "publish_time": alert.publish_time,
            "coordinates": alert.coordinates,
        })

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(serialized, f, indent=2)
    print(f"Successfully saved {len(alerts)} GMDSS warnings to {filepath}", flush=True)


def get_active_warnings(filepath=None):
    """
    Get current in-memory active warnings, loading them from disk if not already cached.
    """
    global active_warnings_db
    if not active_warnings_db or filepath is not None:
        load_warnings_from_file(filepath)
    return active_warnings_db


def filter_alerts_by_position(vessel_lat, vessel_lon, max_distance_nm=60.0, filepath=None):
    """
    Filter active warnings that are within a specified distance of the vessel's current coordinate.
    """
    matched = []
    alerts = get_active_warnings(filepath)
    for alert in alerts:
        if alert.coordinates:
            dist = haversine_distance(vessel_lat, vessel_lon, alert.coordinates[0], alert.coordinates[1])
            if dist <= max_distance_nm:
                matched.append((alert, dist))
    # Sort by severity (Critical first) and then by distance
    severity_rank = {"Critical": 0, "Warning": 1, "Advisory": 2}
    matched.sort(key=lambda x: (severity_rank.get(x[0].severity, 99), x[1]))
    return matched


def filter_alerts_by_route(route_sample_points, max_distance_nm=60.0, filepath=None):
    """
    Filter warnings that are within a specified distance of any point along a route.
    """
    matched = []
    alerts = get_active_warnings(filepath)
    for alert in alerts:
        if alert.coordinates:
            min_dist = float("inf")
            for pt in route_sample_points:
                lat = pt.get("latitude") or pt.get("lat")
                lon = pt.get("longitude") or pt.get("lon")
                if lat is not None and lon is not None:
                    dist = haversine_distance(lat, lon, alert.coordinates[0], alert.coordinates[1])
                    if dist < min_dist:
                        min_dist = dist
            if min_dist <= max_distance_nm:
                matched.append((alert, min_dist))

    severity_rank = {"Critical": 0, "Warning": 1, "Advisory": 2}
    matched.sort(key=lambda x: (severity_rank.get(x[0].severity, 99), x[1]))
    return matched


def render_markdown_summary(filtered_alerts):
    """
    Render a beautiful, premium markdown report block for integration.
    """
    lines = []
    lines.append(GMDSS_DISCLAIMER)
    lines.append("")
    lines.append("## Geolocated GMDSS & NAVTEX Advisories")
    lines.append("")

    if not filtered_alerts:
        lines.append("✅ **No active localized alerts found within your transit corridor safety threshold.**")
        lines.append("All regional transmitters report normal operations.")
        return "\n".join(lines)

    lines.append("| ID / Station | Type | Severity | Proximity | Advisory Snippet |")
    lines.append("| :--- | :--- | :--- | :--- | :--- |")

    for alert, dist in filtered_alerts:
        severity_badge = f"🔴 {alert.severity.upper()}" if alert.severity == "Critical" else \
                         f"🟡 {alert.severity.upper()}" if alert.severity == "Warning" else \
                         f"🔵 {alert.severity.upper()}"

        snippet = alert.message_text.replace("\n", " ")
        if len(snippet) > 85:
            snippet = snippet[:82] + "..."

        lines.append(f"| **{alert.alert_id}**<br>_{alert.station_name}_ | {alert.alert_type} | {severity_badge} | **{dist:.1f} NM** | {snippet} |")

    lines.append("")
    lines.append("> [!NOTE]")
    lines.append("> The closest proximity calculations are based on the warning's reported geodesic coordinate anchor.")
    lines.append("> Standard safety guidelines dictate keeping a sharp lookout and monitoring VHF Channel 16.")

    return "\n".join(lines)


def demo_naples():
    """
    Demonstrate filtering for a vessel operating near Naples / Gulf of Ischia (40.80N, 14.15E).
    """
    vessel_lat = 40.80
    vessel_lon = 14.15
    print(f"--- SIMULATING VESSEL AT GULF OF NAPLES ({vessel_lat}N, {vessel_lon}E) ---")
    alerts = filter_alerts_by_position(vessel_lat, vessel_lon, max_distance_nm=45.0)
    summary = render_markdown_summary(alerts)
    print(summary)


if __name__ == "__main__":
    demo_naples()
