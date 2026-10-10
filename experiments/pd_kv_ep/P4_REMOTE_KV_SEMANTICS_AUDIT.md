# P4 Remote-KV Semantics Audit

Date: 2026-09-28

Status: **PART I complete; code changes intentionally not made yet.**

This audit is a prerequisite for the P4 integrated validation requested in the
research log. It separates three different mechanisms which were previously
represented by one `remote_kv_tokens` field:

1. classic P/D KV transfer (`P -> D`);
2. exact remote prefix reuse at Prefill (`R -> P`, then `P -> D`);
3. a characterization-only direct remote fetch to Decode (`R -> D`).

They have different compute accounting, byte accounting, and dependency DAGs.
The current simulator extension implements a useful network barrier
characterization, but it does not yet implement the second mechanism
faithfully.

## 1. Scope and evidence levels

The conclusions below are divided into:

- **repository-observed:** directly read from this checkout's Python code;
- **public-system-observed:** supported by current upstream vLLM/Mooncake
  documentation or source;
- **inference:** a comparison between the two, explicitly labelled as such.

No old P4 network result is promoted to a serving-level result by this audit.

## 2. Current simulator data path

### 2.1 Request input and routing

`serving/core/router.py` loads `remote_kv_tokens` and `remote_kv_bytes` from a
flat or agentic JSONL request and passes them into `Request`.

`serving/core/request.py` stores:

```text
remote_kv_tokens
remote_kv_tokens_remaining
remote_kv_bytes
input_block_hashes
```

The request object does not contain a remote-prefix state machine, a remote
lookup state, a fetched-prefix block table, or a suffix-only prompt length.
`remote_kv_tokens_remaining` is a scalar accounting field.

### 2.2 Scheduler lookup and compute accounting

The normal prefix-cache lookup is in `Scheduler._schedule_waiting()`
(`serving/core/scheduler.py:210-217`). It can reduce `num_computed` only for
blocks found by the simulator's local/lower-tier `KVCacheManager`.

The remote-KV extension is not part of that lookup path. Instead, in
`Scheduler._build_batch()` (`serving/core/scheduler.py:331-346`), it does:

```text
pd_tokens = num_new
remote_tokens = min(remote_kv_tokens_remaining, num_new)
remote_kv_tokens_remaining -= remote_tokens
pd_tokens -= remote_tokens
```

Crucially, `num_new` itself is unchanged and
`req.num_computed_tokens = computed_before + num_new` remains unchanged
(`serving/core/scheduler.py:348-352`). Therefore:

```text
current simulator model compute tokens = full scheduled prompt tokens
current simulator native P2D tokens     = prompt tokens - remote_kv_tokens
current simulator remote fetch tokens   = plan-provided remote tokens
```

This is an intentional characterization shortcut in the existing extension,
not correct remote-prefix compute accounting.

### 2.3 Native P2D byte generation

`_pd_kv_send_bytes()` in `serving/core/trace_generator.py:1073-1085`
converts `batch.pd_kv_send_tokens` into per-layer, per-TP-rank K/V bytes:

```text
2 * KV_heads * head_dim * tokens * KV_dtype_bytes / TP
```

For `LAYERWISE`, the `qkv_proj` row in each transformer block uses these bytes
as a P2D point-to-point transfer (`trace_generator.py:1420-1435`). The q/query
activation is not included.

For `POST_PREFILL`, the separate post-prefill marker uses the same incremental
token accounting and multiplies by the number of layers
(`trace_generator.py:1088-1098`, `1490-1510`).

### 2.4 Layerwise release order

The normal trace generator walks the transformer blocks in increasing layer
order. In `LAYERWISE`, each block's `qkv_proj` row carries its P2D marker, so
the graph has the following local dependency:

```text
compute layer i (including qkv_i)
    -> P2D_KV_i
    -> following compute rows in the graph
```

The next layer is not gated by completion of `P2D_KV_i`; it is gated only by
the graph's model-compute dependencies. Thus, after layer `i` releases its
KV, layer `i+1` can compute and release its KV while the earlier transfer is
still active. This matches the previously identified non-blocking layerwise
assumption.

The current implementation does not model a finite sender staging buffer in
the default path. The optional FlowSim finite-buffer mode is a sensitivity
model, not the default serving semantics.

### 2.5 Remote fetch creation and waiter attachment

`AsyncGraphExecutor._new_p2d_flow()` creates the native P2D `FlowSpec` and
immediately calls `_attach_remote_kv_fetches()`
(`serving/core/flowsim_worker.py:938-967`).

`_attach_remote_kv_fetches()` then creates one `REMOTE_KV_FETCH` FlowSpec per
plan entry and registers each flow as a waiter on the **same graph node** as
the native P2D flow (`flowsim_worker.py:969-1003`).

The resulting dependency for a graph node is:

```text
P2D_KV node ready
       |
       +--> native P2D flow
       |
       +--> remote fetch flow(s)
       |
       +--> node completes at max(all attached flow finishes)
```

The remote fetch start timestamp is the `ready` timestamp of that already
activated P2D node. It is not a remote lookup that starts at request arrival,
and it is not a remote fetch that makes suffix Prefill compute possible.

There is an additional implementation boundary: remote fetches are attached
when a native P2D node is activated. A plan with a fully remote prefix and no
native P2D node would not naturally enter this attachment path. That case is
not covered by the current integrated extension and must be handled explicitly
if a true `R -> P` or `R -> D` mode is added.

### 2.6 Graph and Decode admission

For FlowSim, the native P2D sender and remote fetch waiters are kept in the
same asynchronous graph. `_complete_flow()` removes a flow from the node's
pending waiter set and calls `_finish_node()` only when the set becomes empty
(`flowsim_worker.py:1161-1186`).

The serving frontend then marks the Prefill handoff complete only after the
Prefill graph has completed and its P2D handoff state is satisfied
(`serving/__main__.py:1357-1375`). `router.transfer_prefill_request()` calls
`decode_scheduler.add_decode()` (`serving/core/router.py:381-396`).

The Decode-side request therefore waits on the current graph's effective
handoff completion. In the observed current implementation, the path is:

```text
full Prefill compute
 -> layerwise native P2D graph nodes
 -> remote fetches attached to a P2D node
 -> completion of the Prefill graph / P2D handoff
 -> Decode admission
 -> Decode compute and EP
 -> first Decode token
```

The exact completion is a max over the P2D graph's required flow/node
dependencies. It is not a separately modelled `max(remote-prefix-ready,
suffix-Prefill-ready, full-P2D-ready)` barrier.

### 2.7 TTFT and first-token timestamps

`Scheduler.add_done()` records Prefill completion and `prefill_ttft` when the
Prefill request reaches its prompt length (`scheduler.py:499-527`). For a P/D
request, the request is then transferred to Decode. On Decode, the first
generated token sets `decode_first_token_time_ns`, `decode_ttft`, and replaces
the user-visible `ttft` with the Decode first-token TTFT
(`scheduler.py:545-563`).

Thus the integrated CSV can contain a legitimate Decode-side TTFT. However,
that metric is only as semantically valid as the preceding admission DAG. It
cannot turn the current full-compute plus sibling-waiter implementation into
real remote-prefix reuse by itself.

## 3. DAG-A: current simulator

The current extension is best described as the following characterization DAG.
It is **not** the canonical remote-prefix DAG:

```text
request arrival
      |
      v
Prefill scheduler computes N_total prompt tokens
      |
      +--> layer 0 compute -> P2D_KV_0 (N_total accounting minus remote scalar)
      |                              |
      |                              +--> remote fetches are submitted here
      |
      +--> layer 1 compute -> P2D_KV_1
      |
      +--> ...
      |
      +--> last layer compute -> P2D_KV_last
                                     |
       remote fetches ----------------+
       native P2D flows --------------+
                                     v
                         graph/P2D completion barrier
                                     |
                                     v
                              Decode admission
                                     |
                              Decode EP rounds
                                     |
                              first Decode token
```

Important properties of DAG-A:

1. remote-hit tokens are removed from native P2D byte accounting;
2. remote-hit tokens are **not** removed from Prefill compute;
3. remote fetches begin only when the attached native P2D node is ready;
4. remote fetch and native P2D are sibling waiters at that node;
5. the Decode admission path still includes the whole Prefill compute and all
   required native P2D graph completion;
6. a remote fetch can finish early and have zero exposure to TTFT if a later
   native P2D shard remains the last completion.

Therefore the latest integrated result of near-zero TTFT sensitivity is
consistent with the current DAG and is not evidence that remote prefix reuse is
intrinsically free.

## 4. Public real-system semantics

### 4.1 Classic disaggregated P/D

Current vLLM documentation describes classic disaggregated Prefill/Decode as
one Prefill instance producing KV and one Decode instance consuming it. The
Decode side retrieves KV from the Prefill side through a KV connector. The
NIXL guide states that standard disaggregated prefilling moves KV from P to D,
and the KV offloading guide describes the classic `remote_prefiller` consumer
as pulling blocks from the remote Prefill worker.

The public NIXL P/D sequence is therefore:

```text
request -> P full prefill compute -> P owns full KV
                              |
                              v
                         D pulls P KV
                              |
                              v
                         D admission/decode
```

This is `P -> D`, not a remote prefix-cache hit. A P2D implementation that
ships only a suffix must have an explicit guarantee that the Decode worker
already owns the omitted prefix KV.

### 4.2 Exact remote prefix reuse at Prefill

The current upstream vLLM scheduler/connector contract distinguishes external
computed tokens from locally computed tokens. The scheduler asks the connector
for additional matched tokens beyond the local prefix, allocates recipient-side
KV blocks, and the connector loads those blocks. The public vLLM design notes
that a cache hit avoids redundant prompt computation, and the current connector
interface returns external tokens that are then treated as already computed.

For an exact remote prefix hit, the real serving DAG is:

```text
request arrival
      |
      +--> exact prefix lookup / block ownership resolution
      |          |
      |          v
      |   remote provider fetches prefix KV to Prefill
      |          |
      |          v
      |   prefix blocks materialized in Prefill KV cache
      |
      +--> Prefill computes uncached suffix only
                   |
                   v
       Prefill owns complete prefix + suffix KV
                   |
                   v
          P -> D transfers required complete KV
                   |
                   v
              Decode admission
```

The remote fetch and suffix compute may overlap if the connector is asynchronous
and layer-aware, but the suffix cannot use a remote prefix block before that
block is materialized in the Prefill KV layout. The Decode barrier must wait for
the complete KV representation needed by Decode.

### 4.3 Bidirectional P/D multi-turn reuse

The current upstream NIXL documentation describes a related multi-turn path:
Decode retains prior-turn blocks; on the next turn Prefill pulls those blocks
from Decode, computes only new tokens, then sends the updated KV back to Decode.
That DAG is:

```text
D(previous-turn KV) -> P(prefix materialization)
                              |
                       P computes suffix
                              |
                       P -> D updated KV
                              |
                         D next turn
```

This is different from a generic provider directly sending a prefix to Decode.

### 4.4 Mooncake Store / P2P role distinction

Current Mooncake documentation distinguishes:

- `MooncakeConnector`: direct P/D KV transfer;
- `MooncakeStoreConnector`: shared KV pool and hash-based prefix reuse;
- `MultiConnector`: composition of direct P/D transfer and shared-store reuse.

The public vLLM P2P tier similarly distinguishes a remote Prefiller from a
generic remote KV source. A consumer can pull blocks from a remote source, but
the orchestration layer selects the role and peer. This means a production
deployment can realize different DAGs depending on whether the request is:

1. classic P/D with a known Prefill owner;
2. external prefix load into Prefill followed by suffix compute;
3. direct remote load into Decode because the Decode-side connector owns the
   exact external blocks;
4. a bidirectional multi-turn exchange.

No single `remote_kv_tokens` scalar is sufficient to identify which of these
is active.

## 5. DAG-B: real public baseline used for this study

For the current Mooncake-prefix + PD research question, the semantically
conservative baseline is **DAG-B1**, not the current DAG-A:

```text
request + block hashes
      |
      +--> remote ownership lookup
      |          |
      |          v
      |   remote provider -> Prefill: cached prefix KV
      |          |
      |          v
      |   Prefill materializes cached prefix blocks
      |
      +--> Prefill computes only uncached suffix
                   |
                   v
        complete KV = cached prefix + computed suffix
                   |
                   v
              Prefill -> Decode P2D
                   |
                   v
              Decode admission
                   |
                   v
              Decode EP / first token
```

If the deployment instead deliberately implements direct source-to-Decode
fetch, the correct alternative is **DAG-B2**:

```text
request + block hashes
      |
      +--> provider -> Decode: exact cached prefix KV
      |
      +--> Prefill computes uncached suffix
                   |
                   +--> Prefill -> Decode: suffix KV
                                   |
                 Decode waits for both complete inputs
                                   v
                         Decode admission / EP
```

DAG-B2 is a split-source architecture characterization, not a default claim
about Mooncake/vLLM. It requires a legal Decode-side KV layout/assembly API and
must account for the receiver NIC path carrying remote prefix, suffix P2D, and
EP simultaneously.

## 6. Answers to the required questions

### Q1 — Does `remote_kv_tokens` skip full Prefill compute?

**Current simulator:** No. It only reduces the native P2D token byte count.
`num_new`, profiled model compute, `num_computed_tokens`, and layer release
timing still reflect the full scheduled prompt.

**Real exact remote-prefix semantics:** Yes, for the matched prefix (subject to
block alignment and the normal requirement to compute a final token when logits
are needed). The uncached suffix remains local Prefill compute. This is the
semantics documented by vLLM's automatic prefix caching and external-token
connector path.

### Q2 — Are remote-hit tokens removed from native P2D bytes?

**Current simulator:** Yes. `pd_kv_send_tokens` subtracts the scalar remote-hit
count before `_pd_kv_send_bytes()`.

**Real baseline:** Not universally. For DAG-B1, the P2D handoff to Decode must
contain the complete required KV unless Decode already owns the cached prefix.
Therefore removing remote prefix bytes from P2D while not modelling a prior
remote-to-Prefill materialization is incomplete. For DAG-B2, removing prefix
bytes from P2D is correct only if a real provider-to-Decode prefix flow is
present and Decode assembles it with the suffix.

### Q3 — Are remote fetch and native P2D parallel siblings or serial?

**Current simulator:** They are sibling waiters on an activated native P2D graph
node. The remote fetch does not enable suffix compute and does not start at
request lookup time.

**Real DAG-B1:** The remote prefix fetch is upstream of suffix compute (or at
least upstream of the attention layers that consume the fetched prefix), and
the completed prefix plus suffix then feed P2D. It is not generally a sibling
of a complete P2D handoff.

**Real DAG-B2:** Provider-to-Decode prefix and Prefill-to-Decode suffix may be
parallel network inputs, but they are separate flows with an explicit Decode
assembly barrier. That must be implemented as a separate architecture mode.

### Q4 — Does Decode wait remote, native P2D, or both?

**Current simulator:** It waits for the Prefill graph/handoff, whose effective
dependencies include native P2D completion and any remote fetch waiters attached
to the graph. In practice the last native P2D shard can hide the remote fetch.

**Real DAG-B1:** Decode waits for the complete P2D handoff after remote prefix
materialization and suffix compute. The remote fetch influences Decode only if
it delays the Prefill/suffix/complete-handoff critical path.

**Real DAG-B2:** Decode waits for both provider-to-Decode prefix completion and
Prefill-to-Decode suffix completion, then assembles/admits the request.

## 7. Multi-source and block-level semantics

The Mooncake/vLLM public interfaces are block-oriented for cache lookup and
transfer. A request can therefore have a set of blocks whose ownership is not
uniform; the orchestrator/connector may resolve blocks through a remote source
and the Prefill/Decode worker then materializes them into its local KV layout.
However, the current checkout's plan format is a request-level list of fetches
with `src`, `dst`, `bytes`, and optional `block_index`; it has no explicit
per-block hit/miss continuation, lookup result, holder set, or dependency on
suffix compute.

The current plan generator also assigns a provider using a replay policy and
records model-derived bytes. That is adequate for a controlled network-flow
characterization, but it is not proof that the production cache had the same
holder state.

## 8. Semantic classification

### 8.1 Current code

`P4_REMOTE_KV_SEMANTICS = SEMANTICS_PARTIALLY_INVALID` for a paper claim about
real remote-prefix reuse.

It is still valid for the narrower characterization claim:

> Given a pre-existing remote-KV flow plan, measure whether those flows can
> share the FlowSim fabric and participate in a Decode-side handoff waiter.

### 8.2 Results that remain valid

The following claims remain valid within their stated model:

- remote flow bytes are model-derived from Mooncake block token counts and the
  Qwen3 KV geometry;
- Mooncake hashes were kept separate from token IDs;
- remote fetch flows are real FlowSim flows rather than zero-cost metadata;
- optional replica warm-up is charged as same-fabric FlowSim traffic;
- remote and EP flows can overlap on directed FlowSim links;
- the current integrated run can produce a legitimate Decode-side TTFT/TBT CSV
  for its implemented DAG-A.

### 8.3 Results that cannot yet be claimed

Until DAG-B semantics are implemented and validated, do not claim:

- remote prefix reuse skipped Prefill compute;
- current `remote_kv_tokens` represents real external computed tokens;
- the current native-P2D-minus-remote byte count is complete Decode KV
  accounting;
- current provider placement results measure production Mooncake Store source
  selection;
- near-zero TTFT impact proves remote-prefix traffic is not on a real serving
  critical path;
- direct provider-to-Decode split-source assembly is already supported.

## 9. Required correction before experiments

The next code phase must introduce an explicit mode rather than silently
changing the old behavior:

```text
REMOTE_KV_MODE=OFF                 # old P/D baseline
REMOTE_PREFIX_PD_BASELINE          # DAG-B1: R->P, suffix compute, P->D full KV
REMOTE_DIRECT_DECODE_CHARACTERIZE  # DAG-B2; only with explicit Decode assembly
```

At minimum, the B1 mode needs separate accounting for:

```text
remote_prefix_tokens / bytes
uncached_suffix_tokens
prefill_compute_tokens = suffix tokens (+ required final-token rule)
native_p2d_bytes = complete KV required by Decode
remote_to_prefill_bytes
decode_admission = complete KV ready
```

It also needs lifecycle timestamps for lookup, remote fetch, cached-prefix ready,
suffix compute, Prefill completion, native P2D first/last, Decode admission, and
Decode first token. A request-level assertion must reject any run where Decode
admission precedes the required KV materialization.

No code has been changed as part of this audit. The next action is to implement
the smallest explicit `REMOTE_PREFIX_PD_BASELINE` only after this document is
reviewed against the current experiment ledger, then rerun the two existing
Mooncake windows before adding new workload or replication logic.

## 10. Public references

- [vLLM disaggregated prefilling](https://github.com/vllm-project/vllm/blob/main/docs/features/disagg_prefill.md)
- [vLLM NIXL connector usage and bidirectional transfer](https://github.com/vllm-project/vllm/blob/main/docs/features/nixl_connector_usage.md)
- [vLLM KV offloading/P2P including P/D](https://github.com/vllm-project/vllm/blob/main/docs/features/kv_offloading_usage.md)
- [vLLM prefix caching design](https://github.com/vllm-project/vllm/blob/main/docs/design/prefix_caching.md)
- [vLLM external/semantic KV connector discussion](https://github.com/vllm-project/vllm/issues/44223)
- [Mooncake vLLM integration](https://github.com/kvcache-ai/Mooncake)
- [Mooncake Store connector usage](https://github.com/vllm-project/vllm/blob/main/docs/features/mooncake_store_connector_usage.md)



## 12. Corrected B1 integrated validation (2026-09-28)

The explicit `REMOTE_PREFIX_PD_BASELINE` mode was validated on the two existing four-request Mooncake windows using the original small EP4 topology. The old historical outputs were not overwritten.

The corrected lifecycle is observable in the retained FlowSim ledger: the last remote prefix fetch completes before the first affected layerwise P2D release. The scheduler unit check also confirms that a 6,144-token remote prefix plus a 24-token suffix schedules 24 model-computed tokens but charges 6,168 tokens to complete P2D.

The integrated result is therefore semantically valid for a minimal remote-prefix baseline. It is not evidence that provider selection is a strong serving optimization: the existing-holder policy equals first producer when no legal replica exists, while the balanced-replica oracle spends same-fabric warm-up bandwidth and did not produce stable serving headroom. See `P4_GO_NO_GO.md`, `P4_REQUEST_CRITICAL_PATH.csv`, and `P4_NETWORK_ACCOUNTING.csv`.
