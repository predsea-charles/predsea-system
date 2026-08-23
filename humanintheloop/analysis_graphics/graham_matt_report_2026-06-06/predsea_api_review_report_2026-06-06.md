# PredSea API Review Pack for Graham and Matt

Generated: 2026-06-06 17:47 UTC

Route reviewed: **Palma -> Ibiza**

Repeated question: **When is the best moment to leave from Palma to Ibiza today?**

Vessel profile used: **medium / 15-24m**

Important note: each question was sent with the local time corresponding to that forecast run. This lets us see how the live API would answer around the time each package became available.

## 1. Five-Day Evidence Snapshot

| Date | Run | Local time | Forecast wave m | Peak | Peak dir deg | Max current kn | Palma buoy m | Ibiza buoy m | Confidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-06-02 | 2026-06-02T2121Z | 23:21 | 0.4 - 1.5 | 07:00 | 74.0 | 0.8 | 0.4 | 0.8 | medium |
| 2026-06-03 | 2026-06-03T1923Z | 21:23 | 0.7 - 1.3 | 14:00 | 62.0 | 0.7 | 0.3 | 1.2 | medium |
| 2026-06-04 | 2026-06-04T2157Z | 23:57 | 0.8 - 2.1 | 09:00 | 50.0 | 0.8 | missing | missing | low |
| 2026-06-05 | 2026-06-05T1622Z | 18:22 | 0.5 - 1.9 | 11:00 | 60.0 | 0.8 | 0.3 | 1.9 | medium |
| 2026-06-06 | 2026-06-06T1556Z | 17:56 | 0.5 - 1.0 | 15:00 | 110.0 | 0.4 | missing | missing | low |

## 2. Same Question, Different Days

### 2026-06-02 — run 2026-06-02T2121Z (23:21 local)

Evidence headline: forecast wave range **0.4 - 1.5 m**, peak around **07:00**, Ibiza Channel buoy **0.8 m**.

API answer:

```text
Decision: Palma -> Ibiza: Today's practical daylight window has passed; use this as tomorrow morning planning guidance.

Best window: Prefer the lower sea-state window and avoid the forecast peak around 18:00.

Comfort: Moderate. Workable, but not flat calm for guests or sensitive passengers. For this vessel size: 15-24m, use conservative timing.

Risk: Moderate. Peak wave height is near 0.4 m around 18:00.

Why: Latest route signal is: waves build toward 1.5 m around 07:00. Recheck the morning run and buoy observations before committing. Captain knowledge: Departing near the forecast wave peak reduces comfort margin and gives little room if the model timing is late or early.

What could change: the timing or height of the forecast peak shifts in the next run; swell and wind-wave partition data changes the comfort read; Prefer a lower sea-state window before the peak, then confirm with the latest run and observations. Evidence note: this uses combined wave height and mean wave direction; swell and wind-wave components are not available in this evidence package.

Confidence: medium.
```

### 2026-06-03 — run 2026-06-03T1923Z (21:23 local)

Evidence headline: forecast wave range **0.7 - 1.3 m**, peak around **14:00**, Ibiza Channel buoy **1.2 m**.

API answer:

```text
Decision: Palma -> Ibiza: Today's practical daylight window has passed; use this as tomorrow morning planning guidance.

Best window: Prefer the lower sea-state window and avoid the forecast peak around 16:00.

Comfort: Moderate to good. Generally manageable, with comfort still depending on period, direction, and passenger sensitivity. For this vessel size: 15-24m, conditions look manageable.

Risk: Low to moderate. Peak wave height is near 1.3 m around 16:00.

Why: Latest route signal is: forecast peak near 1.3 m around 14:00. Recheck the morning run and buoy observations before committing. Captain knowledge: Departing near the forecast wave peak reduces comfort margin and gives little room if the model timing is late or early.

What could change: the timing or height of the forecast peak shifts in the next run; swell and wind-wave partition data changes the comfort read; Prefer a lower sea-state window before the peak, then confirm with the latest run and observations. Evidence note: this uses combined wave height and mean wave direction; swell and wind-wave components are not available in this evidence package.

Confidence: medium.
```

### 2026-06-04 — run 2026-06-04T2157Z (23:57 local)

Evidence headline: forecast wave range **0.8 - 2.1 m**, peak around **09:00**, Ibiza Channel buoy **missing**.

API answer:

```text
Decision: Palma -> Ibiza: Today's practical daylight window has passed; use this as tomorrow morning planning guidance.

Best window: Prefer the lower sea-state window and avoid the forecast peak around 19:00.

Comfort: Moderate. Workable, but not flat calm for guests or sensitive passengers. For this vessel size: 15-24m, use conservative timing.

Risk: Moderate. Peak wave height is near 1.2 m around 19:00.

Why: Latest route signal is: forecast peak near 2.1 m around 09:00. Recheck the morning run and buoy observations before committing. Captain knowledge: Departing near the forecast wave peak reduces comfort margin and gives little room if the model timing is late or early.

What could change: the timing or height of the forecast peak shifts in the next run; Prefer a lower sea-state window before the peak, then confirm with the latest run and observations. Sea-state detail: At the peak, combined seas are a bow quartering sea from about 199 degrees. Primary swell 0.4 m from 254 degrees; secondary swell 0.3 m from 117 degrees; wind wave 1.1 m from 194 degrees.

Confidence: low.
```

### 2026-06-05 — run 2026-06-05T1622Z (18:22 local)

Evidence headline: forecast wave range **0.5 - 1.9 m**, peak around **11:00**, Ibiza Channel buoy **1.9 m**.

API answer:

```text
Decision: Palma -> Ibiza is workable for the requested forecast day, but avoid the local peak around 13:00.

Best window: Prefer the lower sea-state window and avoid the forecast peak around 13:00.

Comfort: Moderate to poor. Manageable only with conservative timing; guests may find it uncomfortable. For this vessel size: 15-24m, use conservative timing.

Risk: Moderate. Peak wave height is near 1.9 m around 13:00.

Why: The previous best window was morning to early afternoon, and the main remaining watch-out is: forecast peak near 1.9 m around 11:00. Captain knowledge: Departing near the forecast wave peak reduces comfort margin and gives little room if the model timing is late or early.

What could change: the timing or height of the forecast peak shifts in the next run; Prefer a lower sea-state window before the peak, then confirm with the latest run and observations. Sea-state detail: At the peak, combined seas are a following sea from about 60 degrees. Primary swell 0.9 m from 8 degrees; secondary swell 0.7 m from 28 degrees; wind wave 1.5 m from 82 degrees.

Confidence: medium.
```

### 2026-06-06 — run 2026-06-06T1556Z (17:56 local)

Evidence headline: forecast wave range **0.5 - 1.0 m**, peak around **15:00**, Ibiza Channel buoy **missing**.

API answer:

```text
Decision: Palma -> Ibiza is workable for the requested forecast day, but avoid the local peak around 12:00.

Best window: Leave around 18:00 within the requested forecast day. Avoid the local peak around 12:00, when wave height peaks around 0.7 m.

Comfort: Moderate to good. Generally manageable, with comfort still depending on period, direction, and passenger sensitivity. For this vessel size: 15-24m, conditions look manageable.

Risk: Low to moderate. Peak wave height is near 0.7 m around 12:00.

Why: Forecast peak is near 0.7 m around 12:00, while the sampled route value near 18:00 is about 0.5 m. Mean wave direction near the peak is about 93 degrees. Captain knowledge: Departing near the forecast wave peak reduces comfort margin and gives little room if the model timing is late or early.

What could change: the timing or height of the forecast peak shifts in the next run; Prefer a lower sea-state window before the peak, then confirm with the latest run and observations. Sea-state detail: At the peak, combined seas are a stern quartering sea from about 93 degrees. Primary swell 0.5 m from 115 degrees; secondary swell 0.4 m from 18 degrees; wind wave 0.0 m from 84 degrees.

Confidence: low.
```

## 3. Different Evidence During One Day: 2026-06-06

| Run | Local time | Forecast wave m | Peak | Peak dir deg | Max current kn | Ibiza buoy m | Decision line | Best window line |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-06-06T0647Z | 08:47 | 0.5 - 1.0 | 01:00 | 77.0 | 0.5 | 0.7 | Palma -> Ibiza is workable for the requested forecast day, but avoid the local peak around 03:00. | Leave around 13:00 within the requested forecast day. Avoid the local peak around 03:00, when wave height peaks around 1.0 m. |
| 2026-06-06T0732Z | 09:32 | 0.5 - 1.0 | 02:00 | 79.0 | 0.5 | 0.7 | Palma -> Ibiza is workable for the requested forecast day, but avoid the local peak around 04:00. | Leave around 13:00 within the requested forecast day. Avoid the local peak around 04:00, when wave height peaks around 1.0 m. |
| 2026-06-06T1556Z | 17:56 | 0.5 - 1.0 | 15:00 | 110.0 | 0.4 |  | Palma -> Ibiza is workable for the requested forecast day, but avoid the local peak around 12:00. | Leave around 18:00 within the requested forecast day. Avoid the local peak around 12:00, when wave height peaks around 0.7 m. |

### Full conversations for 2026-06-06

#### Run 2026-06-06T0647Z (08:47 local)

Captain:

> When is the best moment to leave from Palma to Ibiza today?

PredSea:

```text
Decision: Palma -> Ibiza is workable for the requested forecast day, but avoid the local peak around 03:00.

Best window: Leave around 13:00 within the requested forecast day. Avoid the local peak around 03:00, when wave height peaks around 1.0 m.

Comfort: Moderate to good. Generally manageable, with comfort still depending on period, direction, and passenger sensitivity. For this vessel size: 15-24m, conditions look manageable.

Risk: Low to moderate. Peak wave height is near 1.0 m around 03:00.

Why: Forecast peak is near 1.0 m around 03:00, while the sampled route value near 13:00 is about 0.6 m. Mean wave direction near the peak is about 77 degrees. Captain knowledge: Departing near the forecast wave peak reduces comfort margin and gives little room if the model timing is late or early.

What could change: the timing or height of the forecast peak shifts in the next run; Prefer a lower sea-state window before the peak, then confirm with the latest run and observations. Sea-state detail: At the peak, combined seas are a following sea from about 77 degrees. Primary swell 0.8 m from 101 degrees; secondary swell 0.6 m from 15 degrees; wind wave 0.2 m from 110 degrees.

Confidence: medium.
```

#### Run 2026-06-06T0732Z (09:32 local)

Captain:

> When is the best moment to leave from Palma to Ibiza today?

PredSea:

```text
Decision: Palma -> Ibiza is workable for the requested forecast day, but avoid the local peak around 04:00.

Best window: Leave around 13:00 within the requested forecast day. Avoid the local peak around 04:00, when wave height peaks around 1.0 m.

Comfort: Moderate to good. Generally manageable, with comfort still depending on period, direction, and passenger sensitivity. For this vessel size: 15-24m, conditions look manageable.

Risk: Low to moderate. Peak wave height is near 1.0 m around 04:00.

Why: Forecast peak is near 1.0 m around 04:00, while the sampled route value near 13:00 is about 0.6 m. Mean wave direction near the peak is about 79 degrees. Captain knowledge: Departing near the forecast wave peak reduces comfort margin and gives little room if the model timing is late or early.

What could change: the timing or height of the forecast peak shifts in the next run; Prefer a lower sea-state window before the peak, then confirm with the latest run and observations. Sea-state detail: At the peak, combined seas are a following sea from about 79 degrees. Primary swell 0.8 m from 104 degrees; secondary swell 0.5 m from 15 degrees; wind wave 0.1 m from 116 degrees.

Confidence: medium.
```

#### Run 2026-06-06T1556Z (17:56 local)

Captain:

> When is the best moment to leave from Palma to Ibiza today?

PredSea:

```text
Decision: Palma -> Ibiza is workable for the requested forecast day, but avoid the local peak around 12:00.

Best window: Leave around 18:00 within the requested forecast day. Avoid the local peak around 12:00, when wave height peaks around 0.7 m.

Comfort: Moderate to good. Generally manageable, with comfort still depending on period, direction, and passenger sensitivity. For this vessel size: 15-24m, conditions look manageable.

Risk: Low to moderate. Peak wave height is near 0.7 m around 12:00.

Why: Forecast peak is near 0.7 m around 12:00, while the sampled route value near 18:00 is about 0.5 m. Mean wave direction near the peak is about 93 degrees. Captain knowledge: Departing near the forecast wave peak reduces comfort margin and gives little room if the model timing is late or early.

What could change: the timing or height of the forecast peak shifts in the next run; Prefer a lower sea-state window before the peak, then confirm with the latest run and observations. Sea-state detail: At the peak, combined seas are a stern quartering sea from about 93 degrees. Primary swell 0.5 m from 115 degrees; secondary swell 0.4 m from 18 degrees; wind wave 0.0 m from 84 degrees.

Confidence: low.
```


## 4. What This Report Already Shows

- The system is now useful enough to review with a captain: it gives a decision, timing, comfort, risk, reasoning, uncertainty, and sea-state components.
- The system is also not yet captain-grade: it can still over-focus on the lowest wave value instead of a practical departure strategy.
- Missing observations need to be shown clearly, because confidence changes when buoy truth is unavailable.
- Route-level advice is not enough for Palma -> Ibiza. Graham's waypoint/turning-point comment should become a core design input.
- The repeated question is a good test because it exposes whether the agent truly understands time, route exposure, and operational context.

## 5. Initial Read Before the Graham/Matt Meeting

- The API is now consistently returning structured co-captain answers: Decision, Best window, Comfort, Risk, Why, What could change, Confidence.
- The evidence is much richer than before: significant wave height, wave direction, current speed, primary/secondary swell, wind-wave component, buoy observations when available.
- The weakest area is not data access anymore. It is operational interpretation: the system still sometimes chooses the lowest wave point rather than a captain-preferred departure window.
- Graham’s waypoint point is visible here: a route-level answer hides where along Palma -> Ibiza the discomfort is expected. We should discuss operational waypoints and segment-specific advice before changing the API semantics.
- Confidence is still label-based. Before turning it into 0-100, we need Graham’s definition of what confidence means operationally.

## 6. Suggested Meeting Questions

1. For Palma -> Ibiza, which waypoints or segments should PredSea always inspect?
2. When wave height is low but timing is late, should the agent prefer “go now”, “wait”, or “use next morning”?
3. What makes a forecast change material enough to alert a captain? Wave height delta, direction shift, current change, or segment exposure?
4. What should “Confidence: medium” mean in captain language?
5. Which answer in this report feels closest to a real co-captain, and which feels least useful?

## 7. Files

- Raw API responses: `raw_api_responses.json`
