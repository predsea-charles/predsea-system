import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "export_web_demo_bundle.py"


def load_exporter():
    spec = importlib.util.spec_from_file_location("export_web_demo_bundle", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_route(day_dir, route_id, route_name):
    route_dir = day_dir / route_id
    route_dir.mkdir(parents=True)
    (route_dir / "daily_snapshot.json").write_text(
        json.dumps({"route": route_name, "forecast": {"wave_max_m": 1.4}}),
        encoding="utf-8",
    )
    (route_dir / "route_decision_map.png").write_bytes(b"map")


def test_export_web_demo_bundle_uses_latest_manifest_and_featured_route(tmp_path):
    exporter = load_exporter()
    output_root = tmp_path / "outputs"
    older_day = output_root / "2026-05-10"
    latest_day = output_root / "2026-05-11"
    older_day.mkdir(parents=True)
    latest_day.mkdir()
    write_route(older_day, "palma_cabrera", "Palma -> Cabrera")
    write_route(latest_day, "palma_ibiza", "Palma -> Ibiza")
    write_route(latest_day, "ibiza_formentera", "Ibiza -> Formentera")
    (older_day / "run_manifest.json").write_text(
        json.dumps({"run_date": "2026-05-10", "routes": ["palma_cabrera"]}),
        encoding="utf-8",
    )
    (latest_day / "run_manifest.json").write_text(
        json.dumps({"run_date": "2026-05-11", "routes": ["palma_ibiza", "ibiza_formentera"]}),
        encoding="utf-8",
    )

    result = exporter.export_web_demo_bundle(
        input_root=output_root,
        output_dir=tmp_path / "web-demo",
        featured_route="palma_ibiza",
    )

    manifest = json.loads((tmp_path / "web-demo" / "demo_manifest.json").read_text())
    latest = json.loads((tmp_path / "web-demo" / "latest.json").read_text())
    assert result.run_date == "2026-05-11"
    assert manifest["run_date"] == "2026-05-11"
    assert manifest["featured_route"] == "palma_ibiza"
    assert [route["id"] for route in manifest["routes"]] == ["palma_ibiza", "ibiza_formentera"]
    assert latest["route"] == "Palma -> Ibiza"
    assert (tmp_path / "web-demo" / "latest_map.png").read_bytes() == b"map"
    assert (tmp_path / "web-demo" / "routes" / "ibiza_formentera" / "daily_snapshot.json").exists()
