import copy
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import captain_knowledge
import forecast_sanity
import observation_alignment
import recommendation_state
import source_lineage


def classify_question(question):
    text = question.lower()
    if any(word in text for word in ["fuel", "another route", "alternative route", "save"]):
        return "fuel_efficiency"
    if any(word in text for word in ["safe to stay", "stay here", "anchorage", "move"]):
        return "location_safety"
    if any(word in text for word in ["best time", "leave", "depart", "calm window", "set off"]):
        return "leave_window"
    if any(word in text for word in ["in 4 hours", "later", "this afternoon", "how will"]):
        return "conditions_soon"
    if any(word in text for word in ["cross", "tonight", "tomorrow"]):
        return "route_timing"
    return "general_decision"


LOCAL_TIMEZONE = ZoneInfo("Europe/Madrid")


def answer_question(question, snapshot, location_label="shared location", current_time=None, current_date=None):
    intent = classify_question(question)
    requested_time = extract_requested_time(question)
    rec = snapshot.get("recommendation", {})
    timing_context = classify_timing_context(question)
    forecast = forecast_for_question_context(
        snapshot.get("forecast", {}),
        question,
        timing_context=timing_context,
        current_date=current_date,
    )
    alignment = observation_alignment.compute_observation_alignment(snapshot)
    sanity = forecast_sanity.forecast_sanity(forecast)
    best_window = rec.get("best_window", "check manually")
    watch_out = rec.get("watch_out", "conditions require manual review")
    confidence = rec.get("confidence")
    vessel_advice = rec.get("vessel_advice")
    wave_max = forecast.get("wave_max_m", "N/A")
    wave_peak = forecast.get("wave_peak_time", "N/A")
    morning_window_passed = is_morning_window_passed(best_window, current_time)
    requested_time_summary = summarize_requested_time(requested_time, forecast)

    if requested_time_summary:
        recommendation = requested_time_summary["recommendation"]
        reason = requested_time_summary["reason"]
    elif intent == "location_safety":
        recommendation = "stay only if you are sheltered; move earlier if exposed"
        reason = f"near {location_label}, the main watch-out is: {watch_out}"
    elif intent == "fuel_efficiency":
        if morning_window_passed:
            recommendation = "do not optimize around the morning window now; reassess against the afternoon peak"
        else:
            recommendation = f"use the direct route during the {best_window} window; reassess if leaving later"
        reason = f"after the best window, waves/current can increase fuel burn and comfort risk. Current forecast peak: {wave_max} m around {wave_peak}"
    elif intent == "leave_window":
        route_window = summarize_best_departure_window(
            forecast,
            current_time=current_time,
            vessel_profile=snapshot.get("vessel_profile"),
        )
        if timing_context == "tomorrow":
            route_timing = summarize_route_timing(
                timing_context,
                forecast,
                best_window,
                watch_out,
                vessel_profile=snapshot.get("vessel_profile"),
            )
            recommendation = route_timing["recommendation"]
            reason = route_timing["reason"]
        elif route_window and not is_late_day(current_time) and not morning_window_passed:
            recommendation = route_window["recommendation"]
            reason = route_window["reason"]
        elif is_late_day(current_time):
            recommendation = "today's practical daylight window has passed; use this as tomorrow morning planning guidance"
            reason = f"latest route signal is: {watch_out}. Recheck the morning run and buoy observations before committing"
        elif morning_window_passed:
            if "before midday" in best_window:
                recommendation = "the calmer morning window has passed; avoid timing your departure near the forecast peak"
            else:
                recommendation = f"the morning part of that window has passed; avoid the {wave_peak} peak and reassess after it"
            reason = f"the previous best window was {best_window}, and the main remaining watch-out is: {watch_out}"
        else:
            recommendation = f"leave {best_window}"
            reason = watch_out
    elif intent == "conditions_soon":
        if is_manageable_peak(forecast, snapshot.get("vessel_profile", {})):
            recommendation = "conditions look workable; no narrow weather window flagged"
            reason = f"forecast wave peak is only near {wave_max} m around {wave_peak}, with no major wave build-up"
        else:
            recommendation = "expect conditions to worsen if your timing overlaps the forecast peak"
            reason = f"forecast wave peak is near {wave_max} m around {wave_peak}"
    elif intent == "route_timing":
        route_timing = summarize_route_timing(
            timing_context,
            forecast,
            best_window,
            watch_out,
            vessel_profile=snapshot.get("vessel_profile"),
        )
        recommendation = route_timing["recommendation"]
        reason = route_timing["reason"]
    else:
        recommendation = best_window
        reason = watch_out

    evidence_note = render_evidence_note(forecast)
    captain_rule_matches = captain_knowledge.match_rules(snapshot, question_intent=intent)
    snapshot["observation_alignment"] = alignment
    snapshot["forecast_sanity"] = sanity
    passage_position = ((forecast.get("passage_evidence") or {}).get("position_context") or {})
    cache_key_snapshot = copy.deepcopy(snapshot)
    cache_key_snapshot["request_context"] = {
        "question": question,
        "current_time": current_time,
        "current_date": current_date,
        "intent": intent,
        "location_label": location_label,
        "position_status": passage_position.get("status"),
        "distance_to_route_nm": passage_position.get("distance_to_route_nm"),
        "nearest_route_point": passage_position.get("nearest_route_point"),
    }

    def build_stance():
        return build_operational_stance(
            route=snapshot.get("route"),
            intent=intent,
            recommendation=recommendation,
            reason=reason,
            confidence=confidence,
            vessel_advice=vessel_advice,
            vessel_profile=snapshot.get("vessel_profile"),
            vessel_class=snapshot.get("vessel_class"),
            vessel_class_assumed=snapshot.get("vessel_class_assumed", False),
            forecast=forecast,
            freshness=snapshot.get("evidence_freshness"),
            evidence_note=evidence_note,
            data_lineage=snapshot.get("data_lineage"),
            captain_rule_matches=captain_rule_matches,
            observation_alignment=alignment,
            forecast_sanity=sanity,
            observations=snapshot.get("observations"),
            route_connection=snapshot.get("route_connection"),
        )

    operational_stance = recommendation_state.get_or_build_stance(
        cache_key_snapshot,
        build_stance,
        vessel_class=snapshot.get("vessel_class"),
    )
    answer = render_captain_answer(operational_stance)
    return {
        "intent": intent,
        "question": question,
        "answer": answer,
        "location_label": location_label,
        "captain_knowledge": captain_knowledge.summarize_matches(captain_rule_matches),
        "forecast_context": forecast,
        "operational_stance": operational_stance,
    }


def build_operational_stance(
    route,
    intent,
    recommendation,
    reason,
    confidence,
    vessel_advice=None,
    vessel_profile=None,
    vessel_class=None,
    vessel_class_assumed=False,
    forecast=None,
    freshness=None,
    evidence_note=None,
    data_lineage=None,
    captain_rule_matches=None,
    observation_alignment=None,
    forecast_sanity=None,
    observations=None,
    route_connection=None,
):
    forecast = forecast or {}
    freshness = freshness or {}
    route_prefix = f"{route}: " if route else ""
    freshness_warning = freshness.get("freshness_warning")
    display_recommendation = recommendation
    if intent == "conditions_soon" and recommendation.startswith("conditions look workable"):
        display_recommendation = "conditions look workable for the next operational window"
    has_clock_times = bool(re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", str(recommendation or "")))
    if not has_clock_times:
        display_recommendation = soften_clock_times(display_recommendation, "the peak window")
    comfort_detail = render_comfort(forecast, vessel_advice, vessel_profile)
    comfort = comfort_detail.split(".", 1)[0]
    vessel_context = render_vessel_context(vessel_advice, vessel_profile, vessel_class, vessel_class_assumed)
    current_detail = render_current_conditions(observations, observation_alignment, freshness)
    trend_detail = render_trend(forecast, observation_alignment, forecast_sanity)

    route_segment_reason = render_route_segment_reason(forecast)
    captain_rule_reason = render_captain_rule_reason(captain_rule_matches)
    reason_text = sentence_case(reason).rstrip(".")
    if not has_clock_times:
        reason_text = soften_clock_times(reason_text, "the peak window")
    why_parts = [reason_text]
    if observation_alignment and observation_alignment.get("warning"):
        why_parts.append(observation_alignment["warning"])
    if route_segment_reason:
        why_parts.append(route_segment_reason.rstrip("."))
    if captain_rule_reason:
        why_parts.append(captain_rule_reason.rstrip("."))
    if forecast_sanity and forecast_sanity.get("summary"):
        why_parts.append(forecast_sanity["summary"])
    route_connection_detail = render_route_connection(route_connection)
    if route_connection_detail:
        why_parts.append(route_connection_detail.rstrip("."))
    lineage_guidance = render_lineage_guidance(data_lineage)
    if lineage_guidance:
        why_parts.append(lineage_guidance.rstrip("."))

    why = f"{'. '.join(unique_sentences(why_parts))}."

    what_could_change = render_what_could_change(forecast, evidence_note, captain_rule_matches)
    if not has_clock_times:
        what_could_change = soften_clock_times(what_could_change, "the peak window")
    if freshness_warning:
        what_could_change = f"{freshness_warning} {sentence_case(what_could_change)}"
    if observation_alignment and observation_alignment.get("warning"):
        what_could_change = f"{observation_alignment['warning']} {sentence_case(what_could_change)}"
    if forecast_sanity and forecast_sanity.get("warnings") and forecast_sanity["warnings"] != ["no_sanity_flags"]:
        what_could_change = f"{forecast_sanity['summary']}. {sentence_case(what_could_change)}"
    if not has_clock_times:
        what_could_change = soften_clock_times(what_could_change, "the peak window")

    decision_text = render_decision_line(route_prefix, intent, display_recommendation, forecast, freshness)
    best_window_text = render_best_window(intent, display_recommendation, forecast)
    if not decision_text.endswith("."):
        decision_text = f"{decision_text}."
    if not best_window_text.endswith("."):
        best_window_text = f"{best_window_text}."

    risk_detail = render_risk(forecast, vessel_advice, vessel_profile)
    risk = risk_detail.split(".", 1)[0]

    confidence = adjust_confidence(confidence, observation_alignment, forecast_sanity, freshness)
    confidence_text = render_confidence(confidence, freshness, observation_alignment, forecast_sanity)
    confidence_label = confidence_text.rstrip(".") if confidence_text else None

    return {
        "route": route,
        "intent": intent,
        "decision": concise_decision_label(display_recommendation, intent, forecast),
        "decision_text": decision_text,
        "best_window": concise_best_window_label(best_window_text),
        "best_window_text": best_window_text,
        "comfort": comfort,
        "comfort_detail": comfort_detail,
        "vessel_context": vessel_context,
        "current_detail": current_detail,
        "trend_detail": trend_detail,
        "risk": risk,
        "risk_detail": risk_detail,
        "why": why,
        "what_could_change": what_could_change,
        "confidence": confidence_label,
        "confidence_detail": confidence_text,
        "freshness_status": freshness.get("freshness_status", "unknown"),
        "freshness_warning": freshness_warning,
        "observation_alignment": observation_alignment or {},
        "forecast_sanity": forecast_sanity or {},
        "route_connection": route_connection or {},
        "route_connection_detail": route_connection_detail,
    }


def render_captain_answer(operational_stance):
    comfort = operational_stance["comfort_detail"]
    if operational_stance.get("vessel_context"):
        comfort = f"{comfort} {operational_stance['vessel_context']}"
    lines = [
        f"Recommendation: {operational_stance['decision_text']}",
        f"CURRENT: {operational_stance.get('current_detail', 'Latest observations are being used.')}",
        f"TREND: {operational_stance.get('trend_detail', 'Trend is broadly steady.')}",
        f"WINDOWS: {operational_stance['best_window_text']}",
        f"COMFORT: {comfort}",
        f"PASSAGE: {operational_stance['route_connection_detail']}" if operational_stance.get("route_connection_detail") else None,
        f"WATCH OUT: {operational_stance['what_could_change']}",
        f"Confidence: {operational_stance['confidence_detail']}" if operational_stance.get("confidence_detail") else None,
        f"What could change: {operational_stance['what_could_change']}",
    ]
    lines = [line for line in lines if line]
    return "\n\n".join(lines)


def render_route_connection(route_connection):
    if not route_connection:
        return None
    distance_nm = route_connection.get("distance_nm")
    travel_minutes = route_connection.get("typical_travel_time_minutes")
    if distance_nm is None or travel_minutes is None:
        return None
    origin = route_connection.get("origin_place_name") or route_connection.get("origin_place_id") or "Origin"
    destination = route_connection.get("destination_place_name") or route_connection.get("destination_place_id") or "Destination"
    hours, minutes = divmod(int(travel_minutes), 60)
    if hours and minutes:
        travel_text = f"{hours}h {minutes}m"
    elif hours:
        travel_text = f"{hours}h"
    else:
        travel_text = f"{minutes}m"
    speed = route_connection.get("typical_speed_kn", 16)
    return f"{origin} -> {destination} is about {distance_nm:.1f} nm and usually takes around {travel_text} at {speed:.0f} kn"


def concise_decision_label(display_recommendation, intent, forecast):
    if intent == "leave_window":
        if "practical daylight window has passed" in display_recommendation:
            return sentence_case(display_recommendation)
        lower = display_recommendation.lower()
        leave_match = re.search(r"\b(leave|depart)\b.*", lower)
        if leave_match:
            clause = display_recommendation[leave_match.start() :].split(";", 1)[0].split("—", 1)[0].strip()
            return sentence_case(clause) + "."
        primary = re.split(r"[;—]", display_recommendation, maxsplit=1)[0].strip()
        if "leave" in primary.lower() or "depart" in primary.lower():
            return sentence_case(primary) + "."
        peak_time = forecast.get("wave_peak_time")
        if peak_time and peak_time != "N/A":
            return "Leave before late morning."
        return "Leave with conservative timing."
    if intent == "conditions_soon":
        return sentence_case(display_recommendation) + "."
    return sentence_case(display_recommendation) + "."


def concise_best_window_label(best_window_text):
    if not best_window_text:
        return "before late morning"
    lowered = best_window_text.lower()
    if "before late morning" in lowered:
        return "before late morning"
    if "before midday" in lowered:
        return "before midday"
    if "through the morning" in lowered:
        return "through the morning"
    if "during daylight hours" in lowered:
        return "during daylight hours"
    if "this evening" in lowered:
        return "this evening"
    if "overnight" in lowered:
        return "overnight"
    if "morning" in lowered:
        return "during the morning"
    if "afternoon" in lowered:
        return "this afternoon"
    if "evening" in lowered:
        return "this evening"
    return best_window_text.rstrip(".")


def unique_sentences(parts):
    seen = set()
    unique = []
    for part in parts:
        normalized = " ".join(str(part).lower().split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(part)
    return unique


def sentence_case(text):
    if not text:
        return ""
    return text[0].upper() + text[1:]


def soften_clock_times(text, replacement="the relevant window"):
    if not text:
        return text
    return re.sub(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", replacement, str(text))


def render_vessel_context(vessel_advice, vessel_profile=None, vessel_class=None, vessel_class_assumed=False):
    if not vessel_advice and not vessel_profile:
        return (
            "For this vessel size: vessel size was not provided; assuming a medium 15-24m profile. "
            "Share LOA or vessel class for a sharper read."
        )

    label = None
    if isinstance(vessel_profile, dict):
        label = vessel_profile.get("label")
    if not label:
        labels = {"small": "under 15m", "medium": "15-24m", "large": "over 24m"}
        label = labels.get(vessel_class, "the selected vessel class")

    assumption = "Assuming " if vessel_class_assumed else ""
    if not vessel_advice:
        return f"For this vessel size: {assumption}{label}."
    if vessel_advice.startswith("manageable for"):
        advice = vessel_advice.replace("manageable for vessels ", "manageable for ")
        return f"For this vessel size: {assumption}{label}, conditions are manageable."
    if vessel_advice.startswith("restricted for"):
        return f"For this vessel size: {assumption}{label}, treat it as {vessel_advice}."
    if vessel_advice.startswith("caution for"):
        return f"For this vessel size: {assumption}{label}, use conservative timing."
    if vessel_advice:
        return f"For this vessel size: {assumption}{label}, {vessel_advice}."
    return f"For this vessel size: {assumption}{label}."


def render_decision_line(route_prefix, intent, recommendation, forecast, freshness):
    stale = freshness.get("freshness_status") not in (None, "current")
    qualifier = " based on the latest available package" if stale else ""
    if intent == "leave_window":
        if "practical daylight window has passed" in recommendation:
            return f"{route_prefix}{sentence_case(recommendation)}."
        if (
            "looks better than" in recommendation
            or "near the forecast peak" in recommendation
            or "conservative timing" in recommendation
            or "night-crossing option" in recommendation
            or "not a comfort recommendation" in recommendation
        ):
            return f"{route_prefix}{sentence_case(recommendation)}."
        leave_match = re.search(r"\b(leave|depart)\b.*", recommendation, re.IGNORECASE)
        if leave_match:
            clause = recommendation[leave_match.start() :].split(";", 1)[0].split("—", 1)[0].strip()
            return f"{route_prefix}{sentence_case(clause)}{qualifier}."
        peak_time = forecast.get("wave_peak_time")
        route = route_prefix.replace(": ", "").strip() or "This route"
        target_label = render_target_window_label(forecast)
        peak_window = peak_period_label(peak_time)
        if peak_time and peak_time != "N/A":
            return f"{route} is workable {target_label}{qualifier}, but avoid the roughest {peak_window} period."
        return f"{route} is workable {target_label}{qualifier}; no sharp peak is flagged in the available package."
    return f"{route_prefix}{sentence_case(recommendation)}."


def render_target_window_label(forecast):
    period = forecast.get("target_period_label")
    if period == "tomorrow":
        return "tomorrow"
    if period in ("morning", "afternoon", "evening"):
        return f"for the requested {period} window"
    if forecast.get("target_local_date"):
        return "for the requested forecast day"
    return "today"


def render_best_window(intent, recommendation, forecast):
    peak_time = forecast.get("wave_peak_time")
    best = extract_lower_sampled_window(recommendation)
    requested_period = forecast.get("target_period_label")
    departure_context = "if departing today"
    if requested_period in ("morning", "afternoon", "evening"):
        departure_context = f"within the requested {requested_period} window"
    elif forecast.get("target_local_date"):
        departure_context = "within the requested forecast day"
    lowered_recommendation = (recommendation or "").lower()
    if requested_period == "morning" and (
        "before midday" in lowered_recommendation
        or "morning to early afternoon" in lowered_recommendation
        or "leave through the morning" in lowered_recommendation
        or "leave before late morning" in lowered_recommendation
    ):
        if "leave through the morning" in lowered_recommendation:
            return "Leave through the morning within the requested morning window. Through the morning remains the calmer part of the window."
        return "Leave through the morning within the requested morning window. Through the morning remains the calmer part of the window."
    if "tomorrow morning looks workable" in lowered_recommendation and (
        "leave before late morning" in lowered_recommendation
        or "leave through the morning" in lowered_recommendation
    ):
        if "leave through the morning" in lowered_recommendation:
            return "Leave through the morning within the requested morning window. Through the morning remains the calmer part of the window."
        return "Leave before late morning within the requested morning window. Through the morning remains the calmer part of the window."
    if best:
        best_window_label = departure_window_label(best)
        if peak_time and peak_time != "N/A":
            if "daylight" in recommendation:
                return (
                    f"Leave {best_window_label} {departure_context}. "
                    f"Avoid the roughest {peak_period_label(peak_time)} period."
                )
            return (
                f"Leave {best_window_label} {departure_context}. "
                f"Conditions are expected to worsen in the roughest {peak_period_label(peak_time)} period."
            )
        return f"Leave {best_window_label} {departure_context}."
    if "lower sampled window is around" in recommendation:
        return sentence_case(recommendation) + "."
    if "leave " in recommendation.lower() or "depart" in recommendation.lower():
        return sentence_case(recommendation) + "."
    if peak_time and peak_time != "N/A":
        return f"Prefer the calmer window and avoid the roughest {peak_period_label(peak_time)} period."
    if intent == "location_safety":
        return "Stay only while sheltered; move earlier if exposure increases."
    return "No narrow departure window identified from the available evidence."


def extract_lower_sampled_window(text):
    match = re.search(
        r"lower sampled (?:practical daylight )?window is around ([0-2]?\d:[0-5]\d)",
        text or "",
        re.IGNORECASE,
    )
    if not match:
        return None
    hour, minute = match.group(1).split(":", 1)
    return f"{int(hour):02d}:{minute}"


def render_comfort(forecast, vessel_advice, vessel_profile):
    wave_max = forecast.get("wave_max_m")
    if wave_max is None:
        return "Unknown from this package; forecast wave height is missing."

    manageable = None
    restricted = None
    if isinstance(vessel_profile, dict):
        manageable = vessel_profile.get("manageable_m")
        restricted = vessel_profile.get("restricted_m")

    if restricted is not None and wave_max >= restricted:
        level = "Less favourable"
        detail = "Expect pronounced motion on exposed sections."
    elif manageable is not None and wave_max >= manageable:
        level = "Moderate"
        detail = "Reduced comfort margin; expect increased motion."
    elif vessel_advice and "caution" in vessel_advice:
        level = "Moderate"
        detail = "More comfortable than the rougher sections, but guests will still notice some motion."
    else:
        level = "More comfortable"
        detail = "Practical for the selected vessel size, with comfort still depending on period, direction, and passenger sensitivity."
    return f"{level}. {detail}"


def render_current_conditions(observations, observation_alignment, freshness):
    record = latest_observation_record(observations)
    if not record:
        return "Latest observations are not available."

    parts = []
    wave = record.get("wave_height_m")
    if isinstance(wave, (int, float)):
        parts.append(f"{record.get('name', 'the nearest buoy')} reports {wave:.1f} m")
    temp = record.get("water_temp_c")
    if isinstance(temp, (int, float)):
        parts.append(f"water temperature is {temp:.1f} C")
    age = observation_alignment.get("observation_age_minutes")
    if age is not None:
        parts.append(f"observations are about {age} minutes old")
    agreement = observation_alignment.get("agreement")
    if agreement and agreement != "unavailable":
        parts.append(f"forecast agreement is {agreement}")
    if freshness.get("freshness_warning"):
        parts.append("forecast freshness should be rechecked before departure")
    return sentence_case(". ".join(parts) + ".")


def render_trend(forecast, observation_alignment=None, forecast_sanity=None):
    hourly = [row for row in forecast.get("hourly") or [] if isinstance(row, dict) and row.get("wave_m") is not None]
    if not hourly:
        base = "Forecast trend is not available."
    else:
        first = hourly[0]["wave_m"]
        last = hourly[-1]["wave_m"]
        if last > first + 0.2:
            base = "Conditions gradually build through the day."
        elif last < first - 0.2:
            base = "Conditions gradually improve through the day."
        else:
            base = "Conditions stay broadly steady through the day."
    if forecast.get("target_period_label") == "tomorrow":
        base = f"Tomorrow looks workable if the latest run keeps the same picture. {base}"
    peak_state = forecast.get("wave_peak_sea_state")
    if peak_state:
        base = f"{base} Peak sea state is {peak_state}."
    if observation_alignment and observation_alignment.get("warning"):
        base = f"{observation_alignment['warning']} {base}"
    if forecast_sanity and forecast_sanity.get("warnings") and forecast_sanity["warnings"] != ["no_sanity_flags"]:
        base = f"{forecast_sanity['summary']}. {base}"
    return sentence_case(base.rstrip(".")) + "."


def render_risk(forecast, vessel_advice, vessel_profile):
    wave_max = forecast.get("wave_max_m")
    peak_time = forecast.get("wave_peak_time")
    if wave_max is None:
        return "Manual review required; wave forecast is missing."
    if vessel_advice and "restricted" in vessel_advice:
        level = "High for this vessel size"
    elif vessel_advice and "caution" in vessel_advice:
        level = "Moderate"
    else:
        level = "Low to moderate"

    peak = f" Peak wave height is near {wave_max:.1f} m"
    if peak_time and peak_time != "N/A":
        peak = f"{peak} during the roughest {peak_period_label(peak_time)} period"
    return f"{level}.{peak}."


def render_route_segment_reason(forecast):
    passage = forecast.get("passage_evidence") or {}
    position_context = passage.get("position_context") or {}
    position_warning = position_context.get("warning")
    position_prefix = ""
    if position_context and not position_warning:
        nearest_point = position_context.get("nearest_route_point")
        if nearest_point:
            position_prefix = f"Using last known position near {nearest_point}. "
    passage_worst = passage.get("worst_segment") or {}
    if passage_worst:
        name = passage_worst.get("label")
        wave = passage_worst.get("wave_m")
        time = passage_worst.get("time") or passage_worst.get("eta")
        comfort = passage_worst.get("comfort")
        if name and wave is not None:
            detail = f"Passage scenario: worst expected section is {name}, near {wave:.1f} m"
            if time:
                period_text = period_label(time)
                if period_text.startswith("the "):
                    detail = f"{detail} during {period_text}"
                else:
                    detail = f"{detail} during the {period_text}"
            if comfort:
                detail = f"{detail}, with {comfort.replace('_', ' ')} comfort"
            if position_warning:
                detail = f"{position_warning} {detail}"
            return f"{position_prefix}{detail}."
    if position_warning:
        return position_warning

    worst_segment = ((forecast.get("route_segments") or {}).get("worst_segment") or {})
    if not worst_segment:
        return None
    name = worst_segment.get("name")
    peak_time = worst_segment.get("peak_time")
    wave = worst_segment.get("max_wave_m")
    sea_state = worst_segment.get("sea_state")
    if not name or wave is None:
        return None
    detail = f"Worst route segment is {name}, near {wave:.1f} m"
    if peak_time:
        detail = f"{detail} during the {period_label(peak_time)}"
    if sea_state:
        detail = f"{detail}, with a {sea_state}"
    return f"{position_prefix}{detail}."


def format_local_time(time_text):
    if not time_text:
        return "the local time window"
    match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", str(time_text))
    if not match:
        return str(time_text)
    return f"{int(match.group(1)):02d}:{match.group(2)} LT"


def render_captain_rule_reason(captain_rule_matches):
    if not captain_rule_matches:
        return None
    rule = captain_rule_matches[0]
    consequence = rule.get("operational_consequence")
    if not consequence:
        return None
    return f"Captain knowledge: {consequence}"


def render_lineage_guidance(data_lineage):
    wind = ((data_lineage or {}).get("wind_forecast") or {})
    source = wind.get("source")
    status = wind.get("status")
    resolution = wind.get("resolution_km")
    source_summary = source_lineage.summarize_sources(data_lineage=data_lineage)
    source_text = source_summary.get("text")

    if source == "meteo_france_arome" and status in ("active", "blended"):
        resolution_text = f"{resolution:g} km" if isinstance(resolution, (int, float)) else "high-resolution"
        return (
            f"Wind context: using ultra-high-resolution {resolution_text} local physics model guidance, "
            "which improves the read on coastal breeze variations around island channels."
        )
    if source == "aemet_harmonie_arome" and status in ("active", "blended", "fallback"):
        resolution_text = f"{resolution:g} km" if isinstance(resolution, (int, float)) else "high-resolution"
        return (
            f"Wind context: using high-resolution {resolution_text} regional model guidance for Spanish coastal detail."
        )
    if source == "ecmwf_open_data":
        return (
            "Wind context: winds are grounded in global structural models; "
            "localized coastal land breezes may vary near channel boundaries."
        ) + (f" {source_text}." if source_text else "")
    if source_text:
        return source_text
    return None


def render_what_could_change(forecast, evidence_note, captain_rule_matches=None):
    checks = []
    if forecast.get("wave_peak_time") not in (None, "N/A"):
        checks.append("the timing or height of the forecast peak shifts in the next run")
    if not has_wave_partition_detail(forecast):
        checks.append("swell and wind-wave partition data changes the comfort read")
    if forecast.get("current_max_kn") is None:
        checks.append("current data is missing or updates materially")
    if not checks:
        checks.append("buoy observations or the next model run diverge from this forecast")
    if captain_rule_matches:
        action = captain_rule_matches[0].get("preferred_action")
        if action:
            checks.append(action.rstrip("."))

    detail = "; ".join(check.rstrip(".") for check in checks)
    if evidence_note:
        return f"{detail}. {evidence_note}"
    return f"{detail}."


def render_confidence(confidence, freshness, observation_alignment=None, forecast_sanity=None):
    if confidence in (None, "", "null"):
        return None
    warning = freshness.get("freshness_warning")
    label = str(confidence).strip().capitalize()
    if observation_alignment and observation_alignment.get("agreement") in {"poor", "very poor"}:
        warning = warning or "Latest buoy observations are lower than the forecast, so confidence is reduced."
    if forecast_sanity and forecast_sanity.get("warnings") and forecast_sanity["warnings"] != ["no_sanity_flags"]:
        warning = warning or "Forecast evolution looks unusually rapid. Recheck buoy observations before committing."
    if warning:
        return f"{label}. {sentence_case(warning)}"
    return f"{label}."


def adjust_confidence(confidence, observation_alignment=None, forecast_sanity=None, freshness=None):
    if confidence in (None, "", "null"):
        return None
    labels = {"high": "High", "medium": "Medium", "low": "Low"}
    label = labels.get(str(confidence).strip().lower(), str(confidence).strip().capitalize() if confidence else "Low")
    if freshness and freshness.get("freshness_status") in {"last_night_run", "unknown"} and label == "High":
        label = "Medium"
    if observation_alignment and observation_alignment.get("agreement") in {"poor", "very poor"}:
        if label == "High":
            label = "Medium"
        elif label == "Medium":
            label = "Low"
    if forecast_sanity and forecast_sanity.get("warnings") and forecast_sanity["warnings"] != ["no_sanity_flags"]:
        if label == "High":
            label = "Medium"
        elif label == "Medium":
            label = "Low"
    return label


def latest_observation_record(observations):
    best = None
    best_age = None
    for record in (observations or {}).values():
        if not isinstance(record, dict) or record.get("wave_height_m") is None:
            continue
        age = observation_age_minutes(record.get("last_sample_utc") or record.get("observed_at_utc"))
        if age is None:
            continue
        if best is None or age < best_age:
            best = record
            best_age = age
    return best


def observation_age_minutes(value):
    if not value:
        return None
    text = str(value).strip().replace(" UTC", "Z")
    parsed = None
    for fmt in ("%Y-%m-%dT%H:%MZ", "%Y-%m-%d %H:%MZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            parsed = datetime.strptime(text, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        return None
    delta = datetime.utcnow() - parsed
    return int(delta.total_seconds() / 60.0)


def has_wave_partition_detail(forecast):
    return any(
        forecast.get(key) is not None
        for key in (
            "swell_1_height_m",
            "swell_1_direction_deg",
            "swell_2_height_m",
            "swell_2_direction_deg",
            "wind_wave_height_m",
            "wind_wave_direction_deg",
        )
    )


def classify_timing_context(question):
    text = question.lower()
    if "tonight" in text:
        return "tonight"
    if "tomorrow" in text:
        return "tomorrow"
    if "this afternoon" in text or "afternoon" in text:
        return "afternoon"
    return None


def forecast_for_question_context(forecast, question, timing_context=None, current_date=None):
    target_date = target_local_date_for_question(question, timing_context=timing_context, current_date=current_date)
    if not target_date:
        return forecast

    hourly = forecast.get("hourly") or []
    day_part = requested_day_part(question, timing_context=timing_context)
    filtered_hourly = [
        localized_hourly_row(row)
        for row in hourly
        if row_local_date(row) == target_date and row_matches_day_part(row, day_part)
    ]
    if not filtered_hourly:
        return forecast

    filtered = copy.deepcopy(forecast)
    filtered["hourly"] = filtered_hourly
    filtered["target_local_date"] = target_date.isoformat()
    filtered["target_period_label"] = day_part or timing_context or "today"
    # Existing route_segments are aggregate summaries over the whole downloaded package.
    # Drop them after day filtering so the answer does not cite stale segment peaks.
    filtered["route_segments"] = {}
    update_forecast_extrema_from_hourly(filtered)
    return filtered


def requested_day_part(question, timing_context=None):
    text = question.lower()
    if "morning" in text:
        return "morning"
    if "afternoon" in text or timing_context == "afternoon":
        return "afternoon"
    if "evening" in text:
        return "evening"
    return None


def row_matches_day_part(row, day_part):
    if not day_part:
        return True
    parsed = parse_row_time_utc(row)
    if parsed is None:
        return True
    minutes = parsed.astimezone(LOCAL_TIMEZONE).hour * 60 + parsed.astimezone(LOCAL_TIMEZONE).minute
    if day_part == "morning":
        return 6 * 60 <= minutes < 12 * 60
    if day_part == "afternoon":
        return 12 * 60 <= minutes < 18 * 60
    if day_part == "evening":
        return 18 * 60 <= minutes <= 22 * 60
    return True


def localized_hourly_row(row):
    localized = copy.deepcopy(row)
    parsed = parse_row_time_utc(row)
    if parsed is None:
        return localized
    local_time = parsed.astimezone(LOCAL_TIMEZONE)
    localized.setdefault("time_model", localized.get("time"))
    localized["time"] = local_time.strftime("%H:%M")
    localized["time_local"] = local_time.strftime("%Y-%m-%d %H:%M")
    return localized


def target_local_date_for_question(question, timing_context=None, current_date=None):
    text = question.lower()
    base_date = parse_local_date(current_date)
    if base_date is None:
        return None
    timing_context = timing_context or classify_timing_context(question)
    if timing_context == "tomorrow":
        return base_date + timedelta(days=1)
    if timing_context == "tonight" or "today" in text:
        return base_date
    return None


def parse_local_date(value):
    if isinstance(value, date):
        return value
    if not value:
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def row_local_date(row):
    parsed = parse_row_time_utc(row)
    if parsed is None:
        return None
    return parsed.astimezone(LOCAL_TIMEZONE).date()


def parse_row_time_utc(row):
    value = row.get("time_utc")
    if not value:
        return None
    text = str(value).strip().replace(" UTC", "Z")
    for fmt in ("%Y-%m-%d %H:%MZ", "%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=ZoneInfo("UTC"))
        except ValueError:
            continue
    return None


def update_forecast_extrema_from_hourly(forecast):
    hourly = forecast.get("hourly") or []
    wave_rows = [row for row in hourly if row.get("wave_m") is not None]
    if wave_rows:
        min_row = min(wave_rows, key=lambda row: row["wave_m"])
        peak_row = max(wave_rows, key=lambda row: row["wave_m"])
        forecast["wave_min_m"] = min_row.get("wave_m")
        forecast["wave_max_m"] = peak_row.get("wave_m")
        forecast["wave_peak_time"] = peak_row.get("time")
        copy_peak_field(forecast, peak_row, "wave_direction_deg", "wave_peak_direction_deg")
        copy_peak_field(forecast, peak_row, "wave_sea_state", "wave_peak_sea_state")
        for component in ("swell_1", "swell_2", "wind_wave"):
            copy_peak_field(forecast, peak_row, f"{component}_height_m", f"{component}_height_m")
            copy_peak_field(forecast, peak_row, f"{component}_direction_deg", f"{component}_direction_deg")

    current_rows = [row for row in hourly if row.get("current_kn") is not None]
    if current_rows:
        current_peak = max(current_rows, key=lambda row: row["current_kn"])
        forecast["current_max_kn"] = current_peak.get("current_kn")
        forecast["current_peak_time"] = current_peak.get("time")


def copy_peak_field(forecast, peak_row, source_key, target_key):
    if peak_row.get(source_key) is not None:
        forecast[target_key] = peak_row.get(source_key)


def summarize_route_timing(timing_context, forecast, best_window, watch_out, vessel_profile=None):
    wave_max = forecast.get("wave_max_m", "N/A")
    wave_peak = forecast.get("wave_peak_time", "N/A")
    current_max = forecast.get("current_max_kn")
    current_text = f" Current peak is near {current_max} kn." if current_max is not None else ""
    hourly_count = len(forecast.get("hourly") or [])

    if timing_context == "tonight":
        return {
            "recommendation": "Tonight looks workable on sea state, but treat it as a night crossing rather than a simple green light",
            "reason": (
                f"forecast wave peak is near {wave_max} m during the roughest {peak_period_label(wave_peak)} period, with the main watch-out: {watch_out}."
                f"{current_text} Recheck the latest buoy observations before departure because darkness reduces visual margin"
            ),
        }
    if timing_context == "tomorrow":
        route_window = summarize_best_departure_window(
            forecast,
            current_time=None,
            vessel_profile=vessel_profile,
        )
        tomorrow_morning = forecast.get("target_period_label") == "morning"
        if isinstance(wave_max, (int, float)) and isinstance(vessel_profile, dict):
            restricted = vessel_profile.get("restricted_m")
            manageable = vessel_profile.get("manageable_m")
            coverage = render_hourly_coverage(hourly_count)
            if restricted is not None and wave_max >= restricted:
                return {
                    "recommendation": "tomorrow morning is not a comfort recommendation for this vessel size unless the morning run improves",
                    "reason": (
                        f"forecast peak is near {wave_max} m during the roughest {peak_period_label(wave_peak)} period{coverage}. "
                        "That is above this vessel profile's restricted threshold, so the morning peak is the watch-out, not the best window"
                    ),
                }
            if manageable is not None and wave_max >= manageable:
                if route_window:
                    if tomorrow_morning:
                        return {
                            "recommendation": "Tomorrow morning looks workable; leave through the morning",
                            "reason": (
                                f"{route_window['reason']}. Through the morning remains the calmer part of the window. "
                                "Confirm with the morning run before committing"
                            ),
                        }
                return {
                    "recommendation": (
                        route_window["recommendation"]
                        if route_window
                        else "tomorrow looks possible only with conservative timing for this vessel size"
                    ),
                    "reason": (
                        route_window["reason"]
                        if route_window
                        else f"forecast peak is near {wave_max} m during the {peak_period_label(wave_peak)} period{coverage}. "
                        "Use the lower sampled window and confirm with the morning run before committing"
                    ),
                }
        coverage = render_hourly_coverage(hourly_count)
        if route_window:
            if tomorrow_morning:
                return {
                    "recommendation": "Tomorrow morning looks workable; leave through the morning",
                    "reason": f"{route_window['reason']}. Through the morning remains the calmer part of the window. Confirm with the morning run before committing",
                }
            return {
                "recommendation": "Tomorrow morning looks workable; leave before late morning",
                "reason": f"{route_window['reason']}. Confirm with the morning run before committing",
            }
        return {
            "recommendation": "Tomorrow looks workable based on the latest forecast package",
            "reason": (
                f"forecast peak is near {wave_max} m during the roughest {peak_period_label(wave_peak)} period{coverage}. "
                "Morning should be the better planning window; confirm with the morning run before committing"
            ),
        }
    if timing_context == "afternoon":
        return {
            "recommendation": f"for the afternoon, use the {best_window} guidance and avoid any local peak window",
            "reason": f"main watch-out is: {watch_out}; forecast wave peak is near {wave_max} m during the roughest {peak_period_label(wave_peak)} period.{current_text}",
        }
    return {
        "recommendation": best_window,
        "reason": watch_out,
    }


def render_hourly_coverage(hourly_count):
    if not hourly_count:
        return " in the current forecast package"
    if hourly_count == 1:
        return " in the available sampled forecast point"
    return f" across {hourly_count} forecast time points"


def extract_requested_time(question):
    match = re.search(r"\b([01]?\d|2[0-3])(?::([0-5]\d))?\b", question)
    if not match:
        return None
    hour = int(match.group(1))
    minute = match.group(2) or "00"
    return f"{hour:02d}:{minute}"


def summarize_requested_time(requested_time, forecast):
    if not requested_time:
        return None
    hourly = forecast.get("hourly") or []
    row = next((item for item in hourly if item.get("time") == requested_time), None)
    if not row:
        return None

    wave = row.get("wave_m")
    peak_time = forecast.get("wave_peak_time", "N/A")
    peak_wave = forecast.get("wave_max_m")
    if wave is None or peak_wave is None:
        return None

    if requested_time == peak_time:
        recommendation = f"{format_local_time(requested_time)} is near the forecast peak; avoid it if comfort matters"
    elif wave < peak_wave:
        recommendation = f"{format_local_time(requested_time)} looks better than the {format_local_time(peak_time)} peak"
    else:
        recommendation = f"{format_local_time(requested_time)} still looks exposed; reassess closer to departure"

    reason = (
        f"forecast is about {wave:.1f} m at {format_local_time(requested_time)}, "
        f"versus the peak near {peak_wave:.1f} m around {format_local_time(peak_time)}"
    )
    current = row.get("current_kn")
    if current is not None:
        reason = f"{reason}; current about {current:.1f} kn"
    return {"recommendation": recommendation, "reason": reason}


def summarize_best_departure_window(forecast, current_time=None, vessel_profile=None):
    hourly = forecast.get("hourly") or []
    peak_time = forecast.get("wave_peak_time", "N/A")
    peak_wave = forecast.get("wave_max_m")
    candidates = [
        row for row in hourly
        if row.get("time") != peak_time
        and row.get("wave_m") is not None
        and is_future_or_current_time(row.get("time"), current_time)
    ]
    if not candidates or peak_wave is None or peak_time == "N/A":
        return None

    practical_candidates = [row for row in candidates if is_practical_daylight_time(row.get("time"))]
    non_peak_practical_candidates = [
        row for row in practical_candidates
        if not is_near_time(row.get("time"), peak_time, minutes=90)
    ]
    candidate_pool = non_peak_practical_candidates or practical_candidates or candidates
    best = best_operational_candidate(candidate_pool)
    best_time = best.get("time")
    best_wave = best.get("wave_m")
    if best_time is None or best_wave is None:
        return None

    peak_direction = forecast.get("wave_peak_direction_deg")
    direction_text = ""
    if peak_direction is not None:
        direction_text = f" Mean wave direction near the peak is about {peak_direction:.0f} degrees"

    best_window_label = departure_window_label(best_time)
    peak_window = peak_period_label(peak_time)
    recommendation_prefix = f"leave {best_window_label}; avoid the roughest {peak_window} period"
    if is_night_time(best_time):
        recommendation_prefix = "leave this evening; that is a night-crossing option"

    if isinstance(peak_wave, (int, float)) and isinstance(vessel_profile, dict):
        restricted = vessel_profile.get("restricted_m")
        manageable = vessel_profile.get("manageable_m")
        if restricted is not None and peak_wave >= restricted:
            recommendation_prefix = f"not a comfort recommendation during the roughest {peak_window} period; {recommendation_prefix}"
        elif manageable is not None and peak_wave >= manageable:
            recommendation_prefix = f"possible today with conservative timing; {recommendation_prefix}"

    return {
        "recommendation": recommendation_prefix,
        "reason": (
            f"forecast peak is near {peak_wave:.1f} m during the roughest {peak_window} period, while the sampled route value "
            f"in the calmer window is about {best_wave:.1f} m.{direction_text}"
        ),
    }


def is_practical_daylight_time(candidate_time):
    minutes = time_to_minutes(candidate_time)
    if minutes is None:
        return False
    return 6 * 60 <= minutes <= 20 * 60


def best_operational_candidate(candidates, tolerance_m=0.15):
    if not candidates:
        return None
    best_wave = min(row.get("wave_m", 999) for row in candidates)
    near_best = [
        row for row in candidates
        if row.get("wave_m") is not None and row.get("wave_m", 999) <= best_wave + tolerance_m
    ]
    return min(near_best or candidates, key=lambda row: time_to_minutes(row.get("time")) or 9999)


def is_night_time(candidate_time):
    minutes = time_to_minutes(candidate_time)
    if minutes is None:
        return False
    return minutes > 20 * 60 or minutes < 6 * 60


def is_near_time(candidate_time, target_time, minutes=90):
    candidate_minutes = time_to_minutes(candidate_time)
    target_minutes = time_to_minutes(target_time)
    if candidate_minutes is None or target_minutes is None:
        return False
    return abs(candidate_minutes - target_minutes) <= minutes


def is_future_or_current_time(candidate_time, current_time):
    if not current_time or not candidate_time:
        return True
    candidate_minutes = time_to_minutes(candidate_time)
    current_minutes = time_to_minutes(current_time)
    if candidate_minutes is None or current_minutes is None:
        return True
    return candidate_minutes >= current_minutes


def time_to_minutes(value):
    match = re.search(r"\b([01]?\d|2[0-3])(?::([0-5]\d))?\b", str(value))
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2) or "00")


def departure_window_label(time_text):
    minutes = time_to_minutes(time_text)
    if minutes is None:
        return "the best available window"
    if minutes < 6 * 60:
        return "overnight"
    if minutes < 10 * 60:
        return "before late morning"
    if minutes < 12 * 60:
        return "through the morning"
    if minutes < 18 * 60:
        return "during daylight hours"
    if minutes < 22 * 60:
        return "this evening"
    return "overnight"


def period_label(time_text):
    minutes = time_to_minutes(time_text)
    if minutes is None:
        return "the available period"
    if minutes < 6 * 60:
        return "overnight"
    if minutes < 10 * 60:
        return "early morning"
    if minutes < 12 * 60:
        return "the morning"
    if minutes < 18 * 60:
        return "daylight hours"
    if minutes < 22 * 60:
        return "this evening"
    return "overnight"


def peak_period_label(time_text):
    minutes = time_to_minutes(time_text)
    if minutes is None:
        return "available period"
    if minutes < 6 * 60:
        return "overnight"
    if minutes < 10 * 60:
        return "early morning"
    if minutes < 12 * 60:
        return "late morning"
    if minutes < 18 * 60:
        return "daylight hours"
    if minutes < 22 * 60:
        return "this evening"
    return "overnight"


def render_evidence_note(forecast):
    component_note = render_wave_component_note(forecast)
    if component_note:
        return component_note

    has_components = any(
        key in forecast
        for key in (
            "swell_1_height_m",
            "swell_1_direction_deg",
            "swell_2_height_m",
            "swell_2_direction_deg",
            "wind_wave_height_m",
            "wind_wave_direction_deg",
        )
    )
    if has_components:
        return None
    if forecast.get("wave_peak_direction_deg") is not None:
        return (
            "Evidence note: this uses combined wave height and mean wave direction; "
            "swell and wind-wave components are not available in this evidence package."
        )
    return (
        "Evidence note: this uses combined wave height only; swell direction and wind-wave "
        "components are not available in this evidence package."
    )


def render_wave_component_note(forecast):
    parts = []
    sea_state = forecast.get("wave_peak_sea_state")
    peak_direction = forecast.get("wave_peak_direction_deg")
    if sea_state and peak_direction is not None:
        parts.append(f"At the peak, combined seas are a {sea_state} from about {peak_direction:.0f} degrees")
    elif sea_state:
        parts.append(f"At the peak, combined seas are a {sea_state}")

    component_texts = []
    for component_name, label in (
        ("swell_1", "Primary swell"),
        ("swell_2", "secondary swell"),
        ("wind_wave", "wind wave"),
    ):
        height = forecast.get(f"{component_name}_height_m")
        direction = forecast.get(f"{component_name}_direction_deg")
        if height is None and direction is None:
            continue
        if height is not None and direction is not None:
            component_texts.append(f"{label} {height:.1f} m from {direction:.0f} degrees")
        elif height is not None:
            component_texts.append(f"{label} {height:.1f} m")
        else:
            component_texts.append(f"{label} from {direction:.0f} degrees")
    if component_texts:
        parts.append("; ".join(component_texts))

    if not parts:
        return None
    return "Sea-state detail: " + ". ".join(parts) + "."


def is_morning_window_passed(best_window, current_time):
    if "morning" not in best_window and best_window != "before midday":
        return False
    if not current_time:
        return False
    hour_text = str(current_time).split(":", 1)[0]
    try:
        hour = int(hour_text)
    except ValueError:
        return False
    return hour >= 12


def is_late_day(current_time):
    if not current_time:
        return False
    hour_text = str(current_time).split(":", 1)[0]
    try:
        hour = int(hour_text)
    except ValueError:
        return False
    return hour >= 20


def is_manageable_peak(forecast, vessel_profile):
    wave_max = forecast.get("wave_max_m")
    if wave_max is None:
        return False
    manageable_m = vessel_profile.get("manageable_m", 1.2)
    return float(wave_max) < float(manageable_m)


def render_decision_screenshot_script(decision):
    lines = [
        "Illustrative WhatsApp screenshot script",
        "Captain: [Shared live location]",
        f"Captain: {decision['question']}",
    ]
    for answer_line in decision["answer"].splitlines():
        lines.append(f"PredSea: {answer_line}")
    lines.append("Caption note: illustrative product example based on public marine data.")
    return "\n".join(lines)
