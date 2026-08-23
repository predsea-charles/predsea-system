import { request, RequestOptions } from "./client";

export interface Route {
  id: string;
  name: string;
  origin: { name: string; latitude: number; longitude: number };
  destination: { name: string; latitude: number; longitude: number };
}

export interface RouteGeometry {
  route_id: string;
  distance_nm: number;
  waypoints: [number, number][];
}

export interface RouteBriefing {
  route_id: string;
  feasibility: string;
  wave_max_m: number;
  current_max_kn: number;
  briefing_markdown: string;
}

export interface RouteEvidence {
  route_id: string;
  timesteps: string[];
  wave_heights: number[];
  wind_speeds: number[];
}

export async function getRoutes(options: RequestOptions = {}): Promise<Route[]> {
  return request<Route[]>("/routes", "GET", undefined, options);
}

export async function getRoute(origin: string, destination: string, options: RequestOptions = {}): Promise<RouteGeometry> {
  return request<RouteGeometry>(
    `/places/route/${encodeURIComponent(origin)}/${encodeURIComponent(destination)}`,
    "GET",
    undefined,
    options
  );
}

export async function getRouteBriefing(routeId: string, options: RequestOptions = {}): Promise<RouteBriefing> {
  return request<RouteBriefing>(`/routes/${routeId}/briefing`, "GET", undefined, options);
}

export async function getRouteEvidence(routeId: string, options: RequestOptions = {}): Promise<RouteEvidence> {
  return request<RouteEvidence>(`/routes/${routeId}/evidence`, "GET", undefined, options);
}

export async function askRouteQuestion(routeId: string, query: string, options: RequestOptions = {}): Promise<{ response: string }> {
  return request<{ response: string }>(
    `/routes/${routeId}/question`,
    "POST",
    { query },
    options
  );
}
