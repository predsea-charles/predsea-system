from __future__ import annotations

from collections import OrderedDict


SOURCE_LABEL_OVERRIDES = {
    "copernicus": "Copernicus",
    "copernicus_med": "Copernicus",
    "copernicus_mediterranean": "Copernicus",
    "ecmwf": "ECMWF",
    "ecmwf_open_data": "ECMWF",
    "meteo_france_arome": "Meteo-France AROME",
    "aemet_harmonie_arome": "AEMET HARMONIE-AROME",
    "puertos_del_estado": "Puertos del Estado",
    "puertos_observations": "Puertos del Estado",
    "puertos_portus": "Portus",
    "puertos_portus_predictions": "Portus predictions",
    "emodnet": "EMODnet Physics",
    "emodnet_physics": "EMODnet Physics",
    "socib": "SOCIB",
    "socib_wmop_sapo": "SOCIB",
    "redmar": "REDMAR",
    "redcos": "REDCOS",
    "redext": "REDEXT",
}


def summarize_sources(snapshot=None, observations=None, source_inventory=None, data_lineage=None, limit=3):
    entries = []

    if snapshot and snapshot.get("source_summary"):
        existing = normalize_source_summary(snapshot["source_summary"], limit=limit)
        if existing.get("sources"):
            return existing

    if source_inventory is None and snapshot:
        source_inventory = snapshot.get("source_inventory")
        if source_inventory is None:
            lineage = snapshot.get("data_lineage") or {}
            source_inventory = lineage.get("source_inventory")
            if data_lineage is None:
                data_lineage = lineage

    _collect_from_source_inventory(entries, source_inventory)
    _collect_from_snapshot(entries, snapshot, observations, data_lineage)
    summary = _summarize_entries(entries, limit=limit)
    return summary


def normalize_source_summary(summary, limit=3):
    if not isinstance(summary, dict):
        return {"primary_source": None, "sources": [], "count": 0, "families": [], "text": None}
    sources = summary.get("sources") or []
    if not isinstance(sources, list):
        sources = [sources]
    normalized_sources = []
    seen = set()
    for source in sources:
        label = normalize_source_label(source)
        if not label:
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized_sources.append(label)
    families = summary.get("families") or []
    if not isinstance(families, list):
        families = [families]
    normalized_families = []
    seen_families = set()
    for family in families:
        if not family:
            continue
        key = str(family).strip().lower()
        if key in seen_families:
            continue
        seen_families.add(key)
        normalized_families.append(key)
    count = int(summary.get("count") or len(normalized_sources))
    text = summary.get("text") or source_text(normalized_sources, limit=limit)
    return {
        "primary_source": normalized_sources[0] if normalized_sources else summary.get("primary_source"),
        "sources": normalized_sources[:limit],
        "count": count,
        "families": normalized_families,
        "text": text,
    }


def source_text(sources, limit=3):
    if not sources:
        return None
    short = sources[:limit]
    if len(sources) > limit:
        return f"Sources used: {', '.join(short)} (+{len(sources) - limit} more)"
    return f"Sources used: {', '.join(short)}"


def source_breadth_score(summary):
    summary = normalize_source_summary(summary)
    source_count = summary.get("count") or 0
    families = [family for family in summary.get("families") or [] if family and family != "unknown"]
    family_count = len(set(families))
    if source_count >= 3 and family_count >= 2:
        return "High"
    if source_count >= 2:
        return "Medium"
    return "Low"


def normalize_source_label(value):
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("label", "name", "source_label", "source", "id"):
            nested = value.get(key)
            if nested:
                return normalize_source_label(nested)
        return None
    text = str(value).strip()
    if not text:
        return None
    lower = text.lower()
    if lower in SOURCE_LABEL_OVERRIDES:
        return SOURCE_LABEL_OVERRIDES[lower]
    if lower.startswith("copernicus"):
        return "Copernicus"
    if lower.startswith("ecmwf"):
        return "ECMWF"
    if lower.startswith("meteo_france"):
        return "Meteo-France AROME"
    if lower.startswith("aemet"):
        return "AEMET HARMONIE-AROME"
    if lower.startswith("puertos"):
        return "Puertos del Estado"
    if lower.startswith("portus"):
        return "Portus"
    if lower.startswith("emodnet"):
        return "EMODnet Physics"
    if lower.startswith("socib"):
        return "SOCIB"
    if lower.startswith("redmar"):
        return "REDMAR"
    if lower.startswith("redcos"):
        return "REDCOS"
    if lower.startswith("redext"):
        return "REDEXT"
    return text.replace("_", " ").replace("-", " ").title()


def _collect_from_source_inventory(entries, source_inventory):
    for entry in source_inventory or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("available") is False:
            continue
        label = normalize_source_label(entry.get("label") or entry.get("id") or entry.get("source_label"))
        if label:
            entries.append({"label": label, "family": normalize_source_family(entry.get("source_family"), label)})


def _collect_from_snapshot(entries, snapshot, observations, data_lineage):
    if not isinstance(snapshot, dict):
        snapshot = {}
    data_lineage = data_lineage or snapshot.get("data_lineage") or {}

    forecast_source = snapshot.get("forecast_source") or {}
    _append_entry(entries, forecast_source.get("label") or forecast_source.get("id"), family="ocean_forecast")

    _append_lineage_entry(entries, data_lineage.get("wind_forecast"), family="atmosphere")
    _append_lineage_entry(entries, data_lineage.get("ocean_forecast"), family="ocean_forecast")
    _append_lineage_entry(entries, data_lineage.get("ground_truth_validation"), family="observation")
    _append_lineage_entry(entries, data_lineage.get("portus_observations"), family="observation")
    _append_lineage_entry(entries, data_lineage.get("portus_predictions"), family="ocean_forecast")

    if isinstance(observations, dict):
        for record in observations.values():
            if not isinstance(record, dict):
                continue
            if record.get("last_sample_utc") is None and record.get("observed_at_utc") is None:
                continue
            _append_entry(
                entries,
                record.get("source_label")
                or record.get("network")
                or record.get("source_system")
                or record.get("source"),
                family="observation",
            )
            observation = record.get("observation")
            if isinstance(observation, dict):
                _append_entry(
                    entries,
                    observation.get("source_label")
                    or observation.get("network")
                    or observation.get("source_system")
                    or observation.get("source"),
                    family="observation",
                )


def _append_lineage_entry(entries, lineage_entry, family):
    if not isinstance(lineage_entry, dict):
        return
    if lineage_entry.get("source") is None:
        return
    _append_entry(entries, lineage_entry.get("source"), family=family)


def _append_entry(entries, value, family=None):
    label = normalize_source_label(value)
    if not label:
        return
    entries.append({"label": label, "family": normalize_source_family(family, label)})


def normalize_source_family(source_family, label=None):
    if source_family:
        text = str(source_family).strip().lower()
        if text in {"atmosphere", "ocean_forecast", "observation", "forecast"}:
            return text
    normalized_label = (label or "").lower()
    if any(token in normalized_label for token in ("meteo-france", "aemet", "ecmwf", "arome", "harmonie")):
        return "atmosphere"
    if any(token in normalized_label for token in ("copernicus", "forecast")):
        return "ocean_forecast"
    if any(token in normalized_label for token in ("puertos", "portus", "emodnet", "socib", "redmar", "redcos", "redext")):
        return "observation"
    return "unknown"


def _summarize_entries(entries, limit=3):
    if not entries:
        return {"primary_source": None, "sources": [], "count": 0, "families": [], "text": None}

    ordered = OrderedDict()
    families = OrderedDict()
    for entry in entries:
        label = entry.get("label")
        if not label:
            continue
        key = label.lower()
        if key not in ordered:
            ordered[key] = label
        family = entry.get("family")
        if family and family != "unknown":
            families[family] = True

    sources = list(ordered.values())
    summary = {
        "primary_source": sources[0] if sources else None,
        "sources": sources[:limit],
        "count": len(sources),
        "families": list(families.keys()),
        "text": source_text(sources, limit=limit),
    }
    return summary
