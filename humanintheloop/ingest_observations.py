"""Multi-source observation ingestion orchestrator.

Builds the canonical ground-truth observation layer from Puertos del Estado,
EMODnet Physics, and optional Portus observations. SOCIB is intentionally
excluded from the active ETL path so observation ingestion remains resilient.
"""

import os

import fetch_emodnet
import fetch_portus
import socib_public
import validation_archive
import fetch_copernicus_insitu


def fetch_all_observations(include_puertos=True, include_emodnet=True, include_portus=False, include_socib=True, include_copernicus=True, dry_run=False):
    """Fetch observations from all configured sources.

    Returns a merged dict of observations and a lineage record
    documenting which sources contributed.
    """
    all_observations = {}
    lineage_sources = []
    errors = {}
    station_metadata_candidates = []

    # Puertos del Estado observations (Phase 2 addition)
    if include_puertos and _puertos_enabled():
        try:
            import fetch_puertos_estado
            puertos_result = fetch_puertos_estado.fetch_balearic_observations(dry_run=dry_run)
            puertos_obs = puertos_result.get("observations", {})
            # Prefix Puertos stations to avoid key collisions across sources
            for key, value in puertos_obs.items():
                prefixed_key = f"puertos_{key}"
                all_observations[prefixed_key] = value
            if puertos_obs:
                lineage_sources.append("puertos_del_estado")
            station_metadata_candidates.extend(puertos_result.get("catalog_stations") or [])
            if puertos_result.get("errors"):
                errors["puertos_del_estado"] = puertos_result["errors"]
        except Exception as error:
            errors["puertos_del_estado"] = str(error)

    # EMODnet Physics observations
    if include_emodnet and _emodnet_enabled():
        try:
            emodnet_result = fetch_emodnet.fetch_emodnet_bundle(dry_run=dry_run)
            emodnet_obs = emodnet_result.get("observations", {})
            for key, value in emodnet_obs.items():
                prefixed_key = key if key.startswith("emodnet_") else f"emodnet_{key}"
                all_observations[prefixed_key] = value
            if emodnet_obs:
                lineage_sources.append("emodnet_physics")
            station_metadata_candidates.extend(emodnet_result.get("stations") or [])
            if emodnet_result.get("errors"):
                errors["emodnet_physics"] = emodnet_result["errors"]
        except Exception as error:
            errors["emodnet_physics"] = str(error)

    # Portus JSON observations and prediction/model metadata
    if include_portus and _portus_enabled():
        try:
            portus_result = fetch_portus.fetch_portus_bundle(dry_run=dry_run)
            portus_obs = portus_result.get("observations", {})
            for key, value in portus_obs.items():
                prefixed_key = key if key.startswith("portus_") else f"portus_{key}"
                all_observations[prefixed_key] = value
            if portus_obs:
                lineage_sources.append("puertos_portus")
            station_metadata_candidates.extend(portus_result.get("stations") or [])
            if portus_result.get("errors"):
                errors["puertos_portus"] = portus_result["errors"]
        except Exception as error:
            errors["puertos_portus"] = str(error)

    # SOCIB public observations (restored Balearic buoy live observations)
    if include_socib and _socib_enabled():
        try:
            socib_obs = socib_public.fetch_public_observations()
            # Merge directly without prefixing, as expected downstream
            for key, value in socib_obs.items():
                all_observations[key] = value
            if socib_obs:
                lineage_sources.append("socib_public")
        except Exception as error:
            errors["socib_public"] = str(error)

    # Copernicus Marine In-Situ observations (France & Italy coverage)
    if include_copernicus and _copernicus_enabled():
        try:
            copernicus_result = fetch_copernicus_insitu.fetch_copernicus_insitu_bundle(dry_run=dry_run)
            copernicus_obs = copernicus_result.get("observations", {})
            for key, value in copernicus_obs.items():
                all_observations[key] = value
            if copernicus_obs:
                lineage_sources.append("copernicus_insitu")
            station_metadata_candidates.extend(copernicus_result.get("stations") or [])
            if copernicus_result.get("errors"):
                errors["copernicus_insitu"] = copernicus_result["errors"]
        except Exception as error:
            errors["copernicus_insitu"] = str(error)

    station_metadata = validation_archive.build_station_metadata_rows(
        all_observations,
        station_metadata=station_metadata_candidates,
    )

    ground_truth_lineage = _build_ground_truth_lineage(
        all_observations, lineage_sources, errors,
    )

    result = {
        "observations": all_observations,
        "station_metadata": station_metadata,
        "ground_truth_lineage": ground_truth_lineage,
        "errors": errors,
    }
    if include_portus and _portus_enabled():
        result["portus"] = portus_result if "portus_result" in locals() else {
            "observations": {},
            "predictions": {},
            "errors": errors.get("puertos_portus", {}),
        }
    return result


def _puertos_enabled():
    """Check if Puertos del Estado ingestion is enabled."""
    return os.environ.get("PREDSEA_ENABLE_PUERTOS_OBSERVATIONS", "1") == "1"


def _portus_enabled():
    """Check if Portus ingestion is enabled."""
    return os.environ.get("PREDSEA_ENABLE_PORTUS_OBSERVATIONS", "1") == "1"


def _emodnet_enabled():
    """Check if EMODnet Physics ingestion is enabled."""
    return os.environ.get("PREDSEA_ENABLE_EMODNET_OBSERVATIONS", "1") == "1"


def _socib_enabled():
    """Check if SOCIB public ingestion is enabled."""
    return os.environ.get("PREDSEA_ENABLE_SOCIB_OBSERVATIONS", "1") == "1"


def _copernicus_enabled():
    """Check if Copernicus Marine In-Situ ingestion is enabled."""
    return os.environ.get("PREDSEA_ENABLE_COPERNICUS_OBSERVATIONS", "1") == "1"


def _build_ground_truth_lineage(observations, sources, errors):
    """Build a ground-truth validation lineage record."""
    if not observations:
        return {
            "source": None,
            "status": "unavailable",
            "providers": [],
        }

    # Determine primary source based on availability
    emodnet_present = "emodnet_physics" in sources
    portus_present = "puertos_portus" in sources
    puertos_present = "puertos_del_estado" in sources
    socib_present = "socib_public" in sources
    copernicus_present = "copernicus_insitu" in sources
    present_sources = []
    if puertos_present:
        present_sources.append("puertos_del_estado")
    if emodnet_present:
        present_sources.append("emodnet_physics")
    if portus_present:
        present_sources.append("puertos_portus")
    if socib_present:
        present_sources.append("socib_public")
    if copernicus_present:
        present_sources.append("copernicus_insitu")

    if present_sources:
        source = "_and_".join(present_sources)
        status = "matched_successfully"
    else:
        source = "puertos_observations"
        status = "matched_successfully"

    return {
        "source": source,
        "status": status,
        "providers": present_sources or sources,
        "station_count": len(observations),
    }
