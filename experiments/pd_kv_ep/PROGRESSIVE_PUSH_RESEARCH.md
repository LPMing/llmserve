# Progressive NIXL Push Research Ledger

## Status

Current status: **semantic implementation and correctness validation passed; serving-level paper motivation not yet established**.

This phase is isolated from the frozen P1-P5/N1-N5 results. The new modes are opt-in and do not relabel the existing `LAYERWISE` mode as progressive Push.

The simulator implements a model-derived, protocol-level NIXL Push abstraction. It does **not** claim to execute upstream CUDA-direct NIXL, GPU memory registration, descriptors, WQEs, polling, or real NIXL software overhead. Those missing costs are zero and are disclosed here.

## Semantic audit summary

Current request path before this phase:

```text
request -> Scheduler chunk -> full Prefill completion -> existing P2D barrier
        -> router.transfer_prefill_request() -> Decode admission
```

`LAYERWISE` creates model-derived KV sends at transformer-layer trace positions. It is not progressive block publication: it does not create a settlement frontier, immutable ranges, coalesced writes, or producer-rank commit.

`POST_PREFILL` creates one post-prefill KV transfer marker. Neither legacy mode is changed.

The new modes are:

- `NIXL_PUSH_WHOLE_REQUEST`: after the final Prefill chunk settles, publish one whole-request logical range, issue writes to the paired Decode ranks, and admit Decode only after all writes and producer-rank commits complete.
- `NIXL_PUSH_PROGRESSIVE`: after each completed Prefill chunk, settle the generated range; publish only complete logical blocks unless the final chunk flushes a partial tail; coalesce until the configured threshold; allow one request-local write in flight per producer rank; and require the final commit barrier before Decode admission.

The supported abstraction boundary is PP1, same TP-compatible P/D layouts, chunked Prefill, prefix caching disabled, and FlowSim. The CLI now rejects Push modes with a non-FlowSim backend or effective prefix caching enabled.

## Source-level implementation

| Concern | Implementation |
|---|---|
| Request state | `serving/core/request.py`: Push epoch, settled/posted frontiers, registration, publication and commit state |
| Settlement/publication | `serving/core/scheduler.py::_push_settlement()`; settlement is derived from the scheduled Prefill chunk and attached after the Prefill compute DAG, not from network completion |
| Trace markers | `serving/core/trace_generator.py`: `nixl_push_settlement`, `nixl_push_write`, `nixl_push_commit` |
| ET conversion | `astra-sim/extern/graph_frontend/chakra/src/converter/llm_converter.py`: event types 6/4/5; WRITE SEND/RECV and commit dependencies |
| Flow execution | `serving/core/flowsim_worker.py`: one in-flight write per `(request, producer rank)`, write completion, all-producer commit retry, compact telemetry |
| Network bytes | `MemoryModel.pd_kv_bytes()`; no arbitrary KV byte override |

The marker-index bug found during validation was corrected: Push markers retain their protocol name while ordinary trace layers retain their positional suffix. Without this correction, Python accepted values such as `32_484` as an integer and silently corrupted settlement telemetry.

A second real bug was corrected in the multi-producer barrier: completion of one producer rank now rechecks all request commit waiters. The request summary is written only after all producer-rank commits are complete.

## Lifecycle invariants validated

For a successful request:

```text
Prefill chunk compute
  -> PUSH_SETTLED
  -> zero or more PUSH_WRITE_SUBMITTED/COMPLETED
  -> final PUSH_COMMITTED for every producer rank
  -> p2d_kv_ready_time
  -> Decode scheduler admission
  -> first token
```

The request-level Push summary verifies:

```text
posted_tokens == settled_tokens == input_tokens
Decode_received_KV_bytes == model-derived total KV bytes
commit_rank_count == number of producer ranks
Decode admission >= all producer-rank commit timestamps
```

`PUSH_SETTLED` is a zero-byte control marker; it does not consume FlowSim network capacity or add artificial delay. WRITE bytes are model-derived per producer-rank/per-destination shards.

## Correctness gates

| Gate | Configuration/evidence | Result |
|---|---|---|
| C0 one chunk | Qwen3, input 10, output 70, Push whole/progressive | Pass. One final settlement, two destination writes, one commit; legal TTFT/TBT/TPOT output. |
| C1 two chunks | input 64, `max-num-batched-tokens=32`, progressive | Pass. settlements `32,64`; ranges `[0,32]`, `[32,64]`; 4 writes because each range has two Decode destinations; final commit after the second range. |
| C2 long prompt | clean matrix at 1,024/4,096/16,384/32,768 input tokens | Pass. All requests finish and produce serving CSV plus Push telemetry. |
| C3 final partial block | input 50, block 16, chunk budget 32 | Pass. settlements `32,50`; final range `[32,50]` is marked final and is flushed. |
| C4 threshold not reached | input 4,096, chunk budget 32, coalesce threshold 1 GiB | Pass. 128 settlement events, only final two writes, final flush and commit. |
| C5 TP2 | TP2 Prefill, two Decode ranks, native AG/RS compatibility path | Pass. two settlement events and two `PUSH_COMMITTED` events; summary `commit_rank_count=2`. An earlier A2A-P2P attempt exposed an old incompatible TP2 ASTRA configuration, not a Push semantic failure. |

The compact event and request ledgers are in:

- `results/progressive_push/PROGRESSIVE_PUSH_EVENTS.csv`
- `results/progressive_push/PROGRESSIVE_PUSH_REQUESTS.csv`

Successful replays clean generated backend inputs unless `--keep-inputs` is supplied. The compact serving CSVs/logs and the three ledgers above are retained; transient full backend inputs were inspected during validation but are not treated as permanent artifacts.

## B0/B1 serving characterization without EP network

The first comparison intentionally disabled EP network service with `FLOWSIM_NETWORK_CLASSES=KV_MOVEMENT`. This isolates the Push handoff timeline; it is not a final performance result.

All runs use the same Qwen3 model-derived bytes, same request, same topology, prefix caching disabled, PP1, and output length 1. `TBT` is therefore only a first token interval and `TPOT=0`; these runs are correctness/isolation evidence, not a Decode-tail study.

| Input tokens | Whole TTFT (ms) | Progressive TTFT (ms) | Improvement | Whole writes | Progressive writes |
|---:|---:|---:|---:|---:|---:|
| 1,024 | 70.318 | 70.318 | 0.00% | 2 | 2 |
| 4,096 | 197.656 | 181.550 | 8.15% | 2 | 4 |
| 16,384 | 1060.301 | 947.558 | 10.63% | 2 | 16 |
| 32,768 | 2874.590 | 2632.998 | 8.41% | 2 | 32 |

Total KV bytes are identical within every pair:

- 1,024: 100,663,296 bytes;
- 4,096: 402,653,184 bytes;
- 16,384: 1,610,612,736 bytes;
- 32,768: 3,221,225,472 bytes.

The measured gain is therefore attributable to earlier publication and overlap with later Prefill computation, not to deleting bytes. The current clean points are below the 20% paper-motivation threshold and use one request with no EP network service.

At 4,096 input tokens, the coalescing threshold sensitivity is informative:

- thresholds 4/8/16/32/64 MiB all publish one range per 2,048-token Prefill chunk because each chunk's model-derived range is already larger than those thresholds;
- a 1 GiB threshold suppresses intermediate publication and produces the same TTFT/ready time as whole-request mode (`197.656 ms` / `192.958 ms`), while still performing the mandatory final flush.

## EP-enabled sanity

A matched 64-token, output-1 run with Qwen3 A2A-P2P and FlowSim FAIR completed for both modes:

| Mode | TTFT (ms) | P2D ready (ms) | TBT (ns) | total KV bytes | writes |
|---|---:|---:|---:|---:|---:|
| Whole | 89.308 | 84.709 | 4,598,832 | 6,291,456 | 2 |
| Progressive | 89.056 | 84.457 | 4,598,832 | 6,291,456 | 4 |

This confirms event classification and serving accounting with EP present. It is not enough to claim a progressive-Push/EP result: output length 1 gives no meaningful TPOT tail or repeated Decode EP rounds.

## Current interpretation

A request-scoped handoff bug was found during the first multi-request replay and fixed before using any result: a short request finishing a mixed-length Prefill batch could previously transfer every request in that batch to Decode. The handoff now transfers only requests whose own final Prefill chunk and Push commit barrier are complete. The corrected path was revalidated with two- and four-request real replays; no request is admitted with `num_computed_tokens == num_tokens_reached`.

The completed real-serving ledger is `results/progressive_push/PROGRESSIVE_PUSH_REAL_SERVING_RESULTS.csv`. Every row is read from a serving CSV; TBT statistics flatten the complete per-request TBT arrays, rather than using a network proxy. For four-request samples, request-level P95/P99 use the largest request by nearest-rank definition; this is reported as a tail diagnostic, not as a statistically stable production percentile.

### Real trace matched results

The common setup is FlowSim, the existing small integrated 1-Prefill/2-Decode gate, prefix caching disabled, PP1, model-derived Qwen3 KV bytes, and matched `NIXL_PUSH_WHOLE_REQUEST` versus `NIXL_PUSH_PROGRESSIVE` runs. This gate uses the existing `2_leaf_4_rank_shared_spine_50g.txt` topology, so it is a semantic/integrated validation rather than a 100/200-Gbps large-scale claim. The two EP-enabled columns use `FLOWSIM_NETWORK_CLASSES=KV_MOVEMENT,EP` and A2A-P2P; the KV-only columns deliberately isolate the Push handoff timeline.

| Trace window | Network classes | TTFT mean Whole -> Progressive | TTFT P99 Whole -> Progressive | TTFT P99 improvement | TBT P99 Whole -> Progressive | TPOT P99 Whole -> Progressive |
|---|---|---:|---:|---:|---:|---:|
| BurstGPT 062460 | KV only | 378.625 -> 344.300 ms | 541.265 -> 475.764 ms | 12.10% | 5.563 -> 5.563 ms | 5.383 -> 5.396 ms |
| BurstGPT 148335 | KV only | 69.784 -> 69.784 ms | 69.784 -> 69.784 ms | 0.00% | 5.131 -> 5.131 ms | 4.555 -> 4.555 ms |
| Mooncake 000114 | KV only | 1366.537 -> 1140.324 ms | 2250.578 -> 1852.725 ms | 17.68% | 6.232 -> 6.232 ms | 6.210 -> 6.210 ms |
| Mooncake 000087 | KV only | 1166.840 -> 956.552 ms | 2354.370 -> 1909.431 ms | 18.90% | 6.619 -> 6.619 ms | 6.365 -> 6.499 ms |
| BurstGPT 062460 | KV + EP | 382.751 -> 349.216 ms | 550.756 -> 484.179 ms | 12.10% | 6.588 -> 6.588 ms | 6.253 -> 6.277 ms |
| Mooncake 000114 | KV + EP | 1367.644 -> 1140.890 ms | 2253.444 -> 1853.398 ms | 17.76% | 6.816 -> 6.816 ms | 6.792 -> 6.792 ms |
| Mooncake 000087 | KV + EP | 1183.615 -> 958.106 ms | 2397.957 -> 1913.099 ms | **20.22%** | 7.644 -> 7.644 ms | 7.309 -> 7.431 ms |
| Mooncake 000103 | KV + EP | 1591.924 -> 1281.961 ms | 2785.317 -> 2231.024 ms | 19.90% | 7.788 -> 7.788 ms | 7.529 -> 7.602 ms |

The EP-enabled `Mooncake 000087` point crosses 20% for request-level TTFT P99, but the two neighboring real windows do not: 000114 is 17.76% and 000103 is 19.90%. Therefore this is a strong, trace-grounded boundary result, not yet a robust “second-window” PASS. The exact same total input/output tokens, arrival order, topology, collective semantics, and model-derived communication generation were used within each matched pair.

### Token-level interpretation

Progressive Push changes the Prefill-to-Decode handoff critical path. It does not remove KV bytes: the request receives the same model-derived KV volume, and Progressive only publishes complete logical ranges earlier. Across the EP-enabled windows, TBT P99 is unchanged to the reported precision. TPOT changes are small and not consistently favorable (for example, 000087 changes by about +1.7% and 000103 by about +1.0%). Thus the present evidence supports a TTFT/handoff effect, not a Decode EP/TBT optimization.

The 1024-token batch-budget refinement on Mooncake 000087 was also matched and completed legally:

| Setting | TTFT mean Whole -> Progressive | TTFT P99 Whole -> Progressive | P99 improvement | TBT P99 | TPOT P99 |
|---|---:|---:|---:|---:|---:|
| `max-num-batched-tokens=1024`, KV only | 1485.552 -> 1251.033 ms | 3064.443 -> 2582.723 ms | 15.72% | 6.619 -> 6.619 ms | 6.234 -> 6.288 ms |

This neighboring sensitivity point did not increase the headroom beyond the 2048-token setting. It also shows why simulator wall-clock must not be confused with serving time: each 1024-token run took roughly fourteen minutes of host execution, while the reported TTFT values are simulated nanoseconds converted to milliseconds.

### Current decision

The Push protocol implementation and serving propagation are valid. The strongest result is a 20.22% TTFT P99 reduction in one real Mooncake + EP window, with two adjacent EP-enabled windows at 17.76% and 19.90%, and no measurable TBT P99 gain. Under the declared evidence standard, this is **borderline but not a robust architecture PASS**: one point crosses the target, but the effect has not yet shown stable two-window headroom, and the primary benefit remains TTFT rather than the KV-vs-EP TBT coupling originally sought.

No final scheduler, arbitration policy, NIXL software overhead, or artificial delay has been implemented. The next research decision should not be to amplify this number by lowering bandwidth, synchronizing arrivals, or inflating KV. If this architecture is retained, the defensible claim is a trace-dependent Push handoff characterization; a stronger CCF-A claim needs a larger sample of natural windows and an explicit source/runtime basis for NIXL costs. Otherwise this phase should be recorded as a bounded positive result and the study should move to a different network-specific problem.

## Link-rate sensitivity with the smaller topology

To remove the 50-Gbps limitation without enlarging the integrated testbed, two new cluster variants were created. They keep the same 1-Prefill/2-Decode endpoint mapping, Qwen3 model, EP4 A2A-P2P traffic, four-request Mooncake 000087 workload, arrival order, and Push parameters. The only topology change is the existing shared-spine link rate:

- `small_one_prefill_two_decode_pd_moe_ep4_100g.json` -> `2_leaf_4_rank_shared_spine_100g.txt`
- `small_one_prefill_two_decode_pd_moe_ep4_200g.json` -> `2_leaf_4_rank_shared_spine.txt`

| Shared link rate | Mode | TTFT mean (ms) | TTFT P99 (ms) | P99 improvement vs Whole | TBT P99 (ms) | TPOT P99 (ms) |
|---:|---|---:|---:|---:|---:|---:|
| 50 Gbps | Whole -> Progressive | 1183.615 -> 958.106 | 2397.957 -> 1913.099 | 20.22% | 7.644 -> 7.644 | 7.309 -> 7.431 |
| 100 Gbps | Whole -> Progressive | 1035.780 -> 925.978 | 2095.379 -> 1864.302 | 11.03% | 7.203 -> 7.203 | 7.007 -> 7.038 |
| 200 Gbps | Whole -> Progressive | 964.934 -> 909.034 | 1954.557 -> 1835.835 | 6.07% | 6.983 -> 6.983 | 6.832 -> 6.845 |

The 100/200-Gbps matched runs completed legally with the same model-derived KV/EP bytes. Increasing link rate reduces absolute TTFT and the amount of exposed P2D serialization; it also reduces the relative advantage of publishing intermediate ranges. TBT P99 remains unchanged at each rate. Therefore the previous 50-Gbps 20.22% point is a low-bandwidth sensitivity result, not a robust high-speed-network result. The compact exact ledger is `results/progressive_push/PROGRESSIVE_PUSH_BW_RESULTS.csv`.

This is an important negative boundary for the Push idea: at the requested 100/200-Gbps rates and the same small integrated workload, Progressive Push does not provide a 20% serving-level TTFT opportunity. No bandwidth was lowered to recover the old result, and no bytes or arrival timing were changed.

## Next experiment boundary

No further synthetic stress is justified for this phase. Any continuation must use another pre-existing Mooncake window or a larger matched trace sample with the same serving semantics, and must report both TTFT and token-level TBT. The current evidence is sufficient to preserve the implementation and the compact ledger, but insufficient to claim that Progressive Push is a general CCF-A motivation or that it improves Decode EP behavior.

This is characterization only; it is not an adaptive scheduler.
