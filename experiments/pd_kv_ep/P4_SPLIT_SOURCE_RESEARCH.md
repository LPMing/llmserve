# P4 Split-Source KV Assembly Research

Date: 2026-09-29

## Decision

**P4B is FINAL NO-GO as a serving-optimization motivation under the current
simulator semantics and tested real Mooncake windows.**

The semantic baseline is correct, and V1 split-source was implemented and
validated. However, V1 does not reduce TTFT on the two existing high-reuse
Mooncake windows. It makes the remote-hit requests slower, and in the
staggered window also increases EP CCT. The result is not promoted as a
positive paper motivation.

The important negative result is precise:

> Under the current supported semantics, suffix Prefill needs the cached prefix
> materialized at Prefill. A legal dual-destination architecture can reduce the
> P2D suffix leg, but the extra provider-to-Decode copy shares the same fabric
> and can delay the provider-to-Prefill dependency that gates suffix compute.

This is a real architecture-level limitation, not a failed byte-accounting
implementation.

## 1. Research question

The tested question was:

> When a request reuses a remote cached prefix and also uses Prefill/Decode
> disaggregation, is the conventional `Remote -> Prefill -> Decode` path an
> unnecessary serial/duplicate movement, and can a legal split-source KV
> assembly change the request critical path and reduce TTFT?

The two candidate paths were:

```text
Current B1:
Remote provider --cached prefix--> Prefill
Prefill --full prefix + suffix KV--> Decode
Decode admission after the Prefill/P2D handoff barrier
```

and the only semantically admissible V1 in this repository:

```text
V1 split-source:
Remote provider --cached prefix--> Prefill   (required for suffix compute)
Remote provider --cached prefix--> Decode    (early Decode materialization)
Prefill --suffix KV only--> Decode
Decode admission after both remote-to-Decode and suffix-P2D completion
```

A pure V2 path,

```text
Remote provider -> Decode prefix
Prefill -> Decode suffix
```

without `Remote -> Prefill`, was not implemented because it contradicts the
current simulator's explicit dependency: the first suffix Prefill compute node
waits for remote-prefix materialization.

## 2. Authoritative current baseline audit

The detailed source audit is in
[`P4_SPLIT_SOURCE_BASELINE_AUDIT.md`](P4_SPLIT_SOURCE_BASELINE_AUDIT.md).
The relevant code paths are:

| Concern | Current implementation |
|---|---|
| Request metadata | `serving/core/router.py` loads `remote_kv_tokens`, `remote_kv_bytes`, `remote_kv_mode`; `serving/core/request.py` stores them. |
| Remote-hit compute accounting | `serving/core/scheduler.py::_schedule_waiting()` treats `REMOTE_PREFIX_PD_BASELINE` remote tokens as already materialized. |
| Layerwise KV release | `serving/core/scheduler.py::_build_batch()` and `trace_generator.py` release per-layer P2D KV while later Prefill layers can continue; previous P2D completion is not a prerequisite for the next layer. |
| Remote-to-Prefill ordering | `serving/core/flowsim_worker.py::_prepare_remote_prefix_fetches()` registers remote fetches as waiters on the first Prefill compute nodes. |
| P2D graph completion | `AsyncGraphExecutor._complete_flow()` clears flow waiters and completes a graph node only after all of its required flows finish. |
| Serving handoff | `serving/__main__.py::complete_htsim_p2d_handoff()` and `router.py::transfer_prefill_request()` transfer the request to Decode only after the Prefill handoff is complete. |
| User-visible TTFT | `Scheduler.add_done()` uses the first Decode token timestamp for P/D TTFT, while preserving Prefill completion separately. |

Therefore the current B1 dependency is:

```text
R->P remote completion
      -> suffix Prefill compute
      -> layerwise P2D
      -> Decode admission
      -> first Decode token
```

The previous B1 implementation and the post-patch B1 regression produced the
same request CSV for the high-reuse window. All request fields other than the
instance representation were identical. This protects the old baseline from
being silently changed by V1 support.

## 3. Byte accounting

For each request:

```text
N_total  = input tokens
N_remote = remote-hit prefix tokens
N_suffix = N_total - N_remote
B_total  = model-derived KV bytes for N_total
B_remote = model-derived KV bytes for N_remote
B_suffix = model-derived KV bytes for N_suffix
```

For Qwen3-30B-A3B in this gate:

```text
48 layers * 2 K/V * 4 KV heads * 128 head_dim * 2 BF16 bytes
= 98,304 KV bytes per input token
```

Current B1:

```text
R->P = B_remote
P->D = B_total = B_remote + B_suffix
Decode logical KV = B_total
```

V1:

```text
R->P = B_remote
R->D = B_remote when the provider-to-Decode shard is non-local
P->D = B_suffix
Decode logical KV = B_remote + B_suffix = B_total
```

The V1 plan generator records the two remote roles separately and does not
use a synthetic byte override. A block that is already local at a destination
does not create a network flow, but remains part of the logical KV assembly.

For the 4-request simultaneous window:

| Quantity | Current B1 | V1 split-source |
|---|---:|---:|
| Logical full P2D KV | 2,436,857,856 B | not sent as one leg |
| Suffix-only logical P2D | not applicable | 624,918,528 B |
| Actual R->P remote network bytes | 1,207,959,552 B | 1,207,959,552 B |
| Actual R->D remote network bytes | 0 B | 1,811,939,328 B |
| Actual P2D flow bytes | approximately 2.41 GiB | approximately 0.62 GiB |
| Total KV network volume | approximately 3.64 GiB | approximately 3.64 GiB |

The key result is that V1 mostly **moves** bytes from P2D to a second remote
leg. It does not obtain a free reduction in total network work.

## 4. Implementation performed

The old modes remain available. The new mode is:

```text
SPLIT_SOURCE_KV_ASSEMBLY
```

Changes made:

1. `make_integrated_remote_kv_plan.py`
   - added V1 plan generation;
   - emits `REMOTE_KV_TO_PREFILL` and `REMOTE_KV_TO_DECODE` roles;
   - keeps block hashes and model-derived bytes unchanged;
   - preserves replica warm-up handling;
   - preserves `DIRECT_DECODE_CHARACTERIZE` as a separate old characterization mode.

2. `scheduler.py`
   - V1 remote-hit tokens reduce Prefill compute exactly as in corrected B1;
   - V1 P2D accounting adds only newly computed suffix tokens;
   - the remote prefix is not charged again to P2D.

3. `flowsim_worker.py`
   - R-to-P flows wait on first Prefill compute nodes;
   - R-to-D flows wait on a request's last P2D barrier node;
   - remote flow subtypes are explicit in telemetry;
   - the old B1 mode still uses the original R-to-P dependency.

4. `run_real_trace.py` and `serving/__main__.py`
   - added the V1 mode to the CLI choices.

The graph-level V1 barrier is intentionally conservative: the R-to-D flow is
attached to the request's last P2D barrier node. This guarantees that the
Prefill graph cannot complete and trigger Decode admission before both the
suffix P2D and all required remote-to-Decode prefix flows finish. It does not
claim a packet-level direct-assembly runtime implementation.

## 5. Correctness gates

### M0: 0% remote hit

Result: **PASS**.

- no remote fetch role is emitted;
- V1 plan has zero remote network bytes;
- it degenerates to ordinary P2D.

### M1: partial hit

Result: **PASS**.

- repeated blocks create both R-to-P and R-to-D legs;
- suffix tokens are the only P2D tokens;
- role-level bytes are disjoint.

### M2: near-full/high hit

Result: **PASS** for plan/accounting semantics.

- cached blocks are represented by remote legs;
- the suffix remains nonzero in the serving model;
- Decode logical receipt remains `B_remote + B_suffix`.

These are correctness tests, not performance claims.

## 6. Real Mooncake experiments

Both windows were already used for the corrected B1 validation. V1 reused the
same request rows, arrivals, input lengths, output lengths, block hashes,
provider mapping, topology, model, EP realization, bandwidth, and LAYERWISE
mode.

Configuration:

```text
Model: Qwen/Qwen3-30B-A3B-Instruct-2507
Topology: small two-Prefill/two-Decode EP4 gate
Backend: FlowSim
EP: A2A_P2P
P2D: LAYERWISE
P2D receiver: ACTUAL
Bandwidth profile: existing experiment profile
Policy: FAIR
Requests: 4 per window
Output cap: unchanged from the existing window
```

This is deliberately a semantic/integrated gate, not a claim about the final
S16/EP64 workload.

### 6.1 Simultaneous high-reuse window

Per-request TTFT for remote-hit requests:

| Request | B1 TTFT | V1 TTFT | Change |
|---:|---:|---:|---:|
| 1 | 123.012 ms | 198.160 ms | +61.1% |
| 2 | 238.698 ms | 238.698 ms | 0.0% |
| 3 | 123.012 ms | 198.160 ms | +61.1% |

Request 0 is the first local producer and is not a remote-hit request. It is
unchanged at 238.698 ms. Request 2 has a logical remote hit but its provider is
local to the Prefill destination in this placement; V1 still adds a remote to
Decode leg, but the batched P2D barrier remains dominated by the other group.

Critical-path telemetry for requests 1 and 3:

| Component | B1 | V1 |
|---|---:|---:|
| Last R->P completion | 59.658 ms | 134.805 ms |
| Last R->D completion | not present | 106.624 ms |
| Last P2D completion | 116.400 ms | 190.534 ms |
| Decode admission | 116.974 ms | 192.121 ms |
| First Decode token | 123.012 ms | 198.160 ms |

Interpretation:

- V1's R-to-D copy finishes before the R-to-P copy in this case;
- nevertheless, R-to-D shares the provider/fabric with R-to-P and changes its
  completion from 59.7 ms to 134.8 ms;
- suffix P2D starts later because suffix compute waits for R-to-P;
- the final suffix-P2D barrier is also later;
- the direct-to-Decode copy does not expose a shorter request critical path.

EP CCT was unchanged in this window:

```text
B1: mean 3.626 us, P99 4.968 us
V1: mean 3.626 us, P99 4.968 us
```

### 6.2 Staggered high-reuse window

Remote-hit request TTFT:

| Request | B1 TTFT | V1 TTFT | Change |
|---:|---:|---:|---:|
| 1 | 93.546 ms | 123.478 ms | +32.0% |
| 2 | 53.479 ms | 65.732 ms | +22.9% |
| 3 | 99.939 ms | 126.187 ms | +26.3% |

Request 0 has no remote hit and is unchanged at 130.847 ms.

Representative network completion times:

| Request | Architecture | Last R->P | Last R->D | Last P2D |
|---:|---|---:|---:|---:|
| 1 | B1 | 29.802 ms | — | 87.345 ms |
| 1 | V1 | 59.734 ms | 43.865 ms | 116.758 ms |
| 2 | B1 | — | — | 3048.399 ms |
| 2 | V1 | — | 3060.478 ms | 3046.836 ms |
| 3 | B1 | 3046.373 ms | — | 3093.946 ms |
| 3 | V1 | 3072.621 ms | 3060.478 ms | 3119.688 ms |

The staggered result is important because it is not a single simultaneous
microburst. V1 still increases remote-hit TTFT by roughly 23–32% across three
requests. The final request in the delayed phase also shows EP impact:

```text
EP CCT mean: 3.609 us -> 4.510 us (+25.0%)
EP CCT P99: 4.968 us -> 8.072 us (+62.5%)
```

This is a side effect of adding another large remote leg to the same FlowSim
fabric, not a serving benefit.

## 7. Why V1 failed to improve TTFT

The current simulator exposes four concrete reasons.

### 7.1 Suffix compute is still gated by R->P

V1 cannot start suffix compute until the remote prefix reaches Prefill. This
is required by the current model semantics. Therefore the R-to-P leg remains
on the critical path even though Decode receives a second copy.

### 7.2 R->D is an additional active transfer, not a free pointer

The V1 R-to-D copy is modelled as real FlowSim traffic. It shares provider
uplinks, leaf/spine paths, and destination links with the R-to-P and EP flows.
It is not an in-memory metadata operation and not an independent ideal
network.

### 7.3 P2D bytes fall, but the critical start time moves later

Reducing P2D from full KV to suffix KV helps only after suffix compute starts.
In both windows, V1 delays that start enough that the smaller suffix transfer
finishes later than the B1 full P2D transfer.

### 7.4 Decode-side assembly does not automatically protect EP

Direct R-to-D traffic enters the Decode-side network path. In the staggered
window it increases EP CCT tails. Thus a design that improves the Prefill/P2D
leg cannot be evaluated using TTFT alone; TBT/EP CCT can regress.

## 8. Why this is not a positive CCF-A motivation yet

The experiment does establish a useful systems fact:

```text
remote prefix reuse + current P/D semantics
=> cached KV may incur an R->P dependency and a later P->D handoff
```

But the tested split-source alternative does not offer a stable serving
headroom. It is worse on both real windows for remote-hit requests. Therefore
we cannot claim:

- a >=20% TTFT improvement;
- a deployable split-source scheduler;
- a general remote-KV architecture advantage;
- a provider-placement or replica-selection opportunity;
- a stable remote-KV/EP co-optimization problem.

The negative result is also not a reason to add more provider fan-in, lower
bandwidth, synchronize arrivals, or enlarge KV bytes. Those would test a
manufactured stress case rather than the architecture question.

## 9. Required artifacts

- [P4_SPLIT_SOURCE_BASELINE_AUDIT.md](P4_SPLIT_SOURCE_BASELINE_AUDIT.md)
- [P4_SPLIT_SOURCE_REQUESTS.csv](P4_SPLIT_SOURCE_REQUESTS.csv)
- [P4_SPLIT_SOURCE_NETWORK.csv](P4_SPLIT_SOURCE_NETWORK.csv)
- [P4B_FINAL_NO_GO.md](P4B_FINAL_NO_GO.md)

The CSVs are compact postprocessed artifacts. They retain request/flow
provenance without promoting FlowSim residual fluid backlog to packet queue,
ECN, PFC, or drop telemetry.

## 10. Final P4 decision

`P4 semantic baseline = PASS` remains true.

`ordinary provider placement = NO-GO` remains true.

`split-source KV assembly = FINAL NO-GO` under the current supported Prefill
semantics and tested real Mooncake windows.

P4 should now be closed rather than expanded through artificial hot-provider
stress. A future paper would need a different, runtime-supported primitive in
which suffix Prefill can consume remote-prefix state without keeping a full
R-to-P critical dependency. That primitive is not represented by the current
simulator and is not claimed here.
