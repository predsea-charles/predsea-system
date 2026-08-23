/**
 * Central API Client configuration for the PredSea Platform.
 * Supports secure, centralized origin base URL and standard timeouts.
 */

export const PREDSEA_API_BASE_URL = 
  process.env.NEXT_PUBLIC_PREDSEA_API_BASE_URL || 
  "https://predsea-api-193957983101.europe-west1.run.app";

export interface RequestOptions {
  timeoutMs?: number;
  headers?: Record<string, string>;
}

export async function request<T>(
  path: string, 
  method: "GET" | "POST" = "GET", 
  body?: any, 
  options: RequestOptions = {}
): Promise<T> {
  const url = `${PREDSEA_API_BASE_URL.replace(/\/$/, "")}${path}`;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), options.timeoutMs || 15000);
  
  const headers = {
    "Content-Type": "application/json",
    ...options.headers
  };

  try {
    const response = await fetch(url, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      const errText = await response.text();
      let detail = errText;
      try {
        const parsed = JSON.parse(errText);
        detail = parsed.detail || errText;
      } catch {}
      const error: any = new Error(detail || `HTTP Error ${response.status}`);
      error.status = response.status;
      error.detail = detail;
      throw error;
    }

    return await response.json() as T;
  } catch (err: any) {
    clearTimeout(timeoutId);
    if (err.name === "AbortError") {
      throw new Error("Request timed out. Please check your connection.");
    }
    throw err;
  }
}
