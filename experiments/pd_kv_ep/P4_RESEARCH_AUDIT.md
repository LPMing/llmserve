# P4 Research Audit

Date: 2026-09-28

> **Superseding integrated follow-up (2026-09-28):** The minimal FlowSim integrated
> remote-KV extension has now been implemented and run, including model-derived remote-hit
> accounting and same-fabric replica warm-up. See
> [`P4_INTEGRATED_SERVING_VALIDATION.md`](P4_INTEGRATED_SERVING_VALIDATION.md) for the
> serving CSV/SLO audit. It confirms the barrier implementation but does not establish
> material TTFT/TBT impact: native P2D remains the last handoff event in the tested windows.


## Current decision

P4 is **not yet a paper-ready PD-specific packet-level problem**.

The corrected Gate 1 result is:

- PASS for demonstrating that provider concentration can change a request-level remote-KV
  completion barrier;
- FAIL for demonstrating that the large gap is caused primarily by packet-level
  P2D-versus-Decode-EP interaction.

The old hot-window P99 claim was also invalid because it used a small-sample index that
excluded the maximum. The corrected hot-window request-barrier P99 improvement is about
3.6%, not 52.45%.

## Audit inputs

- S16_EP64: 8 Prefill servers + 8 Decode servers, four TP2 instances per server (32 Prefill + 32 Decode instances);
- Qwen3-30B-A3B-Instruct-2507;
- 48 layers, 128 experts, top-k=8, EP64;
- 200-Gbps endpoints;
- 4096-byte packet payload;
- LAYERWISE model-derived KV;
- GateRouter-derived A2A_P2P EP events;
- Mooncake Tool/Agent offset 13327, 8 requests;
- FIRST_PRODUCER versus BALANCED_REPLICA_ORACLE.

## Corrected native telemetry

The native binary was rebuilt after adding packet-observed physical directed-link ids.

Results:

- both full replays completed;
- 25,500 input events and 51,000 communication START/END rows per run;
- all 14 remote-KV QPs had observed physical link-id paths;
- the EP event ledger was exactly identical between FIRST and oracle:
  24,718 EP events and 4,859,756,544 EP bytes.

The node path remains the logical endpoint path. The directed-link-id field now records the
physical link ids observed by forward UDP packets, so parallel leaf-spine links are no
longer represented by a single overwritten link id in new runs.

## Gate 1 matched results

### Request-level remote barrier

All values below are reconstructed as:

  max(network_end_ns over remote_kv END events for a request)
  minus the first remote network start for that request.

| backend / case | requests | mean ms | P50 ms | P95 ms | P99 ms | max ms |
|---|---:|---:|---:|---:|---:|---:|
| native full FIRST | 7 | 7.604891 | 7.604891 | 7.605337 | 7.605376 | 7.605386 |
| native full oracle | 7 | 1.632796 | 1.879758 | 2.103084 | 2.104944 | 2.105409 |
| native remote-only FIRST | 7 | 7.136328 | 7.136328 | 7.136813 | 7.136823 | 7.136823 |
| native remote-only oracle | 7 | 1.882021 | 2.068023 | 2.068023 | 2.068023 | 2.068023 |
| FlowSim remote-KV FIRST | 7 | 7.531700 | 7.531700 | not used | not used | 7.531700 |
| FlowSim remote-KV oracle | 7 | 1.079437 | 1.097413 | not used | not used | 1.097413 |

The complete request samples are stored in:

- results/p4_packet_provider/reaudit_low/
- results/p4_packet_provider/reaudit_low_remoteonly/

FlowSim values are residual-fluid outputs, not packet-buffer measurements.

### P2D plus EP incremental effect

Comparing native full with native remote-only:

- FIRST: 7.604891 / 7.136328 - 1 = approximately +6.57% mean barrier;
- oracle: 1.632796 / 1.882021 - 1 = approximately -13.24% mean barrier;
- FIRST max: approximately +6.57%;
- oracle max: approximately +1.81%.

The oracle mean is non-monotonic because the packet scheduler and event timing can change
completion ordering when additional EP flows are present. This is not evidence of a serving
improvement and is not used as a positive claim.

The important observation is that the large FIRST-versus-oracle separation is already present
in the 14-flow remote-only packet replay.

## Capacity decomposition

In the low window:

- remote-KV bytes: 352,321,536 bytes = 336 MiB;
- FIRST: all bytes are served by provider instance 0, using two provider ranks;
- each provider rank carries 168 MiB;
- nominal 200-Gbps serial lower bound per provider rank: 7.046431 ms;
- observed request barrier: 7.605386 ms;
- oracle: the same bytes are spread over 14 provider ranks, with each 24-MiB pair;
- nominal serial lower bound per oracle provider rank: 1.006633 ms.

This is a direct endpoint/provider pooling explanation. The relevant artifact is:

  results/p4_packet_provider/reaudit_low/P4_CAPACITY_DECOMPOSITION.csv

The result does not require ECN, PFC, DCQCN, or packet-size-specific queue behavior to appear.
FlowSim already reproduces the ordering.

## What Gate 1 establishes

It establishes:

  first-owner provider concentration
  -> fewer provider endpoint service opportunities
  -> larger request-level last-fetch barrier

It does not establish:

  remote-KV traffic
  -> Decode EP packet queue
  -> EP collective barrier
  -> serving TBT/TTFT

The native full-versus-remote-only incremental effect is small compared with the
FIRST-versus-oracle provider-placement gap.

Therefore the previous P4 candidate should not be described as a novel
packet-level P2D-versus-EP problem.

## Provider semantics audit

The current replay's FIRST_PRODUCER owner is created by a trace-local dictionary:

- first request that produces a block becomes its permanent owner;
- no finite cache;
- no LRU;
- no eviction;
- no replication traffic;
- no multi-holder state.

The oracle assumes every matched block is already replicated on every Prefill worker and
does not pay replication cost.

Thus the old control is an offline upper bound, not a deployable baseline. The next gate must
determine whether the concentration survives a finite-cache ownership model and stronger
non-oracle baselines.

## Gate 1 status

  GATE1_ENDPOINT_POOLING = PASS

  GATE1_PACKET_SPECIFIC_PD_INTERACTION = FAIL

  GATE1_P4_PAPER_DECISION = DEFERRED_PENDING_FINITE_CACHE_AUDIT

This is not yet a final P4 failure. It means no integrated TTFT/TBT claim is allowed before
the finite-cache and ownership audit.

## Next gate (historical; completed below)

Gate 2 used the original Mooncake request order and block identities with an explicit
finite ownership model. It will first be an offline trace analysis, not a large packet replay.
The purpose is to answer whether the provider concentration is trace-supported or created
only by the current first-writer dictionary.


## Gate 2 — finite-cache ownership audit (completed)

The S16 mapping used by the audit is 8 Prefill servers and 8 Decode servers, with four
TP2 instances per server: 32 Prefill instances and 32 Decode instances.  A cache block is
512 tokens and, for Qwen3-30B-A3B at TP2 and BF16 KV, is 25,165,824 bytes per TP rank,
48 MiB per TP2 instance.  The 2,366-block capacity point is approximately 56.8 GiB per
TP rank, consistent with a 96-GiB GPU, the default 0.9 memory utilization, and a roughly
30-GiB-per-rank weight budget.  The capacity is recorded as an audit assumption, not as a
claim about a measured runtime cache allocation.

The finite audit uses original Mooncake block identities and arrival order.  It uses
local-miss-only insertion with per-instance LRU; a remote fetch is not silently replicated
at the requester.  This is a conservative ownership model and not a replacement cache
implementation.

| window / capacity | requests | remote requests | remote blocks | remote bytes | active providers | max provider share | evictions |
|---|---:|---:|---:|---:|---:|---:|---:|
| offset 13327, 7 / 128 blocks | 7 | 6 | 6 | 288 MiB | 1 | 100.00% | 0 |
| offset 13327, 7 / 2366 blocks | 7 | 6 | 6 | 288 MiB | 1 | 100.00% | 0 |
| offset 13327, 512 / 2366 blocks | 512 | 492 | 3003 | 144,124.40625 MiB | 12 | 77.13% | 0 |
| full tool-agent / 2366 blocks | 23,608 | 22,994 | 218,232 | 10,468,366.8 MiB | 32 | 50.21% | 107,838 |
| full tool-agent / unlimited | 23,608 | 22,994 | 218,497 | 10,480,993.0 MiB | 32 | 50.23% | 0 |

The 512-window exact bytes are in
`results/p4_packet_provider/gate2_window512/finite_cache_audit.json` and
`finite_cache_summary.csv`; the exact value is 144,124.40625 MiB, as recorded in the JSON/CSV artifact.

The audit therefore supports a trace-natural hot-prefix observation: the common block
`mooncake_toolagent:0` is requested 10,938 times in the full trace and remains concentrated
at one provider in the 2,366-block finite model.  However, finite ownership does not create
multiple holders: under local-miss-only insertion every block has at most one owner.  Thus
random-holder, least-loaded-holder, and network-aware-holder policies have no legal choice
set unless replication is added.  The existing replica oracle changes the physical source
without accounting for replication traffic and remains an offline upper bound.

## Gate 3 — matched FlowSim ownership control (completed)

A bounded 64-request window at offset 13327 was built with the same trace, model-derived
bytes, routing, topology, EP events, and 2,366-block finite cache.  The comparison is
finite first-owner versus the existing already-replicated oracle.  FlowSim is residual-fluid
telemetry; it is not packet-buffer or ECN/PFC telemetry.

| case | remote flows | remote requests | mean remote barrier | P50 | P95 | P99 | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| FULL finite first-owner | 122 | 61 | 53.026045 ms | 13.106229 ms | 157.736973 ms | 157.736973 ms | 157.736973 ms |
| FULL replica oracle | 684 | 61 | 11.005868 ms | 14.833840 ms | 16.939261 ms | 16.939261 ms | 16.939261 ms |
| KV_ONLY finite first-owner | 122 | 61 | 53.011180 ms | 13.106229 ms | 157.736973 ms | 157.736973 ms | 157.736973 ms |
| KV_ONLY replica oracle | 684 | 61 | 10.993646 ms | 14.816624 ms | 16.883628 ms | 16.883628 ms | 16.883628 ms |

The first-owner/oracle remote P99 gap is large, but it is essentially unchanged when EP is
removed: FULL changes the first-owner P99 by 0.00% and the oracle P99 by 0.33% relative to
KV_ONLY.  EP collective CCT P99 is 0.106508 ms in both FULL cases.  The small difference in
maximum CCT (0.114372 ms versus 0.193016 ms) does not form a stable ordering and is not a
serving claim.

This closes the causal test:

`hot-prefix ownership -> provider endpoint pooling -> remote-KV last-fetch barrier`

is supported, while:

`hot-prefix ownership -> shared provider/EP packet queue -> EP collective barrier`

is not supported by this matched window.  No integrated TTFT/TBT run is accepted for this
candidate because network-only data cannot be promoted to serving metrics, and the required
PD-specific EP interaction did not survive the KV_ONLY counterfactual.

## Final P4 decision

- `P4_TRACE_SUPPORTED_PROVIDER_POOLING`: **PASS as a separate remote-KV/cache-ownership observation**.
- `P4_PACKET_SPECIFIC_REMOTE_KV_X_EP`: **FINAL_FAIL for the current candidate**.
- `P4_INTEGRATED_SERVING_VALIDATION`: **not run**, correctly—not because of a timeout or
  missing value, but because the matched network control removed the alleged EP mechanism.
- `P4_NEXT_STEP`: do not implement replication, placement, scheduler, or integrated serving
  for this candidate.  Preserve the provider-pooling result as a control/negative result;
  any future remote-KV paper question must introduce a legal finite-cache/replication state
  and re-establish EP path sharing before claiming PD-MoE coupling.
