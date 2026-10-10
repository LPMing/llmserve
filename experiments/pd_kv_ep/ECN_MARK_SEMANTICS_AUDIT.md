# ECN mark semantics audit — immutable S8 D8+K2 replay

## Scope and provenance

This audit uses the frozen event ledger from
`results/natural_ecn_baseline_v1/attempts/s8_d8_k2_i8192_do64_gap5ms/packet_input/events.csv`.
Its SHA-256 is `5109434562416c911ec749a2e57f1eea682cab0f2e40659a306c30d2cbb6cb61`.
The authoritative repeat used the frozen CC_MODE=1 replay configuration,
4096-byte packet payload, FAIR policy, 0.1-ms telemetry interval, the same
topology and stop guard, and added only observational `LOCAL_ECN_MARK` output.
The old baseline and event ledger were not overwritten.

The authoritative FULL run completed 499,776 input events: 378,816 transmitted
network QPs plus 120,960 same-server EP events intentionally omitted from the
scale-out fabric. Its `link_summary.csv`, `cc_events.csv`, `comm_events.csv`, and
`fct.txt` SHA-256 values exactly match the already-frozen CC_MODE=1 baseline.
Thus the observer did not change packet/network behavior in this replay.

## What the counters mean

`link_summary.csv::ecn_marks` is **not a count of CE transitions made at that
link**. In `scratch/common.h::telemetry_phy_tx_begin`, it increments for every
packet whose IPv4 ECN bits equal CE when that packet physically begins
transmission on that directed link. A packet marked upstream is counted again
on every later hop that transmits it with CE. The link-timeseries value is
cumulative; summing its rows would multiply-count observations.

The actual switch marking decision is in
`src/point-to-point/model/switch-node.cc::SwitchNode::SwitchNotifyDequeue`.
For data queues, the switch first removes the departing packet from MMU ingress
and egress accounting, then calls `SwitchMmu::ShouldSendCN`. That function
returns true above Kmax, or probabilistically between Kmin and Kmax. The switch
then sets the IPv4 ECN field to CE. The audit callback records a row only when
the packet was not already CE, at this decision point, with the post-dequeue
MMU egress bytes and that port's Kmin/Kmax. It does not alter the packet or the
decision.

`SwitchMmu::ConfigEcn` converts the configured K values from decimal kB to
bytes (`* 1000`). On the 200-Gbps ports used here, Kmin=600,000 B and
Kmax=2,400,000 B. The exported link queue maximum is the sampled Qbb/netdevice
queue, while ECN admission uses the switch MMU egress-accounting array; these
are related but not identical queue observations.

## Direct answers

### Why can link 169 have 5,134 ECN observations with only 74,376 B max queue?

It has **zero local new CE marks**. All 5,134 CE observations are packets marked
earlier on link 152 and then transmitted on link 169 while still carrying CE.
Link 203 similarly has zero local marks: its 1,368 CE observations are
carry-through. Therefore its sub-Kmin sampled queue does not contradict the
telemetry. The old field counted CE-carrying transmissions, not local
queue-threshold crossings.

### Where were CE transitions actually created?

In the authoritative FULL replay, all 5,134 local new marks were on directed
link 152 (`68 -> 81`), the Prefill shared-NIC uplink, and all were attributed to
P2D KV. Mark provenance identifies request 8 for 2,812 marks and request 9 for
2,322; the eight Decode warm-up requests caused none. No EP flow uses this link.
The post-dequeue MMU egress queue at marking
was 611,536–3,632,028 B; none of these local marks occurred below Kmin. At the
same link, link-summary CE observations are also 5,134, so there is no
carry-through component on the origin link itself.

The full per-link table is `results/ecn_origin_counterfactual_v1/analysis/LOCAL_ECN_ORIGIN_BY_LINK.csv`.
The packet-level rows are
`results/ecn_origin_counterfactual_v1/full_cc1/local_ecn_marks.csv`.

| Directed link | CE transmit observations | Local new marks | Carry-through | sampled max queue | KV / EP bytes on path |
|---|---:|---:|---:|---:|---:|
| 152, 68→81 | 5,134 | 5,134 | 0 | 3,636,160 B | 1,610,612,736 / 0 B |
| 169, 83→76 | 5,134 | 0 | 5,134 | 74,376 B | 1,610,612,736 / 104,595,456 B |
| 203, 84→83 | 1,368 | 0 | 1,368 | 53,716 B | 377,487,360 / 101,015,552 B |

The total of 25,670 `ecn_marks` across 14 links is consequently a sum of
per-link CE-carrying packet transmissions, not 25,670 independent congestion
marking decisions. The same CE packet contributes at multiple hops.

## Additional ECN protocol-fidelity finding

The source currently constructs UDP data IPv4 headers with `SetTos(0)` in
`rdma-hw.cc` (`RdmaHw::AddHeader`/data-header path), so their starting ECN field
is Not-ECT. In this run every local mark row recorded `ecn_before=0`; the switch
still changed the field to CE whenever its congestion predicate fired.
`RdmaHw::ReceiveUdp` accumulates any nonzero ECN bits and sets CNP on the ACK
when `ecnbits` is nonzero. Thus the current fork does produce feedback for its
locally changed packets, but the marking operation is Not-ECT→CE rather than a
standards-faithful ECT(0/1)→CE transition. This is a simulator semantic
limitation, not evidence that the frozen run changed behavior. We did not
modify sender marking eligibility or receiver feedback semantics in this
telemetry task. Any claim specifically about standards-faithful DCQCN requires
a separate correctness fix and revalidation.

In the existing CC_MODE=1 replay, feedback attribution remains exact against
the serving event ledger: 5,134 CNP events were received by KV QPs; 721 KV QPs
received at least one CNP; all 2,420 rate decreases belonged to those KV QPs.
EP QPs had zero CNP and zero rate decreases. This is the behavior of the
current ns-3 fork; it should not be silently generalized to a different or
standards-correct RoCEv2 implementation.

## Interpretation gate

**`CROSS_CLASS_ECN_HYPOTHESIS_FAIL` for this baseline:** local CE generation is
entirely on a KV-only Prefill NIC uplink. The CE observations on shared
downstream links are carry-through, not local KV+EP queue marking.

This does **not by itself prove there is no cross-class FCT interference**:
KV and EP may still share downstream service without crossing the ECN threshold.
That separate question is tested with matched FULL, KV_ONLY, and EP_ONLY
replays over the exact same event ledger and CC_MODE=1 configuration. Those
packet replays do not feed completion back into the serving scheduler and
cannot produce new ns-3 TTFT/TPOT/TBT values.

## Matched CC_MODE=1 class-removal result

The three replay inputs have the same event-ledger SHA and preserve source-port
progression for suppressed events. There were no unmatched flows or route
mismatches in either matched comparison.

| Metric | FULL | Isolated control | Change |
|---|---:|---:|---:|
| EP peer-flow FCT P99 | 44.213 us | 44.213 us (EP_ONLY) | 0.00% |
| EP collective CCT P99 | 67.365 us | 67.364 us (EP_ONLY) | +0.0015% |
| all KV shard FCT P99 | 1.602 ms | 1.386 ms (KV_ONLY) | +15.59% |
| K request 8 handoff proxy | 293.618 ms | 293.992 ms (KV_ONLY) | -0.127% |
| K request 9 handoff proxy | 293.488 ms | 293.607 ms (KV_ONLY) | -0.041% |

The aggregate KV shard P99 is therefore not a request-barrier result. Within
the two new K requests, shard-flow tails changed (request 8 P99 +64.18%; request
9 +14.78%), but both handoff proxies were slightly lower in FULL than KV_ONLY.
The last required shard remained layer 472 in both runs; the layerwise release
span dominates the barrier timing. With only two new K requests, these are
matched mechanism observations, not a stable serving-latency distribution.

For EP collectives, the mean CCT changed from 55.440 us to 55.502 us, while
P99 was effectively unchanged. This is below the branch's 10% request/barrier
stop threshold. The current S8 baseline therefore does not demonstrate a
cross-class barrier problem, even though some individual KV shard FCTs move.
No packet-replay result here is interpreted as TTFT/TPOT/TBT.

## Observer implementation

The optional `LOCAL_ECN_MARK_FILE` hook observes only non-CE→CE decisions in
`SwitchNode::SwitchNotifyDequeue`. It logs timestamp, switch/egress/link,
queue index and MMU bytes, Kmin/Kmax, packet UID, pre-mark ECN bits, QP tuple,
traffic class, and active event/request/collective/layer provenance. It is
disabled unless explicitly requested by the replay runner.
