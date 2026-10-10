# KV–EP Motivation Gates

This report records the ordered motivation search.  The current gate is the
FlowSim topology correctness gate; P1 (topology-induced exposed barrier
contention) is not considered valid until this gate passes.

## Correctness Gate: parallel-link representation

### Problem found

The previous FlowSim topology reader stored a physical link as
`edges[(src, dst)] = link`.  In the S16/S64/S256 Clos files, a leaf–spine
directed pair has multiple parallel 200-Gbps links.  The last record silently
replaced all earlier records.  For example, the S16 topology has 16 physical
links per leaf–spine pair, so the old representation modeled 200 Gbps instead
of the correct 3.2 Tbps aggregate for that directed pair.

Consequently, old FlowSim runs that used these parallel-link topologies cannot
be used for quantitative conclusions about link utilization, backlog, KV FCT,
or EP CCT.  In particular, the old S16/S64 large-scale results are retained as
historical artifacts but are marked **invalid pending rerun**.  Small
topologies without parallel physical links are not affected by this specific
bug.

### Fix

`serving/core/flowsim_backend.py` now:

1. retains every listed physical link while parsing;
2. materializes reverse directions only when the topology file does not already
   contain that direction, preserving the repository's topology convention;
3. aggregates identical parallel directed links by summing capacity;
4. retains physical-link count and per-link capacity in edge metadata and in
   the topology audit;
5. keeps one fluid resource per directed endpoint pair.

This is strict-equivalent capacity aggregation for a fluid model.  It is not
an ECMP implementation and does not claim independent packet-level paths.

### Audited configurations

| topology | listed physical edges | directed physical edges | aggregate directed pairs | parallel leaf–spine pairs | oversubscription |
|---|---:|---:|---:|---:|---:|
| S2P4D / 6 servers | 96 | 192 | 104 | 8 | 1.000 |
| S16 / 8P8D / EP64 | 256 | 512 | 272 | 16 | 1.000 |
| S64 / 64 servers | 1024 | 2048 | 1056 | 32 | 1.000 |
| S256 / 256 servers | 4096 | 8192 | 4224 | 128 | 1.000 |

The S16 audit reports 32 endpoints per leaf, 6.4 Tbps aggregate endpoint
capacity per leaf, 6.4 Tbps aggregate leaf-to-spine capacity per leaf, and
16 physical links (3.2 Tbps aggregate) for each leaf-to-spine pair.  The
topology is therefore 1:1 at the aggregate leaf level, as configured.

Detailed machine-readable and Markdown audits are under
`results/topology_audit/`.

### Direct microcheck

For S16, the corrected backend reports:

```text
leaf 128 -> spine 132: physical_link_count=16, capacity=3200 Gbps
endpoint 0 -> leaf 128: physical_link_count=1, capacity=200 Gbps
parallel-link aggregate capacity check: PASS
```

### Remaining backend limitation relevant to P1

The corrected FlowSim backend still uses one BFS path over aggregate directed
pairs for each `(src, dst)` endpoint pair.  The Clos has two logical spine
choices between distinct leaves, but the current fluid backend selects one of
them; parallel physical links are represented as aggregate capacity.  This is
acceptable for the first P1 placement screen only if a placement changes the
actual endpoint/leaf paths or receiver-side cut.  It must not be described as
path-aware ECMP.

## P1: topology-induced exposed barrier contention

P1 is now being prepared with an explicit offline placement-map hook in
`scripts/build_model_derived_replay.py`.  A placement map is a bijection from
prefill instance IDs to decode instance IDs.  It changes neither request
arrival times, source prefill instances, model-derived KV bytes, GateRouter
EP bytes/routes, topology, nor decode compute anchors.  The default behavior
remains `DEFAULT_RR` when no map is supplied.

`scripts/generate_p1_placements.py` generates:

- `DEFAULT_RR`;
- `LOAD_ONLY` (same matched mapping in the current balanced cluster);
- a deterministic random permutation;
- `MIN_OVERLAP_ORACLE` (leaf-aligned characterization bound);
- `MAX_OVERLAP_ORACLE` (leaf-crossed characterization bound).

The two oracle maps are offline bounds, not an online placement algorithm and
not a proposed final design.

P1 network-only runs will be used only for discovery.  Their
`ttft_data_plane_proxy` remains a lower-level replay anchor, not integrated
TTFT.  A P1 result can pass the motivation gate only after a matched
placement difference is reproduced in integrated serving and propagates to
TTFT/TBT/SLO.

## Evidence status

| priority | status | reason |
|---|---|---|
| Correctness Gate | **PASS** | Parallel capacity is retained and audited; direct aggregate-capacity microcheck passes. |
| P1 placement × exposed barrier | **FAIL (initial screen)** | Two real trace windows changed the P2D leaf geometry, but no >=20% network/serving gap appeared; integrated serving was not justified because the network-only gap was already small. |
| P2 last-shard amplification | **FAIL (initial screen)** | Legal alternate-spine/offline striping controls did not change request-level last-shard FCT on BurstGPT or Mooncake windows; no barrier headroom was observed. |
| P3 receiver-side incast | **FAIL (initial screen)** | 4-instance fan-in changed EP CCT P99 by 10.9% and KV FCT P99 by 0.07%; the 1-instance fan-in upper bound changed EP CCT strongly but still changed KV FCT/TTFT proxy by <1%. |
| P4 barrier-aware multipath | **FAIL (initial screen)** | Current BFS versus alternate-spine/round-robin path controls did not change KV FCT P99 or request barrier tails. |
| P5 EP realization / route geometry | **NETWORK-LEVEL CANDIDATE; SERVING GATE INCONCLUSIVE** | Same-byte GateRouter versus uniform peer realization changed EP CCT P99 by about 79%; the S64 integrated follow-up was stopped before producing a result, so no serving PASS is claimed. |

No serving-level PASS is claimed by this file yet.

## P1 initial matched screen (corrected topology)

The first screen used S16 / 8P8D / EP64 / 200 Gbps, Qwen3-30B-A3B,
LAYERWISE P2D, GateRouter-derived EP traffic, and the same 64 requests for
all maps.  The placement map changed only the P/D instance pairing.  All maps
generated exactly 3,099,230,208 P2D bytes and 29,219,094,528 EP bytes for the
BurstGPT window; the Mooncake window generated 70,211,862,528 P2D bytes and
73,010,774,016 EP bytes.

| trace window | placement comparison | KV FCT P99 | EP CCT P99 | network-only observation |
|---|---|---:|---:|---|
| BurstGPT 60s window 074181, 64 requests, 4x arrival rate | DEFAULT_RR vs MAX_OVERLAP_ORACLE | 23.741 vs 23.741 ms | 106.508 vs 106.508 µs | no difference at reported precision |
| BurstGPT 30s window 148335, 64 requests, 4x arrival rate | DEFAULT_RR vs MAX_OVERLAP_ORACLE | 16.990 vs 16.990 ms | 98.644 vs 105.660 µs | +7.1% EP CCT for crossed leaf map |
| Mooncake conversation 60s window 000036, 64 requests | DEFAULT_RR vs MAX_OVERLAP_ORACLE | 933.265 vs 933.265 ms | 363.895 vs 380.829 µs | +4.7% EP CCT; no KV FCT change |

The Mooncake run used a 5 ms EP aggregation only to keep the 37.1万-flow
discovery replay bounded.  After fixing the aggregation reader to preserve
`active_request_ids`, all 64 requests retained nonzero request-level EP CCT
provenance.  This result is valid for fluid discovery, but not a packet-level
queue result.

### Why this P1 screen failed

The crossed map does change P2D paths: P2D from Leaf0 is sent to Decode Leaf3
instead of Decode Leaf2.  However, the EP64 collective is a single symmetric
decode pool spanning both Decode leaves.  Its GateRouter-derived traffic
therefore puts nearly the same aggregate EP demand on both Decode leaf
ingresses.  Swapping the P2D demand between those leaves changes which of two
symmetrical cuts is used, but not the demand geometry seen by the collective
barrier.  The observed differences (0–7.1% EP CCT and 0% KV FCT) are below the
motivation gate and are not evidence for a serving-level PASS.

This is a mechanism-driven FAIL for the tested P1 realization, not a claim
that every topology-aware P/D placement is uninteresting.  The current
single-BFS FlowSim route also selects one logical spine rather than modeling
ECMP; introducing ECMP here merely to create a placement gap would violate the
correctness gate.  P2 is therefore the next priority, because it tests the
request-level last-shard barrier without changing the model-derived traffic.

## P2 initial last-shard screen

P2 used the same corrected S16/EP64 ledger and compared three path controls:

- `CURRENT_BFS`: current backend's one shortest path per endpoint pair;
- `ALT_SPINE`: the other legal shortest Clos spine for cross-leaf P2D flows;
- `ECMP_ROUND_ROBIN`: deterministic round-robin over the two legal shortest
  logical spine choices.

The event ledger, model-derived bytes, request arrivals, source/destination
endpoints, and layerwise shard count were unchanged.  The path annotations are
offline characterization controls; they do not claim that FlowSim has packet
ECMP, and FlowSim queue values remain residual fluid backlog.

| workload | traffic | KV FCT P99, current | KV FCT P99, alternate/striped | last-minus-median completion gap P99 |
|---|---|---:|---:|---:|
| BurstGPT 60s window 074181, 64 requests, 4x | KV_ONLY | 23.741 ms | 23.741 ms | 11.587 ms in all three modes |
| BurstGPT 60s window 074181, 64 requests, 4x | FULL + FAIR | 23.741 ms | 23.741 ms | unchanged |
| Mooncake conversation 60s window 000036, 64 requests, 1x | KV_ONLY | 933.265 ms | 933.265 ms | 455.353 ms in all three modes |

The nonzero last-minus-median gap confirms that request completion is a max
barrier rather than a sum of flow delays.  However, the route controls did not
change the max barrier.  The reason is structural in these runs: the S16
fabric is 1:1 at the aggregate leaf level, each endpoint has a 200-Gbps
dedicated link, and the two spine choices have equal capacity.  Moving a P2D
flow between equivalent spines changes the link identity but not the service
rate of the last shard.  The Mooncake long-context case increases absolute
FCT, but it does not create a routing-seed-dependent tail.

P2 is therefore a FAIL for the tested legal path variation, not evidence that
last-shard barriers are semantically unimportant.  The barrier exists and is
visible in the completion gap, but this non-oversubscribed topology does not
provide >=20% routing headroom.  Creating a collision by lowering bandwidth,
adding delay, or forcing an arbitrary path would not be a valid motivation.

## P3 initial receiver-fan-in screen

P3 changed only the destination Decode instance of P2D flows, preserving TP
shard correspondence (source TP rank maps to the same TP rank in the selected
Decode instance).  EP rows, request arrivals, layerwise bytes, and source
instances were unchanged.  The workload was Mooncake conversation window
000036, 64 requests, S16/EP64/200 Gbps, with a trace-faithful 4x arrival-rate
scaling for the pressure screen.

| P2D destination population | KV FCT P95 | KV FCT P99 | EP CCT P99 | replay TTFT proxy P99 |
|---:|---:|---:|---:|---:|
| 32 Decode instances (spread) | 384.795 ms | 933.317 ms | 0.421 ms | 957.669 ms |
| 4 Decode instances (fan-in) | 385.427 ms | 933.317 ms | 0.467 ms | 957.669 ms |
| 1 Decode instance (offline upper bound) | 385.427 ms | 934.014 ms | 3.010 ms | 958.365 ms |

The four-instance fan-in is the relevant realistic screen: it increases EP
CCT P99 by about 10.9%, but KV FCT P99 changes by less than 0.1% and the
replay TTFT proxy is unchanged at the reported precision.  The one-instance
case is an intentionally strong upper bound: it increases EP CCT by more
than 7x, yet KV FCT P99 and the lower-level TTFT proxy still change by less
than 1%.  This is consistent with the serving semantics already established:
the P2D flow is released nonblocking, and handoff is controlled by the final
KV shard, not by the sum of all destination-side traffic.  A large EP delay
does not automatically delay TTFT when the request's last KV shard is already
complete.

P3 is therefore a FAIL for the required serving-visible motivation gate.  The
experiment does confirm a network-only receiver-side EP effect, but it does
not provide the required TTFT/handoff headroom.  Promoting the one-instance
upper bound to a paper result would be misleading because it is not a
balanced P/D deployment and still lacks integrated serving propagation.

## P4 initial barrier-aware multipath screen

P4 is covered by the corrected-topology `CURRENT_BFS`, `ALT_SPINE`, and
`ECMP_ROUND_ROBIN` controls from the P2 screen.  They changed legal path
identity while preserving all bytes and request timing.  On BurstGPT and
Mooncake, request-level KV FCT P99 and the last-shard completion gap were
unchanged.  Because no network-level barrier headroom appeared in these
non-oversubscribed S16 controls, there is no basis for an integrated P4 PASS.
P4 is marked FAIL for this topology/backend realization rather than being
re-run with an artificial bottleneck.

## P5 supporting route-geometry screen

For the BurstGPT 60s window 074181, 64 requests, S16/8P8D/EP64/200 Gbps,
LAYERWISE P2D, the builder produced two EP ledgers with exactly the same
model-derived aggregate communication volume:

| realization | EP bytes | P2D bytes | EP CCT P99 | KV FCT P99 | replay TTFT proxy P99 |
|---|---:|---:|---:|---:|---:|
| GateRouter A2A_P2P | 29,219,094,528 | 3,099,230,208 | 0.1065 ms | 23.741 ms | 28.192 ms |
| Uniform peer A2A, same remote bytes per source | 29,219,094,528 | 3,099,230,208 | 0.1909 ms | 23.741 ms | 28.192 ms |

The uniform row is explicitly an offline same-byte counterfactual: each source
keeps the GateRouter-derived number of remote routed tokens, but distributes
those bytes uniformly over the non-self peers.  It does not invent bytes or
claim to model the native all-to-all implementation.  The roughly 79% EP CCT
gap demonstrates that peer-route geometry, not only aggregate EP volume, can
matter in the shared P2D/EP fabric.  It is useful supporting evidence for a
future route-geometry paper direction.

An S64 integrated FlowSim follow-up with the same 64-request BurstGPT window
and `A2A_P2P` versus `NATIVE_AG_RS` was started with compact logs, but made no
serving progress/output before it was stopped.  Both manifests are marked
`ABORTED`; no TTFT/TBT/SLO value was inferred from that attempt.  Therefore
P5 is not a PASS under the serving-level gate.  The network-only result must
be followed by a tractable integrated experiment before it can support a
CCF-A claim.

## Parallel-link capacity recheck

This recheck was required after the FlowSim topology audit found that a
leaf--spine pair in the S16 Clos contains sixteen physical 200-Gbps links.
The numerical tables in the earlier P1/P2/P5 sections are retained as
chronological discovery notes, but their BurstGPT `23.741 ms` values are
superseded by the current-backend rerun below and are not used for the
capacity conclusion.
The corrected FlowSim representation keeps one fluid resource for the pair
with capacity `16 * 200 Gbps = 3.2 Tbps`, while retaining the physical-link
count for audit.  This does **not** make a single GPU/NIC flow transmit at
3.2 Tbps: every endpoint still enters the fabric through its own 200-Gbps
endpoint link.  The 3.2-Tbps resource is available to the aggregate of
multiple flows crossing that leaf--spine bundle.  The model is capacity-
equivalent for a fluid bundle, but it does not model per-packet ECMP hashing
or individual physical-link packet queues.

The recheck used two different classes of topology.  The original small
motivation topology
`configs/ns3/two_prefill_6_rank_shared_spine.txt` has 7 listed physical edges,
14 directed edges after reverse materialization, and zero parallel pairs.
Consequently, `AGGREGATE` and `SINGLE_PHYSICAL_LEGACY` are exactly the same
model for that topology.  The original large/small layerwise motivation
numbers are therefore not caused by the later 3.2-Tbps aggregation fix:

| workload | policy | KV FCT max/P99, aggregate | KV FCT max/P99, legacy | EP CCT max/P99, aggregate | EP CCT max/P99, legacy |
|---|---|---:|---:|---:|---:|
| small KV | FAIR | 0.280172 ms | 0.280172 ms | 0.104877 ms | 0.104877 ms |
| small KV | EP_FIRST | 0.280172 ms | 0.280172 ms | 0.095872 ms | 0.095872 ms |
| small KV | KV_FIRST | 0.253159 ms | 0.253159 ms | 0.347531 ms | 0.347531 ms |
| large KV | FAIR | 16.485118 ms | 16.485118 ms | 0.127330 ms | 0.127330 ms |
| large KV | EP_FIRST | 16.485116 ms | 16.485116 ms | 0.095872 ms | 0.095872 ms |
| large KV | KV_FIRST | 16.107628 ms | 16.107628 ms | 12.895746 ms | 12.895746 ms |

The same table also confirms the original small experiment's qualitative
observation: in the small-KV point, FAIR/EP_FIRST KV FCT is 10.67% above the
KV_ONLY value, while EP_FIRST protects the EP collective.  That observation
survives unchanged because no parallel bundle exists in that topology.

The S16/8P8D/EP64/200-Gbps BurstGPT 64-request replay is different.  Its
topology has sixteen physical links per directed leaf--spine pair, so the
legacy sensitivity deliberately collapses each pair to 200 Gbps.  The valid
aggregate replay produced:

| policy/control | KV FCT P99 | EP CCT P99 | comparison |
|---|---:|---:|---|
| KV_ONLY | 28.174421 ms | -- | KV baseline |
| EP_ONLY | -- | 0.098644 ms | EP baseline |
| FULL + FAIR | 28.174421 ms | 0.106508 ms | KV +0.00%; EP +7.97% |
| FULL + EP_FIRST | 28.174421 ms | 0.098644 ms | KV +0.00%; EP +0.00% |
| FULL + KV_FIRST | 28.174421 ms | 0.230031 ms | KV +0.00%; EP +133.19% |

For reference only, the intentionally under-capacity legacy sensitivity for
the same 64-request replay gave 28.224392 ms for KV_ONLY and FULL+FAIR, but
3.968832 ms EP CCT for FULL+FAIR.  It is not a physical S16 result and must
not be used as a motivation number.

The previously reported `32 active Decode + 64 concurrent P2D` network-only
point requires an additional correction.  Its original event ledger was not
preserved; only completed flow ledgers were retained.  A diagnostic recovery
replay reconstructed the requested flow records from those ledgers, without
claiming a new source trace.  Under the old under-capacity interpretation it
reproduced the historical values `FULL+FAIR = 318.116 ms` and
`KV_ONLY = 257.718 ms`, i.e. `+23.44%`.  With the S16 aggregate capacity,
the recovered same flow records gave `FULL+FAIR = 46.192 ms` and
`KV_ONLY = 46.192 ms`, i.e. `0.00%` KV slowdown; `FULL+EP_FIRST` also remained
46.192 ms.  This shows that the former KV-critical result was caused by the
missing parallel-link capacity, not by a robust S16 serving phenomenon.  It
is retained only as an audit of the old result, not as valid evidence for a
paper claim.  A future re-test of that workload must be generated from its
original request/event builder and saved as a new native aggregate ledger.

### Capacity-recheck conclusion

The 3.2-Tbps aggregation does not invalidate the earliest small motivation
experiment, because that topology has no parallel leaf--spine links.  It does
invalidate the earlier S16 high-pressure claim that KV was measurably slowed
by EP under the corrected topology: after restoring the sixteen physical
links, the tested KV handoff is endpoint/barrier limited rather than
leaf--spine-bundle limited.  The robust result that remains is the EP-side
asymmetry: KV_FIRST can substantially hurt EP, while EP_FIRST protects EP in
the valid aggregate model.  The prior `EP_FIRST -> KV +23.44%` S16 result is
not a valid current result.
