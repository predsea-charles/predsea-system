# PredSea API Error Contract Reference

This reference catalog defines all possible API error status codes, their structural formats, meanings, and recommended frontend recovery/retry strategies.

---

## 🛑 General Error Response Shape

All handled API errors conform to the standard FastAPI RFC-7807 problem details or custom details array schema:

```json
{
  "detail": [
    {
      "loc": ["query", "origin"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

Or for semantic domain errors (e.g. unknown route):

```json
{
  "detail": "Unknown place ID 'eze-sur-mer'"
}
```

---

## 📚 Error Dictionary

| HTTP Status | Error Type / Code | Meaning | Retry? | Recommended User-Facing Message |
| :--- | :--- | :--- | :--- | :--- |
| **`400`** | `ValidationError` | A required request parameter or body property is missing or improperly typed. | ❌ No | "Please check your inputs and try again." |
| **`401`** | `Unauthorized` | Invalid or missing authentication headers (where applicable). | ❌ No | "Please log in again to restore access." |
| **`403`** | `Forbidden` | Access token does not permit reading this resource. | ❌ No | "You do not have permission to view this page." |
| **`404`** | `NotFound` | The requested Place ID, Route ID, or pre-rendered artifact does not exist. | ❌ No | "The requested nautical route or place could not be found." |
| **`422`** | `Unprocessable` | Syntactical parsing success but semantic validation failure (e.g. invalid date formats).| ❌ No | "The request contains invalid parameters." |
| **`429`** | `TooManyRequests`| Rate limits exceeded. | 🔄 Yes (Delay) | "Rate limit exceeded. Retrying in a few moments..." |
| **`500`** | `InternalError` | Critical exception encountered inside the solver or DB drivers on GCP. | 🔄 Yes | "The marine forecast service is busy. Retrying..." |
| **`503`** | `Unavailable` | External provider services (SOCIB, CMEMS) did not respond in time. | 🔄 Yes | "Live oceanographic feeds are offline. Retrying..." |

---

## 🛡️ Recommended Frontend Error Normalization

Use a central normalization wrapper to parse raw errors before presentation, avoiding raw technical details or stack traces on-screen:

```typescript
export function normalizeApiError(error: any): { message: string; retryable: boolean } {
  const status = error?.status || error?.response?.status;
  const detail = error?.data?.detail || error?.response?.data?.detail;
  
  let message = "A temporary connection error occurred.";
  let retryable = false;

  if (status === 404) {
    message = "The requested nautical route, port, or forecast could not be found.";
  } else if (status === 429) {
    message = "Rate limits exceeded. Please wait a moment.";
    retryable = true;
  } else if (status >= 500) {
    message = "PredSea services are busy resolving model forecasts. Retrying...";
    retryable = true;
  } else if (typeof detail === "string") {
    message = detail;
  }

  return { message, retryable };
}
```
