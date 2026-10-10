# Offline EP Critical-Flow Protection Validation

## Question

Does protecting only the EP flows that are predicted to determine a
collective barrier preserve the `EP_FIRST` benefit while releasing bandwidth
to KV movement?

This is an offline oracle experiment.  It is not an online scheduler and the
oracle is not a deployable policy.

## Matched setup

- S16 / 8 Prefill servers + 8 Decode servers / 128 logical GPUs.
- Qwen3-30B-A3B-Instruct-2507, TP2, EP64, 128 experts, top-k 8, 48 layers.
- 200-Gbps endpoint links and corrected parallel leaf-spine aggregate fluid
  capacities.
- LAYERWISE, model-derived P2D bytes and GateRouter-derived A2A_P2P EP bytes.
- Same event ledger, request set, timestamps, paths and bytes in every case.
- FlowSim queue is residual fluid backlog, not packet-buffer occupancy.
- KV barrier is `max(required KV end) - min(requested KV start)` per request,
  never a sum of flow FCTs.
- EP CCT is `last EP flow end - collective requested start`.

The oracle files are generated from a FAIR completion order.  `CRITICAL_EXACT`
selects every flow tied at the FAIR last completion of each collective;
`TOP1/TOP5/TOP10` select the slowest 1/5/10% of flows per collective.

## Window 1: Mooncake Tool/Agent, 64 requests

The exact and top-k policies were replayed against the same uncoalesced
64-request event ledger.  The protected byte fractions are 45.27%, 1.55%,
5.50% and 10.44% for exact, top-1%, top-5% and top-10%, respectively.

| policy | EP mean (ms) | EP P99 (ms) | KV handoff mean (ms) | KV handoff P99 (ms) |
|---|---:|---:|---:|---:|
| FAIR | 0.089156 | 0.106508 | 53.026045 | 157.736973 |
| EP_FIRST | 0.088915 | 0.098644 | 53.577349 | 159.852497 |
| CRITICAL_EXACT | 0.131031 | 0.161559 | 53.642314 | 159.648015 |
| TOP1 | 0.097570 | 0.114373 | 53.168369 | 158.232437 |
| TOP5 | 0.117720 | 0.155582 | 53.479202 | 159.317715 |
| TOP10 | 0.129233 | 0.168482 | 53.611575 | 159.585100 |

Relative to `EP_FIRST`, TOP1 increases EP P99 by 15.95% and TOP5 by 57.72%,
while their KV P99 changes by -1.01% and -0.33%.  The exact set is worse for
EP (+63.78% P99) without a meaningful KV benefit.

## Window 2: BurstGPT / exposed-barrier gate, 64 requests

This is a second uncoalesced 64-request ledger with a different request and
arrival composition.  Protected byte fractions are 45.42%, 1.69% and 5.68%
for exact, top-1% and top-5%.

| policy | EP mean (ms) | EP P99 (ms) | KV handoff mean (ms) | KV handoff P99 (ms) |
|---|---:|---:|---:|---:|
| FAIR | 0.087872 | 0.098644 | 12.914671 | 25.381526 |
| EP_FIRST | 0.087830 | 0.098644 | 12.915203 | 25.381526 |
| CRITICAL_EXACT | 0.128694 | 0.151559 | 12.916349 | 25.381526 |
| TOP1 | 0.096303 | 0.106509 | 12.914861 | 25.381526 |
| TOP5 | 0.115419 | 0.137966 | 12.915354 | 25.381526 |

Relative to `EP_FIRST`, TOP1 increases EP P99 by 7.97% and TOP5 by 39.86%;
KV P99 is unchanged to the recorded precision.  Thus the result is not a
single-window artifact, but it also provides no KV/TTFT headroom.

## Mechanism diagnosis

The offline set is selected from the old FAIR completion order.  Once only
that set receives priority, the formerly non-critical EP flows are still part
of the same collective barrier.  They now share the residual bandwidth with
KV and can become the new last-completing flows.  The identity of a critical
flow is therefore policy-dependent; it is not a fixed property that can be
protected independently of the rest of the collective.

This explains all three observations:

1. `CRITICAL_EXACT` protects many old stragglers but creates new stragglers.
2. TOP1 is selective enough to avoid a large KV benefit, but not selective
   enough to preserve `EP_FIRST` CCT.
3. TOP5/TOP10 move toward protecting more EP traffic and therefore converge
   toward the EP-side behavior of an all-EP priority class, without reducing
   the request-level KV barrier.

The result is a negative characterization of simple offline critical-flow
protection.  A useful future design would need a collective-wide guarantee or
online residual-slack prediction, not a static list of flow IDs.  That is a
new design question, but this experiment does not establish enough
serving-level headroom to make it the current paper motivation.

## Decision

`CRITICAL_ONLY_FINAL_FAIL_NO_KV_HEADROOM`.

The direction was tested on two uncoalesced real-trace-derived windows, with
exact and neighboring top-k protection levels.  It fails the required
criterion because no policy produced a meaningful reduction in request KV
barrier, and the selective policies degraded EP CCT relative to `EP_FIRST`.
No integrated TTFT/TBT result is inferred from these network-only replays.

## Reproducibility

The oracle generator is
`scripts/make_critical_flow_oracles.py`; the analysis script is
`scripts/analyze_critical_policy_results.py`.  Compact JSON summaries are in
`results/candidate_barrier_criticality/mooncake64_summary.json` and
`results/candidate_barrier_criticality/exposed_summary.json`.
