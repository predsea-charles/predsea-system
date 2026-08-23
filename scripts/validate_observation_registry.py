#!/usr/bin/env python3
"""Validate the extensible observation-source registry without network access."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
for import_root in (PROJECT_ROOT, PROJECT_ROOT / "humanintheloop"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))


def _connector_exists(connector: str) -> bool:
    try:
        return importlib.util.find_spec(connector) is not None
    except (ImportError, ModuleNotFoundError, AttributeError):
        return False


def validate_registry(path: Path, environment: str | None = None) -> dict:
    registry = json.loads(path.read_text())
    errors: list[str] = []
    if registry.get("schema_version") != "predsea.observation_registry.v1":
        errors.append("unsupported schema_version")

    source_ids: set[str] = set()
    active_sources = 0
    for index, source in enumerate(registry.get("sources") or []):
        prefix = f"sources[{index}]"
        required = (
            "source_id",
            "provider",
            "connector",
            "discovery_mode",
            "enabled_environments",
            "variables",
        )
        for field in required:
            if not source.get(field):
                errors.append(f"{prefix} missing {field}")
        source_id = source.get("source_id")
        if source_id in source_ids:
            errors.append(f"duplicate source_id {source_id}")
        source_ids.add(source_id)
        if not set(source.get("enabled_environments") or []) <= {"test", "prod"}:
            errors.append(f"{prefix} has an invalid environment")
        if len(source.get("variables") or []) != len(set(source.get("variables") or [])):
            errors.append(f"{prefix} has duplicate variables")
        connector = source.get("connector")
        if connector and not _connector_exists(connector):
            errors.append(f"{prefix} connector is not importable: {connector}")
        if environment is None or environment in (source.get("enabled_environments") or []):
            active_sources += 1

    if not source_ids:
        errors.append("registry has no sources")
    if environment and active_sources == 0:
        errors.append(f"registry has no sources enabled for {environment}")
    return {
        "schema_version": "predsea.observation_registry_validation.v1",
        "status": "succeeded" if not errors else "failed",
        "registry": str(path),
        "source_count": len(source_ids),
        "active_source_count": active_sources,
        "environment": environment,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("registry", type=Path)
    parser.add_argument("--environment", choices=("test", "prod"))
    args = parser.parse_args()
    report = validate_registry(args.registry, args.environment)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
