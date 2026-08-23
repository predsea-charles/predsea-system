import { request, RequestOptions } from "./client";

export interface CoordinatesWeather {
  latitude: number;
  longitude: number;
  wave_height_m: number;
  wind_speed_kn: number;
  current_speed_kn: number;
  timestamp: string;
}

export async function getCoordinatesWeather(latitude: number, longitude: number, options: RequestOptions = {}): Promise<CoordinatesWeather> {
  return request<CoordinatesWeather>(
    `/locations/weather?latitude=${latitude}&longitude=${longitude}`,
    "GET",
    undefined,
    options
  );
}
