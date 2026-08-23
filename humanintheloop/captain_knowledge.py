import json
from pathlib import Path


KNOWLEDGE_DIR = Path(__file__).with_name("captain_knowledge")


def load_json_compatible_file(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_knowledge(base_dir=KNOWLEDGE_DIR):
    base_dir = Path(base_dir)
    return {
        "rules": load_json_compatible_file(base_dir / "graham_rules.yaml"),
        "cases": load_json_compatible_file(base_dir / "graham_cases.json"),
        "vessel_thresholds": load_json_compatible_file(base_dir / "vessel_thresholds.yaml"),
        "route_exposure_notes": load_json_compatible_file(base_dir / "route_exposure_notes.yaml"),
    }


def route_exposure_note(route_id, knowledge=None):
    knowledge = knowledge or load_knowledge()
    return (knowledge.get("route_exposure_notes") or {}).get(route_id)


def match_rules(snapshot, question_intent=None, knowledge=None):
    knowledge = knowledge or load_knowledge()
    return [
        rule
        for rule in knowledge.get("rules", [])
        if rule_matches(rule.get("condition") or {}, snapshot, question_intent)
    ]


def rule_matches(condition, snapshot, question_intent=None):
    forecast = snapshot.get("forecast") or {}
    route_id = snapshot.get("route_id")
    vessel_class = snapshot.get("vessel_class")

    route_ids = condition.get("route_ids")
    if route_ids and route_id not in route_ids:
        return False

    vessel_classes = condition.get("vessel_classes")
    if vessel_classes and vessel_class not in vessel_classes:
        return False

    question_intents = condition.get("question_intents")
    if question_intents and question_intent not in question_intents:
        return False

    min_wave = condition.get("min_wave_m")
    if min_wave is not None and comparable_wave_height(forecast) < float(min_wave):
        return False

    sea_states = condition.get("sea_state_in")
    if sea_states and not sea_state_matches(forecast, sea_states):
        return False

    sector = condition.get("direction_sector")
    if sector and not direction_sector_matches(forecast, sector):
        return False

    horizon_gt = condition.get("forecast_horizon_hours_gt")
    if horizon_gt is not None:
        horizon = forecast.get("forecast_horizon_hours")
        if horizon is None or float(horizon) <= float(horizon_gt):
            return False

    if condition.get("near_peak") and not is_peak_relevant(forecast):
        return False

    return True


def comparable_wave_height(forecast):
    candidates = [
        forecast.get("wave_max_m"),
        forecast.get("swell_1_height_m"),
        ((forecast.get("route_segments") or {}).get("worst_segment") or {}).get("max_wave_m"),
    ]
    valid = [float(value) for value in candidates if isinstance(value, (int, float))]
    return max(valid) if valid else 0.0


def sea_state_matches(forecast, expected_labels):
    labels = {str(label).lower() for label in expected_labels}
    candidates = [forecast.get("wave_peak_sea_state")]
    worst_segment = ((forecast.get("route_segments") or {}).get("worst_segment") or {})
    candidates.append(worst_segment.get("sea_state"))
    for row in forecast.get("hourly") or []:
        candidates.append(row.get("wave_sea_state"))
    return any(str(candidate).lower() in labels for candidate in candidates if candidate)


def direction_sector_matches(forecast, sector):
    directions = [
        forecast.get("swell_1_direction_deg"),
        forecast.get("wave_peak_direction_deg"),
    ]
    for row in forecast.get("hourly") or []:
        directions.append(row.get("swell_1_direction_deg"))
        directions.append(row.get("wave_direction_deg"))
    return any(direction_in_sector(direction, sector) for direction in directions if direction is not None)


def direction_in_sector(direction, sector):
    direction = float(direction) % 360.0
    sector = sector.upper()
    ranges = {
        "N": ((337.5, 360.0), (0.0, 22.5)),
        "NE": ((22.5, 67.5),),
        "E": ((67.5, 112.5),),
        "SE": ((112.5, 157.5),),
        "S": ((157.5, 202.5),),
        "SW": ((202.5, 247.5),),
        "W": ((247.5, 292.5),),
        "NW": ((292.5, 337.5),),
    }
    return any(start <= direction < end for start, end in ranges.get(sector, ()))


def is_peak_relevant(forecast):
    return forecast.get("wave_peak_time") not in (None, "N/A") and forecast.get("wave_max_m") is not None


def summarize_matches(matches, limit=2):
    summaries = []
    for rule in matches[:limit]:
        summaries.append(
            {
                "id": rule.get("id"),
                "consequence": rule.get("operational_consequence"),
                "preferred_action": rule.get("preferred_action"),
                "confidence": rule.get("confidence"),
            }
        )
    return summaries
