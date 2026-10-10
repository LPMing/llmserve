# N2 P2D-Handoff / Decode-EP Phase-Synchronization Audit

## Hypothesis

If many P2D handoffs complete in a narrow interval, Decode admission could
compress a population of requests into the same continuous-batching wave.
Their first MoE steps would then align, creating an EP burst and a collective
barrier tail. The required causal chain is:

`P2D ready clustering -> Decode admission clustering -> EP phase alignment ->
shared-fabric burst -> EP CCT/TBT tail`.

## Reality audit

The current simulator has separate P2D-ready and Decode scheduler-admission
timestamps. FlowSim also records the EP event start time and collective
provenance. Thus the mechanism is representable without adding a scheduler
policy. The model-derived replay does not infer synchronization from request
arrival alone; the relevant point is the request-level last P2D completion.

## Real-trace discovery

Two 16-request slices were converted without synthetic byte overrides and
replayed with Qwen3-30B-A3B, EP64, LAYERWISE model-derived KV, GateRouter
A2A_P2P, S16 topology and aggregate FlowSim capacity.

| trace window | request-level P2D completion clustering | FlowSim observation |
|---|---|---|
| Mooncake Conversation, 30s window 000045 | at most 2 completions in any 5/10/20/50-ms bin | completion spread from 29.5 ms to 3.47 s; EP CCT about 0.099–0.107 ms |
| Mooncake Tool/Agent, first 16 converted requests | at most 2 in 5/10-ms, 4 in 20-ms, 6 in 50-ms bins | completion spread from 50.1 ms to 3.23 s; EP CCT about 0.099–0.107 ms |

The traces do contain arrival bursts, but large and heterogeneous prompt
lengths turn those into a broad last-KV-completion spread. The first/last
P2D layerwise event spans are likewise request-size dependent. Therefore the
natural trace evidence does not currently show the narrow request-level
handoff burst required by N2.

## Evidence boundary

These are network-discovery replays. Their `ttft_data_plane_proxy` is not
integrated TTFT, and FlowSim queue is residual fluid backlog, not packet
buffer occupancy. No N2 serving claim is made from these results.

## Current decision

`N2_FINAL_FAIL_NO_NATURAL_HANDOFF_CLUSTERING` for the tested real windows.
The failure is mechanism-based: request-level last-shard completion is too
spread out for handoff synchronization to compress the Decode population.
An artificial synchronized release or arbitrary output/prompt modification
would not be a valid refinement. The next direction is N3, but only after
auditing whether the cluster config actually has multiple NIC/rail resources.
