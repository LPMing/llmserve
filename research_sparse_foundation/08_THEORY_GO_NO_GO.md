# 08 — Theory gate and GO / NO-GO

## Gate summary

| Gate | Status | Evidence / blocker |
|---|---|---|
| Source provenance | PARTIAL | HEAD known; dirty worktree and incomplete run→source/config/output binding |
| RR/RAND provenance | PASS for simulator policies | Fixed token ordinal; 3 regression tests pass; still not learned model routes |
| Profile domain | FAIL for EP32/EP64 quantitative timing | 99.9536% of retained sidecar layer-equivalent rank queries clamp AE below measured minimum; no GPU driver for recalibration |
| Real learned routing | BLOCKED | No real Qwen token→expert output or exact pair matrix available |
| S16 physical rank mapping | FAIL / BLOCKING | Config implies 192 ASTRA ranks, physical topology has 128 GPU endpoints, no FlowSim map; generated EP-rank labels repeat local GPU IDs |
| Sparse A2A DAG | NOT_VALIDATED | Exact converter path is dormant from standard trace/graph generation and lacks end-to-end graph tests |
| P0 crossover | THEORY PARTIAL, runtime unproven | Payload-only illustrative model predicts fewer sparse bytes with high EP under uniform routing; no startup/latency or real matrix comparison |
| P1 cut headroom | BLOCKED | Cannot compute authentic per-cut work or legal placement gain without route matrix and rank map |
| Performance experiment | NOT RUN | Correctly stopped before FlowSim/ns-3 performance runs |

## Final classification

```text
INSUFFICIENT_MODEL_PROVENANCE
PROFILE_CALIBRATION_BLOCKED
SPARSE_A2A_DAG_NOT_VALIDATED
```

Do **not** label P0 or P1 as mechanism `FINAL_FAIL`: their decisive real-model
inputs are unavailable. Do **not** label either `GO`: the theory table is a
payload-only illustration, not an execution-cost crossover or Serving result.

## Tests and rerun commands

```bash
PYTHONPATH=. /home/lpm/.conda/envs/llmsim-flowsim/bin/python \
  research_sparse_foundation/test_gate_router_provenance.py
PYTHONPATH=. /home/lpm/.conda/envs/llmsim-flowsim/bin/python \
  experiments/pd_kv_ep/scripts/test_flowsim_collective_scope.py
PYTHONPATH=. /home/lpm/.conda/envs/llmsim-flowsim/bin/python \
  experiments/pd_kv_ep/scripts/test_pd_decode_capacity_admission.py
/home/lpm/.conda/envs/llmsim-flowsim/bin/python \
  research_sparse_foundation/audit_inputs.py
/home/lpm/.conda/envs/llmsim-flowsim/bin/python \
  research_sparse_foundation/theory_reference.py
```

All checks listed above passed in this audit; the performance experiment gate
did not pass and no performance simulation was run.

## Smallest next actions that can reopen a performance gate

1. Obtain actual Qwen3 model router outputs for a fixed input batch and at
   least multiple MoE layers; preserve token, layer, source rank, selected
   experts, owner rank, and exact payload accounting.
2. Profile RTXPRO6000 MoE compute at activated-expert counts 1/2/4 (and relevant
   token counts); otherwise avoid quantitative EP32/64 Serving claims.
3. Resolve S16 logical-rank/shadow-rank semantics into a unique physical map;
   fix the metadata EP ordinal and require a topology/rank-map validation test.
4. Wire route records and EP global ranks through `generate_trace()` and
   `generate_graph()` to the exact A2A converter; test dispatch, compute,
   combine, matched peers, barriers, and byte conservation on a small legal EP
   group.
5. Rebind any future run to a clean source revision, config/workload hashes,
   backend version, exact command, and output hashes.

Only after these prerequisites pass should the first minimum network-only
correctness experiment be considered. It should not be a motivation sweep.
