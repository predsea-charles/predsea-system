# Route Confidence Scoring

## Goal
Make route confidence less brittle while staying conservative when the evidence is weak.

The current scorer is too eager to return `Low` when:
- there is no same-day prior run,
- a source is offline,
- or the route comparison signal is missing a clean prior snapshot.

We want the scorer to:
- keep `single_model_consistency` as the default method,
- compare the current route forecast against the previous available forecast, even if that prior forecast is from a previous day,
- penalize confidence when a source is offline,
- and explain why the score is low in a way that is useful to captains and operators.

## Scope
This change applies to the API request-time reliability block returned by route question responses.

It does not change:
- database schema,
- ETL storage,
- route geometry,
- or the external response envelope beyond the existing `reliability` block.

## Inputs Used By The Scorer
The scorer should evaluate the following request-time inputs:

- current route snapshot
- latest place-weather evidence for the route endpoints
- current source freshness metadata
- the previous available route forecast snapshot

The scorer should look for the most recent earlier route snapshot even when it is not in the same day. If the forecast bundle exists for the time being asked about, that forecast should be compared against the current route snapshot.

## Confidence Logic

### Default method
Use `single_model_consistency` unless a real multi-model comparison is available.

### Comparison rule
Compare the current route snapshot against the latest prior forecast snapshot for the same route.

Prefer:
1. same-day earlier runs,
2. then the latest run from the most recent earlier date.

### Offline source penalty
If a relevant source is offline, reduce confidence by one step unless the overall score is already `Low`.

Offline source status should matter on its own. It is not just a note.

### Lower-bound rule
The final confidence score is the lowest safe score after all checks are combined.

That means:
- freshness can say `High`,
- but offline source status or forecast variance can still push the final result to `Medium` or `Low`.

## Thresholds

### Freshness
- `High`: age under 180 minutes
- `Medium`: age between 180 and 360 minutes
- `Low`: age over 360 minutes

### Forecast variance
For single-model route consistency:
- `High`: variance under 10%
- `Medium`: variance between 10% and 25%
- `Low`: variance over 25%

### Offline source adjustment
- `High` may drop to `Medium`
- `Medium` may drop to `Low`
- `Low` stays `Low`

## Reasoning Output
The `reliability` block should explain the score with a short human-readable reason.

Examples:
- Previous forecast snapshot was unavailable, so the scorer stayed conservative.
- A relevant source was offline, which lowered confidence.
- The route changed sharply between consecutive forecasts.
- Freshness and consistency both looked acceptable.

The `details` object should continue to include the comparison kind and the metrics used to reach the score.

## API Output Contract
Keep the existing `reliability` block shape and continue returning:

- `confidence_score`
- `evaluation_method`
- `age_minutes`
- `reason`
- `details`

The API should keep `evaluation_method` as `single_model_consistency` by default.

## Implementation Notes
- Add the offline-source penalty in the scorer, not in the database or ETL.
- Prefer comparing route snapshots over guessing from a missing same-day run.
- Keep the final score conservative, but do not collapse everything to `Low` just because one source is absent.

## Testing
Add or update tests to cover:
- same-day previous forecast comparison,
- previous-day fallback comparison,
- offline source penalty,
- and the new reason text when confidence is lowered.

The tests should prove that the scorer:
- uses the prior available forecast when same-day history is missing,
- drops confidence when a source is offline,
- and explains why the score moved down.
