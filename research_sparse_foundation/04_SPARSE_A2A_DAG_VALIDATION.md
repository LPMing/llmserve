# 04 — Sparse A2A Serving DAG validation

## What the current ordinary Serving path emits

`serving/core/trace_generator.py::_emit_moe_block()` computes aggregate
per-rank work using `GateRouter.route_ep()`. Its communication realization is
the vLLM-style `ALLGATHER` dispatch plus `REDUCESCATTER` combine. It emits one
aggregate expert compute row per local EP rank, with its latency obtained from
`_lookup_moe(local_tokens, activated_experts)`.

This is not a token-level learned routing graph. With BALANCED, the per-rank
compute values are analytic equal-load approximations; with RR/RAND they are
simulator-policy outputs. The MoE compute profile is aggregated, not a sequence
of per-expert GPU kernels.

## Checked-out exact A2A converter

The modified Chakra `llm_converter.py` contains an `A2A_P2P` path that:

1. reads a route ID from an EXPERT marker;
2. requires an exact pair matrix and a one-to-one list of physical EP ranks;
3. emits one SEND/RECV per non-local source/destination owner pair;
4. forms a rank-local join over all emitted sends and receives;
5. places the dispatch join before expert compute and the combine phase after
   the local expert compute dependency.

That code is dormant in the current standard graph-generation path:

- `trace_generator.py` emits `ALLGATHER`/`REDUCESCATTER`, not `A2A_P2P` route IDs;
- `graph_generator.py::generate_graph()` constructs the converter with P/D and
  optional event metadata only; it does not pass `ep_global_ranks` or
  `a2a_routing`;
- the checked-out converter comments that graph generation imports the
  installed Chakra package, so edits to the checkout are not runtime proof
  unless that package is installed/revision-bound.

No test was found that builds all EP-rank graphs from a true route matrix and
checks the matched SEND/RECV graph through Serving completion.

## Requirement matrix

| Required invariant | Audit result |
|---|---|
| One actual source→owner message per routed pair, bytes conserved | Converter has code for aggregate pair entries; no true Qwen matrix or integrated test: **NOT_VALIDATED** |
| Every rank-local join waits for exactly its required dispatch peers | Join implementation exists for exact P2P, but not exercised end-to-end: **NOT_VALIDATED** |
| Send/receive buffer lifetime is legal | Not modeled/verified by the checked-out event DAG: **NOT_VALIDATED** |
| Expert compute cannot start before required dispatch input | Converter join is a dependency in the dormant P2P code; integrated execution: **NOT_VALIDATED** |
| Combine waits for corresponding expert compute | Local dependency exists in the converter path; complete group execution: **NOT_VALIDATED** |
| Decode token waits for all required combine outputs | Ordinary graph's collective dependency is present; exact sparse path and scheduler feedback: **NOT_VALIDATED** |
| GPU does not execute invalid concurrent expert work | Current graph serializes the aggregate local MoE compute; actual kernel overlap semantics are not represented: **NOT_VALIDATED** |
| Directed physical-link capacity and rank mapping are correct | S16 mapping gate fails; **NOT_VALIDATED** |
| Router matrix and compute profile query are paired | Actual router outputs absent; EP32/64 AE queries mostly clamped: **FAIL** |

## Serving dependency conclusion

The ordinary AG/RS path has a graph-level dispatch→MoE compute→combine order,
but that does not validate the dormant sparse-A2A path. Do not infer a
model-correct sparse result, network-level sparse-A2A CCT, or integrated
TTFT/TBT from the converter code or BALANCED sidecars.

**Gate:** `SPARSE_A2A_DAG_NOT_VALIDATED`; no sparse-A2A Serving performance
experiment is authorized by the current evidence.
