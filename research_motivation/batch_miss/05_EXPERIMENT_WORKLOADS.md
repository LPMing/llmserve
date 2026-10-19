# Workload and matched-run design

All cases use full serving-integrated FlowSim with deterministic controlled requests, not real-trace replay. Prefix caching and chunked prefill are off; routing is RR; `max_num_seqs=8`; token budget=2,048; candidate output length=8. R0 requests have input128/output16, arrive at t=0 and form six active sequences per each of four P/D lanes. Candidate R1 and same-size R2 requests have input2048/output8 and arrive at t=30ms in E1–E3. Arrivals go through normal router/scheduler; network issue times are not overridden.

| Case | Request population | Network condition | Purpose |
|---|---|---|---|
| E0_SINGLE | one 2,048-token R1 | no background | first-token semantics and isolated floor |
| E1_ONE_KV | 24 R0 + one R1 | `KV_ISOLATED` | virtual isolation counterfactual; EP placed on independent per-link capacity copy |
| E2_ONE_KV | same as E1 | FAIR shared fabric | one candidate with recurring Decode EP |
| E3_MAX_4_KV | 24 R0 + R1 + 3 R2, all 2,048-token KV | E3a `KV_ISOLATED`; E3b FAIR | maximum planned P2D concurrency: four source GPUs on the same rail |
| E3_400G_HIGH_BANDWIDTH | same 28 requests as E3b | FAIR, all NIC-to-ToR rails at400G | bandwidth sensitivity only; 800G/server, not the authoritative 2×200G topology |
| E4_R2_STAGGERED | same count/sizes, R1 at30ms, R2 at130ms | FAIR, unchanged2×200G topology | removes R1–R2 KV overlap; R2 can still overlap later EP |

**Naming correction:** `E3_MAX_4_KV` is the maximum-concurrency point, not the task-defined 400G case. The actual 400G test is explicitly named `E3_400G_HIGH_BANDWIDTH` in the final CSV.

## Absolute sequence (E3b)

R0: 24 requests arrive at0; six per each of four TP1 Prefill instances. Their handoff completes54.349ms; the 16-output-token R0s drive 16 recurrent EP4 AG/RS Decode iterations over the run. Each receiving scheduler has six running requests and two free slots.

R1/R2: request24 and requests25–27 arrive30ms. Prefill batches start54.349ms while old Decode is active. The first P2D layer releases54.496ms; layerwise releases then occur through126.970ms. Each request sends201,326,592 B over48 layers. Four source GPUs 0–3 share P0 rail0. Their streams overlap R0 EP traffic on the actual directed ToR cut.

R1 becomes ready128.817ms because Prefill compute completes after its last required KV. At handoff the Decode lane is6/8; R1 is admitted, making7/8. Batch8 is already fixed and executing. It completes, then Batch9 is selected with R1 included. No arrival or flow time was manually pinned to the boundary.

E4 R2 arrival is130ms; its first KV release is130.147ms, after R1's last KV completion127.149653ms. No R1–R2 KV interval overlaps. EP and later R2 traffic remain in the run, so E4 is specifically a target-KV-window negative control, not a no-network experiment.

## Reproduction assets

See `RUN_COMMANDS.md`, `generate_workload.py`, `generate_sensitivity_config.py`, the JSONL workloads, rank map, and cluster configs in this directory. Compact event, flow, overlap, link-fluid, scheduler and graph ledgers are in `results/`. Large transient outputs were under `/tmp/bm_*`; the exported provenance and commands are retained for reruns.
