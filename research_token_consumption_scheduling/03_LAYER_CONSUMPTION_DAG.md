# Layer-consumption DAG and independent oracle

## Existing B0 behavior

The trace generator releases layerwise KV after that layer's Prefill QKV computation. Later Prefill layers continue while earlier transfers are in flight. Nevertheless, the integrated serving path admits Decode only after the request's entire P2D graph/handoff is complete. Thus current semantics are:

```text
Prefill layer l computes KV_l → P2D flow_l is released
       Prefill continues with l+1 without waiting for flow_l
all required P2D shards complete → request-level Decode admission
Decode executes a full token graph → token completion
```

This means an early KV layer can finish and sit unused while the last layer drains. Network completion of a layer is not currently connected to a Decode-layer readiness callback.

## Candidate layer-wise dependency (conditional legality)

For Decode token `t+1`, transformer layer `l` can execute only when:

1. Prefill has already sampled output token `t` (the oracle starts at sampler-ready, `177.175 ms`);
2. the complete previous Decode layer has produced the hidden state consumed by layer `l`;
3. the KV state for layer `l` is committed at Decode for every request in the unsplit batch and both TP ranks;
4. no conflicting KV read/write or TP inconsistency exists.

The modeled recurrence is:

```text
start_l  = max(finish_(l-1), max_KV_ready(l, request∈batch, rank∈TP2))
finish_l = start_l + max_rank(profile_compute_us[l, rank])
```

The full four-request batch is not split for free. Every layer waits for all four requests × two TP-rank shards. The batch's critical per-layer compute duration is the maximum of the two rank profiles. The final layernorm/lm_head/sampler tail is retained. No bytes are removed, no link is added, and no request's KV is skipped.

This recurrence is a conditional dependency model, not proof that the current serving runtime can legally execute it. The existing allocator/admission path commits and exposes the request after the full P2D handoff; it has no per-layer KV reservation/commit ledger for Decode. The oracle therefore assumes that each completed layer's KV occupies a stable, non-conflicting Decode slot while later layer transfers continue. Slot allocation, append-position safety, and concurrent cache-capacity invariants are not modeled or verified here. Until those invariants are established in a runtime, B2 must be read as an optimistic oracle bound, not a validated executable schedule.

## Event evidence classes

| Event/data | Classification | Source |
|---|---|---|
| P2D request/layer/rank release and flow completion | `SIMULATED` | A0 integrated FlowSim `a0_sampler_debug_flows.jsonl` |
| Per-layer Decode operator durations and graph total | `PROFILE_DERIVED` | Chakra `.et` graph produced by the existing trace generator from RTX PRO 6000 profile |
| TP collective join/CCT | `NOT_OBSERVED` | Each rank ET contains 48 zero-duration `ALLREDUCE` nodes; `collective_telemetry.jsonl` is header-only |
| Decode layer starts/finishes under the recurrence above | `ORACLE_MODELED` | Independent resource-constrained event calculation; not a serving backend run |
| Client token emission | `NOT_OBSERVED` | No independent client-output event in this simulator path |

The event CSV has 48 rows, each with eight required P2D shards (four requests × TP2), all 384 target flow bytes conserved, and rank-specific/profile-derived compute costs. It also records two zero-duration ET `ALLREDUCE` nodes per layer (one per TP rank) and explicitly marks the collective runtime event as `NOT_RECORDED`. The config uses EP1, so this fixture has no cross-node MoE EP barrier. Its first/last layer readiness and oracle schedule show that the decode compute cursor is already later than each layer's KV-ready time. No layer waits for KV in the modeled B2 schedule. The final modeled second token is `191.570 ms`.

## Result and what it does not establish

The B2 oracle hides all `182.646480 - 177.175 = 5.471480 ms` of post-sampler full-transfer drain behind legal sequential layer compute, reaching the 14.395-ms decode compute floor. It keeps the original full P2D payload of 403,537,920 B/request. However:

- It assumes per-layer KV commit/readiness at Decode, which the present integrated scheduler does not expose.
- It assumes stable, non-conflicting per-layer KV slots; current request-level allocation/admission has not been shown to support staged commits or concurrent append safely.
- The ET has TP collective nodes, but no nonzero duration or collective completion telemetry for them. B2 honors only the zero-duration collective semantics represented in this graph; it cannot validate physical TP collective joins or prove the same layer times on a real multi-GPU system.
- It omits additional layer synchronization, DMA staging, memory commit, and scheduler/launch overhead. Let total added cost be `H`.
- It uses sampler-ready as a conditional start for token interval analysis; this is not an observed client emission timestamp.
- It is not integrated-serving output. A real runtime must establish that each complete layer's KV can be installed/committed while later layers are in flight, and that the generated first token can be delivered independently.

Against A0's sampler-anchored first interval, B2 can tolerate `H < 5.471480 ms` just to improve. To reach a 15% reduction target (`≤16.886508 ms`), it requires `H ≤2.491508 ms` total, approximately `51.906 us/layer` averaged across 48 layers. This is a break-even sensitivity, not a measured overhead.

Numerically, the ideal B2 proxy interval of 14.395 ms clears that 15% threshold against A0's 19.866480-ms sampler proxy. But A2 DELTA already has the same 14.395-ms interval and the same token2/token3 timestamps in the integrated run, while transferring 456× fewer KV bytes. Thus clearing the threshold against A0 is not evidence of incremental novelty or a client-visible result.

