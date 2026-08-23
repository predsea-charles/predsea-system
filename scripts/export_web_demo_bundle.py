import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace


ROUTE_ARTIFACTS = (
    "daily_snapshot.json",
    "route_decision_map.png",
)


def latest_day_dir(input_root):
    root = Path(input_root)
    candidates = sorted(
        path for path in root.iterdir()
        if path.is_dir() and ((path / "run_manifest.json").exists() or (path / "latest_run.json").exists())
    )
    if not candidates:
        raise RuntimeError(f"No dated PredSea runs with run_manifest.json found under {root}.")
    return candidates[-1]


def resolve_run_dir(day_dir):
    day_dir = Path(day_dir)
    latest_path = day_dir / "latest_run.json"
    if latest_path.exists():
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        return day_dir / latest["path"]
    return day_dir


def load_manifest(run_dir):
    return json.loads((Path(run_dir) / "run_manifest.json").read_text(encoding="utf-8"))


def route_ids_from_manifest(manifest):
    routes = manifest.get("routes") or []
    if not routes:
        raise RuntimeError("Run manifest has no routes to export.")
    return routes


def copy_route_artifacts(day_dir, output_dir, route_id):
    source_dir = Path(day_dir) / route_id
    target_dir = Path(output_dir) / "routes" / route_id
    target_dir.mkdir(parents=True, exist_ok=True)

    for artifact in ROUTE_ARTIFACTS:
        src = source_dir / artifact
        if src.exists():
            shutil.copy2(src, target_dir / artifact)
        else:
            print(f"⚠️ Warning: Optional route artifact {artifact} missing in {source_dir}")
    return target_dir


def copy_featured_artifacts(output_dir, featured_route):
    route_dir = Path(output_dir) / "routes" / featured_route
    snapshot_src = route_dir / "daily_snapshot.json"
    if snapshot_src.exists():
        shutil.copy2(snapshot_src, Path(output_dir) / "latest.json")
    map_src = route_dir / "route_decision_map.png"
    if map_src.exists():
        shutil.copy2(map_src, Path(output_dir) / "latest_map.png")


def write_demo_manifest(output_dir, run_manifest, route_ids, featured_route):
    routes = [
        {
            "id": route_id,
            "snapshot": f"routes/{route_id}/daily_snapshot.json",
            "map": f"routes/{route_id}/route_decision_map.png",
        }
        for route_id in route_ids
    ]
    manifest = {
        "run_date": run_manifest.get("run_date"),
        "run_id": run_manifest.get("run_id"),
        "created_at_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "source_created_at_utc": run_manifest.get("created_at_utc"),
        "featured_route": featured_route,
        "routes": routes,
        "latest": {
            "snapshot": "latest.json",
            "map": "latest_map.png",
        },
    }
    (Path(output_dir) / "demo_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def export_web_demo_bundle(input_root, output_dir, run_date=None, featured_route="palma_ibiza"):
    input_root = Path(input_root)
    day_dir = input_root / run_date if run_date else latest_day_dir(input_root)
    if not day_dir.exists():
        raise RuntimeError(f"PredSea run directory does not exist: {day_dir}")

    run_dir = resolve_run_dir(day_dir)
    run_manifest = load_manifest(run_dir)
    route_ids = route_ids_from_manifest(run_manifest)
    if featured_route not in route_ids:
        featured_route = route_ids[0]

    output_dir = Path(output_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    for route_id in route_ids:
        copy_route_artifacts(run_dir, output_dir, route_id)
    copy_featured_artifacts(output_dir, featured_route)
    write_demo_manifest(output_dir, run_manifest, route_ids, featured_route)

    return SimpleNamespace(output_dir=output_dir, run_date=run_manifest.get("run_date"), routes=route_ids)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Export PredSea daily outputs as a stable web-demo bundle.")
    parser.add_argument("--input-root", default="outputs", help="Root containing dated PredSea Action outputs.")
    parser.add_argument("--output-dir", default="outputs/web-demo", help="Directory for web-ready demo files.")
    parser.add_argument("--date", dest="run_date", help="Specific run date, YYYY-MM-DD. Defaults to latest.")
    parser.add_argument("--featured-route", default="palma_ibiza", help="Route used for latest.* convenience files.")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    result = export_web_demo_bundle(
        input_root=args.input_root,
        output_dir=args.output_dir,
        run_date=args.run_date,
        featured_route=args.featured_route,
    )
    print(f"Wrote web demo bundle to {result.output_dir}")
    print(f"Run date: {result.run_date}")
    print(f"Routes: {', '.join(result.routes)}")


if __name__ == "__main__":
    main()
