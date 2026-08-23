import os
import pytest
from api.schemas import VesselProfile
from api.weather_routing import AStarWeatherRouter


def test_vessel_routing_safety_block():
    # Set a ridiculously low wave tolerance (0.1 meters)
    # The router should fail because wave height in the dataset will exceed this tolerance.
    profile = VesselProfile(
        length_over_all_m=12.0,
        beam_m=3.5,
        draft_m=1.2,
        vessel_type="monohull",
        cruising_speed_knots=10.0,
        max_wave_height_tolerance_m=0.5
    )
    
    router = AStarWeatherRouter(vessel_profile=profile)
    
    with pytest.raises(ValueError, match="A\\* Weather Routing failed: no valid path exists"):
        router.find_route(
            origin_lat=42.729167,
            origin_lon=3.208333,
            dest_lat=42.6,
            dest_lon=3.2,
        )


def test_vessel_routing_speed_penalty_comparison():
    # Compare travel times of a small vessel vs a large vessel
    # BOTH have cruising speed of 10.0 knots.
    # Small vessel is subject to the 20% speed penalty in steep chop.
    # Large vessel is NOT subject to the penalty.
    
    small_profile = VesselProfile(
        length_over_all_m=12.0,  # < 20m
        beam_m=3.5,
        draft_m=1.2,
        vessel_type="monohull",
        cruising_speed_knots=10.0,
        max_wave_height_tolerance_m=3.0
    )
    
    large_profile = VesselProfile(
        length_over_all_m=25.0,  # >= 20m
        beam_m=6.0,
        draft_m=2.0,
        vessel_type="monohull",
        cruising_speed_knots=10.0,
        max_wave_height_tolerance_m=3.0
    )
    
    router_small = AStarWeatherRouter(vessel_profile=small_profile)
    router_large = AStarWeatherRouter(vessel_profile=large_profile)
    
    route_small = router_small.find_route(
        origin_lat=39.52,
        origin_lon=2.58,
        dest_lat=39.84,
        dest_lon=3.14,
    )
    
    route_large = router_large.find_route(
        origin_lat=39.52,
        origin_lon=2.58,
        dest_lat=39.84,
        dest_lon=3.14,
    )
    
    # Check that small vessel takes at least as long as or longer than large vessel
    # due to the speed degradation penalty in wave fields.
    assert route_small["estimated_time_h"] >= route_large["estimated_time_h"]
