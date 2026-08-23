import { request, RequestOptions } from "./client";

export interface ActiveWarning {
  id: string;
  source: string;
  headline: string;
  description: string;
  severity: string;
  issued_at_utc: string;
}

export async function getActiveWarnings(options: RequestOptions = {}): Promise<ActiveWarning[]> {
  return request<ActiveWarning[]>("/warnings/active", "GET", undefined, options);
}

export async function getObservationStations(options: RequestOptions = {}): Promise<any[]> {
  return request<any[]>("/observations/stations", "GET", undefined, options);
}

export async function evaluateModels(options: RequestOptions = {}): Promise<any> {
  return request<any>("/forecasts/evaluate", "GET", undefined, options);
}
