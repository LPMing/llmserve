# 02 — Theoretical contention model and opportunity bounds

## Scope and validity

This is a necessary-condition model for the current Qwen3-30B-A3B profile and the implemented FlowSim path. It is not a predictor of packet queueing or a production arrival model. The network service abstraction is directed-link capacity plus max-min fluid sharing. A serving delay exists only when network completion moves a dependency barrier past work that would otherwise have continued or completed.

## Model-derived KV size

For a prompt with `N` tokens, the full BF16 KV bytes for Qwen3-30B-A3B are:

```text
B_KV(N) = N × L × 2(K,V) × H_KV × d_head × bytes_per_element
        = N × 48 × 2 × 4 × 128 × 2
        = N × 98,304 bytes.
```

With TP2, the serving ledger emits 48 × 2 = 96 layer/rank shards. Tested sizes: 32 tokens → 3,145,728 B; 128 → 12,582,912 B; 2,048 → 201,326,592 B; 8,192 → 805,306,368 B. These are model-derived, not overrides. At 200 Gbit/s, serialization-only lower bounds if the entire transfer used one continuously available link are 0.126, 0.503, 8.053, and 32.212 ms. These are not predicted request latencies: data is sharded, released layerwise, and may use multiple links while Prefill compute proceeds.

## Network service model

Let flow `i` have release time `r_i`, bytes `B_i`, and route `P_i`. Every directed link `e` has capacity `C_e`; endpoint/NIC rails are additional resources. At time `t`, a feasible allocation `x_i(t)` obeys `Σ_{i:e∈P_i} x_i(t) ≤ C_e` for each resource. Completion is the first time `∫[r_i,finish_i] x_i(t)dt = B_i`. FlowSim uses max-min sharing. Two flows contend only when their service intervals and at least one directed resource overlap.

For one shared bottleneck of capacity `C`, two equal-size flows of `B` released together under equal max-min share finish at `2B/C`; each isolated flow finishes at `B/C`. This is a 2× flow-FCT change but says nothing by itself about serving: if the delay fits under compute slack, or the flow is not the final required shard, the serving barrier need not move.

## Implemented MoE communication semantics (important limitation)

The current serving trace generator does **not** emit a GateRouter-derived
source-expert-owner A2A peer matrix. In `serving/core/trace_generator.py`,
`_emit_moe_block()` obtains GateRouter routing for expert compute, but the
network communication currently follows the configured vLLM
`allgather_reducescatter` realization:

```text
dispatch: ALLGATHER over the configured EP dimension
expert compute: per-rank profile lookup using the routed/padded token counts
combine: REDUCESCATTER over the configured EP dimension
```

For Qwen3-30B-A3B BF16, the trace generator calculates:

```text
dispatch_per_token = (hidden_size + num_experts) × bytes_per_element
                   = (2048 + 128) × 2 = 4,352 bytes
combine_per_token  = hidden_size × bytes_per_element
                   = 2048 × 2 = 4,096 bytes
dispatch AG data_size per rank = max(1, floor(S / EP)) × 4,352 bytes
combine RS data_size            = S × 4,096 bytes
```

Here `S` is `dp_sum_total_len` when available, otherwise this rank's padded
batch token count; EP is the configured collective degree. These values are
the ASTRA-Sim collective inputs (`comm_size`), **not a standalone measured
network-wide byte total**. Network-wide transmitted bytes depend on the
collective implementation and topology and must be read from its event/packet
ledger. The `total_ring_data()` helper used by power accounting is not a
substitute for that ledger. Therefore the current results validate contention
under this AG/RS collective abstraction, not exact MoE A2A routing geometry.

Although `_emit_moe_block()` contains historical comments saying “ALLTOALL”,
the emitted communication types are `ALLGATHER` and `REDUCESCATTER`. No claim
in this audit should describe them as strict All-to-All. `GateRouter` affects
expert-compute token distribution here; it does not currently provide a
physical per-source/per-expert-owner packet route matrix.

## Barrier exposure

For a P2D request with required transfers `i∈K`, `T_KV-ready = max_i finish_i`. For an EP collective `g` with required peer messages `j∈g`, `T_CCT(g) = max_j finish_j - T_start(g)`. A request/token sees only network delay not hidden by legal compute overlap or other dependencies.

For a layerwise P2D shard, the relevant quantity is its remaining hiding slack before its completion is needed. A shard-FCT increase smaller than this slack is hidden. At request handoff, only changes to the maximum required completion can move KV-ready; improving a non-last shard has no immediate benefit unless it becomes critical after another shard is improved. Similarly, improving a non-last EP peer does not change CCT until it reaches the collective maximum.

Necessary condition for serving-visible opportunity:

```text
shared-resource overlap
AND a contended flow/peer is or becomes barrier-critical
AND the resulting delay exceeds available serving slack.
```

The serving improvement upper bound of any scheduler is no greater than the network-induced delay actually exposed at the relevant barrier. If all delay is hidden, even an ideal priority oracle has zero TTFT/TBT headroom.

## What bounded experiments say

- **KV–KV:** unequal model-derived request sizes share P2D links and change per-shard mean/P99 FCT by up to +0.9%/+4.84% in the 32+128-token pair. Request last-shard completion, KV-ready, and TTFT do not move. With 128 tokens paired with 2,048 or 8,192 tokens, the short-request shard P99 rises +25.35%, but its request-level last-shard completion and TTFT still do not move.
- **KV–EP:** D4 with a late 8,192-token P2D request has same-directed-link time overlap. Relative to virtual KV isolation, EP CCT P99 rises +1.08%; TTFT/KV-ready are unchanged and Decode TPOT changes by <0.01% after the scheduler wakeup fix.
- **EP–EP:** two legal independent groups can contend when they issue separate Decode rounds concurrently and their actual participant routes share a directed server-NIC/ToR cut. A bounded Qwen3 TP2/EP4-per-group FlowSim test now demonstrates this: each group collective has four participants and twelve peer flows, and both groups use shared directed links. Matched CCT changes are 1.6–6.4%, while TPOT/TBT changes are under 1%. The per-layer dispatch+combine CCT deltas sum exactly to the measured per-token TBT delta across 48 layers; the effect reaches the serving barrier, but is only 0.75–0.80% of total TBT at these operating points. The collective remains a group barrier; no per-request flow split was introduced.

These observations fit the barrier/slack model: network service differs, but the changed completion is either not the last required shard or is absorbed by Prefill/Decode timing. They do not prove that every legal PD-MoE deployment lacks a network opportunity.

## Theory gate result

**Necessary-condition analysis: complete. Serving opportunity: NOT ESTABLISHED.** KV and EP can share resources, and EP groups can share links, but the tested points do not show that a feasible scheduler can materially improve a serving barrier. No exact optimum for the multi-link, layer-released event set was computed; current evidence does not justify implementing a scheduler.
