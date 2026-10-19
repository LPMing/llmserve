# 06 — P1: critical-cut-aware sparse MoE routing/placement

## Necessary model

Given a real layer route matrix `M_ij`, a physical rank placement `π`, paths
`P_ij(π)`, payload `b`, and directed-link capacity `C_e`, define per-cut work:

```text
W_e(π) = b × Σ(i,j: e∈P_ij(π)) M_ij
T_network ≥ max_e W_e(π)/C_e
```

Dispatch and combine require separate matrices/paths if the return mapping is
not the exact reverse. The collective barrier is bounded by the maximum
required peer completion, not the sum of all peer FCTs. Expert compute and
the next layer's release must be placed into the same DAG before claiming a
token-level gain.

## When a placement opportunity can exist

A traffic-cut opportunity requires all of the following:

1. Actual model routing produces a reproducible nonuniform `M_ij` or a
   placement-dependent cut load.
2. The highest-work cut is a real bottleneck on a required collective path.
3. A legal decision can change the owner/rank placement or route while
   preserving model semantics and fixed GPU/NIC resources.
4. Migration/rebalancing and local compute penalties do not consume the gain.
5. The exposed communication delay survives GPU/next-layer overlap and reaches
   a Serving token barrier.

If the routing/placement and physical fabric are symmetric and `M_ij` is
uniform in expectation, there is no systematic cut hotspot for a cut-aware
policy to remove. Finite-batch fluctuations can create hot cuts, but their size
and repeatability require actual layer-level router outputs.

## Current inputs

- The 2,078 retained route sidecars identify `BALANCED` analytic routing; they
  are not true Qwen token routes.
- No route matrix CSV can be populated without inventing the central data; see
  `02_REAL_ROUTING_MATRIX.csv`.
- The S16 GPU/NIC graph is specified, but the ASTRA logical-rank count and
  physical GPU endpoint IDs do not have a validated bijection; see
  `03_PHYSICAL_MAPPING.md`.
- No profiled AE=2/4 data is available for EP64/EP32 rank compute.
- An exact route matrix does not reach the sparse A2A converter through the
  standard trace/graph API.

Therefore neither the current critical cut nor its last required peer is
computable from authoritative model evidence. There is no defensible value for
`W_e`, collective CCT, or Serving critical-path headroom at this point.

## Decision

**P1 theory gate: NOT PASSED / INPUT-BLOCKED.** Do not run a cut-placement
oracle or FlowSim sweep on BALANCED sidecars. This is not a mechanism FAIL;
the candidate requires actual routes, legal placement controls, and a valid
rank map first.

## Novelty boundary

“Move experts to reduce communication” is not a new claim by itself. Gimbal
already describes source-DP-to-expert routing statistics and expert placement
that jointly considers expert load, source-aware communication, and migration
stability. FAST schedules all-to-all GPU communication and balances
one-to-one scale-out transfers. P1 can only be reconsidered if it identifies a
distinct, measurable barrier/cut objective and a legal placement decision not
subsumed by those systems; no such distinction has been demonstrated here.
