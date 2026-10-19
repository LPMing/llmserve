# Direction A — go/no-go

## Decision

**Shared-network mechanism observed; Direction A full motivation gate: NOT
PASSED.** A has a modest serving-visible mean change, but no useful
TTFT/TBT/SLO opportunity over the FAIR baseline has been demonstrated.

This no-go is based on all three measured cross-request categories, not only
the latest KV–EP fixture. The prior controlled KV–KV cases produced shard-FCT
increases up to +10.91% mean / +25.35% P99 for a 128-token victim, but did not
change its last-shard completion, KV-ready timestamp, or TTFT. The prior
EP–EP two-group cases produced +6.39% dispatch CCT, +1.58–3.11% combine CCT,
and +0.75–0.80% integrated TPOT/TBT, with TTFT unchanged. The earlier
corrected integrated KV–EP point produced +1.08% EP CCT P99 and no measurable
TTFT or material TPOT change. See
[`02_DIRECTION_A_PRIOR_CASES.csv`](02_DIRECTION_A_PRIOR_CASES.csv) and
[`research_audit/12_EP_EP_GROUP_VALIDATION.md`](../../research_audit/12_EP_EP_GROUP_VALIDATION.md).

The physical resource mapping and overlap are valid in the tested FlowSim
fixture, and the FAIR run has real analytical fluid backlog on D0 receiver
rail `60->56`. In the A7L2M workload, the collective CCT distribution shifts
from mean 10.639 us / p99 11.020 us under the cross-class isolated
counterfactual to mean 10.838 us / p99 12.464 us under FAIR. This is a 1.9%
mean and 13.1% p99 network-side penalty.

The request-level KV handoff/TTFT does not change at displayed precision;
the post-last-layer drain delta is about 8.6 us (long request) or 5.9 us
(medium request) against 73.7 / 56.9 ms handoff spans. Seed pooled ITL mean
changes by about 0.32%, and seed P99 remains 8.164 ms. The serving exposure
is therefore small in this controlled point.

## Why this is not a positive algorithm result

- The main counterfactual is `EP_ISOLATED`, not an alternative finite,
  deployable same-capacity schedule.
- The exact point did not include a matched `EP_ONLY` / `KV_ONLY` pair.
- The current collective realization is AG/RS peer expansion, not exact
  GateRouter A2A.
- No packet-level feedback, RNIC arbitration or physical switch priority is
  validated here.
- A small TBT delta leaves no evidence that a request/barrier-aware policy
  beats static class priority.

The operating point was not expanded further: the profile-derived offered
load is already about 91.2% per rail, while theory predicts a ≤1.58% fully
exposed EP/TBT contribution for the relevant byte ratios. More artificial
load would not answer whether this is a useful serving opportunity.

## Scope of the conclusion

The result only bounds this model, TP1 KV path, EP4 AG/RS realization,
200-Gbps shared receiver rail and controlled arrival window. It does not
prove absence of contention in all deployment topologies or traffic mixes.
However, within this tested point, moving on to a new scheduler is not
justified by the observed A-side serving headroom.

The broader A-side evidence supports a bounded conclusion: the simulator can
represent KV–KV, KV–EP and independent-group EP–EP sharing, and each can move
network metrics. In the tested legal workloads, KV–KV shard tails were
absorbed before request handoff; EP–EP propagated a sub-1% token-delay change;
KV–EP propagated only a small collective change. This is not a universal
claim that other topologies, exact routed A2A implementations, or resource
models cannot expose larger barriers. It is a no-go for claiming useful
serving-level scheduling headroom from the tested cases.
