import { 
  mapApiPlaceToPlaceOption, 
  mapApiWeatherToWeatherSummary, 
  mapApiBriefingToBriefingViewModel,
  mapApiEvidenceToWaveTimeline
} from "./adapters";
import { Place, PlaceWeather } from "./places";
import { RouteBriefing, RouteEvidence } from "./routes";

describe("PredSea UI adapters tests", () => {
  test("mapApiPlaceToPlaceOption correctly maps properties", () => {
    const mockPlace: Place = {
      id: "eze",
      name: "Èze-sur-Mer",
      latitude: 43.727,
      longitude: 7.361,
      type: "main_place"
    };

    const result = mapApiPlaceToPlaceOption(mockPlace);
    expect(result.label).toBe("Èze-sur-Mer");
    expect(result.value).toBe("eze");
    expect(result.coords.lat).toBe(43.727);
  });

  test("mapApiWeatherToWeatherSummary handles nullable fields safely", () => {
    const mockWeather: PlaceWeather = {
      place_id: "eze",
      name: "Èze-sur-Mer",
      temperature_c: 24.5,
      wind_speed_kn: 12.0,
      wind_direction_deg: 180,
      wave_height_m: 0.40,
      current_speed_kn: 0.15,
      source: "copernicus"
    };

    const result = mapApiWeatherToWeatherSummary(mockWeather);
    expect(result.temperature).toBe("24.5°C");
    expect(result.windSpeed).toBe("12.0 kn");
    expect(result.isSafe).toBe(true);
  });

  test("mapApiBriefingToBriefingViewModel maps feasibility ratings", () => {
    const mockBriefing: RouteBriefing = {
      route_id: "nice_eze",
      feasibility: "Caution",
      wave_max_m: 1.6,
      current_max_kn: 0.5,
      briefing_markdown: "Swell warning"
    };

    const result = mapApiBriefingToBriefingViewModel(mockBriefing);
    expect(result.rating).toBe("Caution");
    expect(result.maxWave).toBe("1.60 m");
  });

  test("mapApiEvidenceToWaveTimeline preserves timeline and maps properly", () => {
    const mockEvidence: RouteEvidence = {
      route_id: "nice_eze",
      timesteps: ["2026-07-10T12:00:00Z"],
      wave_heights: [0.38],
      wind_speeds: [11.2]
    };

    const result = mapApiEvidenceToWaveTimeline(mockEvidence);
    expect(result.heights[0]).toBe(0.38);
    expect(result.windSpeeds[0]).toBe(11.2);
  });
});
