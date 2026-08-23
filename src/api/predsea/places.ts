import { request, RequestOptions } from "./client";

export interface Place {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  type: string;
  aliases?: string[];
}

export interface PlaceWeather {
  place_id: string;
  name: string;
  temperature_c: number;
  wind_speed_kn: number;
  wind_direction_deg: number;
  wave_height_m: number;
  current_speed_kn: number;
  source: string;
}

export async function searchPlaces(options: RequestOptions = {}): Promise<Place[]> {
  return request<Place[]>("/places", "GET", undefined, options);
}

export async function resolvePlace(query: string, options: RequestOptions = {}): Promise<{ resolved: boolean; place_id: string; canonical_name: string }> {
  return request<{ resolved: boolean; place_id: string; canonical_name: string }>(
    `/places/resolve?query=${encodeURIComponent(query)}`,
    "GET",
    undefined,
    options
  );
}

export async function getPlaceWeather(placeId: string, options: RequestOptions = {}): Promise<PlaceWeather> {
  return request<PlaceWeather>(`/places/${placeId}/weather`, "GET", undefined, options);
}

export async function getDistance(origin: string, destination: string, options: RequestOptions = {}): Promise<{ distance_nm: number }> {
  return request<{ distance_nm: number }>(
    `/places/distance?origin=${encodeURIComponent(origin)}&destination=${encodeURIComponent(destination)}`,
    "GET",
    undefined,
    options
  );
}
