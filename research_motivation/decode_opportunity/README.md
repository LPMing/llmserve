# Decode-Opportunity-Aware KV Handoff — result bundle

This folder contains the reproducible small integrated FlowSim study. It validates a conditional connection between model-derived P2D handoff completion and the next legal Decode slot; it does **not** validate a production-wide online scheduler or a paper-ready SLO gain.

Read in order:

1. `01_TP_RANK_VALIDATION.md` — rank mapping, actual receiver and shared-cut checks.
2. `02_METRIC_SEMANTICS.md` — sampler boundary, reported TTFT/TTST and second-token definitions.
3. `03_THEORETICAL_OPPORTUNITY.md` and `03_COMPLETION_BOUNDS.csv` — first bound and correction for the final one-shard-per-request shared cut.
4. `04_DECODE_OPPORTUNITY_CALIBRATION.md` — naturally generated D0/D1 slot release and adjacent boundary checks.
5. `05_NETWORK_ONLY_RESULTS.csv` — isolated/coflow request grouping controls.
6. `06_SERVING_INTEGRATED_RESULTS.csv` plus `ledgers/` — full-DAG request, shard, batch, collective and targeted link records.
7. `07_KV_EP_FEEDBACK_ANALYSIS.md` — network→scheduler→token attribution and limits.
8. `08_SLO_AND_BASELINES.md`, `09_FAILURE_ANALYSIS.md`, `10_FINAL_GO_NO_GO.md` — metrics, related-work gate, final classification.
9. `RUN_PROVENANCE.md` and `run_integrated_controls.sh` — hashes and reproduction entrypoint.

Compact export sizes are modest; original simulation scratch outputs are under `/tmp` and are not needed to read the report. Re-run with `bash run_integrated_controls.sh /tmp/<new-run> MAIN` or `NEIGHBORS`; `ALL` runs both sets.
