# PredSea Frontend Screen-to-Endpoint Matrix

This matrix provides a complete map matching each known frontend component and user action to its live backend API endpoint.

---

| Frontend Component | User Action | Target API Endpoint | Method | Required Parameters | Caching & Refresh Guidelines | Fallback / Error Handling |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Origin Selector** | Population | `GET /places` | `GET` | None | Cache for full session. | Use preloaded fallback local ports. |
| **Destination Selector**| Selection | `GET /places` | `GET` | None | Cache for full session. | Filter by reachable distances locally. |
| **Fuzzy Search Box** | Typing / Resolve | `GET /places/resolve` | `GET` | `query` (fuzzy name) | Cache result for 24h. | Alert "No matching place found". |
| **Interactive Map** | Display route path | `GET /places/route/{origin}/{destination}` | `GET` | `origin`, `destination` | Cache path geometry. | Render straight geodesic fallback line. |
| **Daily Briefing Box** | Display briefing | `GET /routes/{route_id}/briefing` | `GET` | `route_id` | Revalidate every 3 hours. | Show "Briefing temporarily unavailable".|
| **Marine Wave Chart** | Timeline display | `GET /routes/{route_id}/evidence` | `GET` | `route_id` | Revalidate every 3 hours. | Render empty timelines or flat zero bounds.|
| **Conversational Chat** | Ask route question | `POST /routes/{route_id}/question` | `POST`| `route_id`, `query` | Never cache POST requests. | Display "AI mate is busy, please retry". |
| **General Chat** | Ask location question| `POST /question` | `POST`| `latitude`, `longitude`, `query` | Never cache POST requests. | Display "AI mate is busy, please retry". |
| **Warnings Badge** | Display active alert | `GET /warnings/active` | `GET` | None | Revalidate every 30 minutes. | Hide warnings badge (fail-safe clean state).|
| **Sensor Validation Panel**| Live verification | `GET /observations/stations` | `GET` | None | Cache for 1 hour. | Hide live data feeds section. |
| **Model Evaluator** | Model accuracy review | `GET /forecasts/evaluate` | `GET` | None | Cache for 24 hours. | Show "Offline analysis model" message. |
