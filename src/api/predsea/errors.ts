/**
 * Error normalization helper for PredSea UI elements.
 * Ensures we present neat, user-friendly feedback instead of raw stack traces.
 */

export interface NormalizedError {
  message: string;
  retryable: boolean;
  status?: number;
}

export function normalizeError(error: any): NormalizedError {
  const status = error?.status;
  const detail = error?.detail;
  
  let message = "A temporary connection error occurred.";
  let retryable = false;

  if (status === 400) {
    message = "One of your input parameters is incorrect. Please verify and retry.";
  } else if (status === 401) {
    message = "Your session has expired. Please log in again.";
  } else if (status === 403) {
    message = "You do not have permission to view this forecast data.";
  } else if (status === 404) {
    message = "The requested place, route, or forecast could not be located in our dataset.";
  } else if (status === 429) {
    message = "Too many requests. Please wait a moment.";
    retryable = true;
  } else if (status && status >= 500) {
    message = "PredSea forecast services are currently resolving model outputs on GCP. Retrying...";
    retryable = true;
  } else if (typeof detail === "string" && detail.trim() !== "") {
    message = detail;
  } else if (error?.message) {
    message = error.message;
  }

  return { message, retryable, status };
}
