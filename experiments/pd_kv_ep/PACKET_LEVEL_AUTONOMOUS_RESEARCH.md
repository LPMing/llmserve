# Packet-Level Autonomous Research

> **Phase-II update (2026-09-29):** the earlier P4 packet/request-barrier
> candidate was subsequently downgraded by the authoritative integrated/P4B
> audit. The current post-P4 search ledger is
> [`NEW_DIRECTIONS_RESEARCH.md`](NEW_DIRECTIONS_RESEARCH.md), and its final
> bounded outcome is [`NEW_DIRECTIONS_FINAL_REPORT.md`](NEW_DIRECTIONS_FINAL_REPORT.md).
> Do not cite the historical P4/P5 status below as the current conclusion.

Historical status: P1–P3 FINAL_FAIL; the simple critical-flow protection
refinement also FINAL_FAIL; P4 was initially recorded as a packet/request-barrier
candidate; P5 was stopped by that earlier PASS rule. The later phase-II audit
supersedes that status for current paper claims.

This document records authoritative conclusions from native ns-3 packet-level
experiments. FlowSim results, old single-link-bundle results, and network-only
proxies are not used as serving-level evidence here.

## Global packet-backend correctness

- The S16 topology keeps all physical parallel leaf-spine interfaces. Each
  physical directed link is 200 Gbps; the topology is not represented as one
  3.2-Tbps endpoint link.
- The corrected packet replay registered all physical directed links and
  preserved the ECMP interface set. Queue, ECN, PFC, flow completion, and
  request/event ledgers are compact event-level telemetry.
- `CC_MODE=1` is the documented MLX/DCQCN path. The older replay template used
  `CC_MODE=12`, which is not one of the implemented CC branches and must not be
  described as DCQCN.
- FlowSim fluid backlog remains analytical only. It is not used as packet
  queue, ECN, PFC, or packet-loss evidence.

## P1 — Cross-timescale congestion control

### Hypothesis

Decode EP bursts could trigger ECN/CNP and a DCQCN rate decrease whose recovery
outlives the short EP burst, delaying subsequent KV or EP barrier traffic.

### Stage 0: CC correctness

The native backend now emits compact `CNP` and `RATE` events. The telemetry is
event-level; it does not write per-packet text logs. On the corrected S16,
32-Decode/64-P2D replay with 4-KB payloads and `CC_MODE=1`, the run completed
in 425 s CPU time / 426 s wall time with 351 MB peak RSS and recorded:

- 51,784 CNP events;
- 36,939 MLX rate-decrease events;
- 1,926 rate-recovery events;
- CNP-to-rate-decrease delay: median about 2.3 us, P95 about 4.0 us;
- recovery events began on the approximately 0.9-ms RP timer scale.

This proves that the backend has a real ECN -> ACK-CNP -> DCQCN rate-state ->
recovery path. It does not by itself prove serving impact.

### Important correctness fix

The MLX implementation previously assigned `RdmaQueuePair::m_rate` directly in
its rate-decrease and recovery paths without updating `m_nextAvail`, the state
used by the NIC scheduler to pace the next packet. The native implementation
was corrected so all MLX transitions update both the QP rate and NIC pacing.
The change does not add delay or alter bytes/routes; it makes the existing
rate-control state effective on packet serialization.

### Stage 1 and refinements

All cases use the same model-derived event ledger, bytes, timestamps, routes,
and Qwen3/EP64 traffic. `CC_MODE=0` is a matched no-rate-feedback
counterfactual with the same packet topology and ECN marking; it is not claimed
to be a deployable transport.

| case | traffic selected | CC comparison | KV handoff mean delta | KV handoff P99 delta | EP CCT delta |
|---|---:|---|---:|---:|---:|
| short-QP gate | 1 P2D request + original EP rounds | mode 1 vs 0 | 0% | 0% | 0% |
| long-KV-8 | 8 concurrent P2D requests, 8.39-MB model-derived layer shards | mode 1 vs 0 | +0.52% | +0.66% | 0% |
| long-KV-16 | 16 concurrent P2D requests, same ledger family | mode 1 vs 0 | +0.49% | +0.59% | 0% |

The long-KV-8 flow-level effect was real: flow FCT mean increased from 0.257
ms to 0.396 ms (+54.0%) and P99 from 1.054 ms to 1.959 ms (+85.9%) under
DCQCN. However, the request barrier was determined by the last layerwise
shard after a long release span, so the request-level handoff changed by less
than one percent. EP collective CCT was unchanged because the short EP QPs
completed before their feedback could affect their packet schedule, and each
replay event creates a fresh QP.

### P1 diagnosis and decision

The mechanism is real at packet/flow level, but the required serving/barrier
amplification did not occur in three mechanism-driven operating points:

`ECN/CNP/DCQCN state change -> flow slowdown`, but not
`flow slowdown -> last required KV shard / EP barrier -> >=20% request metric`.

Increasing to 32 long-KV requests would mostly multiply packet cost while the
16-request point already showed the same barrier absorption. The P1 direction
therefore fails the paper-quality request/barrier criterion:

**P1_FINAL_FAIL_FOR_CURRENT_SERVING_BARRIER**

This is not evidence that DCQCN is unimportant in production. It is evidence
that this simulator's fixed layerwise release schedule and fresh-QP-per-event
semantics do not expose the cross-timescale effect to a serving barrier.

## P2 — Persistent-QP congestion-state inheritance

### Reality audit

The replay frontend allocates a new source port in every `send_flow()`, creates
a new `RdmaClientHelper`, and `RdmaClient::StartApplication()` calls
`RdmaDriver::AddQueuePair()`. DCQCN state is stored in that newly created
`RdmaQueuePair`. There is no QP/endpoint reuse or state transfer across
requests.

### Decision

The current backend cannot test persistent-QP inheritance. Adding a persistent
QP solely to create the effect would be an unvalidated transport model, so no
such extension is made.

**P2_FINAL_FAIL_CURRENT_BACKEND_NO_QP_REUSE**

## P3 — Layerwise KV generation-drain backpressure

### Reality audit

The native network model has a QP in-flight window and switch/PFC buffers, but
the replay frontend schedules each model-derived event at its precomputed
timestamp. There is no NIXL/UCX staging-buffer object, registered-buffer
capacity, or callback that blocks Prefill KV generation when network drain is
slow. Consequently, the packet backend can show network queueing and QP
windowing, but it cannot legitimately turn that state into Prefill stall or
TTFT without adding a new serving/resource model.

### Decision

No arbitrary 32-MB/64-MB producer buffer is introduced. Under the current
native packet semantics, finite generation-drain backpressure is not testable
without expanding the serving/runtime model beyond a packet-backend fix.

**P3_FINAL_FAIL_CURRENT_FRONTEND_HAS_NO_PRODUCER_RESOURCE**

## P4 — Hot-prefix remote-KV provider egress

### Hypothesis

Mooncake block reuse can make many requests fetch the same already-cached KV
blocks from the first producer/provider. The provider endpoint NIC and its
outgoing QP serialization can then become a request-level barrier even when
aggregate Clos capacity is not globally saturated. Decode-side EP can share the
same physical fabric, but the primary exposed barrier is the last remote-KV
fetch needed by each request.

This is a PD/MoE-specific candidate only when the chain is preserved:

`real hot block reuse -> provider egress concentration -> packet/QP serialization and queue -> last remote-KV fetch -> request handoff/TTFT exposure`.

### Reality audit

The converted Mooncake traces contain block identity separate from token IDs.
The 512-token block size is recorded in the conversion metadata. The measured
reuse is not inferred from prompt similarity:

| trace | requests | block references | unique blocks | repeated-reference fraction | hottest block references |
|---|---:|---:|---:|---:|---:|
| Mooncake Tool/Agent | 23,608 | 409,616 | 183,300 | 55.25% | 10,938 |
| Mooncake Conversation | 12,031 | 288,500 | 182,790 | 36.64% | 12,031 |

The native replay builder already supports `REMOTE_KV_FETCH`. Remote bytes are
computed from Qwen3-30B-A3B's 48 layers, KV heads, head dimension and dtype;
no `REMOTE_KV_SIZE_MB` override is used. The packet backend carries the event
as a distinct `serving_role=remote_kv` P2D-class flow.

### Matched packet experiment

Both windows use:

- S16 / 128 serving GPUs, 8 Prefill and 8 Decode instances;
- Qwen3-30B-A3B-Instruct-2507, TP2, EP64, 128 experts, top-k 8, 48 layers;
- 200-Gbps endpoint links, corrected physical parallel leaf-spine links;
- 4-KB packet payload, native ns-3 packet backend, FAIR;
- LAYERWISE model-derived KV events and GateRouter-derived Decode EP;
- the same request rows, arrivals, EP routes, EP bytes, and decode issue ledger;
- `FIRST_PRODUCER`: the current trace-local cache source;
- `BALANCED_REPLICA_ORACLE`: an offline upper bound assuming the matched
  blocks already have legal replicas on Prefill workers and choosing a
  deterministic provider per request/block.

The oracle does not add replication traffic and is not a deployable policy.
Its anchor is explicitly frozen to the first-producer aggregation so provider
selection cannot alter the Decode/EP issue timeline. The corrected builder
verifies that the EP event tuples (start, source, destination, bytes, event
and collective) are identical between the two ledgers.

### Results

Request-level remote-KV barrier is computed as the maximum completed remote-KV
flow per request minus that request's remote-fetch issue time. It is not a sum
of flow FCTs and is not reported as TTFT.

| real trace window | policy | remote flow count | remote-KV bytes | request barrier mean | P50 | P99 | EP CCT P99 |
|---|---|---:|---:|---:|---:|---:|---:|
| Tool/Agent offset 13327, 8 requests | FIRST_PRODUCER | 14 | 352 MiB | 7.6049 ms | 7.6049 ms | 7.6052 ms | 0.1296 ms |
| same window | BALANCED_REPLICA_ORACLE | 14 | 352 MiB | 1.6328 ms | 1.8798 ms | 2.0977 ms | 0.1298 ms |
| Tool/Agent offset 0, 8 requests | FIRST_PRODUCER | 10 | 768 MiB | 6.0596 ms | 4.3741 ms | 4.3743 ms | 0.1136 ms |
| same window | BALANCED_REPLICA_ORACLE | 32 | 768 MiB | 3.8077 ms | 2.0680 ms | 2.0809 ms | 0.1171 ms |

Relative request-barrier headroom is therefore:

- low-output window: mean -78.5%, P99 -72.4%;
- hot-burst window: mean -37.2%, P50 -52.7%, P99 -52.5%.

The low-output window is the stricter matched result: every EP event is
identical and the remote KV bytes are identical. The hot-burst window has the
same EP ledger after the anchor fix and the same aggregate remote bytes; the
oracle has more remote flow endpoints because the same cached blocks are
served from more pre-existing replicas. That flow-count change is disclosed,
not hidden.

### Packet mechanism

In the low-output window, FIRST_PRODUCER sends the seven matched 50,331,648-B
remote fetches through only two provider ranks (seven flows per provider).
The request barrier is about 7.6 ms, consistent with provider-side QP/NIC
serialization. The oracle spreads those same bytes over fourteen providers;
request barriers fall to 1.06–2.11 ms. The exact packet paths, per-link queues,
ECN and PFC telemetry are present in the two run directories under `/tmp`.
The change is not a fabricated ECMP collision or reduced bandwidth.

The Decode EP barrier is almost invariant in the low-output window:
collective CCT mean 0.104850→0.104881 ms and P99
0.129628→0.129793 ms. Thus the measured headroom is genuinely on the
request-level remote-KV barrier, while EP is a matched concurrent workload
and not a proxy for the KV result.

### P4 decision

**P4_PASS_HOT_PREFIX_PROVIDER_EGRESS_BARRIER**

The direction passes the packet/request-barrier gate: two non-identical real
Mooncake windows produce greater than 20% request-level headroom under the
same model-derived traffic and same EP ledger. P1–P3 were not passed, and P5
is not run because the autonomous search stops at the first valid PASS.

This is not yet an integrated TTFT/TBT PASS. Native ns-3 replay is a network
backend experiment and does not itself run the serving scheduler. The next
paper-validation step must connect the same provider placement and remote-KV
completion barrier to integrated TTFT, then include replication warm-up/cost
and a deployable placement policy. No TTFT, TPOT or TBT value is inferred in
this report.

### Main review risks

1. The balanced source is an offline oracle; a real system must pay replication
   cost and maintain cache consistency.
2. Provider-egress concentration can be described as cache placement/load
   balancing unless the paper demonstrates the request barrier, hot-block
   temporal fanout and PD/MoE coupling together.
3. Packet queue/ECN/PFC evidence is authoritative only for native ns-3; no
   FlowSim fluid backlog is mixed into this claim.
4. The current windows are deliberately small because EP64 packet replay takes
   about five minutes per eight-request case. Larger-window and integrated
   serving validation remain required.

## Supporting refinement — selective EP critical-flow protection

Before treating `EP_FIRST` as over-protection, an offline oracle test was run
on the existing Mooncake and BurstGPT-derived uncoalesced 64-request ledgers.
`CRITICAL_EXACT` protects flows tied at the FAIR last completion of each EP
collective; TOP1/TOP5/TOP10 protect the slowest corresponding fraction. The
experiment keeps request arrivals, model-derived bytes, EP routes, P2D routes,
topology and event timestamps fixed. Full results and metric definitions are
in `CRITICAL_EP_PROTECTION_VALIDATION.md`.

The oracle does not expose useful KV headroom. In the Mooncake window, TOP1 and
TOP5 increase EP CCT P99 relative to EP_FIRST by 15.95% and 57.72%, while
changing KV handoff P99 by -1.01% and -0.33%. In the second window, TOP1 and
TOP5 increase EP CCT P99 by 7.97% and 39.86%, with no KV P99 change. The exact
FAIR straggler set is worse for EP because unprotected collective flows become
new stragglers. This is a mechanism-driven negative result: collective
criticality is policy-dependent, so protecting a static subset is not
equivalent to protecting the barrier.

Decision: **CRITICAL_ONLY_FINAL_FAIL_NO_KV_HEADROOM**. This refinement is not
used to claim a scheduler result, and no TTFT/TBT is inferred from it.

## P5 — Layerwise burst shaping

Not run. The P4 packet/request-barrier candidate satisfies the stopping rule.

## Evidence discipline

- P1–P3 are explicit FINAL_FAIL conclusions for the current backend semantics;
  their negative results are retained above.
- P4 packet artifacts are temporary under `/tmp`; the compact summary and
  commands are recorded in `results/p4_packet_provider/p4_summary.json` and
  `PACKET_LEVEL_PAPER_FEASIBILITY.md`.
- No TTFT/TBT/SLO value is inferred from packet FCT or EP CCT.
- `BALANCED_REPLICA_ORACLE` is offline characterization, not a scheduler,
  placement algorithm, priority policy or final solution.
