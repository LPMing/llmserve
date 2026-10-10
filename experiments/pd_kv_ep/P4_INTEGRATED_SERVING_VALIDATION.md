# P4 Integrated Serving Validation: Remote-KV Barrier and Replica Warm-up

> **Superseded for semantic claims by `P4_REMOTE_KV_SEMANTICS_AUDIT.md` and `P4_GO_NO_GO.md`.** The original tables below describe the legacy sibling-waiter implementation. The corrected `REMOTE_PREFIX_PD_BASELINE` rerun is the authoritative integrated result.

Date: 2026-09-28

## Decision

This document supersedes the earlier statement that the P4 integrated gate had not been
run. The minimal integrated extension is now implemented and has completed successfully.
The result is deliberately split into three claims:

| Claim | Result |
|---|---|
| Remote-KV fetches can enter the integrated Decode-admission barrier | **PASS** |
| Replica warm-up/copy traffic is charged to the same FlowSim fabric | **PASS** |
| The current real Mooncake windows produce a material remote-KV contribution to TTFT/TBT | **FAIL / not demonstrated** |
| The P4 provider-placement gap is already a PD+MoE serving-level paper result | **FAIL for the current gate** |

The failure is a valid negative result, not a missing value. In both tested integrated
windows, native P2D KV completion remained the last required handoff event. Remote fetches
were earlier, so changing their provider did not change `p2d_kv_ready_time_ns` or TTFT.

The old packet-level P4 result remains useful as a **remote-provider barrier** result, but it
must not be promoted to an integrated TTFT/TBT claim.

## What was changed

### Request and scheduler semantics

`serving/core/request.py` stores `remote_kv_tokens` and `remote_kv_bytes` as separate
characterization metadata. `serving/core/router.py` preserves the fields when loading flat
or agentic workloads.

In `serving/core/scheduler.py`, only prefill chunks consume
`remote_kv_tokens_remaining`. Those tokens are removed from the native P2D byte count, while
model compute remains unchanged. Therefore a remote hit is not double-counted as both a
remote fetch and a Prefill-to-Decode transfer.

The model-derived Qwen3-30B-A3B calculation used by the plan generator is:

```
KV bytes = matched_tokens * 48 layers * 2(K,V) * 4 KV heads
           * 128 head_dim * 2 bytes(BF16)
```

Mooncake `input_block_hashes` are treated only as block identities. They are never treated as
token IDs.

### FlowSim barrier integration

`serving/core/flowsim_worker.py` creates one `REMOTE_KV_FETCH` FlowSpec per selected
block/destination shard. The flow is registered as a waiter on the same graph node that
carries the request's native P2D handoff. Thus Decode admission waits for both native P2D
and remote fetch completion.

The worker also accepts a top-level `warmup` list. Each entry becomes a real
`REMOTE_KV_REPLICATION` flow submitted at network time zero. Remote fetches are held until
all warm-up flows finish. Warm-up traffic uses the same FlowSim network and policy as P2D/EP;
it is not a zero-cost metadata operation.

FlowSim queue values remain residual fluid backlog. They are not packet-buffer occupancy and
cannot be used as ECN/PFC/drop measurements.

## Workloads and controls

Two real Mooncake Tool/Agent windows were used.

1. `30s__window_000098`, first four requests: a high-reuse but simultaneous gate.
2. `300s__window_000005`, rows 1680--1683: a high-reuse staggered gate. The first two
   requests arrive at 240 s and the next two at 243 s, preserving the source timing.

For each window:

- `FIRST_PRODUCER`: repeated blocks are fetched from the first trace-local producer;
- `BALANCED_REPLICA`: balanced source choices are preceded by explicit same-fabric replica
  copies;
- `NO_REMOTE`: matched serving control with all prompt KV sent through native P2D;
- Qwen3 model-derived bytes and GateRouter EP demand are unchanged;
- `EP64`, TP2, two Prefill and two Decode instances, FlowSim, 200-Gbps profile;
- `A2A_P2P`, `LAYERWISE`, actual Decode receiver;
- four requests and four output tokens only to keep the integrated gate tractable. The input
  lengths, block identities, arrival ordering, and KV accounting are not shortened.

The four-request SLO values below are diagnostic only. The repository's analyzer correctly
marks a baseline with fewer than ten requests or `baseline-kind=diagnostic` as invalid for a
paper SLO claim.

## Integrated result A: simultaneous high-reuse gate

Plan accounting:

| policy | remote fetch bytes | remote fetch tokens | warm-up bytes | warm-up flows |
|---|---:|---:|---:|---:|
| FIRST_PRODUCER | 1.125 GiB | 12,288 | 0 | 0 |
| BALANCED_REPLICA | 1.125 GiB | 12,288 | 0.5219 GiB | 13 |

Both policies produced exactly the same serving results:

| policy | TTFT P99 | TPOT P99 | TBT mean P99 | TBT token P99 | diagnostic joint SLO |
|---|---:|---:|---:|---:|---:|
| NO_REMOTE | 214.177 ms | 3.706 ms | 8.466 ms | 10.893 ms | 1.00 |
| FIRST_PRODUCER | 214.177 ms | 3.706 ms | 8.466 ms | 10.893 ms | 1.00 |
| BALANCED_REPLICA | 214.177 ms | 3.706 ms | 8.466 ms | 10.893 ms | 1.00 |

The output is valid integrated serving output, but this window has no meaningful
cross-request KV/EP overlap: all four requests enter the first prefill wave together and
native P2D remains the handoff tail.

## Integrated result B: staggered hot-prefix gate

Plan accounting:

| policy | remote fetch bytes | remote fetch tokens | warm-up bytes | warm-up flows |
|---|---:|---:|---:|---:|
| FIRST_PRODUCER | 1.6875 GiB | 18,432 | 0 | 0 |
| BALANCED_REPLICA | 1.6875 GiB | 18,432 | 0.28125 GiB | 6 |

The selected four requests contain approximately 73.6% repeated input tokens under the
trace's 512-token block identity. The first two arrive at 240 s and the next two at 243 s.
The native P2D count is approximately 0.6046 GiB after removing remote-hit tokens.

### Network ordering

| event | FIRST_PRODUCER | BALANCED_REPLICA |
|---|---:|---:|
| replica warm-up last completion | n/a | 12.081 ms from simulation start |
| request 1 remote-fetch last completion | 240.029581 s | 240.015047 s |
| request 2/3 remote-fetch last completion | 243.048552 s | 243.024397 s |
| request 1 native P2D last completion | 240.126903 s | 240.126903 s |
| request 2/3 native P2D last completion | 243.122782 s | 243.122782 s |

The remote fetch is therefore faster than the native P2D tail by approximately 97--123 ms
in this run. The different provider placement changes remote-fetch completion, but not the
last required P2D shard and hence not `p2d_kv_ready_time_ns`.

The integrated FlowSim telemetry did observe real directed-link overlap:

- 3,840 EP flows;
- 384 P2D flows;
- 72 remote-fetch flows;
- six mixed directed links in both policies;
- global KV/EP overlap fraction about `1e-4` because the total activity span includes the
  long source-trace gap.

This proves the data-plane overlap exists in the integrated run. It does not prove that the
remote-provider flow is exposed on the serving critical path.

### Serving result

| policy | TTFT P99 | TPOT P99 | TBT mean P99 | TBT token P99 | diagnostic joint SLO |
|---|---:|---:|---:|---:|---:|
| NO_REMOTE | 135.928 ms | 956.401 ms | 958.444 ms | 2,863.787 ms | 0.75 |
| FIRST_PRODUCER | 135.928 ms | 956.405 ms | 958.448 ms | 2,863.800 ms | 0.75 |
| BALANCED_REPLICA | 135.928 ms | 956.421 ms | 958.464 ms | 2,863.845 ms | 0.75 |

The very large TBT tail is a legitimate scheduler output from this highly staggered,
short-output gate; it is not attributed to remote KV. Relative to `NO_REMOTE`:

- FIRST_PRODUCER changes TTFT P99 by 0.000%;
- BALANCED_REPLICA changes TTFT P99 by 0.000%;
- FIRST_PRODUCER changes TPOT P99 by about 0.0004%;
- BALANCED_REPLICA changes TPOT P99 by about 0.0020%;
- the maximum recorded TBT changes by less than 0.0039%.

The SLO attainment is also unchanged at 75%, but it is explicitly diagnostic rather than a
paper-grade SLO claim because the matched baseline has four requests.

## Why P4 does not yet propagate to TTFT/TBT

The causal chain needed by P4 is:

```
hot-prefix provider concentration
  -> provider egress queue
  -> last remote block fetch delay
  -> Decode admission barrier
  -> TTFT
```

The current integrated gate instead follows:

```
hot-prefix provider choice
  -> remote-fetch completion changes
  -> native P2D last shard remains later
  -> p2d_kv_ready unchanged
  -> TTFT unchanged
```

For TBT, the required chain would be:

```
remote-KV/provider traffic
  -> active Decode EP queueing
  -> EP collective CCT
  -> decode iteration delay
  -> TBT
```

The gate observed P2D/EP overlap but did not show a stable policy-dependent EP barrier or TBT
change. The large absolute TBT outlier is present in the no-remote control and therefore is
not evidence for P4.

Replica warm-up also did not change TTFT because this trace has a long idle interval before
the selected requests. The six-copy, 0.28125-GiB warm-up completes at simulation start,
well before the first request at 240 s. That is a correct accounting result, not free
replication: the copies are present in the FlowSim ledger and block remote fetch release.
It does mean this gate tests **pre-warmed replicas**, not an online replica created at the
instant of a hot request.

## Artifacts

- Plan generator: `scripts/make_integrated_remote_kv_plan.py`.
- Staggered workload: `workloads/real/integrated_remote_kv_staggered_4req/`.
- Staggered serving output: `results/integrated_remote_kv_staggered_4req/`.
- Integrated summary: `results/integrated_remote_kv_staggered_4req/integrated_summary.md`.
- High-reuse simultaneous serving output: `results/integrated_remote_kv_highreuse_4req/`.
- Existing packet-level P4 audit: `P4_RESEARCH_AUDIT.md` and `P4_CURRENT_SIMULATION_AUDIT.md`.

## Final P4 status

`REMOTE_KV_BARRIER_INTEGRATED = PASS` as an implementation gate.

`P4_PROVIDER_EGRESS -> TTFT/TBT/SLO = NOT ESTABLISHED`.

The current P4 candidate should be kept as a mechanism/control result. It should not yet be
presented as a CCF-A motivation claim. A stronger paper would need to make the remote-fetch
last completion, rather than native P2D, the serving-visible barrier under a trace-supported
and finite-cache state.
