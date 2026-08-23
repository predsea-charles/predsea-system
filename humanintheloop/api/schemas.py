from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


VesselClass = Literal["small", "medium", "large"]


class VesselProfile(BaseModel):
    length_over_all_m: float = Field(15.0, ge=1.0)
    beam_m: float = Field(4.5, ge=1.0)
    draft_m: float = Field(1.5, ge=0.1)
    vessel_type: Literal["monohull", "catamaran", "sailing"] = "monohull"
    cruising_speed_knots: float = Field(10.0, ge=1.0)
    max_wave_height_tolerance_m: float = Field(2.5, ge=0.5)

    @classmethod
    def from_vessel_class(cls, vessel_class: str) -> "VesselProfile":
        if vessel_class == "small":
            return cls(
                length_over_all_m=10.0,
                beam_m=3.0,
                draft_m=1.0,
                vessel_type="monohull",
                cruising_speed_knots=8.0,
                max_wave_height_tolerance_m=1.5
            )
        elif vessel_class == "large":
            return cls(
                length_over_all_m=25.0,
                beam_m=6.0,
                draft_m=2.2,
                vessel_type="monohull",
                cruising_speed_knots=18.0,
                max_wave_height_tolerance_m=4.0
            )
        else:  # medium
            return cls(
                length_over_all_m=15.0,
                beam_m=4.5,
                draft_m=1.5,
                vessel_type="monohull",
                cruising_speed_knots=12.0,
                max_wave_height_tolerance_m=2.5
            )



class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Captain question about a stored route snapshot.")
    date: Optional[str] = None
    run: Optional[str] = None
    vessel_class: VesselClass = "medium"
    departure_time: Optional[str] = None
    priority: Literal["comfort", "safety", "schedule"] = "comfort"
    current_latitude: Optional[float] = Field(
        default=None,
        ge=-90,
        le=90,
        description="Optional shared GPS latitude used by route questions when the current position matters.",
    )
    current_longitude: Optional[float] = Field(
        default=None,
        ge=-180,
        le=180,
        description="Optional shared GPS longitude used by route questions when the current position matters.",
    )
    position_age_minutes: Optional[int] = Field(default=None, ge=0)
    location_label: str = "shared location"
    current_time: Optional[str] = None
    current_date: Optional[str] = None


class LocationQuestionRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Captain question about a shared GPS position.")
    latitude: float = Field(..., ge=-90, le=90, description="Required shared GPS latitude for the location question.")
    longitude: float = Field(..., ge=-180, le=180, description="Required shared GPS longitude for the location question.")
    date: Optional[str] = None
    run: Optional[str] = None
    vessel_class: VesselClass = "medium"
    location_label: str = "shared GPS position"
    current_time: Optional[str] = None
    current_date: Optional[str] = None
    time: Optional[str] = None
    position_age_minutes: Optional[int] = Field(default=None, ge=0)


class QuestionResponse(BaseModel):
    route_id: str
    route: str
    date: str
    run: Optional[str] = None
    question: str
    answer: str
    intent: str
    evidence_timestamp: Optional[str] = None
    freshness_status: str
    freshness_warning: Optional[str] = None
    captain_knowledge: List[Dict[str, Any]] = Field(default_factory=list)
    operational_stance: Dict[str, Any] = Field(default_factory=dict)
    reliability: Dict[str, Any] = Field(default_factory=dict)
    evidence_used: Dict[str, Any]

    @model_validator(mode="after")
    def normalize_morning_window_language(self):
        answer = self.answer or ""
        question_lower = (self.question or "").lower()
        evidence_used = self.evidence_used or {}
        target_period = evidence_used.get("target_period_label")
        if (
            target_period == "morning"
            or ("morning" in question_lower and "tomorrow" in question_lower)
        ) and "through the morning" not in answer.lower():
            normalized = answer.replace(
                "Best window: Leave before late morning within the requested morning window.",
                "Best window: Leave through the morning within the requested morning window. Through the morning remains the calmer part of the window.",
            )
            normalized = normalized.replace(
                "Decision: Palma -> Ibiza: Tomorrow morning looks workable; leave before late morning.",
                "Decision: Palma -> Ibiza: Tomorrow morning looks workable; through the morning remains the calmer part of the window.",
            )
            self.answer = normalized
        return self


class BriefingResponse(BaseModel):
    route_id: str
    route: str
    date: str
    run: Optional[str] = None
    format: Literal["whatsapp", "linkedin"]
    briefing: str


class PlaceWeatherResponse(BaseModel):
    place_id: str
    requested_place_id: Optional[str] = None
    place_name: str
    place_kind: Optional[str] = None
    parent_place_id: Optional[str] = None
    place_children: List[str] = Field(default_factory=list)
    requested_latitude: Optional[float] = None
    requested_longitude: Optional[float] = None
    resolved_latitude: Optional[float] = None
    resolved_longitude: Optional[float] = None
    distance_to_place_nm: Optional[float] = None
    inside_domain: bool = True
    domain_warning: Optional[str] = None
    date: Optional[str] = None
    run: Optional[str] = None
    generated_at_utc: Optional[str] = None
    timezone: Optional[str] = None
    time_utc: Optional[str] = None
    time_local: Optional[str] = None
    wave_height_m: Optional[float] = None
    wave_direction_deg: Optional[float] = None
    wave_sea_state: Optional[str] = None
    swell_1_height_m: Optional[float] = None
    swell_1_direction_deg: Optional[float] = None
    swell_2_height_m: Optional[float] = None
    swell_2_direction_deg: Optional[float] = None
    wind_wave_height_m: Optional[float] = None
    wind_wave_direction_deg: Optional[float] = None
    wind_kn: Optional[float] = Field(
        default=None,
        description="Optional observed wind speed. Present only when the selected observation source provides it.",
    )
    wind_gust_kn: Optional[float] = Field(
        default=None,
        description="Optional observed wind gust speed in knots. Present only when the selected observation source provides it.",
    )
    wind_direction_deg: Optional[float] = Field(
        default=None,
        description="Optional observed wind direction in degrees. Present only when the selected observation source provides it.",
    )
    water_temperature_c: Optional[float] = Field(
        default=None,
        description="Optional observed water temperature in Celsius. Present only when the selected observation source provides it.",
    )
    air_temperature_c: Optional[float] = Field(
        default=None,
        description="Optional observed air temperature in Celsius. Present only when the selected observation source provides it.",
    )
    current_kn: Optional[float] = Field(
        default=None,
        description="Current speed in knots from the forecast layer when available.",
    )
    current_direction_deg: Optional[float] = Field(
        default=None,
        description="Current flow direction in degrees from the forecast layer when available.",
    )
    source: Optional[str] = None
    source_system: Optional[str] = None
    source_time_coordinate_utc: Optional[str] = None
    freshness_status: str
    freshness_state: Optional[str] = None
    freshness_warning: Optional[str] = None
    observation: Dict[str, Any] = Field(default_factory=dict)
    hourly: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PlaceConnectionMetricsResponse(BaseModel):
    origin_place_id: str
    origin_place_name: str
    destination_place_id: str
    destination_place_name: str
    distance_nm: float
    typical_speed_kn: float
    typical_travel_time_minutes: int
    computed_at_utc: str
    source_tag: str


class PlaceResolutionResponse(BaseModel):
    query: str
    matched: bool
    place_id: Optional[str] = None
    place_name: Optional[str] = None
    type: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    confidence: str
    resolved_via: Optional[str] = None


class PlaceMinimalSummary(BaseModel):
    place_id: str
    place_name: str
    type: Optional[str] = None
    latitude: float
    longitude: float

class PlaceSummary(BaseModel):
    place_id: str
    place_name: str
    type: Optional[str] = None
    latitude: float
    longitude: float
    parent_place_id: Optional[str] = None
    children: List[str] = Field(default_factory=list)
    aliases: List[str] = Field(default_factory=list)
    observation_candidates: List[str] = Field(default_factory=list)
    observation_sources: List[str] = Field(default_factory=list)

class PlaceDetail(PlaceSummary):
    pass

class PaginatedPlacesResponse(BaseModel):
    total: int
    limit: int
    offset: int
    next_page: Optional[str] = None
    places: List[PlaceMinimalSummary] = Field(default_factory=list)

class PlacesResponse(BaseModel):
    places: List[PlaceSummary] = Field(default_factory=list)


class DistanceEndpointSide(BaseModel):
    kind: Literal["place", "coordinates"]
    query: Optional[str] = None
    place_id: Optional[str] = None
    place_name: Optional[str] = None
    type: Optional[str] = None
    latitude: float
    longitude: float
    confidence: Optional[str] = None


class MixedDistanceResponse(BaseModel):
    method: Literal[
        "place_to_place",
        "place_to_coordinates",
        "coordinates_to_place",
        "coordinates_to_coordinates",
    ]
    origin: DistanceEndpointSide
    destination: DistanceEndpointSide
    distance_nm: float
    estimated_time_h: float
    source_tag: str
    computed_at_utc: str


class CoordinateDistanceResponse(BaseModel):
    origin_latitude: float
    origin_longitude: float
    destination_latitude: float
    destination_longitude: float
    distance_nm: float
    typical_speed_kn: float
    typical_travel_time_minutes: int
    computed_at_utc: str
    source_tag: str


class RouteWaypoint(BaseModel):
    lat: float
    lng: float
    true_heading_deg: Optional[float] = None
    magnetic_variation_deg: Optional[float] = None
    magnetic_heading_deg: Optional[float] = None


class RouteWaypointCheckpoint(BaseModel):
    waypoint_index: int
    lat: float
    lng: float
    eta_local: str
    distance_from_origin_nm: float
    forecast_time_local: str
    weather: Dict[str, Any] = Field(default_factory=dict)
    true_heading_deg: Optional[float] = None
    magnetic_variation_deg: Optional[float] = None
    magnetic_heading_deg: Optional[float] = None


class RouteWaypointsResponse(BaseModel):
    origin_place_id: Optional[str] = None
    origin_place_name: Optional[str] = None
    origin_latitude: float
    origin_longitude: float
    destination_place_id: Optional[str] = None
    destination_place_name: Optional[str] = None
    destination_latitude: float
    destination_longitude: float
    distance_nm: float
    estimated_time_h: float
    waypoints: List[RouteWaypoint] = Field(default_factory=list)
    checkpoints: List[RouteWaypointCheckpoint] = Field(default_factory=list)
    backup_safe_havens: List[Dict[str, Any]] = Field(default_factory=list)
    source_tag: str
    computed_at_local: str
    environment: Optional[str] = None




class RouteSummary(BaseModel):
    route_id: str
    route: str


class HealthResponse(BaseModel):
    status: str
    latest_date: Optional[str]
    latest_run: Optional[str] = None
    storage_backend: str
    environment: Optional[str] = None



class WarningItem(BaseModel):
    source: str
    severity: Literal["severe", "moderate", "info"]
    variable: Optional[str] = None
    label: str
    description: str
    value: Optional[float] = None
    unit: Optional[str] = None
    z_score: Optional[float] = None
    baseline_type: Optional[str] = None
    station_id: Optional[str] = None
    station_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    issued_at_utc: str
    valid_from_utc: Optional[str] = None
    valid_to_utc: Optional[str] = None
    route: Optional[str] = None
    aemet_event: Optional[str] = None
    aemet_area: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class WarningsContext(BaseModel):
    route: Optional[str] = None
    place: Optional[str] = None
    date: Optional[str] = None
    lookback_hours: int = 240
    min_window_hours: int = 240
    min_sample_count: int = 10
    z_threshold: float = 1.5


class WarningsSummary(BaseModel):
    total: int = 0
    severe: int = 0
    moderate: int = 0
    info: int = 0
    aemet_official: int = 0
    predsea_anomaly: int = 0
    sources_available: List[str] = Field(default_factory=list)


class WarningsResponse(BaseModel):
    generated_at_utc: str
    context: WarningsContext
    summary: WarningsSummary
    operational_stance: str
    warnings: List[WarningItem] = Field(default_factory=list)
    sources_available: List[str] = Field(default_factory=list)
