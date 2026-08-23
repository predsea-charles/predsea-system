# PredSea Language v1 Design

## Goal

Define the canonical captain-facing language for PredSea.

PredSea is a decision aid, not an autopilot and not a replacement for the captain or official forecasts. Its job is to summarize forecasts, observations, and local knowledge into operational intelligence. The captain owns the decision.

This spec defines the visible response language for:

- `/routes/{route_id}/question`
- `/routes/{route_id}/briefing`
- place weather responses when they are rendered for humans
- WhatsApp text generated from the API

It does not change the meteorological or route-evidence calculations themselves.

## Core Principles

### 1. PredSea never owns the decision

Avoid language that sounds like an instruction or an order.

Avoid:

- `GO`
- `NO GO`
- `SAFE`
- `DANGEROUS`
- `LEAVE NOW`
- `DO NOT CROSS`
- `YOUR PLAN`
- `YOU SHOULD`
- `My plan`

Prefer:

- `Suggested timing`
- `Preferred window`
- `Conditions become less favourable`
- `Earlier departures offer better comfort`
- `Reduced comfort margins`
- `Conditions are manageable`
- `Consider reviewing the latest forecast`
- `Experienced crews would normally manage these conditions`

### 2. Speak like an experienced local captain

PredSea should sound like someone who has reviewed the charts, the forecast, and the local situation.

Good examples:

- `Earlier departures offer the best comfort margins.`
- `Conditions gradually deteriorate through the afternoon.`
- `Arrivals later in the day are likely to experience increased motion.`
- `The roughest conditions are expected near Ibiza this evening.`
- `Nothing operationally significant has changed.`
- `The latest forecast supports the earlier picture.`

### 3. Use windows, not exact times

Visible text should prefer operational windows instead of timestamps.

Avoid:

- `10:23`
- `20:00`
- `Window closes in 2 hours`

Prefer:

- `Early morning`
- `Late morning`
- `Through the afternoon`
- `During daylight hours`
- `Overnight`
- `During the evening`
- `Roughest conditions expected this evening`

Exact times should appear only when the captain explicitly asks for them.

### 4. Use Europe/Madrid local time in visible output

User-facing text should use local time. UTC belongs in technical evidence only.

Example:

- visible: `Early morning`
- evidence: `2026-06-12T06:00:00Z`

### 5. Avoid absolute safety language

Avoid:

- `Safe`
- `Guaranteed`
- `No issues`
- `Perfect`
- `Dangerous`
- `Will handle this easily`

Prefer:

- `Manageable`
- `Moderate comfort`
- `Reduced comfort`
- `Increased motion`
- `Less favourable`
- `Experienced crews should have no difficulty`
- `Guests are likely to notice movement`

### 6. Keep numbers out of the default answer

Do not expose dense numeric detail by default.

Avoid:

- `0.8m`
- `0.9m`
- `1.0m`
- `1.1m`

Prefer:

- `Conditions start relatively calm.`
- `Motion gradually increases.`
- `The roughest conditions are expected near arrival.`
- `Seas build steadily through the day.`

Detailed values belong in evidence mode or when explicitly requested.

### 7. Separate forecast changes from recommendation changes

Captains care more about operational change than numerical drift.

Bad:

- `Wave height increased from 1.2m to 1.3m.`

Better:

- `No operational change.`
- `The latest forecast supports the earlier picture.`
- `Preferred departure window remains unchanged.`

If the recommendation changes, the response must say why.

Example:

- `The earlier caution referred to the morning peak.`
- `According to the latest forecast and observations, that period has passed and afternoon conditions are now more favourable.`

## Priority Order

When response rules conflict, apply them in this order:

1. PredSea never owns the decision
2. Use local time only in visible output
3. Use windows, not exact times
4. Avoid absolute safety language
5. Avoid excessive numbers
6. Keep recommendations stable across follow-up questions
7. Expand detail only when the captain asks `why?` or requests evidence

## Default Response Structure

The default answer should be short and operational.

Recommended sections:

- `Recommendation`
- `Suggested timing`
- `Expected comfort`
- `Considerations`
- `Confidence`
- `What could change`

Example:

```text
Suggested timing: Earlier departures offer the best comfort margins.
Expected comfort: Moderate.
Considerations: Conditions become progressively less favourable later in the day. The roughest part is expected near arrival.
Confidence: Medium.
What could change: If the evening deterioration arrives later than expected, the preferred departure window may extend slightly.
```

## Fallback Behavior

When the forecast is stale, the observations are old, or the model and buoy picture disagree:

- say so plainly
- keep the recommendation conservative
- avoid inventing certainty

Example phrases:

- `The latest forecast supports the earlier picture, but buoy observations are older than usual.`
- `Nothing operationally significant has changed, but confidence is lower until the next update.`
- `Latest buoy observations are lower than the forecast. Recheck before departure.`

## Surface Scope

This language applies to:

- route question answers
- route briefings
- place weather summaries when shown to humans
- WhatsApp rendering

The same canonical stance should be phrased consistently across all surfaces.

## Forbidden Language

The following phrases should be removed from captain-facing output unless they are explicitly quoted as part of evidence:

- `safe`
- `safe crossing`
- `guaranteed smooth`
- `no issues`
- `you are good to go`
- `do not cross`
- `leave now`
- `my plan`
- `your plan`
- `you should`
- `window closes in 2 hours`
- `forecast run is fresh`
- `well within your envelope`
- `upper comfort threshold`

## Good vs Bad Examples

### Departure timing

Bad:

- `Depart at 10:23.`
- `Peak at 21:00.`

Good:

- `Leave before late morning.`
- `The roughest conditions are expected this evening.`

### Comfort

Bad:

- `Safe for a 20m yacht.`
- `Guaranteed smooth.`

Good:

- `More comfortable in the morning.`
- `Conditions remain manageable, though guests may notice movement later.`

### Forecast change

Bad:

- `Wave height changed from 1.2m to 1.3m.`

Good:

- `No operational change.`
- `The latest forecast supports the earlier picture.`

### Follow-up question consistency

Bad:

- First answer: `Do not leave today.`
- Second answer: `Comfortable this evening.`

Good:

- First answer: `Morning departures are preferred.`
- Second answer: `The same morning window remains the better option.`

## Relationship to the Recommendation Cache

This language spec does not define the operational recommendation itself.

It defines how the already-computed recommendation is rendered. The operational stance cache should remain canonical, and the language layer should translate that stance into the captain-facing surface without re-deriving the decision.

## Testing

Add tests that confirm:

- visible answers avoid forbidden language
- visible answers use local time wording
- exact timestamps do not appear by default
- repeated questions keep the same operational wording
- evidence views can still show technical UTC detail
- low-confidence and stale-observation cases produce conservative phrasing

## Implementation Note

This is a language contract, not a forecast engine change.

If the forecast engine says one thing and the language rules say another, the engine result wins on substance, but the rendered text must still follow this spec’s tone, safety boundaries, and time style.
