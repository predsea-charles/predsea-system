# PredSea Skills

This file describes PredSea's current product capabilities, not Codex agent
skills.

## Implemented Now

The working implementation is in `humanintheloop/`.

### Data Skills

- Fetch SOCIB public observations for the current Balearic situation.
- Fetch bounded Copernicus Marine Mediterranean forecasts for waves and surface
  currents.
- Save local NetCDF forecast files into `humanintheloop/mvp_data/`.
- Build structured route snapshots under
  `humanintheloop/mvp_data/routes/<route_id>/`.
- Validate stored route forecasts against route-specific SOCIB buoy observations.
- Produce wave-height validation time series and wave-direction vector context
  plots.

### Route Decision Skills

- Analyze configured routes from `humanintheloop/routes.json`:
  - `palma_ibiza`
  - `palma_cabrera`
  - `ibiza_formentera`
  - `alcudia_ciutadella`
- Sample representative points along the selected route corridor.
- Use exposed-route maximum wave/current values per hour, not a broad
  Balearic box average.
- Adjust recommendations by vessel class:
  - `small`: under 15m
  - `medium`: 15-24m
  - `large`: over 24m
- Answer requested-time questions such as `Can I leave at 17:00?`.
- Adjust answers based on current decision time, including demo overrides via
  `--current-time`.

### Captain Communication Skills

- Convert structured marine facts into a captain-facing answer with:
  - `Recommendation`
  - `Reason`
  - `Confidence`
- Generate LinkedIn-ready briefing text.
- Generate WhatsApp-style briefing text.
- Generate a WhatsApp screenshot script.
- Render a WhatsApp/Telegram-style PNG with:
  - PredSea logo
  - simulated shared-location card
  - emphasized key values
  - confidence badge

### Supported Early Question Intents

- Leave/wait timing:
  - `Can I leave at 17:00?`
  - `What is the best time to leave?`
- Local stay/move safety:
  - `Is it safe to stay here this afternoon?`
- Conditions soon:
  - `How will the sea be here in 4 hours?`
- First-pass fuel/efficiency:
  - `Can I save fuel by using another route to Ibiza?`

## Not Implemented Yet

- Real WhatsApp integration.
- Real GPS ingestion from a captain's phone.
- Automatic parsing of arbitrary start/end destinations.
- Full LLM-backed query understanding.
- Website dashboard or subscription flow.
- Map/GIF animation output.
- SOCIB WMOP/SAPO forecast integration.
- Production scheduler for periodic data refresh.
- Cached on-demand question answering separated from data download.
- Alternative-route optimization for fuel or comfort.

## Next Skills To Build

1. Query-context extraction:
   - current/shared location
   - destination
   - requested time
   - intent
2. Arbitrary route generation for routes not yet in `routes.json`.
3. Configurable corridor-width sampling instead of fixed route sample points.
4. A scheduled refresh command that downloads observations/forecasts every X
   minutes or hours.
5. A fast answer command that reads the latest snapshot without downloading data.
6. LLM communication layer that rewrites structured facts into captain language
   without inventing marine conditions.
7. Expanded decision types:
   - leave/wait
   - stay/move
   - comfort/risk
   - fuel/reroute
8. Validation loop comparing forecasts against SOCIB observations.
9. Separate baseline forecast storage for fair PredSea-vs-global-app marketing
   win detection.
10. Menorca Channel truth source integration for Alcudia-Ciutadella validation.
11. Scalar temperature and wind-speed forecast validation.
