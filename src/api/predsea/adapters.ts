import { Place, PlaceWeather } from "./places";
import { RouteGeometry, RouteBriefing, RouteEvidence } from "./routes";
import { normalizeError } from "./errors";

export interface PlaceOption {
  label: string;
  value: string;
  coords: { lat: number; lon: number };
}

export interface RouteMapModel {
  routeId: string;
  distance: string;
  points: [number, number][];
}

export interface WeatherSummary {
  temperature: string;
  windSpeed: string;
  windDirection: number;
  waveHeight: string;
  currentSpeed: string;
  isSafe: boolean;
}

export interface BriefingViewModel {
  routeId: string;
  rating: "Manageable" | "Caution" | "Unsafe";
  maxWave: string;
  maxCurrent: string;
  markdown: string;
}

export interface WaveTimelineModel {
  labels: string[];
  heights: number[];
  windSpeeds: number[];
}

export function mapApiPlaceToPlaceOption(place: Place): PlaceOption {
  return {
    label: place.name,
    value: place.id,
    coords: { lat: place.latitude, lon: place.longitude }
  };
}

export function mapApiRouteToRouteMapModel(route: RouteGeometry): RouteMapModel {
  return {
    routeId: route.route_id,
    distance: `${route.distance_nm.toFixed(1)} NM`,
    points: route.waypoints || []
  };
}

export function mapApiWeatherToWeatherSummary(weather: PlaceWeather): WeatherSummary {
  const waveHeight = weather.wave_height_m ?? 0;
  const isSafe = waveHeight < 1.5; // Threshold bounds for safe/caution conditions
  return {
    temperature: `${(weather.temperature_c ?? 0).toFixed(1)}°C`,
    windSpeed: `${(weather.wind_speed_kn ?? 0).toFixed(1)} kn`,
    windDirection: weather.wind_direction_deg ?? 0,
    waveHeight: `${waveHeight.toFixed(2)} m`,
    currentSpeed: `${(weather.current_speed_kn ?? 0).toFixed(2)} kn`,
    isSafe
  };
}

export function mapApiBriefingToBriefingViewModel(briefing: RouteBriefing): BriefingViewModel {
  const rating = (briefing.feasibility || "Manageable") as "Manageable" | "Caution" | "Unsafe";
  return {
    routeId: briefing.route_id,
    rating,
    maxWave: `${(briefing.wave_max_m ?? 0).toFixed(2)} m`,
    maxCurrent: `${(briefing.current_max_kn ?? 0).toFixed(2)} kn`,
    markdown: briefing.briefing_markdown || ""
  };
}

export function mapApiEvidenceToWaveTimeline(evidence: RouteEvidence): WaveTimelineModel {
  const formatTime = (isoStr: string) => {
    try {
      const d = new Date(isoStr);
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch {
      return isoStr;
    }
  };
  return {
    labels: (evidence.timesteps || []).map(formatTime),
    heights: evidence.wave_heights || [],
    windSpeeds: evidence.wind_speeds || []
  };
}

export function mapApiErrorToUserMessage(error: any): string {
  return normalizeError(error).message;
}
