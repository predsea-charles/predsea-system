# PredSea: 90-Day Roadmap and Business Model
*Prepared July 2, 2026 — post Google for Startups feedback ("too early stage" for the larger grant). Working budget: ~$1,700 GCP credit.*

## 1. Executive summary

PredSea has real, working assets: a live Cloud Run API (`predsea-api`, europe-west1) with 26 endpoints, 22 routes and 23 places across the Balearics and a handful of mainland Spanish ports, real multi-source evidence (Copernicus Marine, Puertos del Estado's REDEXT/REDCOS/REDMAR/HF_RADAR networks, EMODnet Physics), a human-domain-knowledge layer (Graham's captain rules), and informal pilot users already receiving briefings. What it doesn't have yet is proprietary physics simulation running in production (the WRF/NEMO/SWAN "own 1km model" story is a roadmap item, not a shipped one — see §2) or any paying customer.

Google's feedback is a signal, not a setback: right now PredSea is pitching HPC scale before it has revenue or a fully reconciled technical story. The highest-leverage use of the next 90 days and $1,700 is not a bigger simulation — it's converting the pilots you already have into paying customers using the system that already works, while running one small, well-documented HPC proof-of-concept that gives you real numbers (cost, runtime, accuracy) to bring back to Google or another funder later. Revenue + one credible technical proof point is a much stronger "graduation" case than a bigger ask with no revenue.

## 2. Honest state of the system (updated July 2 — from reading the actual code, not just the docs)

The first version of this section was based on documentation alone, which pointed to the proprietary WRF/NEMO/SWAN stack being purely aspirational. Reading the actual code changed that assessment — you're further along on infrastructure than the docs suggested, with one important correction sitting on top of that progress.

**Real, and further along than the docs suggested:**
- `scripts/daily_orchestrator.py` and `scripts/gcp_orchestrator.py` contain genuine, working GCE Spot VM automation — real `gcloud compute instances create --provisioning-model=SPOT` calls, status polling, and teardown, not pseudocode.
- Git history confirms real hands-on infrastructure work in the days right after the credit landed: "Configure successful custom WRF/WPS compilation on Cloud Build" (Jun 23), "complete Phase 2 custom WRF/ROMS high-resolution modeling setup" (Jun 23), "Fix premature GCE Spot VM termination" (Jun 25) — that last commit message in particular only gets written after something ran on real hardware and broke in a specific way.
- `scripts/wrf_forecast_ingestor.py`, `roms_forecast_ingestor.py`, and `swan_forecast_ingestor.py` are real, correctly written NetCDF parsers: they open real output files with `xarray`, do proper nearest-neighbor grid sampling against your actual place/route registry, apply correct unit conversions (Kelvin→Celsius, Pa→hPa, m/s→knots), and write into the same BigQuery `evidence_rows` schema your observation pipeline already uses. These are production-ready the moment real model output lands in the GCS path they expect.
- The Puertos del Estado observation connector does real, live THREDDS/Portuscopia discovery of buoy/tide-gauge/radar stations — not a hardcoded list.

**Still not real — the one correction that matters most:** `humanintheloop/hpc_cost_summary.json` (the file claiming "12/12 wins vs. CMEMS, $6.03 spent, proceed to production") is not a measurement. `humanintheloop/scripts/model_comparison.py` — the script that's supposed to load real forecast and observation data — instead generates synthetic values with `np.random.seed(42)` and deliberately gives your "own model" a smaller error term than CMEMS's, with a code comment that says outright this "demonstrates the potential accuracy gain from high-resolution localized models." That construction guarantees a near-universal win before any real data is touched. `hpc_cost_summary.py` compiles its cost figures from constants explicitly labeled `# Fixed known VM compile costs` whenever a real GCS cost report isn't present — which is what produced the numbers currently on file. Separately, `simulation/Dockerfile` only builds WRF/WPS today — there's no ROMS/SWAN/NEMO/CROCO build stage in it, so the coupled "own stack" isn't fully assembled in the production container yet, even though standalone compile scripts for each model exist and look real.

- **Internally inconsistent and still worth fixing before your next external conversation:** the modeling domain is defined three different ways across your own docs (ROMS/CROCO bounds vs. NEMO bounds vs. the roadmap's larger France/Italy bounds), and the Spot VM size is cited as three different machine types across different docs and scripts. A technical reviewer (at Google or elsewhere) finding three answers to "what's your grid resolution" is exactly what reads as "too early stage" — independent of how real the underlying engineering is.
- **A known, named bug:** the `/maps/overlays/{variable}/{filename}` endpoint has documented reliability/rendering issues — this is your map tile layer, the most visual, demo-able part of the product, so it's worth fixing early even though it's unglamorous.

**Bottom line on where you actually stand:** you have real GCP orchestration, at least one real successful WRF compilation, and production-ready ingestion code waiting for real data. What you don't yet have is a confirmed, complete WRF+ROMS+SWAN run whose output has actually been ingested and validated against real buoy observations — and the one document that claims you already have that (`hpc_cost_summary.json`) needs to be treated internally as a placeholder, not a result, until Appendix A is done. Also write (or let me help write) a single one-page "system of record" — one domain, one VM size, one honest sentence about proprietary-model vs. Copernicus-based today — before any of this goes into another deck.

## 3. Who to sell to first

You already have the right pilot profile in the informal usage that exists (Palma–Ibiza, Palma–Cabrera, Ibiza–Formentera, Alcudia–Ciutadella briefings, feedback from a named captain, Graham). The fastest path to revenue is not a new market — it's converting people already looking at your output.

**Immediate ICP (next 90 days):** independent charter yacht captains and small charter operators (2–10 boats) based in Mallorca/Ibiza, currently mid-season (July–September), who are already fielding "should we go today" questions from clients. This segment is small enough to reach by founder-led outreach, understands the value instantly (they already make this decision daily), and doesn't need the France/Italy/Canaries expansion story to say yes.

**Not yet the target:** superyacht captains and enterprise/cargo operators — those are the pitch deck's aspirational segments, and they'll expect the proprietary-model story to actually be true (higher resolution, SLA, hazard aggregation) before they pay enterprise prices. Chasing them now risks a credibility gap in the first sales conversation.

## 4. Business model recommendation

Given the current state, price and position on what's actually true today — multi-source fused evidence with freshness/confidence scoring, worst-segment route analysis, human-expert rules layered on top, delivered conversationally via WhatsApp — rather than on unbuilt physics.

- **Free trial** (2–4 weeks): full access, no card required. Purpose is to get 5–10 real captains using it through peak season and generate testimonials/usage data.
- **Captain plan** — flat monthly fee per vessel (roughly €25–40/month is a defensible range for a tool used daily for an operational decision, well below what one bad routing decision costs in fuel/time/client trust). Includes daily briefing, route questions via WhatsApp, place weather.
- **Operator plan** — per-fleet pricing (base fee + reduced per-vessel rate) for charter companies managing multiple boats. This tier doesn't need new tech yet, just a shared account/billing wrapper — good candidate for a "coming soon, join the pilot" waitlist rather than something to build now.
- **Do not price or pitch a premium/enterprise tier around proprietary simulation until the real validation in Appendix A exists.** Selling that today is the exact overreach Google just flagged.

Target for the 90 days: 5 paying captains by end of September. That's a small, credible number — enough to say "we have paying customers" in the next funding conversation, without needing to have solved enterprise sales.

## 5. Spending the $1,700 GCP credit deliberately

The credit is small — treat it as funding one focused proof point, not general infrastructure.

1. **Fix `/maps/overlays/...`** (cheap, high visual payoff — this is what a pilot customer or a Google reviewer will actually look at).
2. **Reconcile the domain/VM/cadence documentation** (no cost, but a prerequisite — do this before touching any credit-funded compute).
3. **Finish and validate the real run you're closer to than you thought.** You already have working Spot VM orchestration and at least one successful WRF compilation — this is not a start-from-scratch task, it's closing a loop: get one complete WRF+ROMS+SWAN run (or WRF+SWAN first, if ROMS isn't fully wired) producing real NetCDF output in GCS, run it through your existing, already-correct ingestors, and replace the synthetic comparison in `model_comparison.py` with a real one against real buoy observations. Full technical scope is in Appendix A.
4. **Keep the Cloud Run API as the always-on production path.** It already scales to zero and is cheap — don't let the HPC experiment touch the thing that's making pilots happy.
5. Track actual GCP spend against this credit weekly — a real cost table (compute, storage, egress) is itself useful evidence for a future grant application, since "we don't actually know what this costs yet" was implicitly part of why the ask looked premature.

## 6. 90-day plan

**Month 1 (July):** Fix the map overlay bug. Write the one-page reconciled system-of-record doc. Reach out directly to the 5–10 captains/operators already receiving informal briefings and convert 2–3 to the free trial with a committed end-date and a clear "then it's €X/month" expectation.

**Month 2 (August):** Complete the real WRF+ROMS+SWAN run, ingest it, and run the real (not synthetic) accuracy comparison per Appendix A. Document actual cost/runtime/accuracy — whatever it turns out to be. Convert free trials to paying (aim for 5 paying vessels by end of month). Start tracking the metrics in §7.

**Month 3 (September, before season closes):** Package the results — revenue traction + one real technical proof point + the reconciled architecture doc — into the next funding conversation, whether that's a reapplication to Google for Startups, another program, or angel/pre-seed conversations. Use the actual GCP cost data from the proof-of-concept to make a specific, defensible ask instead of a round number.

## 7. Metrics to start tracking now

**Business:** number of pilot captains, trial-to-paid conversion, MRR, WhatsApp questions per captain per week, churn/drop-off.

**Technical:** confidence-score distribution across live queries, uptime/freshness of each data source (Copernicus, Puertos del Estado, EMODnet), and — once the real run and real comparison in Appendix A are done — actual cost, wall-clock time, and real (not synthetic) accuracy versus the current Copernicus-based baseline.

## 8. Team roles for this plan

- **Charles** — HPC/ocean prediction: documentation reconciliation, map overlay fix, completing the real WRF/ROMS/SWAN run and validation (Appendix A), GCP cost tracking.
- **Matt** — product/WhatsApp: pilot captain relationships, trial-to-paid conversion, billing wrapper for the Operator tier.
- **Kobus** — WhatsApp dialog/UX: keeping the conversational experience smooth as real paying users (not just informal testers) start relying on it.
- **Graham** — domain expert: pilot customer introductions (his captain network), QA on whether the answers actually match what an experienced captain would say — this is your most defensible differentiator, so keep him close to every pilot conversation.

## 9. Bottom line

The strongest next pitch to Google (or anyone else) isn't "give us more credit for bigger models." It's "we took $1,700, got 5 paying captains through Balearic season, fixed a real production bug, and finished a real, honestly-validated WRF+ROMS+SWAN run that tells you exactly what it costs and how accurate it is at scale." That's a graduation story, not an early-stage one — and unlike the version of this pitch that existed on July 2, every number in it will survive someone reading the code.

## Appendix A: Scope to replace synthetic validation with a real WRF/ROMS/SWAN vs. real buoy comparison

Goal: turn `model_comparison.py` and `hpc_cost_summary.json` from fabricated placeholders into a real, defensible result — using code that, encouragingly, mostly already exists and is already correct.

**Step 1 — Get one complete model run's output into GCS in the shape the ingestors expect.**
Use the existing orchestration (`scripts/gcp_orchestrator.py`, `scripts/daily_orchestrator.py`, `scripts/vm_startup.sh`) to run WRF (plus ROMS/SWAN if compiled and ready — start with WRF+SWAN alone if ROMS isn't fully wired yet) for one real day, end to end, without interruption. Output must land at `gs://<bucket>/predictions/{run_date}/runs/{run_id}/` with filenames the ingestors already look for (containing `d03`/`wrfout` for WRF, `roms`/`his`/`avg` for ROMS, `swan`/`wave` for SWAN — see the `download_*_file_from_gcs()` function in each ingestor). This is the one step that costs real GCP credit and your real time; everything after it is software work you can do without spending more.
*Effort: mostly waiting/monitoring plus fixing whatever breaks — you've already hit and fixed one real failure mode (premature Spot VM termination), so budget for at least one more surprise.*

**Step 2 — Run the existing ingestors against that real output.**
`wrf_forecast_ingestor.py`, `roms_forecast_ingestor.py`, and `swan_forecast_ingestor.py` are already correctly written for this — no code changes needed, just execution (e.g. `python scripts/wrf_forecast_ingestor.py --run-date ... --run-id ...`, and the ROMS/SWAN equivalents) pointed at the real bucket. Confirm rows land in BigQuery `evidence_rows` with `forecast_source_id` = `predsea_wrf` / `predsea_roms` / `predsea_swan`.
*Effort: low — this is running existing code, not writing new code.*

**Step 3 — Reconcile the comparison stations with your real observation network.**
`model_comparison.py`'s `STATIONS` dict currently hardcodes four placeholder names (`dragonera_buoy`, `mahon_buoy`, `palma_buoy`, `valencia_buoy`) with hand-typed lat/lon — these don't correspond to the dynamically discovered station IDs your real Puertos del Estado connector (`station_catalog.py`) actually produces. Before comparing anything real, pick 3–5 real, currently-reporting REDEXT/REDCOS (or SOCIB, if still flowing) stations close enough to your model domain to be useful, using their real `station_id`s.
*Effort: small — mostly a query against your existing station catalog / BigQuery `station_metadata` table.*

**Step 4 — Replace the synthetic data generator with a real BigQuery query.**
Rewrite `fetch_predictions_and_observations()` to, for each variable/station/time window, pull real forecast rows (matching `forecast_source_id` for WRF/ROMS/SWAN) and real observation rows (`source_system` = `puertos_del_estado`/`socib`) from `evidence_rows`, matched by station proximity and a time tolerance (e.g. nearest observation within ±30 minutes of each forecast timestamp). The existing `compute_metrics()` function (RMSE/bias/correlation/MAE) is already correct and doesn't need to change — only what feeds it does.
*Effort: medium — the one real piece of new code on this list, roughly a day of focused work; the BigQuery schema is already documented in `humanintheloop/docs/bigquery-evidence-rows.md`.*

**Step 5 — Make `hpc_cost_summary.py` pull real costs.**
Replace the `# Fixed known VM compile costs` constants with either a Cloud Billing export query or, more simply, actual VM runtime (from `gcloud compute instances describe` / your own run logs) multiplied by the published Spot price for the machine type used. Doesn't need to be fancy — it just needs to stop being a hardcoded guess.
*Effort: small.*

**Step 6 — Add a guardrail so this can't silently happen again.**
Tag every generated report with an explicit `"data_source": "real"` or `"data_source": "synthetic_fallback"` field, and make `hpc_cost_summary.py` refuse to output `recommendation: proceed_to_production` when any input is a fallback. This is the highest value-per-minute item on this list — cheap insurance against a placeholder ever being mistaken for a result again.
*Effort: trivial.*

**What this gets you:** a real number instead of a fabricated one — likely a more modest, more credible win rate (or even a loss on some variables, which is normal and fine for a first real high-resolution run) that you can put in front of Google, an investor, or your own team honestly. If the real result turns out good, it's a far stronger asset than "12/12" ever was, precisely because it will survive someone reading the code behind it.

**Status as of July 2:** Steps 2, 4, and 5 above are done — `scripts/{wrf,roms,swan}_forecast_ingestor.py` now carry real latitude/longitude through to BigQuery, `humanintheloop/scripts/model_comparison.py` was rewritten to query real forecast/observation rows and match them by real distance and time (never fabricates a result, tested in `tests/test_model_comparison.py`), and `humanintheloop/scripts/hpc_cost_summary.py` was rewritten to only report real or clearly-labeled-estimate costs and never auto-recommend "proceed to production" (tested in `tests/test_hpc_cost_summary.py`). The stale `humanintheloop/hpc_cost_summary.json` claiming 12/12 wins has been replaced with an honest placeholder. What's left is Step 1 — actually running a real WRF+SWAN (and ROMS, if wired) job on GCP — which needs your live credentials and can't be done from here. See `docs/real-validation-runbook.md` for the exact commands.
