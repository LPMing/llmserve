# Direction B — 8 GPUs sharing two 200-Gbps NIC rails

## Question

Does modeling four GPUs per NIC as a shared endpoint resource reveal
cross-request interference that a one-GPU/one-NIC abstraction would miss,
and does ordinary traffic-class priority change serving outcomes?

## Tested physical interpretation

The two NIC rails are separate directed 200-Gbps resources, not one
800-Gbps GPU-facing link and not eight independent 50-Gbps links. Four GPU
rank endpoints are mapped behind each rail through high-capacity local access
edges. On each D0 rail, nine P2D candidates (seven 2048-token and two
1024-token requests) overlap with one recurrent EP4 Decode group. Two rails
run independently, with 18 candidates and two EP4 groups total. Eight seed
requests (four per EP group) remain active; each has 128 prompt tokens and
24 output tokens. Candidates have one output token to avoid adding another
Decode population after their first token.

All candidate KV bytes are model-derived. No KV or EP byte override is used.
The arrival time is derived from actual seed Decode events at 67,284,113 ns.
This is a controlled, high-load mechanism workload rather than a production
arrival trace.

## Capacity estimate

Per D0 RX rail, estimated average demand is 180.990 Gbps P2D plus 1.405 Gbps
EP = 182.396 Gbps, or 91.20% of the 200-Gbps direction. This is the
profile-derived estimate. The integrated FAIR telemetry independently
measures 64.872308 ms of full-capacity active intervals in the 74.321-ms
candidate KV release-to-ready window, or 87.29% time-weighted occupancy per
rail. Both rails meet the intended high average-load band. Activity is
layer-bursty (207 event-driven episodes, maximum 1.522 ms), rather than one
unbroken saturation episode. FAIR KV/EP simultaneously-active time is
1.296263 ms (1.74% of the window) per rail. The fluid backlog peaks at
31.540 MiB.

## Main experiment

Run the same B workload and topology under FAIR, EP_FIRST, KV_FIRST, and the
EP_ISOLATED virtual-capacity counterfactual. Results are in
`03_DIRECTION_B_RESULTS.csv`. The direct comparison asks whether the two
traffic classes have different urgency at a shared endpoint rail. It does
not yet ask whether individual requests within the same class need distinct
priority.

## Status

Shared-rail resource contention and class-priority consequences are measured
in integrated FlowSim. This does **not** establish a need for fine-grained
request/collective scheduling: EP_FIRST already provides nearly all observed
Decode benefit without a measurable candidate TTFT cost in this point.
Packet-level NIC/switch validation is still required before making a physical
RDMA scheduling claim.
