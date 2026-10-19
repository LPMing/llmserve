# Direction A — cross-request KV/KV, KV/EP and EP/EP

## Question and hypothesis

Can communications from different requests and different Decode collectives
share a directed physical bottleneck, and does class priority change a
serving barrier? The minimal useful A case is a recurring EP4 Decode group
whose cross-server peers use one D-side 200-Gbps receive rail while newly
arrived requests release layerwise, model-derived P2D KV on that same rail.

The candidate operating points were selected analytically, not by sweeping
to overload: 8×2048-token P2D requests (88.02% estimated mean rail load) and
7×2048 + 2×1024 requests (91.20%). The KV sizes, EP bytes and compute-release
times come from the Qwen3 model config and RTXPRO6000 profile bundle. No byte
override or artificial delay was used. The controlled seed arrivals and
candidate event-derived arrival are documented in
`generated/A7L2M_primary_manifest.json` and `generated/A8_neighbor_manifest.json`.

## Mechanism prerequisites

1. There are multiple request IDs and a recurrent Decode seed cohort.
2. Candidate P2D and EP peer paths share the same directed D0 NIC rail.
3. Their active intervals overlap in the actual telemetry.
4. The Decode group waits for each collective's last peer; a request's Decode
   admission waits for all required P2D KV.

The fixture passes these structural checks in integrated FlowSim. It does
not validate packet-level RoCE/ECN behavior or exact GateRouter A2A.

## Findings

The 8-request neighbor and 7-long/2-medium primary point both produce a
finite fluid backlog and a small EP collective tail change under FAIR versus
the EP-isolated virtual-capacity control. In the primary A7L2M case, EP
collective CCT p99 is 12.464 us under FAIR and 11.020 us under EP-isolated
(+13.1%); mean is 10.838 versus 10.639 us (+1.9%). The P2D request barrier
and TTFT do not move at the reported precision. Seed Decode TBT/TPOT moves
only slightly (see `02_DIRECTION_A_RESULTS.csv`).

Thus the tested shared cut can expose a network-level EP collective barrier,
but the observed effect does not establish a large serving opportunity.
Layerwise P2D release slack absorbs nearly all of the KV-side delay.

## Earlier cross-request cases (supplementary evidence)

Direction A is broader than the recent KV–EP fixture. The durable historical
records also contain controlled KV–KV and EP–EP cases; their measurements are
summarized separately in [`02_DIRECTION_A_PRIOR_CASES.csv`](02_DIRECTION_A_PRIOR_CASES.csv)
so they are not mistaken for new runs from the current A7/A8 matrix.

- **KV–KV:** two distinct requests sharing the modeled P2D cut increased the
  small (32-token) and large (128-token) request shard-FCT P99 by 4.84% and
  3.01% in the corrected 32+128 case. In the retained 128-token-victim
  size-skew cases (paired with 2048- or 8192-token background), the victim's
  shard-FCT mean/P99 increased by 10.91%/25.35%. Despite that shard-level
  tail, the last required shard, KV-ready time, and TTFT were unchanged. The
  raw flow and request ledgers for these cases remain under
  `research_audit/results/minimal_kv_kv_*`.
- **EP–EP:** two legal, independent EP4 groups shared the same D0–D1 directed
  cut. The measured dispatch CCT increased 6.39%; combine increased 1.58% or
  3.11% at the two tested group populations. Integrated TPOT/TBT increased
  only 0.75–0.80%, with TTFT unchanged. This was AG/RS peer expansion, not
  exact GateRouter A2A; the compact metrics, setup and reproduction recipe are
  durable, while the large raw telemetry was transient in `/tmp`.
- **KV–EP:** the historical corrected integrated point changed EP CCT P99 by
  1.08%, with no visible TTFT/KV-ready shift and <0.01% TPOT-mean change. A
  separate native ns-3 fixed-issue-time replay measured +7.11% dispatch CCT
  and +0.16% mean P2D-message FCT, but it did not feed completion back into
  serving and therefore supplies no TTFT/TBT evidence.

Across these cases, network contention is demonstrable; the recurring
negative result is that the request/collective barrier moves much less than
individual shard/flow metrics. KV–KV is especially illustrative: a +25.35%
victim shard-FCT P99 did not move the request's max-completion barrier because
the delayed shards still finished before the already-determined final
required shard. EP–EP reaches TBT, but the summed per-token network exposure
is below one percent in the tested groups. Full values and evidence quality
are recorded in the supplementary CSV and the referenced audit reports.

## Controls not run

This bounded campaign did not run a separate `EP_ONLY` or `KV_ONLY` scheduler
simulation for these exact points. `EP_ISOLATED` is an analytical
cross-class-capacity counterfactual, not the same thing as `EP_ONLY`, not a
physical link, and not a deployable policy. Do not infer an EP-only baseline
from it.

## Status

The selected theoretical load region is legal enough for a bounded
mechanism/serving experiment, and that experiment observed shared-rail
contention. It did **not** pass the full Direction A motivation criterion:
P2D-ready/TTFT was unchanged, the token-tail impact was negligible, and no
same-resource serving oracle established avoidable loss. See
`02_DIRECTION_A_GO_NO_GO.md`.
