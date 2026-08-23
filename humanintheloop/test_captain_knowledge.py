import captain_knowledge


def sample_snapshot():
    return {
        "route_id": "ibiza_palma",
        "route": "Palma -> Ibiza",
        "vessel_class": "small",
        "forecast": {
            "wave_max_m": 1.3,
            "wave_peak_time": "14:00",
            "wave_peak_direction_deg": 315.0,
            "wave_peak_sea_state": "beam sea",
            "swell_1_height_m": 0.8,
            "swell_1_direction_deg": 315.0,
            "route_segments": {
                "open_water_conditions": {
                    "name": "Mid Palma-Ibiza",
                    "max_wave_m": 1.3,
                    "peak_time": "14:00",
                    "sea_state": "beam sea",
                },
                "worst_segment": {
                    "id": "open_water_conditions",
                    "name": "Mid Palma-Ibiza",
                    "max_wave_m": 1.3,
                    "peak_time": "14:00",
                    "sea_state": "beam sea",
                },
            },
        },
    }


def test_load_knowledge_has_structured_graham_rules():
    knowledge = captain_knowledge.load_knowledge()

    rule_ids = {rule["id"] for rule in knowledge["rules"]}

    assert "avoid_departure_at_peak_wave" in rule_ids
    assert "wave_direction_more_important_than_height_for_comfort" in rule_ids
    assert "ibiza_palma_nw_swell_channel_caution" in rule_ids
    for rule in knowledge["rules"]:
        assert "condition" in rule
        assert "operational_consequence" in rule
        assert "preferred_action" in rule
        assert "confidence" in rule
    assert knowledge["vessel_thresholds"]["small"]["label"] == "under 15m"
    assert "ibiza_palma" in knowledge["route_exposure_notes"]
    assert "andratx_ibiza" in knowledge["route_exposure_notes"]
    assert "ibiza_mahon" in knowledge["route_exposure_notes"]
    assert knowledge["cases"][0]["captain"] == "graham"


def test_match_rules_applies_route_vessel_and_direction_context():
    matches = captain_knowledge.match_rules(sample_snapshot())
    matched_ids = [match["id"] for match in matches]

    assert "small_vessels_need_conservative_timing" in matched_ids
    assert "wave_direction_more_important_than_height_for_comfort" in matched_ids
    assert "ibiza_palma_nw_swell_channel_caution" in matched_ids
    assert matches[0]["operational_consequence"]
    assert matches[0]["preferred_action"]
