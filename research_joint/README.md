# Network–Serving joint research gate

This directory records a bounded theory-first investigation. It does **not** introduce a production scheduler. Full configuration/run provenance and negative controls are in `00_BASELINE_AUDIT.md`; the final stop decision is `15_FINAL_GO_NO_GO.md`.

## Reproduce the bounded B experiment

Use the repository root and the recorded environment. The original transient ASTRA input trees are auto-cleaned after a successful run, so these are canonical replay commands (explicitly spell out the effective `LAYERWISE` default):

```bash
timeout 180s env PYTHONPATH=.:astra-sim/extern/graph_frontend \
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
FLOWSIM_MAX_TELEMETRY_ROWS=200000 FLOWSIM_MAX_FLOW_TELEMETRY_ROWS=200000 \
/home/lpm/.conda/envs/llmsim-flowsim/bin/python -u -m serving \
  --network-backend flowsim \
  --cluster-config experiments/pd_kv_ep/configs/ep_ep_minimal/two_ep4_groups_full.json \
  --dataset experiments/pd_kv_ep/workloads/two_ep4_groups_full_8req.jsonl \
  --num-reqs 8 --request-routing-policy RR \
  --max-num-seqs 8 --max-num-batched-tokens 512 \
  --no-enable-prefix-caching --no-enable-chunked-prefill \
  --pd-kv-transfer-mode LAYERWISE --flowsim-policy FAIR \
  --log-level WARNING --log-interval 60 \
  --run-id <unique-run-id> --output <request-output.csv> \
  --flowsim-telemetry <telemetry.jsonl>
```

For B3 add `--research-decode-phase-delay-ns 20000 --research-decode-phase-dp-group ep_b`. For B0 use the matched existing A-only config `experiments/pd_kv_ep/configs/ep_ep_minimal/two_ep4_groups_a_only.json`; for B1 use `research_joint/configs/two_ep4_group_b_only.json`. Both use `experiments/pd_kv_ep/workloads/two_ep4_groups_a_only_4req.jsonl` and `--num-reqs 4`.

Compact analysis of retained request outputs and scratch FlowSim telemetry:

```bash
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_joint/scripts/analyze_b_phase_runs.py
```

The 20-µs phase parameter is a one-time initial serving gate, not a recurring delay. `queue_bytes`/FlowSim backlog must be described only as analytical residual fluid, never a packet queue, ECN/PFC, or loss measurement. Raw 55–56 MiB telemetry remains in `/tmp` and is not duplicated in this research directory.

## Artifact index

`02_THEORY_GATE_RESULTS.csv` is the machine-readable candidate gate. `06_B_PHASE_EXPERIMENTS.csv` and `11_SERVING_INTEGRATED_COMPARISON.csv` contain measured bounded outcomes. `10_THEORY_SIM_DISCREPANCY_LOG.csv` preserves the failed first wakeup implementation as an invalid diagnostic, not as performance evidence. A/C and S0–S3 cells not measured are explicitly `NOT_RUN`.
