# 06. Conclusion & Engineering Roadmap

This document summarizes the technical achievements of the **PredSea** oceanographic forecasting architecture and outlines the future engineering roadmap.

---

## 1. Summary of Current Architectural State

PredSea's working hypothesis is that high-resolution ($1\text{ km}$) regional ocean modeling does not require expensive, dedicated supercomputer infrastructure — that serverless GCP Batch orchestration, parallel process-level Python pre-processing, and the CROCO/SWAN/WRF numerical engines can deliver it instead. As of this development cycle:

1.  **High-Resolution Coastal Granularity**: The 5 Western Mediterranean 1 km CROCO grids are defined and have compiled binaries; validated runs to date confirm numerical stability at 6h and 24h horizons (see `04_empirical_validation.md` for the exact per-region status), not yet a full operational forecast product.
2.  **Compute Orchestration**: CROCO and SWAN run as parallel per-region GCP Batch jobs sharing one upstream WRF run; `daily_orchestrator.py` now chains WRF → regional CROCO+SWAN submission → real Batch-status polling automatically (see `05_cloud_deployment_and_ops.md`). A 2026-07-29 production incident (a shared timeout budget between the WRF VM and the combined CROCO+SWAN Batch phase killed a live 6h test while 3 of 5 regions were still legitimately running) led to decoupling those two timeouts — see `05_cloud_deployment_and_ops.md` §1a. Specific pre-processing/runtime speed numbers have not been re-measured since this pipeline changed and are not repeated here to avoid restating stale figures.
3.  **Cost**: STANDARD (on-demand) provisioning is currently used deliberately for reliability during validation, not SPOT; a verified, current per-day cost figure for the full 5-region suite has not yet been compiled. SPOT is the intended cost-saving target once the pipeline is stable (see `05_cloud_deployment_and_ops.md`, Section 2).
4.  **Physical & Empirical Accuracy**: A verified fix exists for one specific bulk-flux sign-convention bug (`03_thermodynamics_and_fluxes.md`, Section 2). No comparison against SOCIB buoys, satellite SST, or other independent observations has been performed yet — this remains open work, not a completed accomplishment.
5.  **Wave Engine Migration (in progress)**: SWAN is being replaced project-wide by WaveWatch III (WW3) after exhaustive tuning ruled out every SWAN parameter as the cause of persistent non-convergence in 3 of the 5 regions (see `02_modeling_suite.md`, Section 5). A 5-region 6h WW3 breadth test has passed with a workload-proportional core allocation; a WRF-forced 24h, 5-region test is the next validation gate, currently blocked on a WRF domain-coverage fix. See `docs/agent-handoff-ww3-wrf-migration-2026-08-05.md` for exact current status.

---

## 2. Technical & Strategic Roadmap

### Milestone A: Multi-Day Diurnal Thermal Skin Layer Tracking
The CROCO 24-hour stability gate has passed for most regions (see `04_empirical_validation.md`), but multi-day forecasting ($96 - 120\text{ hours}$) during summer marine heatwaves requires higher vertical resolution in the upper $1\text{ meter}$ ocean skin layer:

*   **$s$-Coordinate Refinement**: Increase vertical levels from $N=32$ to $N=40$ or $N=50$, increasing surface stretching ($\theta_s = 8.0$) to place 5 vertical layers within the top $1\text{ meter}$.
*   **Diurnal Warm-Layer Modeling**: Integrate explicit Cool-Skin / Warm-Layer parameterizations (e.g. Fairall et al. COARE scheme) to track diurnal surface warming peaks ($+1.5^\circ\text{C} - 2.5^\circ\text{C}$ afternoon spikes) and nocturnal mixing decay.

### Milestone B: Full Operational CROCO-Wave Wave-Current Coupling
Expand two-way standalone runs into active three-way dynamic OASIS3-MCT coupled cycles. Written against SWAN below; given the SWAN→WW3 migration described in `02_modeling_suite.md` Section 5, this milestone's counterparty is expected to become WW3 once the migration completes, not SWAN — CROCO's own OASIS coupling toolbox is solver-agnostic on the wave side, so this does not change the milestone's feasibility, only which binary it targets:

*   **Wave Radiation Stress Feedback**: Dynamically pass SWAN $S_{xx}, S_{xy}, S_{yy}$ radiation stress gradients into CROCO to drive wave-induced longshore currents, wave setup in harbors, and wave-current bottom friction enhancement.
*   **Current Refraction Feedback**: Pass CROCO $1\text{ km}$ hourly surface currents back into SWAN to compute Doppler-shifted wave refraction in high-current channels (e.g., Ibiza-Formentera Freus channel).

### Milestone C: Automated Captain-Facing Decision APIs & Alerting
Bridge raw numerical model outputs directly to operational maritime decision tools:

*   **Vessel Response Threshold Engine**: Translate $1\text{ km}$ wave spectra, wind against current vectors, and cross-channel steepness into vessel-class safety statuses (`favorable`, `workable`, `conservative`, `restricted`) for small ($<12\text{m}$), medium ($12-24\text{m}$), and large ($>24\text{m}$) motor and sailing yachts.
*   **Automated Artifact Dispatch**: Automatically compile daily briefing maps, WhatsApp captain advisories, and LinkedIn operational summaries upon forecast completion.
*   **FastAPI / Deck.gl Production Endpoints**: Serve real-time oceanographic vector fields and wave condition layers to mobile and web dashboards at sub-second latencies.

---

## 3. Concluding Remarks

This document set describes an architecture in active development, not an operational product. The core design choices — one shared WRF run feeding independent per-region CROCO/SWAN Batch jobs, run-scoped GCS outputs, structural validation gates before publication — are in place and have started producing real, passing 6h/24h regional runs. What remains before this can honestly be called a validated forecasting platform for maritime operators is exactly what Section 2's roadmap and the open items in `05_cloud_deployment_and_ops.md` describe: multi-day horizon coverage across all 5 regions, real coupling between CROCO and SWAN, independent observational validation, and the reliability/observability hardening the architecture review identified. Overstating current status has been a recurring problem in earlier drafts of this document set; this rewrite is intended to fix that, not to replace one round of overclaiming with another.
