# 09 — Sparse A2A minimal screen: result and validity

## Run inventory

The first builder invocation with `--ep-bin-us 0` was rejected by argument
validation and produced no experiment result. The valid run used a 1-µs bin.
The matched FlowSim runs were `exact_ep_only`, `exact_full`,
`uniform_ep_only`, `uniform_full`, plus `exact_kv_only`. All emitted flows
completed. This is a network-only replay: no scheduler callback changes later
events when a flow finishes.

## Descriptive output

Nearest-rank percentiles over 336 coalesced phases:

| Route realization | Traffic | Mean CCT (µs) | P50 | P95 | P99 | Max |
|---|---|---:|---:|---:|---:|---:|
| GateRouter-derived surrogate | EP_ONLY | 70.938 | 65.051 | 98.644 | 101.269 | 116.287 |
| GateRouter-derived surrogate | FULL | 70.942 | 65.051 | 98.644 | 101.269 | 116.287 |
| “Uniform same-byte” counterfactual | EP_ONLY | 75.987 | 65.051 | 135.830 | 135.830 | 135.830 |
| “Uniform same-byte” counterfactual | FULL | 75.998 | 65.051 | 135.830 | 135.830 | 139.617 |

Across matched phase IDs, counterfactual-minus-surrogate P99 is +34.2% in both
EP_ONLY and FULL. P2D's FULL-minus-EP_ONLY CCT delta is zero at P95/P99 for both
realizations; only one of 336 phases is positive, with maxima 1.341 µs (exact)
and 3.787 µs (counterfactual). Request-level KV FCT mean/P50/P95/P99 are
identical between FULL and KV_ONLY in this replay: 6.031 ms / 5.114 ms / 8.006
ms / 12.127 ms. A generated `ttft_data_plane_proxy` differs by only about
0.248 µs mean between EP_ONLY and FULL; it is not integrated TTFT and must not
be reported as serving performance.

These values are descriptive outputs of the builder/backend combination. They
are **not valid evidence of route optimization headroom** for the reasons below.

## Invalidating issues discovered

1. **The counterfactual is not work-preserving.** It retains aggregate bytes
   per source but rewrites destination assignments and therefore changes the
   token→expert work. It is not an alternative legal route for the same model
   execution.
2. **Deterministic remainder concentration.** For each source, integer
   remainder bytes are assigned to the first destination IDs. With small
   per-source counts this can reduce active destinations and create receiver
   concentration. The apparent CCT gap is present in EP_ONLY, before KV is
   added.
3. **Collective phase is not faithful.** All 48 MoE layers are coalesced into
   one phase per event bin, not 48 independent dispatch/combine barriers per
   Decode iteration. A collective ID here is not a serving Decode-round ID.
4. **No integrated feedback.** Event times are anchored from profiler-backed
   independent-request compute and uncongested P2D estimates. Network completion
   does not move request admission or later token issue times.
5. **Telemetry truncates.** Each run retained at most 4,096 telemetry rows and
   explicitly marks telemetry truncated. Do not infer full-run link utilization
   or queue distributions from this sidecar.
6. **Not packet-level.** Queue values are FlowSim residual fluid backlog; there
   was no ns-3/HTSim packet run for this candidate.

## Classification

```text
SPARSE_A2A_MODEL_NOT_VALIDATED
```

The result does not pass a mechanism or paper-motivation gate. It does establish
that this builder's same-byte route counterfactual can create a large CCT
difference without P2D. The correct action is to fix semantic provenance before
any further experiment—not to increase requests, load, or link pressure.

