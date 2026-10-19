# MoE Decode DAG semantics audit

## Scope and interpretation

Model under inspection: Qwen3-30B-A3B-Instruct-2507, 48 MoE layers, 128 experts, top-k 8, BF16, RTX PRO 6000 profile. The questions below distinguish (i) standard current Serving-generated traces, (ii) the dormant exact A2A_P2P converter extension, and (iii) the full Decode iteration callback. These are not interchangeable.

## Current standard Serving trace: AG/RS

`serving/core/trace_generator.py::_emit_moe_block()` (lines 1107–1196) emits:

```text
attention/output hidden state
    -> EXPERT-start marker: ALLGATHER dispatch
    -> per-rank aggregate MoE compute row
    -> EXPERT-END marker: REDUCESCATTER combine
    -> next transformer layer
```

At lines 1131–1145 the comments and code select the vLLM `allgather_reducescatter` realization. The dispatch payload is computed from hidden/router-logit sizes; combine uses the pre-scatter buffer. `GateRouter.route_ep()` supplies per-rank `local_tokens` and `activated_experts` for compute lookup, but not a source→owner pair matrix.

`serving/core/flowsim_worker.py::_activate()` (roughly 1646–1689) collects all participant collective nodes. `_start_collective()` (1587–1645) waits until every participating rank's graph node is ready, submits peer flows, and `_complete_flow()` (1782–1810) completes **all** participant collective nodes only when the entire collective flow set is complete. Thus in the standard AG/RS path:

- Dispatch is a group-wide release barrier before any rank's aggregate expert compute.
- Expert compute is represented per rank, not as one global compute node, but the collective predecessor currently releases all rank compute nodes together.
- Combine is likewise a group-wide barrier before downstream rank-local graph nodes.
- The group completion event is an actual dependency in this path, not just telemetry.

Some synchronization is inherent to an AG/RS collective's output contract. Whether the all-rank *completion callback* is stricter than each rank's local output-readiness requires comparing to the exact deployed collective/runtime semantics; it cannot be declared an erroneous barrier merely because it delays the graph.

## Dormant exact A2A_P2P extension

`astra-sim/extern/graph_frontend/chakra/src/converter/llm_converter.py::emit_exact_a2a_p2p()` (634–702) uses an explicit `pair_matrix`, global EP ranks, and per-peer SEND/RECV nodes. It adds a **rank-local** zero-time join whose parents include every nonlocal outgoing send and incoming receive for that rank. The MoE compute row on that rank depends on its local marker/join (conversion loop around 938–969). The analogous combine join is also local.

Consequences:

- A rank's compute may become ready before other ranks' joins finish. The `ep_p2p_flow_groups`/`ep_collective_*` bookkeeping in `flowsim_worker.py` writes a group CCT after all recorded nodes complete (1811–1833); this telemetry completion does not gate those graph nodes.
- This is already a coarse rank/owner-local streaming capability in the dormant path. Calling all of A2A_P2P a group-wide barrier would be wrong.
- The local join is stronger than input readiness: dispatch compute waits for both outgoing sends and incoming receives. A compute owner normally needs its required inbound token activations; its outbound dispatch completion may be unnecessary unless buffer aliasing/lifetime or the real transport imposes that dependency. For combine, a source rank needs all required returned contributions for its local token set, not necessarily all of its own outgoing combine sends.
- The current event model emits one aggregate owner compute task; it does not expose per-expert or per-token partial compute readiness. It also joins aggregate peer messages, not each token's top-k completion graph.
- At the end of a complete Serving graph, the batch/EP job is still reported complete only after all graph nodes finish. That final iteration/request barrier remains; per-owner progress does not mean a token can be returned before its required expert contributions are assembled.

## Why this extension is not the current integrated path

`serving/core/graph_generator.py::generate_graph()` (205–266) constructs `LLMConverter` with P/D receiver arguments and optional serving event metadata; it does not pass `ep_global_ranks` or `a2a_routing`. The standard `trace_generator._emit_moe_block()` writes AG/RS marker rows, not `A2A_P2P` route IDs. The converter constructor accepts route metadata, but the checked-in standard graph path does not feed it. Several historical scripts/reports use a separate event-ledger path; they do not change this standard integrated DAG.

There is also a source/API mismatch: the current `GateRouter.route_ep(layer_num,batch_id,total_len,ep_size)` returns `RoutingResult(local_tokens,activated_experts,source_tokens)` only. A retained event-builder calls `routing.pair_matrix` and a `source_tokens=` argument that current `GateRouter` does not implement. That builder cannot establish a current-version route matrix without code changes.

## Token and request barriers

The exact P2P path can let each rank progress once its local join completes, but a rank's next-layer hidden state requires all relevant expert outputs for that rank's local tokens. The serving iteration callback still waits for the entire submitted group graph. The target metric for a candidate must therefore be the reduction in the **last required rank/collective completion** that survives through the 48-layer Decode DAG, not the earliest owner's start time or a sum of local overlap windows.

## DAG finding

There is no evidence that the standard integrated AG/RS graph already performs owner-level readiness. Conversely, an owner-local join already exists in the separate A2A_P2P converter. A narrower possible dependency improvement is to release each owner compute from its required inbound Dispatch only (and each source continuation from its required inbound Combine only), while preserving buffer, expert, top-k, and iteration barriers. This is a plausible implementation question, not yet proven to be unnecessary synchronization or a paper problem.

