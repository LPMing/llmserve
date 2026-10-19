# NIC-versus-fabric attribution

## Modeled resources

The generated FlowSim topology has six physical servers: four Prefill and two
Decode. Every server has eight GPU-rank endpoints, two independent 200-Gbps
NIC-facing rails, and four GPU ranks mapped behind each rail. The topology
contains a single ToR, no spine. Directed NIC links are separate in each
direction. High-capacity GPU-to-NIC access edges (7.2 Tbps in the fixture)
represent local access abstractly and are not the target bottleneck.

For Direction A, P2D to D0 and cross-server EP peers in the same EP4 group
share the D0 RX directed link `60->56`. For Direction B, group A and its
P2D cohort use `60->56`; group B and its P2D cohort use `60->57`. These are
two independent 200-Gbps D0 RX rails, not a single pooled 400-Gbps receiver
queue. The topology/rank mapping preserves the 8-GPU/two-NIC relationship;
it does not model one independent 50-Gbps NIC per GPU.

## What the telemetry proves

In Direction B FAIR, each selected D0 rail carries active KV and EP work at
the same time. During the 74.321-ms candidate KV release-to-ready window,
each rail has 64.872 ms of active/full-capacity allocation (87.29%
time-weighted), with 207 event-driven busy episodes and a maximum episode of
1.522 ms. The residual fluid backlog peaks at 31.540 MiB. Up to 9 KV plus 4
EP flows are represented as active on a rail. However, FAIR's simultaneous
KV-and-EP-active time totals only 1.296 ms (1.74% of that window); under
KV_FIRST, EP stays active/pending for 62.625 ms due to strict class service.
This proves shared-resource allocation and shows how the FlowSim policy
changes service, but not that physical RNIC/switch queues behave the same.

It does **not** identify a distinct ToR egress bottleneck beyond the modeled
NIC-facing directed link, nor does it show a physical RNIC queue or switch
queue. The attachment and topology config treat NIC egress/ingress as the
finite 200-Gbps edges; there is no lower-level queue partition.

## Important model boundaries

FlowSim currently applies fluid max-min or strict class allocation on
directed links. It does not simulate:

- packet serialization or packet boundaries;
- per-QP RNIC dequeue/arbitration;
- switch output queues or buffer admission;
- ECN marks, CNP, PFC, drops, or DCQCN;
- true packet HOL blocking or RDMA ACK timing.

Therefore, phrases such as “31.5 MiB switch queue” or “KV blocked the NIC
queue” would be incorrect. Use “FlowSim analytical residual fluid backlog
on the modeled D0 receive-link resource.” The large KV_FIRST EP delay is a
class-level fluid service result, not a measured packet-priority inversion.

## Validation still needed

To claim the same effect on RDMA hardware, export the exact rank endpoints,
per-layer releases, group participants, and policy class mapping to a
native-ns-3 or hardware case. Verify that control traffic (ACK/CNP) remains
protected and that the 200-Gbps server-NIC sharing is represented as two
rails with four GPU ranks per rail. A fixed-timestamp packet replay would
validate network behavior only; it would not produce integrated TTFT/TBT
unless packet completion is fed back to the serving scheduler.
