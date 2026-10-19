# Session, Cache, and Serving Causality

## Full-session comparison

The root requests start from the same four session arrivals; each child is released only after its own warm-up request completes, so child timestamps are not frozen from the old topology.

| Session | 4P1D full | 4P1D DELTA | 3P2D full and DELTA |
|---|---:|---:|---:|
| prefix-session-0 | 211.436 ms | 205.965 ms | 181.432 ms |
| prefix-session-1 | 211.436 ms | 205.965 ms | 222.092 ms |
| prefix-session-2 | 211.436 ms | 205.965 ms | 176.874 ms |
| prefix-session-3 | 211.436 ms | 205.965 ms | 226.790 ms |

4P1D DELTA improves this fixture's mean full-session completion by 2.59%. Static 3P2D improves mean by 4.56%, but its maximum is 7.26% later than the 4P1D maximum and two sessions finish later than the 4P1D reference time. B2's 3P2D DELTA timeline is exactly equal to B1's full-transfer timeline.

## Cache locality under the role change

Each root warms a 4096-token prefix; its child appends tokens under the same session/token-hash chain. The cache manager, not a hand-written routing assumption, records hit/miss state. On 3P2D, fewer Prefill instances change where some roots and children land. The fixture includes identical prefixes across sessions, so a 3P2D root can naturally hit 4080 tokens from another resident session; B2's corresponding root transfer is 1,572,864 B rather than the 402,653,184 B prefix payload. This cross-session hit is a property of the controlled token fixture and block-hash semantics, not evidence that production sessions share this prefix distribution.

No prefix is copied for free between Prefill instances. This run does not use CXL/CPU restore. Existing documentation notes that FlowSim's lower-tier memory load path can have zero modeled duration; no result here relies on it.

## Causal chain for A0 versus A2

```text
same child arrival (150.107 ms)
  → same source prefix hit (4096), same 9-token compute
  → same last sampler compute completion (177.175 ms)
  → A0 sends 403,537,920 B; last flow ends 182.646480 ms
    A2 sends   884,736 B; last flow ends 176.419675 ms
  → A2 P2D-ready/graph completion is then gated by sampler at 177.175 ms
  → both produce the same sampler-ready first-token proxy
  → A2's Decode/token schedule starts earlier after KV becomes ready
  → final child completion moves from 211.436480 to 205.965 ms
```

This establishes that destination reuse removes large redundant network bytes and shortens P2D readiness. In this workload, the released network tail is not part of the measured sampler-compute critical path; the observed user-facing candidate appears in later completion/inter-token timing, not in a valid measured TTFT. It does not prove that all runtime implementations can emit a token before the destination has admitted the request.

## Cache and batch interactions

- Decode cache compatibility and references are checked by the new reservation protocol.
- The graph still waits for all KV needed by Decode before Decode admission.
- B changes both instance placement and scheduler batch membership; child arrival shifts with the actual warm-up finish.
- B1/B2 have the same per-session completion and token timeline, so the smaller P2D payload in B2 is hidden by compute/other scheduling work at these four sessions.
- No SLO thresholds are configured and no SLO percentages are calculated.
- Four sessions do not support production-tail quantiles.
