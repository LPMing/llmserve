# 08 — Sparse A2A model and theory screen

## Intended question

For a collective, a useful first-order lower bound is per directed cut, not
`sum(all bytes)/one link rate`:

`T_collective >= max_cut(B_cut / C_cut)`

where `B_cut` is the bytes that must cross a directed cut and `C_cut` is its
simultaneously available capacity. A true collective also has release times,
endpoint/NIC limits, route multiplicity, protocol overhead and a max/last-peer
barrier. If multiple flows share a cut, their individual completion times
depend on the service discipline and concurrent active set.

For a same-request KV handoff the serving event is the last required shard, not
the sum of shard FCTs. For an EP round it is the last required peer/message, not
the mean P2P latency. These barrier definitions are necessary, but not enough:
the release/compute DAG must also be accurate.

## Frozen configuration in the bounded screen

| Parameter | Value |
|---|---|
| Model profile | Qwen3-30B-A3B-Instruct-2507, BF16 profile; 48 layers, 128 experts, top-k 8 |
| Cluster | S16 EP64: 16 servers, 8 Prefill + 8 Decode, 8 GPUs/server, 128 GPU endpoints |
| Parallelism | TP2; EP64 across eight Decode servers; two experts per EP rank |
| Network | 200-Gbps endpoint NIC resources, 1:1 Clos; 4 leaves + 2 spines; four parallel links per leaf/spine pair represented as aggregate directional fluid capacity in FlowSim |
| Requests | First 16 requests of preserved BurstGPT window `30s__window_148333.jsonl`; 2,203 input tokens, 715 output tokens, 1.0-second source span |
| P2D | `LAYERWISE`, 1,536 layer events, 216,563,712 model-derived bytes |
| EP | 10,768 aggregate flow events, 2,117,074,944 bytes; 336 coalesced phase/barrier records |
| FlowSim | `FAIR`, residual-fluid/max-min service; replay issue times are fixed independently of network completion |

The byte formula in the builder is 98,304 bytes per input token across the
configured TP ranks, yielding `2,203 × 98,304 = 216,563,712` P2D bytes. EP bytes
are produced by its GateRouter-derived route matrix and model tensor sizes;
there is no synthetic byte override. These statements validate byte accounting
for this replay, not the correctness of its collective semantics.

## Why the lower bound does not establish a result

Aggregate total bytes do not identify `B_cut`: the actual source/destination
pair matrix and placement determine which traffic crosses each leaf/spine or
receiver cut. FlowSim's parallel-link aggregation is appropriate only for its
aggregate fluid abstraction; it does not model packet ECMP, packet queues,
ECN/PFC or QP-level behavior. Moreover, the builder coalesces all 48 MoE layers
within an EP time bin into one phase, and starts that phase at the earliest
constituent Decode step. Therefore the resulting 336 records are not faithful
per-layer/per-token collective barriers and cannot be used to infer TBT.

The useful theoretical test would hold the actual token→expert assignments,
bytes, arrivals and compute fixed, then test whether a changed physical
placement/path changes `B_cut` for the last peer and whether P2D adds exposure.
The current “uniform” matrix does not satisfy the first condition.

## Scope of conclusion

The measured approximate CCT is physically plausible as a fluid-model output,
but the experiment does not pass the semantic precondition for interpreting it
as a legal route-geometry headroom bound. It is a diagnostic that found a
counterfactual-construction defect, not evidence of an optimization ceiling or
of a production bottleneck.

