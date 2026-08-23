import { request, RequestOptions } from "./client";

export async function askLocationQuestion(
  latitude: number, 
  longitude: number, 
  query: string, 
  options: RequestOptions = {}
): Promise<{ response: string }> {
  return request<{ response: string }>(
    "/question",
    "POST",
    { latitude, longitude, query },
    options
  );
}
