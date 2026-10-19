# Joint network–Serving upper-bound screen

## Objective and four controls

The declared diagnostic objective is mean request P2D-ready time, with
makespan reported as a guard against hiding a harmed last request. This is not
a production SLO objective; the four-request cohort is too small to establish
one.

| Arm | Meaning for the current workload | Result/status |
|---|---|---|
| S0: original Serving + FAIR | Real Serving scheduler plus packet network | Integrated custom-topology run **NOT_RUN**. Packet-only simultaneous release is 32.481310ms mean ready. |
| S1: original Serving + strongest network-only | Reorder/pacing only already-produced flows | Fixed network-only bundle pacing gives 20.451317ms mean ready, 37.04% better, but makespan +0.83%; not Serving-integrated. |
| S2: Serving-only + FAIR | Reorder Prefill work without reading network state | **No action set in the tested fixture**: one active task per independent Prefill server, no queued alternative; not run. |
| S3: network-feedback Serving | Select future Prefill work/chunk using live network state | **NOT_RUN**: no alternate ready work and no exposed KV wait in the profile ledger; no theoretical increment to test. |
| S4: offline joint oracle | Knows all future compute/release/network state | Not run as an optimizer; this fixture's layerwise exposed-wait upper bound is zero. |

## Incremental-headroom calculation

For the four simultaneous equal-size POST_PREFILL shards per receiver rail,
an independent single-cut network oracle reduces mean P2D completion by at
most 37.5%, without changing the last completion. The native 8.2ms pacing
baseline obtains 37.04% mean improvement and slightly increases makespan. That
is already a network-only result; no additional serving feedback is needed to
obtain the fixed-release ordering gain.

For the profile-derived LAYERWISE schedule, latest P2D-ready is 134.059112ms
(CC0) or 134.963180ms (CC1), while Prefill compute ends at 135.319248ms.
Therefore the network-attributable wait at the downstream Prefill-end/Decode
admission boundary is `max(0, T_KV_ready - T_prefill_end) = 0` in both cases.
An oracle that eliminates all network delay cannot make KV-ready earlier than
the already-completed compute boundary for purposes of this handoff. This is a
zero incremental-headroom upper bound for this concrete profile/workload, not a
claim about every possible deployment.

No legitimate S3 action can be evaluated without adding alternative ready
work or a different legal serving state. Adding such work solely to force a
positive feedback result would change the tested problem. Per the mission's
15% screening rule, this candidate does not pass the algorithm-development
gate on current evidence.
