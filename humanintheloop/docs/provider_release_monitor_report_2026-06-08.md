# PredSea Provider Release Monitor Report

Generated: 2026-06-08  
Timezone used for operational interpretation: Mallorca local time, CEST (UTC+2)

## Scope

This report reviews the outputs from the GitHub Actions workflow:

`provider-release-monitor.yml`

and the archived monitor payloads in Google Cloud Storage:

`gs://predsea-daily-outputs/provider-monitor/`

The available GCS sample covers 2026-06-05 through 2026-06-08, with 62 probe runs and 248 dataset records.

The latest GitHub Actions artifact checked was run `27162999445`, created on 2026-06-08 at 19:52 UTC. It contains the same structure as GCS: one probe JSON plus the daily `provider_release_probes.jsonl`.

## Datasets Monitored

| Provider | Dataset | Meaning |
|---|---|---|
| Copernicus | `copernicus_currents` | Mediterranean surface currents forecast metadata |
| Copernicus | `copernicus_waves` | Mediterranean waves forecast metadata |
| SOCIB | `socib_sapo_waves` | SOCIB SAPO Balearic wave model runs from THREDDS |
| SOCIB | `socib_wmop_currents` | SOCIB WMOP surface hydrodynamic model runs from THREDDS |

## Key Findings

Copernicus is consistently reachable. Across the 62 probes reviewed, both Copernicus datasets were available every time.

SOCIB THREDDS is not consistently reachable from GitHub Actions. Across the same 62 probes, both SOCIB datasets were available 20 times and timed out 42 times. The observed error was:

`<urlopen error timed out>`

This means SOCIB is useful, but the ETL should treat it as an opportunistic secondary source unless retries/cache fallback are strong.

## First Seen Times

### Copernicus Currents

| Provider update time (local) | First seen by monitor (local) | Monitor lag |
|---|---:|---:|
| 2026-06-04 16:02 | 2026-06-05 12:31 | 20.5h |
| 2026-06-05 17:57 | 2026-06-05 19:00 | 1.1h |
| 2026-06-06 14:03 | 2026-06-06 14:43 | 0.7h |
| 2026-06-07 14:13 | 2026-06-07 14:47 | 0.6h |
| 2026-06-08 15:36 | 2026-06-08 15:44 | 0.1h |

Operational read: currents usually appear/update around early-to-mid afternoon local time in this sample. The first row is not representative because monitoring started after the previous update.

### Copernicus Waves

| Provider update time (local) | First seen by monitor (local) | Monitor lag |
|---|---:|---:|
| 2026-06-05 04:03 | 2026-06-05 12:31 | 8.5h |
| 2026-06-05 19:17 | 2026-06-05 19:47 | 0.5h |
| 2026-06-06 04:04 | 2026-06-06 05:20 | 1.3h |
| 2026-06-06 18:59 | 2026-06-06 19:36 | 0.6h |
| 2026-06-07 04:28 | 2026-06-07 05:23 | 0.9h |
| 2026-06-07 19:54 | 2026-06-07 20:40 | 0.8h |
| 2026-06-08 06:44 | 2026-06-08 07:48 | 1.1h |
| 2026-06-08 10:11 | 2026-06-08 11:51 | 1.7h |
| 2026-06-08 20:25 | 2026-06-08 21:03 | 0.6h |

Operational read: Copernicus waves have multiple daily metadata updates. Useful morning updates were first seen around 05:20, 07:48, or later depending on the day. Evening updates were usually seen around 19:30-21:00 local.

### SOCIB SAPO Waves

| Model run | First seen by monitor (local) | Approx lag from 00Z run |
|---|---:|---:|
| 2026-06-05 00Z | 2026-06-05 14:15 | 12.3h |
| 2026-06-06 00Z | 2026-06-06 14:43 | 12.7h |
| 2026-06-07 00Z | 2026-06-07 12:55 | 10.9h |
| 2026-06-08 00Z | 2026-06-08 10:05 | 8.1h |

Operational read: the SOCIB SAPO daily wave run appears much later than a captain would expect for a morning operational briefing. In this sample, the new run was first seen between 10:05 and 14:43 local.

### SOCIB WMOP Currents

| Model run | First seen by monitor (local) | Approx lag from 00Z run |
|---|---:|---:|
| 2026-06-05 00Z | 2026-06-05 14:15 | 12.3h |
| 2026-06-06 00Z | 2026-06-06 14:43 | 12.7h |
| 2026-06-07 00Z | 2026-06-07 12:55 | 10.9h |
| 2026-06-08 00Z | 2026-06-08 19:17 | 17.3h |

Operational read: WMOP currents are even less predictable than SAPO waves in this sample. On 2026-06-08 the current run was not first seen until 19:17 local.

## Reliability Summary

| Dataset | Probes | Available | Errors | Availability |
|---|---:|---:|---:|---:|
| Copernicus currents | 62 | 62 | 0 | 100% |
| Copernicus waves | 62 | 62 | 0 | 100% |
| SOCIB SAPO waves | 62 | 20 | 42 | 32% |
| SOCIB WMOP currents | 62 | 20 | 42 | 32% |

## Recommended ETL Timing

For the current MVP, Copernicus should remain the dependable base source for scheduled production runs.

Recommended daily ETL schedule:

| Local time | Purpose | Reason |
|---|---|---|
| 06:00-06:30 | Early morning operational package | Often catches Copernicus wave morning update; useful for captains planning early departures. |
| 08:30 | Morning customer-facing package | Practical delivery time; if SOCIB is missing, publish with Copernicus and freshness note. |
| 12:30-13:00 | Midday refresh | Good chance to capture SOCIB SAPO/WMOP if released; useful for afternoon decisions. |
| 16:00 | Afternoon/evening refresh | Captures Copernicus currents update on most observed days. |
| 20:30-21:15 | Evening planning package | Captures Copernicus wave evening update; useful for next-day planning. |

SOCIB should be checked opportunistically at each run, but the ETL should not fail if SOCIB times out.

## Operational Implications

1. A morning PredSea answer should not wait for SOCIB. The observed SOCIB first-seen times are too late and too unreliable for morning captain operations.
2. A midday or afternoon PredSea refresh is valuable because SOCIB may become available after 10:00-14:00 local.
3. The API should expose source freshness clearly, especially when SOCIB is absent or stale.
4. For customer trust, the agent should say something like: "Copernicus forecast is current; SOCIB high-resolution local run has not yet been available in today's monitor."

## Suggested Product Language

When SOCIB is missing:

`Current operational read is based on the latest Copernicus Mediterranean forecast. SOCIB local model was not available in the latest provider check, so local-model confidence is reduced.`

When SOCIB is available:

`Current operational read uses Copernicus plus the latest available SOCIB local model run. Confidence improves where both sources agree.`

## Suggested ETL Improvements

1. Keep provider monitor running hourly.
2. Do not fail the production ETL when SOCIB times out.
3. Store provider availability inside every evidence package:
   - `source`
   - `dataset`
   - `available`
   - `latest_model_run`
   - `provider_updated_at`
   - `first_seen_at`
   - `error`
4. Add a provider-status endpoint to the API, for example:
   - `GET /providers/status?date=latest`
5. Use the provider monitor to trigger extra ETL runs when a genuinely new dataset appears.

## Bottom Line

Copernicus is ready for scheduled operational use.

SOCIB is valuable, especially for local credibility and high-resolution interpretation, but the current observed delivery/reachability pattern means it should be treated as a bonus source with graceful fallback.

For captain-facing decisions, the best near-term strategy is:

`Copernicus-first, SOCIB-enhanced when available, always source-aware.`
