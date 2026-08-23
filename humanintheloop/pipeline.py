"""Multi-tier ETL pipeline orchestrator.

Coordinates the full Phase 2 data pipeline:

1. Atmospheric ingestion (tiered: AROME -> HARMONIE -> ECMWF)
2. Oceanographic forecast download (Copernicus)
3. Grid blending (interpolate ocean onto atmospheric grid)
4. Observation ingestion (Puertos del Estado + Portus)
5. Route analysis with blended data
6. Evidence package generation with full lineage

This module wires together all the Phase 1 and Phase 2 components
into a single pipeline execution.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import ingest_atmosphere
import ingest_observations
import evidence_package
import source_lineage


def run_pipeline(
    route=None,
    vessel_class="medium",
    output_dir=None,
    dry_run=False,
    skip_atmosphere=False,
    skip_puertos=False,
):
    """Execute the full multi-tier ETL pipeline.

    Parameters
    ----------
    route : dict, optional
        Route configuration. Uses default route if not provided.
    vessel_class : str
        Vessel size class for recommendations.
    output_dir : str or Path, optional
        Output directory for artifacts.
    dry_run : bool
        If True, skip actual API calls.
    skip_atmosphere : bool
        If True, skip atmospheric ingestion.
    skip_puertos : bool
        If True, skip Puertos del Estado observations.

    Returns
    -------
    dict
        Pipeline result with snapshot, lineage, and artifact paths.
    """
    import route_analysis

    output_dir = Path(output_dir or "mvp_data")
    output_dir.mkdir(parents=True, exist_ok=True)
    route = route or route_analysis.load_route()

    pipeline_run_id = _generate_run_id()
    print(f"Pipeline run: {pipeline_run_id}", flush=True)

    # Step 1: Atmospheric ingestion
    atmo_result = _step_atmospheric(output_dir, dry_run, skip_atmosphere)

    # Step 2: Oceanographic forecast (Copernicus - existing)
    ocean_result = _step_ocean_forecast(output_dir, route, dry_run)

    # Step 3: Grid blending (if we have both atmospheric and ocean data)
    blend_result = _step_grid_blend(atmo_result, ocean_result, output_dir)

    # Step 4: Observation ingestion
    obs_result = _step_observations(dry_run, skip_puertos)

    # Step 4b: GMDSS warnings ingestion
    gmdss_result = _step_gmdss_warnings(output_dir, dry_run)

    # Step 5: Build route snapshot with lineage
    snapshot = _step_build_snapshot(
        route, vessel_class, ocean_result, obs_result, atmo_result, blend_result,
    )

    # Step 6: Write outputs
    route_output = output_dir / "routes" / route["id"]
    _write_pipeline_outputs(snapshot, route, route_output, pipeline_run_id)

    return {
        "run_id": pipeline_run_id,
        "route_id": route["id"],
        "output_dir": str(route_output),
        "snapshot": snapshot,
        "atmospheric": atmo_result,
        "ocean": ocean_result,
        "blend": blend_result,
        "observations": obs_result,
        "gmdss": gmdss_result,
    }


def _generate_run_id():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _step_atmospheric(output_dir, dry_run, skip):
    """Step 1: Run atmospheric tier selection."""
    if skip:
        print("Skipping atmospheric ingestion.", flush=True)
        return {
            "wind_result": {"available": False, "source": None},
            "wind_lineage": {
                "source": None,
                "resolution_km": None,
                "status": "skipped",
                "tier": None,
            },
        }

    print("Step 1: Atmospheric wind ingestion (tiered)...", flush=True)
    try:
        atmo_dir = Path(output_dir) / "atmosphere" if output_dir else None
        result = ingest_atmosphere.run_atmospheric_ingestion(
            output_dir=str(atmo_dir) if atmo_dir else None,
            dry_run=dry_run,
        )
        wind = result["wind_result"]
        if wind.get("available"):
            print(
                f"  Wind source: {wind['source']} "
                f"(Tier {wind.get('tier')}, {wind.get('resolution_km')} km)",
                flush=True,
            )
        else:
            print(
                f"  No atmospheric wind available. "
                f"Errors: {wind.get('errors', {})}",
                flush=True,
            )
        return result
    except Exception as error:
        print(f"  Atmospheric ingestion failed: {error}", flush=True)
        return {
            "wind_result": {"available": False, "source": None, "error": str(error)},
            "wind_lineage": {
                "source": None,
                "resolution_km": None,
                "status": "error",
                "tier": None,
            },
        }


def _step_ocean_forecast(output_dir, route, dry_run):
    """Step 2: Download Copernicus ocean forecast."""
    print("Step 2: Copernicus ocean forecast...", flush=True)
    try:
        import fetch_data
        import route_analysis

        if not dry_run:
            forecast_files = fetch_data.get_balearic_forecast(dry_run=False) or {}
        else:
            forecast_files = {
                "waves_path": Path(fetch_data.OUTPUT_DIR) / "balearic_waves.nc",
                "currents_path": Path(fetch_data.OUTPUT_DIR) / "balearic_currents.nc",
            }

        waves_path = Path(forecast_files["waves_path"])
        currents_path = Path(forecast_files["currents_path"])

        forecast = route_analysis.forecast_summary_from_files(
            waves_path, currents_path, route=route,
        )
        print("  Copernicus forecast loaded.", flush=True)
        return {
            "available": True,
            "forecast": forecast,
            "waves_path": str(waves_path),
            "currents_path": str(currents_path),
            "lineage": {
                "source": "copernicus_med",
                "resolution_km": 4.0,
                "status": "active",
            },
        }
    except Exception as error:
        print(f"  Ocean forecast failed: {error}", flush=True)
        return {
            "available": False,
            "forecast": {},
            "error": str(error),
            "lineage": {
                "source": "copernicus_med",
                "resolution_km": 4.0,
                "status": "error",
            },
        }


def _step_grid_blend(atmo_result, ocean_result, output_dir):
    """Step 3: Blend atmospheric and ocean grids."""
    wind_result = atmo_result.get("wind_result", {})
    wind_lineage = atmo_result.get("wind_lineage", {})
    ocean_lineage = ocean_result.get("lineage", {})

    if not wind_result.get("available") or not wind_result.get("dataset_path"):
        print("Step 3: Grid blending skipped (no atmospheric data).", flush=True)
        return {
            "blended": False,
            "reason": "no atmospheric wind dataset available",
        }

    if not ocean_result.get("available") or not ocean_result.get("waves_path"):
        print("Step 3: Grid blending skipped (no ocean data).", flush=True)
        return {
            "blended": False,
            "reason": "no ocean forecast dataset available",
        }

    print("Step 3: Grid blending (atmosphere + ocean)...", flush=True)
    try:
        import xarray as xr
        import grid_blender
        import wind_loader

        wind_ds = wind_loader.load_wind_dataset(
            wind_result["dataset_path"],
            provider_id=wind_result.get("source"),
        )
        ocean_ds = xr.open_dataset(ocean_result["waves_path"])

        blended_ds, lineage = grid_blender.blend_wind_and_ocean(
            wind_ds, ocean_ds, wind_lineage, ocean_lineage,
        )

        blend_path = output_dir / "atmosphere" / "blended.nc"
        blend_path.parent.mkdir(parents=True, exist_ok=True)
        blended_ds.to_netcdf(str(blend_path))

        print(f"  Blended dataset saved to {blend_path}", flush=True)
        ocean_ds.close()
        wind_ds.close()

        return {
            "blended": True,
            "path": str(blend_path),
            "lineage": lineage,
        }
    except Exception as error:
        print(f"  Grid blending failed: {error}", flush=True)
        return {
            "blended": False,
            "reason": str(error),
        }


def _step_observations(dry_run, skip_puertos):
    """Step 4: Fetch observations from all sources."""
    print("Step 4: Observation ingestion...", flush=True)
    try:
        result = ingest_observations.fetch_all_observations(
            include_puertos=not skip_puertos,
            include_portus=True,
            dry_run=dry_run,
        )
        obs_count = len(result.get("observations", {}))
        print(f"  Observations: {obs_count} stations.", flush=True)
        return result
    except Exception as error:
        print(f"  Observation ingestion failed: {error}", flush=True)
        return {
            "observations": {},
            "ground_truth_lineage": {
                "source": None,
                "status": "error",
            },
            "errors": {"all": str(error)},
        }


def _step_gmdss_warnings(output_dir, dry_run=False):
    """Step 4b: GMDSS warnings ingestion."""
    print("Step 4b: GMDSS warnings ingestion...", flush=True)
    try:
        import gmdss_aggregator
        alerts = gmdss_aggregator.MOCK_WARNINGS_DATABASE
        gmdss_file = Path(output_dir) / "active_gmdss_warnings.json"
        gmdss_aggregator.save_warnings_to_file(alerts, filepath=gmdss_file)
        return {"available": True, "path": str(gmdss_file), "count": len(alerts)}
    except Exception as error:
        print(f"  GMDSS warnings ingestion failed: {error}", flush=True)
        return {"available": False, "error": str(error)}


def _step_build_snapshot(route, vessel_class, ocean_result, obs_result, atmo_result, blend_result):
    """Step 5: Build the route snapshot with full data lineage."""
    import route_analysis

    observations = obs_result.get("observations", {})
    forecast = ocean_result.get("forecast", {})

    snapshot = route_analysis.build_route_snapshot(
        observations, forecast, route=route, vessel_class=vessel_class,
    )

    # Attach data lineage
    wind_lineage = atmo_result.get("wind_lineage", {
        "source": None,
        "resolution_km": None,
        "status": "not_configured",
    })
    ocean_lineage = ocean_result.get("lineage", {
        "source": "copernicus_med",
        "resolution_km": 4.0,
        "status": "active",
    })
    ground_truth = obs_result.get("ground_truth_lineage", {
        "source": None,
        "status": "unavailable",
    })
    portus_result = obs_result.get("portus")

    # If blending happened, update ocean lineage
    if blend_result.get("blended") and blend_result.get("lineage"):
        blend_lineage = blend_result["lineage"]
        ocean_lineage = blend_lineage.get("ocean_forecast", ocean_lineage)
        wind_lineage_status = "blended" if wind_lineage.get("source") else wind_lineage.get("status")
        wind_lineage = {**wind_lineage, "status": wind_lineage_status}

    snapshot["data_lineage"] = {
        "wind_forecast": wind_lineage,
        "ocean_forecast": ocean_lineage,
        "ground_truth_validation": ground_truth,
    }
    if portus_result:
        snapshot["data_lineage"]["portus_observations"] = portus_result.get(
            "observations_lineage",
            {"source": None, "status": "unavailable"},
        )
        snapshot["data_lineage"]["portus_predictions"] = portus_result.get(
            "predictions_lineage",
            {"source": None, "status": "unavailable"},
        )
        snapshot["portus"] = portus_result

    source_inventory = []
    if ocean_result.get("lineage"):
        source_inventory.append(
            {
                "id": ocean_result["lineage"].get("source"),
                "label": ocean_result["lineage"].get("source"),
                "available": ocean_result.get("available", False),
                "source_family": "ocean_forecast",
            }
        )
    if atmo_result.get("wind_result", {}).get("source"):
        source_inventory.append(
            {
                "id": atmo_result["wind_result"].get("source"),
                "label": atmo_result["wind_result"].get("label") or atmo_result["wind_result"].get("source"),
                "available": atmo_result["wind_result"].get("available", False),
                "source_family": "atmosphere",
            }
        )
    if portus_result:
        source_inventory.append(
            {
                "id": "puertos_portus",
                "label": "Portus",
                "available": bool(portus_result.get("observations")),
                "source_family": "observation",
            }
        )
    snapshot["source_summary"] = source_lineage.summarize_sources(
        snapshot=snapshot,
        observations=observations,
        source_inventory=source_inventory,
        data_lineage=snapshot.get("data_lineage"),
    )
    snapshot["data_lineage"]["source_summary"] = snapshot["source_summary"]
    snapshot["data_lineage"]["source_inventory"] = source_inventory

    return snapshot


def _write_pipeline_outputs(snapshot, route, output_dir, run_id):
    """Step 6: Write all pipeline artifacts."""
    import briefing as briefing_module

    print(f"Step 6: Writing outputs to {output_dir}...", flush=True)
    briefing_module.write_outputs(snapshot, output_dir=output_dir, route=route)

    # Write pipeline manifest
    manifest = {
        "run_id": run_id,
        "route_id": route["id"],
        "route_name": route["name"],
        "data_lineage": snapshot.get("data_lineage", {}),
        "created_at_utc": snapshot.get("created_at_utc"),
    }
    manifest_path = output_dir / "pipeline_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"  Pipeline complete: {run_id}", flush=True)
