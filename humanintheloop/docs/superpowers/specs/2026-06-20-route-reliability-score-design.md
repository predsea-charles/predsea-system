# Route Reliability Score Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dynamic `reliability` block to the route question JSON response, computed inside the API at request time from both route snapshot evidence and the latest place-weather evidence.

**Architecture:** Keep the score local to the API process and compute it only when `/routes/{route_id}/question` is handled. A small helper module will gather freshness timestamps, route snapshot evidence, and latest place-weather payloads, then resolve a conservative confidence score using the lowest safe result across freshness and variance/consistency. The response payload shape stays the same except for one new `reliability` object; existing `operational_stance` fields remain intact for compatibility.

**Tech Stack:** Python, FastAPI, Pydantic, existing `EvidenceStore` / `GcsEvidenceStore`, existing `decision_engine` and `api.services`, `pytest`.

---

## Background

The route-question endpoint already returns a structured JSON payload with `operational_stance`, `evidence_used`, and freshness metadata. Today the visible confidence remains qualitative and is still effectively a fallback. The new requirement is to compute a machine-readable confidence result dynamically inside the API process and expose it as:

```json
"reliability": {
  "confidence_score": "High",
  "evaluation_method": "multi_model_consensus",
  "age_minutes": 42
}
```

This should happen without changing any database schema and without changing the existing top-level payload contract beyond adding the `reliability` field.

## Scope

This change applies to the JSON response returned by `POST /routes/{route_id}/question`.

It does **not** change:
- the BigQuery schema
- the ETL storage shape
- the text-only briefing endpoint
- the existing `operational_stance` payload

The new scorer must read both:
- the route snapshot / route evidence already loaded for the question
- the latest place-weather evidence for the places involved in the route

## Design

### 1. New reliability helper

Add a focused helper module in the API layer, for example `api/reliability.py`, that accepts:
- the loaded route snapshot
- the route question request
- the current `EvidenceStore`

The helper will:
- collect the route snapshot evidence already used by the response
- load the latest place-weather payloads relevant to the route
- compute freshness age in minutes
- detect whether multi-model consensus is available
- otherwise fall back to single-model run-over-run consistency
- resolve the final score using the strict lower-bound rule

### 2. Data inputs

The scorer should read from:
- `store.load_snapshot(route_id, run_date, run_id)`
- `store.load_place_weather(place_id, run_date, run_id)` for the route’s relevant places
- route fields already present in snapshot data, such as `forecast`, `observations`, `route_connection`, and `data_lineage`
- place-weather fields such as `observed_at_utc`, `source_time_coordinate_utc`, `freshness_state`, `freshness_status`, `source_label`, and `network`

Relevant places should be derived from the route context already available in the snapshot and route metadata, rather than inventing a new registry or database lookup path.

### 3. Freshness age

`age_minutes` is the delta in minutes between the current system time and the oldest contributing model update used in the response.

Rules:
- prefer `source_time_coordinate_utc`
- then `observed_at_utc`
- then any route snapshot evidence timestamp already available
- if multiple evidence sources are used, take the oldest timestamp
- if timestamps are missing, return a conservative sentinel age and a low score rather than failing the request

### 4. Variance / consistency path

The scorer chooses one of two methods:

#### Multi-model consensus
Use this when both a regional high-resolution model and a global baseline model are present in the data for the same request. Compute:

`V_model = (|Regional - Global| / Global) * 100`

Use the strongest comparable scalar available in the route context for the current request, such as the current wave-height or weather field already exposed in the snapshot. The exact variable choice must be consistent inside the helper and documented in the code.

#### Single-model consistency
Use this when only one model stream is available. Compare the current run against the previous run cycle for the same target time block:

`V_run = (|Current_Run - Previous_Run| / Previous_Run) * 100`

The helper should resolve the previous run from the same date when possible, and fall back to the latest prior run for that date when needed.

### 5. Threshold matrix

Resolve the score conservatively:

**High**
- `age_minutes < 180`
- and `V_model < 15%` or `V_run < 10%`

**Medium**
- `180 <= age_minutes <= 360`, or
- `15% <= V_model <= 30%`, or
- `10% <= V_run <= 25%`

**Low**
- `age_minutes > 360`, or
- `V_model > 30%`, or
- `V_run > 25%`

Final resolution rule:
- if any evaluated dimension maps lower, the final `confidence_score` must be the lower result
- freshness can cap the score even when variance looks strong
- variance can cap the score even when freshness is high

### 6. Output contract

Extend `QuestionResponse` to include:

```json
"reliability": {
  "confidence_score": "High",
  "evaluation_method": "multi_model_consensus",
  "age_minutes": 42
}
```

Allowed values:
- `confidence_score`: `High`, `Medium`, `Low`
- `evaluation_method`: `multi_model_consensus`, `single_model_consistency`

Keep `operational_stance.confidence` and `operational_stance.confidence_detail` unchanged so existing consumers still work.

## Implementation files

- Modify `api/app.py`
  - compute reliability inside the route question handler
  - inject the new `reliability` block into the JSON response

- Modify `api/schemas.py`
  - add a Pydantic model or typed dict for the `reliability` block
  - add the new field to `QuestionResponse`

- Add `api/reliability.py`
  - load supporting evidence
  - compute age, variance/consistency, and the final score
  - return a plain dictionary ready for the response payload

- Modify `api/services.py` only if needed
  - keep the existing decision and operational stance logic intact
  - avoid moving the scorer into ETL or storage layers

- Add tests in `test_api_app.py`
  - response includes `reliability`
  - high / medium / low threshold cases
  - multi-model and single-model method selection
  - conservative lower-bound behavior
  - graceful fallback when weather evidence is sparse

## Error handling

The scorer must never make the question endpoint fail just because the reliability inputs are incomplete.

If the helper cannot find sufficient data:
- return `confidence_score = "Low"`
- return the best method label that applies to the available evidence
- keep `age_minutes` as an integer sentinel rather than raising

The route question endpoint should still return the same answer text and stance fields even when the reliability helper degrades gracefully.

## Testing

Minimum tests:
- the route-question JSON response includes the new `reliability` block
- a fresh, low-variance request resolves to `High`
- stale evidence resolves to `Low`
- intermediate freshness or variance resolves to `Medium`
- if both freshness and variance are available, the lower result wins
- if only single-model evidence exists, the method is `single_model_consistency`
- if both model families exist, the method is `multi_model_consensus`

## Non-goals

- No database schema changes
- No ETL rewrite
- No new briefing text format
- No change to the existing `operational_stance` contract
- No score storage outside the API response for this first pass
