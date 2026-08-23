# PredSea Frontend Handoff Integration Checklist

This interactive checklist is designed for frontend developers to systematically verify their integration of PredSea's backend services.

---

## 🏁 Setup & Configuration
- [ ] **Establish Base URL:** Configured `NEXT_PUBLIC_PREDSEA_API_BASE_URL` env variable pointing to `https://predsea-api-193957983101.europe-west1.run.app`.
- [ ] **CORS Verification:** Preflight checks verified from browser origin domains.
- [ ] **Generate Types:** Ran `npm run api:generate` to produce the fully-typed OpenAPI definitions layer under `src/api/generated/openapi.ts`.

## 📍 Places & Routes Mapping
- [ ] **Origin/Destination Dropdowns:** Bound correctly to `GET /places` payload.
- [ ] **Place Resolver:** Attached search typing handlers to `GET /places/resolve` for automatic alias matching (e.g. mapping "eze-sur-mer" to canonical "eze").
- [ ] **Nautical Map Routing:** Leaflet or Mapbox polylines render spatial waypoint matrices loaded from `GET /places/route/{origin}/{destination}`.

## 📈 Oceanographic Variable Rendering
- [ ] **Units Compliance:** Checked that wave heights display in **meters (m)**, winds and currents in **knots (kn)**, and distances in **nautical miles (NM)**.
- [ ] **Directions Interpretation:** Current and wind arrow icons rotate correctly relative to Degrees ($^\circ$ True) from true North.
- [ ] **Time-Semantics Integrity:** UTC times parse correctly (preserving source offsets) and convert properly to client device local times for display.

## 💬 Conversational AI & Warnings
- [ ] **Chat Submission:** Bound route-specific chat queries to `POST /routes/{route_id}/question`.
- [ ] **Warning Flags:** Warning panel queries `GET /warnings/active` every 30 minutes to dynamically display active anomalies or official GMDSS alerts.

## 🛡️ Error & Edge Case Handling
- [ ] **Validation Failures:** All 422/400 errors map to generic helper warnings instead of raw stack traces.
- [ ] **Offline / Loading States:** Empty timelines or missing values render beautiful empty states instead of zero measurements or breaking.
- [ ] **Mock Verification:** Toggled local mock API server to test extreme sea states and timeout errors locally.
