# Progressive NIXL Push — Simulator Semantic Audit

## Current status

`COMPATIBLE_WITH_ABSTRACTION`

The current simulator can represent the protocol-level distinction between
Prefill settlements, immutable KV ranges, network WRITE events, final commit,
and Decode admission. It does not implement NIXL, CUDA-direct memory
registration, GPU block addresses, descriptor construction, polling, or real
NIXL completion notifications. The implementation target is therefore a
model-derived protocol/data-plane abstraction, not a claim that upstream vLLM
already runs Progressive Push for this simulator configuration.

The upstream RFC explicitly describes Progressive block handoff as an opt-in,
capability-gated NIXL Push path. Its initial boundary includes CUDA-direct
Push, one causal full-attention KV group, contiguous block table, compatible
P/D layouts, same TP, PP1, chunked Prefill, prefix caching disabled, and no
speculative decoding. The public RFC is vLLM issue #53703; the current NIXL
Push design document describes P writing into Decode's pre-allocated memory.

## A. Current request-to-Prefill execution

### A.1 Request arrival and admission

1. `serving/core/router.py::load_requests()` loads flat/agentic requests and
   keeps them arrival-sorted.
2. `Router.route_arrived_requests()` places an arrived request into a Prefill
   scheduler.
3. `serving/core/scheduler.py::Scheduler.schedule()` first serves running
   requests, then admits waiting requests through `_schedule_waiting()`.
4. With `enable_chunked_prefill=true`, the scheduler uses the remaining token
   count, `max_num_batched_tokens`, and
   `long_prefill_token_threshold` to choose `num_new`. A long prompt is
   therefore split across multiple scheduler/model batches when the token
   budget or per-request threshold is smaller than the remaining prompt.
5. `Scheduler._build_batch()` records `(request, num_new,
   computed_before)` in `Batch.scheduled_tokens`, and classifies `num_new > 1`
   as a Prefill chunk. This classification is observational and drives the
   profiled attention lookup; it is not a NIXL settlement event today.

Relevant source locations:

- `serving/core/scheduler.py:150-202`: running-request scheduling;
- `serving/core/scheduler.py:204-278`: waiting-request admission and chunk
  sizing;
- `serving/core/scheduler.py:280-292`: next-chunk sizing;
- `serving/core/scheduler.py:314-398`: Batch formation and per-request
  scheduled-token accounting.

### A.2 Model trace and chunk completion

`serving/__main__.py` calls `generate_trace()` after the scheduler batch is
formed. `serving/core/trace_generator.py::_build_batch_ctx()` derives
`prefill_chunk` from `sum(batch.prefill_q_list)`. The trace then emits the
complete 48-layer Qwen3 transformer execution for that scheduler batch.

The graph is converted by `serving/core/graph_generator.py` and executed by
the selected backend. Completion returns through `serving/__main__.py` to
`Scheduler.add_done()`.

`Scheduler.add_done()` advances a chunk's accounting after the graph reports
completion. Intermediate chunks execute the `num_new > 1` branch and cache
completed blocks if prefix caching is enabled. They do not transfer the
request to Decode. Only when `num_computed_tokens >= original_input` does the
current Prefill request become `prefill_done_now`.

Relevant source locations:

- `serving/core/trace_generator.py:966-1000`: BatchCtx and Prefill chunk
  derivation;
- `serving/core/trace_generator.py:1573-1645`: complete model trace per
  scheduler batch;
- `serving/core/scheduler.py:550-650`: graph completion and request state
  transitions.

## B. Current P/D handoff semantics

### B.1 Existing modes

The CLI currently accepts only:

- `LAYERWISE`;
- `POST_PREFILL`.

`serving/core/trace_generator.py` emits:

- `LAYERWISE`: the `qkv_proj` row of every transformer block carries the
  model-derived per-rank K/V bytes for the current scheduled Prefill tokens;
  the Chakra Prefill converter creates a P2D SEND/RECV at that layer point.
- `POST_PREFILL`: one `pd_kv_transfer` marker is appended after the final
  Prefill layers and carries the same model-derived K/V payload for the
  scheduled chunk.

Neither mode is Progressive NIXL Push. In particular, LAYERWISE is keyed by
transformer-layer completion, not by completed Prefill chunks and immutable
logical KV blocks.

### B.2 Existing handoff barrier

The Prefill scheduler calls `router.transfer_prefill_request()` only after the
request reaches its full prompt. For interactive FlowSim, the worker tracks
the P2D sender/network completion and calls `complete_htsim_p2d_handoff()`;
that function sets `p2d_kv_ready_time_ns` and then invokes the router. The
Decode scheduler's `add_decode()` therefore occurs only after the current
P2D handoff barrier.

For native/analytical paths, the normal completion callback calls the same
router transfer after the Prefill request is complete. The Decode side is not
admitted by an intermediate layerwise send.

Relevant source locations:

- `serving/core/router.py:389-404`: Prefill-to-Decode transfer callback;
- `serving/__main__.py:1494-1562`: network completion and Prefill handoff;
- `serving/__main__.py:1364-1383`: FlowSim P2D-ready completion;
- `serving/core/scheduler.py:569-610`: full-Prefill completion and handoff.

### B.3 Existing byte accounting

For Qwen3:

`per-rank KV bytes = 2 * num_key_value_heads * head_dim * tokens * KV_dtype_bytes / TP`.

The current model config gives 4 KV heads, head dimension 128, 48 layers,
BF16 weights/KV by default, and TP2. The per-layer LAYERWISE payload is
computed by `_pd_kv_send_bytes()`; POST_PREFILL multiplies that incremental
payload by `num_hidden_layers`.

The existing accounting is model-derived and does not include Q activations.
There is no duplicate-byte correction that could be reused as Progressive
publication state; the new mode must maintain its own logical frontier.

## C. Block and cache layout

`serving/core/kv_cache_manager.py::request_block_hashes()` constructs a
block-hash chain. `TieredKVCacheManager` allocates blocks and can index full
blocks after completed compute. `block_size` defaults to 16 tokens at
`serving/__main__.py:530`, with per-instance overrides in the cluster config.

The current block manager is a cache-capacity/prefix-reuse model. It does not
currently expose a per-request immutable-publication frontier to the P2D
writer, and it does not represent device addresses or NIXL registration
handles. Progressive Push will use a logical-range abstraction:

`request epoch + producer rank + [logical block start, logical block end)`.

No physical block address is inferred.

The final partial block is not a complete cache block under the normal
block-pool rule. It may become a Progressive final-tail range only after final
Prefill settlement. A non-final partial block must never be published.

## D. Qwen3-30B-A3B compatibility

Current config: `configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json`.

| RFC capability | Current configuration | Decision |
|---|---|---|
| one causal full-attention KV group | 48 full-attention layers; no sliding-window/MLA field | compatible at KV protocol level |
| contiguous block table | simulator has 16-token logical block chain; no physical address table | compatible with logical-range abstraction |
| same TP | S16 reference uses TP2 on both P/D sides | compatible |
| PP1 | S16 reference has PP1 | compatible |
| chunked Prefill | enabled by default; controlled by token budget/threshold | compatible |
| prefix caching disabled | current CLI default is enabled | run Progressive experiments with explicit `--no-enable-prefix-caching` |
| speculative decoding disabled | no speculative-decoding model/state in current simulator | compatible |
| CUDA-direct NIXL Push | no NIXL/CUDA registration implementation | abstraction only |
| MoE FFN | 128 experts, top-k 8; KV path remains full-attention KV | compatible; MoE is outside KV layout, but EP is a separate shared-fabric consumer |

Qwen3 is therefore `COMPATIBLE_WITH_ABSTRACTION`, not a claim of upstream
NIXL runtime compatibility. The progressive protocol correctness tests must
first disable prefix caching and use PP1/TP2.

## E. Missing semantics that the new mode must add

The current simulator lacks the following state transitions:

1. Prefill settlement as a first-class event;
2. sealed immutable KV frontier by request and producer rank;
3. early destination registration/readiness;
4. pending published ranges and adjacent-range coalescing;
5. one request-local WRITE in flight;
6. WRITE completion separate from Prefill chunk completion;
7. final-tail publication and flush;
8. producer-rank commit;
9. Decode admission waiting for all producer-rank commits.

These will be implemented as a new opt-in mode, not by renaming LAYERWISE.
Existing LAYERWISE, POST_PREFILL, remote-prefix, and FlowSim semantics must
remain unchanged.

## F. Audit decision and next step

The simulator is semantically sufficient for a faithful logical protocol
extension with model-derived bytes and explicit state assertions. It is not
sufficient to model NIXL descriptor/polling software overhead; that overhead
will remain zero and will be disclosed as a network/serving abstraction.

Next implementation order:

1. add `NIXL_PUSH_WHOLE_REQUEST` as an opt-in clean baseline;
2. add `NIXL_PUSH_PROGRESSIVE` with settlement/publication/WRITE/commit state;
3. run C0–C5 correctness gates before any performance sweep;
4. only then run the integrated whole-vs-progressive comparison.



## G. Implemented validation addendum

The opt-in implementation is now present in the Python scheduler, Chakra
converter, and FlowSim executor. It adds `PUSH_SETTLED` as a zero-byte control
marker, distinct from WRITE and COMMIT. This matters when a Prefill chunk
settles but the coalescing threshold has not been reached: the chunk is still
observable without inventing a network transfer.

The validated invariants are:

- non-final incomplete blocks are not published;
- final partial blocks are flushed;
- one WRITE is in flight per request/producer-rank scope;
- all producer-rank commits are required before Decode admission;
- Push marker names are not assigned ordinary layer indices;
- request summary telemetry is flushed only after all producer-rank commits.

The clean integrated characterization is recorded in
`PROGRESSIVE_PUSH_RESEARCH.md` and the compact exact-metrics ledger
`results/progressive_push/PROGRESSIVE_PUSH_REAL_SERVING_RESULTS.csv`.
A request-scoped handoff bug found during the first mixed-length replay was
fixed before accepting results: completion of a short Prefill batch member no
longer transfers unrelated longer requests to Decode. Corrected two- and
four-request replays complete with request-local Push commit barriers.

The real multi-request evidence now includes BurstGPT and Mooncake windows,
with and without FlowSim EP service. Progressive publication reduces TTFT
because it exposes completed ranges before the final Prefill computation
finishes. The strongest matched point is 20.22% request-level TTFT P99
improvement in Mooncake window 000087 with EP enabled; adjacent EP-enabled
windows are 17.76% and 19.90%. Token-level TBT P99 remains unchanged to the
reported precision. Therefore the protocol semantics and TTFT propagation are
validated, but the result is a borderline characterization, not a robust
paper-level PASS and not evidence of a Decode-EP optimization.

A subsequent bandwidth sensitivity used the same small endpoint topology at
100 Gbps and 200 Gbps. TTFT P99 Whole -> Progressive changed from
2095.379 -> 1864.302 ms (11.03%) at 100 Gbps and 1954.557 -> 1835.835 ms
(6.07%) at 200 Gbps; TBT P99 was unchanged at each rate. The authoritative
CSV is `results/progressive_push/PROGRESSIVE_PUSH_BW_RESULTS.csv`. This
bounds the earlier 50-Gbps result: it is not a general high-speed-network
claim.
