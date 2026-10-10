# Failed and Bounded Research Attempts

This file consolidates the research directions that were either disproved,
failed the serving-level motivation gate, or could not be tested without
inventing unsupported simulator semantics.  A network-only gap is not counted
as a serving-level paper result unless an integrated TTFT/TBT/SLO path also
passed.

## Executive summary

No previous direction has produced a robust CCF-A serving-level motivation.
The strongest valid observations are:

1. Decode-side fluid/packet congestion can strongly change EP CCT and KV
   request handoff metrics.
2. The current serving timeline often hides that network delay from TTFT/TBT.
3. `EP_FIRST` protects EP reliably, while its additional KV cost is usually
   small under the current nonblocking P2D semantics.
4. Remote-prefix/provider and split-source experiments changed remote-KV
   barriers, but did not produce a stable integrated serving opportunity.
5. Several historical large effects were invalidated by topology or capacity
   modeling errors and must not be reused.

## 1. Invalidated or non-authoritative results

### 1.1 Old parallel-link FlowSim results

The old reader overwrote `edges[(src,dst)]` when a leaf-spine pair had
parallel links.  An S16 pair with 16 x 200 Gbps links was therefore modeled as
one 200 Gbps resource instead of the correct 3.2 Tbps aggregate fluid
resource.  The old S16/S64/S256 quantitative results are invalid for
utilization, KV FCT, EP CCT, and queue conclusions.

The historical `+23.44%` KV slowdown under 32 Decode + 64 P2D was recovered
under the old capacity interpretation, but became `0.00%` after the correct
aggregate capacity was restored.  It was caused by the missing parallel-link
capacity, not a robust PD serving effect.

Evidence: `MOTIVATION_GATES_REPORT.md`, `PD_NETWORK_RESEARCH_GATES.md`.

### 1.2 Old 50G/100G/200G small topology endpoint mismatch

`2_leaf_4_rank_shared_spine_50g.txt` declares switch IDs 4 and 5, leaving only
endpoint IDs 0--3, while the associated 1P(TP1)+2D(TP2) serving configuration
generates ranks 0--4.  Rank 4 collides with a switch ID.  Results from this
file are diagnostic only, not authoritative five-rank results.

The current rerun uses an endpoint-consistent 8-rank, 2P(TP2)+2D(TP2), P:D=1:1
configuration.  Native ns-3 also required a 50 Gbps KMIN/KMAX/PMax parameter
bucket; without it the simulator correctly aborted rather than producing a
result.

## 2. KV versus Decode-EP policy crossover attempts

### 2.1 `EP_FIRST -> KV/TTFT` crossover

The intended hypothesis was that protecting EP would significantly delay KV.
Repeated EP64 experiments with realistic model-derived bytes, including
32 Decode + 64 P2D and finite 32 MiB staging sensitivity, did not establish
this.  `EP_FIRST` and `FAIR` often had nearly identical request-level KV FCT
and TTFT.  The current nonblocking layerwise P2D producer can continue
releasing KV while earlier transfers drain, and request TTFT waits only for the
last required handoff barrier.

Decision: **FAIL as a general static-policy crossover under current serving
semantics.**

Evidence: `CHARACTERIZATION_REPORT.md`, `PD_KV_EP_RESEARCH_SUMMARY.md`.

### 2.2 `KV_FIRST` as a robust alternative

`KV_FIRST` can substantially reduce KV completion time, but it repeatedly
causes very large EP CCT/TBT penalties.  It is therefore a useful control, not
an independent solution.  The preferred policy changes with pressure only at
the network metric level; no stable integrated SLO crossover was established.

### 2.3 Critical-only EP protection

Offline `CRITICAL_EXACT`, `TOP1`, `TOP5`, and `TOP10` protection was tested
against two real-trace-derived windows.  Selective protection created new
collective stragglers: TOP5 increased EP P99 by up to 57.72% relative to
`EP_FIRST`, while KV P99 had essentially 0% headroom.  The identity of the
critical flow is policy-dependent, so an old critical-flow list is not stable.

Decision: `CRITICAL_ONLY_FINAL_FAIL_NO_KV_HEADROOM`.

Evidence: `CRITICAL_EP_PROTECTION_VALIDATION.md`.

## 3. Placement, path, and barrier attempts

### 3.1 P1 placement x exposed barrier

Matched P/D pairing changed P2D leaf geometry but not request bytes, GateRouter
EP traffic, or decode load.  Across real windows the EP CCT change was 0--7.1%
and KV FCT did not change.  The symmetric Decode EP pool placed comparable
demand on both Decode cuts, so swapping P2D pairing did not change the barrier
service rate.

Decision: **FAIL serving motivation screen.**

### 3.2 P2 last-shard/path-straggler amplification

Alternate legal spine and deterministic striping controls changed path labels
but did not change request-level last-shard FCT or KV barrier tails.  The
non-oversubscribed 1:1 topology and equivalent spine capacities left the last
shard's service rate unchanged.

Decision: **FAIL for tested legal path variation.**

### 3.3 P3 receiver-side incast

Fan-in changed network metrics, but the realistic four-instance fan-in case
changed EP CCT P99 by about 10.9% and KV FCT P99 by about 0.07%.  An extreme
one-instance upper bound increased EP CCT strongly while changing the TTFT
proxy and KV FCT by less than 1%.  Integrated 64D+64P2D validation showed
about +2.5% TBT and less than +1% TTFT.

Decision: **Network mechanism exists; serving-level motivation FAIL.**

### 3.4 P4 barrier-aware multipath

Current BFS, alternate-spine, and round-robin logical spine controls did not
change request KV FCT P99 or the last-shard barrier.  The aggregate fluid
model has one selected path per endpoint pair and does not model packet ECMP
hashing.

Decision: **FAIL under the valid topology/backend model.**

### 3.5 EP route-geometry / exposed-barrier candidate

GateRouter exact A2A_P2P versus same-byte uniform peer realization produced an
approximately 79% network-only EP CCT gap.  The gap was already present in
EP-only traffic and therefore was not proven to be P2D-specific.  Integrated
TBT/TTFT validation was not completed as a positive result.

Decision: **generic EP route-geometry observation; no PD serving PASS.**

Evidence: `MOTIVATION_GATES_REPORT.md`,
`results/exposed_barrier_validation/EXPOSED_BARRIER_FAIL_REPORT.md`.

## 4. Packet-level directions that failed or remain bounded

### 4.1 Packet P2D cut/fan-in

The old packet replay showed large effects (`+54.3%` EP CCT P99 and `+96.5%`
KV FCT P99), but the corrected parallel-link replay invalidated those numbers
for the old route representation.  The corrected integrated FlowSim gate
showed only about `+5.0%` TBT and less than `+1%` TTFT.  A 256-entry integrated
attempt reached the wall-clock limit and produced no serving CSV, so no metric
was inferred from it.

Decision: **packet/network mechanism valid; serving-level paper gate FAIL.**

Evidence: `P2_PACKET_REPLAY_GATE.md`.

### 4.2 Cross-timescale ECN/DCQCN response

Native packet feedback changed ECN/CNP/rate and individual flow FCT, but KV
request barriers and EP CCT changed below 1% in the tested long-KV 8/16 cases.
Layerwise release and fresh QPs absorbed the transport response.

Decision: `P1_FINAL_FAIL_FOR_CURRENT_FRONTEND`.

### 4.3 Persistent-QP state inheritance

The current replay creates a fresh QP per flow and does not reuse DCQCN state
between requests.  Adding persistent state would fabricate a mechanism not
represented by the current runtime.

Decision: `P2_FINAL_FAIL_CURRENT_BACKEND_NO_QP_REUSE`.

### 4.4 Finite generation-drain backpressure

The frontend has no validated producer staging resource that blocks Prefill
when P2D drain falls behind.  Network slowdown therefore cannot be promoted
to TTFT without inventing a buffer capacity and blocking rule.

Decision: `P3_FINAL_FAIL_CURRENT_FRONTEND_HAS_NO_PRODUCER_RESOURCE`.

### 4.5 Layerwise transport burst shaping

The current builder can split a model event into flow records, but does not
model NIXL/UCX rendezvous, WQE credits, NIC pacing, or validated injection
granularity.  Packet payload size changes packetization, not transport release
semantics.

Decision: `P5_FINAL_FAIL_CURRENT_BACKEND_NO_TRANSPORT_GRANULARITY`.

Evidence: `P5_LAYERWISE_BURST_SHAPING_AUDIT.md`.

## 5. Remote-KV and cache directions

### 5.1 Ordinary provider placement / replica oracle

Remote prefix reuse correctly reduces Prefill compute and changes TTFT.  A
provider-placement oracle changed fluid backlog, but did not stably change
integrated TTFT; replica warm-up traffic is non-free.  Provider placement was
therefore downgraded from a packet candidate to NO-GO as the primary serving
motivation.

Decision: **ordinary provider placement NO-GO.**

Evidence: `P4_GO_NO_GO.md`, `P4_RESEARCH_AUDIT.md`.

### 5.2 Split-source KV assembly

The current semantics require the remote prefix to be materialized at Prefill,
so the legal V1 variant is dual destination:

```text
Remote -> Prefill prefix
Remote -> Decode prefix
Prefill -> Decode suffix
```

The extra Remote-to-Decode copy did not remove the Remote-to-Prefill
dependency.  On two high-reuse windows it made representative remote-hit TTFT
22.9--61.1% worse and also increased EP-side metrics in one window.

Decision: `P4B_FAIL_LOW_SERVING_HEADROOM` / final NO-GO.

Evidence: `P4B_FINAL_NO_GO.md`, `P4_SPLIT_SOURCE_RESEARCH.md`.

### 5.3 Hot-prefix provider-egress barrier

This was a valid packet/request-barrier candidate: real Mooncake windows showed
37.2--78.5% remote-KV barrier headroom under a balanced-provider oracle with
the same bytes and EP ledger.  However, integrated TTFT/TBT/SLO validation did
not establish a positive serving result, and the oracle assumes pre-existing
replicas unless replication cost is explicitly charged.

Decision: **packet/request-barrier PASS, complete serving-paper candidate not
validated.**

Evidence: `PACKET_LEVEL_PAPER_FEASIBILITY.md`, `P4_INTEGRATED_SERVING_VALIDATION.md`.

## 6. New direction search N1--N5

| direction | failure reason |
|---|---|
| N1 Decode batch-boundary amplification | Natural 32D+32P2D point exposed about 6.5% TTFT; neighboring 32D+64P2D point about 1.2%; not stable enough. |
| N2 P2D handoff phase synchronization | Real Mooncake Conversation and Tool/Agent windows had at most two completions per 5/10 ms; no natural narrow handoff wave. |
| N3 multi-NIC/rail mismatch | Current S16 has no validated NIC/rail resource or assignment semantics. |
| N4 cross-request KV batching/HOL | KV remains request/layer/shard scoped; only EP memory coalescing exists. |
| N5 recovery/rehydration storm | No failure, invalidation, restart, migration, or recovery-triggered event model exists. |

Evidence: `NEW_DIRECTIONS_FINAL_REPORT.md` and `NEW_DIRECTIONS_RESEARCH.md`.

## 7. Progressive Push sensitivity

Progressive Push implementation and lifecycle correctness passed, but the
serving motivation was not robust:

- one 50G small-topology Mooncake window: 20.22% TTFT P99 improvement;
- adjacent 50G windows: 17.76% and 19.90%;
- same workload at 100G: 11.03%;
- same workload at 200G: 6.07%;
- TBT P99 did not improve at any rate.

The old 50G point also used the endpoint-inconsistent 4-rank topology.  It was
replaced by an endpoint-consistent S16/EP64 native ns-3 replay, but the new
result is still only a low-rate packet-level sensitivity bound: integrated
serving did not complete within the tested runtime budget and therefore no
TTFT/TBT/SLO claim is attached to it.

Evidence: `PROGRESSIVE_PUSH_RESEARCH.md`,
`PROGRESSIVE_PUSH_BW_RESULTS.csv`.

## 8. Simulator and experiment failures

These are not research hypotheses, but they invalidated intermediate results:

1. FlowSim parallel-link overwrite understated S16/S64/S256 aggregate
   capacity.
2. The old native packet topology route table exposed one physical interface
   from a parallel bundle; corrected replay changed link distribution and
   invalidated old ECMP claims.
3. An early integrated P/D scheduler path admitted Decode before the P2D
   barrier because `req.is_init = False` was missing; those CSVs were
   discarded and rerun.
4. A Push request-scoped handoff bug transferred every request in a mixed
   Prefill batch; it was fixed before the retained Push results.
5. The small 1P(TP1)+2D(TP2) packet setup had a non-rectangular ASTRA rank
   world and a rank/switch ID collision.
6. Native ns-3 had no 50G KMIN/KMAX/PMAX map entry and aborted before packet
   simulation; the missing speed bucket is now added explicitly.
7. Large 256-request integrated packet/FlowSim attempts exceeded practical
   runtime/RSS limits; no serving values were imputed.

## 9. Valid 50G native packet-level rate sensitivity

The endpoint-consistent S16/EP64 replay was rerun at 50 Gbps and 200 Gbps
with the same model-derived event ledger, 4-KB packets, LAYERWISE P2D, and
GateRouter A2A_P2P.  The completed 50G large-KV replay showed:

- FAIR: EP CCT P99 324.63 us versus 112.25 us at 200G, approximately
  +189.2%;
- FAIR: KV request FCT P99 144.50 ms versus 143.48 ms at 200G, approximately
  +0.7%;
- KV_FIRST: EP CCT P99 1.873 ms, approximately +476.5% over 50G FAIR;
- EP_FIRST: EP CCT P99 324.57 us, essentially unchanged from 50G FAIR;
- 50G produced 50,495 ECN marks under FAIR, with no PFC pause or packet drop
  in this bounded window.

This is a valid packet-level observation that lower rate amplifies the
barrier-sensitive EP tail much more than the long, last-shard KV request
barrier.  It is not a complete serving motivation: the integrated 4-request,
3-request, 1-request, and minimal 8-token packet-serving runs all exceeded
their runtime bounds, so no TTFT/TBT/SLO was inferred.  It also does not show
that EP_FIRST is always useful: in this ledger it did not improve EP P99 over
FAIR.  The result therefore remains a rate-sensitivity boundary and a
packet-level candidate, not a PASS for a CCF-B/CCF-A paper problem.

The exact completed comparison is in
`PACKET_RATE_50G_VALIDATION.md`; compact rows are in
`results/packet_rate_sensitivity/rate_policy_summary.csv`.

## Current interpretation

The repeated pattern is not simply “200 Gbps is too fast.”  It is:

```text
network metric gap
    -> often hidden by compute/admission overlap
    -> small TTFT/TBT gap
```

Lowering rate to 50G can expose a real packet-level bottleneck, but only if the
topology is endpoint-consistent and the 50G congestion-control configuration
is valid.  A 50G result will be treated as a rate-sensitivity result unless it
also has a matched 100/200G boundary and a stable serving-visible mechanism.
