# P4 Split-Source Baseline Audit

Date: 2026-09-29

Status: **Gate 0 complete; V1 is the only semantically admissible next step in
the current simulator.** No split-source implementation or new result is
claimed by this document.

## 1. Scope

This audit reconstructs the currently implemented
`REMOTE_PREFIX_PD_BASELINE` path from the serving frontend, scheduler, and
FlowSim worker. The purpose is to decide whether a direct
`Remote Provider -> Decode` path can replace the current
`Remote Provider -> Prefill -> Decode` path without changing model semantics.

The audit distinguishes:

- **control-plane events:** scheduler admission, graph creation, request
  handoff, and Decode admission;
- **data-plane events:** remote KV fetches, layerwise P2D KV flows, and EP
  collectives;
- **logical KV accounting:** tokens/bytes required by a request;
- **network KV accounting:** bytes actually sent on each network leg.

## 2. Current request DAG (B1 baseline)

The current corrected mode is:

```text
request arrival
    |
    v
remote prefix plan is associated with the request
    |
    v
FlowSim submits remote-prefix fetches R -> P
    |
    | remote fetch completion is a dependency of the first Prefill compute node
    v
Prefill computes only the uncached suffix
    |
    | layerwise model trace releases P2D KV nodes
    v
Prefill -> Decode sends the complete prefix + suffix KV
    |
    v
all required P2D graph dependencies complete
    |
    v
Decode admission
    |
    v
Decode compute / EP / first token
```

This is not an assumption based on the previous report; it follows from the
current code paths below.

### 2.1 Request input and remote-prefix fields

`serving/core/router.py` loads `remote_kv_tokens`, `remote_kv_bytes`, and
`remote_kv_mode` from the workload and passes them to `Request`.

`serving/core/request.py:20-88` stores the remote-hit token/byte counts and
the `REMOTE_PREFIX_PD_BASELINE` mode. The request object does not store a
separate prefix state object or an independent Decode-side remote-KV waiter.

### 2.2 Scheduler compute accounting

`serving/core/scheduler.py:_schedule_waiting` treats
`REMOTE_PREFIX_PD_BASELINE` remote-hit tokens as already materialized in the
Prefill KV layout. It raises the initial `num_computed` count by
`remote_kv_tokens`, so the scheduled compute covers only the suffix.

`serving/core/scheduler.py:_build_batch` preserves the full logical handoff:

```text
P2D tokens for the first Prefill chunk
= suffix tokens in that chunk
  + complete remote prefix tokens exactly once
```

Subsequent layerwise chunks contribute their newly generated suffix tokens.
Therefore the baseline does not omit the cached prefix from the Decode KV
state even though its Prefill compute is skipped.

### 2.3 Layerwise release semantics

The trace generator emits each transformer layer in order. In LAYERWISE mode,
the layer's `qkv_proj` row carries that layer's P2D communication. A later
Prefill layer is not held until the previous P2D flow has completed; it can
release its own KV while earlier P2D flows are still in flight. The current
default has no sender staging/NIC backpressure in the serving model.

This means the baseline has:

```text
QKV_i / suffix compute_i -> P2D_i
QKV_{i+1} / suffix compute_{i+1} -> P2D_{i+1}
```

with network overlap across layers, while Decode waits for the request-level
handoff barrier.

### 2.4 Remote fetch ordering in FlowSim

`serving/core/flowsim_worker.py:_prepare_remote_prefix_fetches` scans the
submitted Prefill graph, creates `REMOTE_KV_FETCH` flows, and registers them as
waiters on the first Prefill compute node. The remote flows are submitted
before that compute node is allowed to run.

The relevant dependency is therefore:

```text
R -> P remote fetch completion
       |
       v
first suffix Prefill compute
       |
       v
layerwise P2D flows
```

This is the strongest available in-repository evidence that the current
simulator assumes the suffix computation needs the remote prefix materialized
at Prefill. A pure V2 implementation that sends the prefix only to Decode
would remove this dependency and would not be equivalent to the current
model semantics.

### 2.5 Decode admission

For FlowSim, flow completion clears the associated graph-node waiter. The
Prefill graph completes only after its required compute and P2D dependencies
complete. `serving/__main__.py:1363-1385` then calls
`router.transfer_prefill_request`, and `router.py:389-404` calls
`decode_scheduler.add_decode`.

Thus the current authoritative Decode-ready time is the completion of the
Prefill/P2D handoff barrier, not the completion of an independently tracked
remote-prefix-to-Decode flow.

## 3. Byte accounting

For a request with:

```text
N_total  = total prompt tokens
N_remote = remote-hit prefix tokens
N_suffix = N_total - N_remote
```

and model-derived full-cache bytes:

```text
B_total  = KV bytes for N_total
B_remote = KV bytes for N_remote
B_suffix = KV bytes for N_suffix
```

the current B1 baseline is:

```text
R -> P remote leg:  B_RP = B_remote
P -> D P2D leg:     B_PD = B_total = B_remote + B_suffix
total KV movement:  B_remote + B_total
```

The two occurrences of `B_remote` are two independent network legs. They are
not a claim that one physical link transmitted the same bytes twice; they are
the logical R-to-P and P-to-D transfers.

The current plan generator computes block-level remote-hit bytes from the
Qwen3-30B-A3B model parameters in
`experiments/pd_kv_ep/scripts/make_integrated_remote_kv_plan.py`. It does not
use an arbitrary `REMOTE_KV_SIZE_MB` override.

## 4. Current critical path decomposition

The current implementation exposes the following timestamps:

| Timestamp | Source | Meaning |
|---|---|---|
| `arrival` | `Request.arrival` | request arrival in the serving clock |
| remote fetch start/finish | FlowSim KV telemetry | R-to-P remote block transfer |
| Prefill completion | `Request.prefill_completion_time_ns` | Prefill scheduler reaches prompt length |
| P2D ready | `Request.p2d_kv_ready_time_ns` | complete current P/D handoff barrier |
| Decode admission | `Request.decode_admit_time_ns` | Decode scheduler accepts request |
| first token | `Request.decode_first_token_time_ns` | first Decode-side generated token |
| TTFT | `Request.decode_ttft` / `Request.ttft` | arrival to first Decode token for P/D |

The current code does not yet have separate
`remote_to_decode_finish`, `suffix_p2d_finish`, or a
`max(remote_to_decode, suffix_p2d)` admission barrier. Adding those fields is
necessary for split-source validation.

## 5. Gate A decision

### A1: Does suffix Prefill currently require the remote prefix at Prefill?

**Yes, under the current simulator semantics.** The first Prefill compute node
is explicitly blocked by the R-to-P remote fetch. The simulator therefore
models the suffix as being computed after the remote prefix is materialized at
the Prefill worker.

This conclusion is about the current supported model, not a universal claim
about every production runtime. A production implementation could expose a
different primitive, but that primitive is not currently represented here.

### A2: Can V2 (`R -> D` prefix plus `P -> D` suffix) be implemented directly?

**Not without changing the modeled Prefill dependency.** A V2 run that sends
the prefix only to Decode while allowing suffix compute to proceed would be an
unsupported semantic shortcut in this repository.

### A3: Selected variant

The next implementation must therefore be **V1 dual-destination remote
prefix**:

```text
R -> P prefix       (required before suffix compute)
R -> D prefix       (early Decode-side materialization)
P -> D suffix       (only newly computed suffix KV)
```

V1 keeps the existing compute dependency intact. It changes only the KV
movement architecture and makes Decode admission wait for both destinations.

Its network accounting is:

```text
B_RP = B_remote
B_RD = B_remote
B_PD = B_suffix
Decode receives = B_remote + B_suffix = B_total
total network KV movement = 2*B_remote + B_suffix
```

Compared with B1, V1 sends the same total number of logical KV bytes but
changes the P-to-D leg from full KV to suffix-only KV and adds an explicit
R-to-D leg. The possible benefit can only come from a changed critical path,
parallelism, or path/cut utilization—not from silently deleting required KV.

## 6. Consequences for implementation

The minimal implementation must add explicit roles:

- `REMOTE_KV_TO_PREFILL`;
- `REMOTE_KV_TO_DECODE`;
- `P2D_SUFFIX_KV`.

It must also add per-request completion state for:

```text
remote_to_prefill_finish
remote_to_decode_finish
suffix_p2d_finish
decode_admit = max(all required components)
```

For V1, `REMOTE_KV_TO_PREFILL` remains a prerequisite of the first suffix
compute node. `REMOTE_KV_TO_DECODE` is an independent Decode-side waiter.
`P2D_SUFFIX_KV` is the only P2D KV flow for the suffix. The old full-P2D flow
must not remain active in V1.

The first correctness invariant is:

```text
Decode_received_KV_bytes == B_remote + B_suffix == B_total
```

The second is:

```text
decode_admit >= remote_to_decode_finish
decode_admit >= suffix_p2d_finish
```

and, because of the current compute semantics:

```text
suffix_compute_start >= remote_to_prefill_finish
```

## 7. Current result interpretation

The earlier P4 results remain valid only for the corrected B1 question:

> Does remote prefix reuse with R-to-P materialization, suffix-only Prefill
> compute, and full P-to-D handoff produce a serving-visible result?

They do not answer whether V1 split-source can improve the handoff barrier.
The new experiment must therefore compare B1 and V1 with identical requests,
hashes, compute, provider, topology, bandwidth, and EP workload.

No V1 result is claimed until the byte and lifecycle assertions above pass.

