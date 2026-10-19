# Serving-barrier analysis

## Metric definitions used here

- Request KV handoff span: last completion among the request's required
  layerwise P2D shards minus the first required shard's request/start time.
  It is a request-level max-barrier interval, not the sum or mean of 48 shard
  FCTs.
- Post-last-release drain: last required shard completion minus release of
  the final required layer. This isolates the drain after layerwise producer
  release has ended.
- `p2d_kv_ready_time_ns`: absolute event timestamp when required P2D KV is
  ready at the Decode side. Candidate `TTFT` is a duration from arrival to
  first token; in this fixture `arrival + TTFT == p2d_kv_ready_time` for the
  one-token candidates.
- EP collective CCT: last peer completion minus collective start. It is a
  collective barrier metric, not an individual P2P flow latency.
- Token ITL/TBT: per-token intervals of the eight seed requests, which each
  produce 24 output tokens. There are 184 pooled intervals; samples within a
  request are correlated.

## KV chain: release → drain → readiness → TTFT

In the B workload, each 2048-token candidate transfers 201,326,592 model-
derived bytes in 48 layer shards; each 1024-token candidate transfers
100,663,296 bytes. Request handoff spans are about 73.66 ms and 56.89 ms,
while the drain after the last layer release is about 1.19 ms and 0.77 ms.
The candidate TTFTs are 74.468 ms and 57.757 ms under FAIR, EP_FIRST,
KV_FIRST, and EP_ISOLATED at the recorded precision. No Decode capacity queue
wait is observed.

This result fits the current layerwise serving semantics: each layer's KV
can be sent while later Prefill layers continue. Most transfer time is hidden
under producer/serving progress; only the final required KV readiness gates
Decode. Priority changes alter the measured post-release drain by only a few
microseconds, far below the 57–74 ms request path. The experiment therefore
does not establish a meaningful EP_FIRST→TTFT penalty.

The retained `kv_event_telemetry.jsonl` bounds the value of a request-targeted
KV oracle for this exact fixture. Grouping required `KV_COMPLETED` events by
request, the last transfer finishes 653.791 us before the Prefill completion
callback/`P2D_READY` for 2048-token candidates and 793.964 us before it for
1024-token candidates under FAIR. The gap remains positive under all three
class policies and the EP-isolated counterfactual. Since `add_decode()` is
called at the completed Prefill batch timestamp, the candidate is already
waiting for that later compute completion; advancing network service alone
cannot advance its first-token time. The maximum candidate TTFT gain from
reordering these KV flows is therefore 0 in this workload. This is an
event-derived upper bound, not an executed priority algorithm, and does not
bound network-FCT redistribution in other workloads.

## EP chain: shared service → collective barrier → token interval

The matched B run changes only the simulated class arbitration and keeps
requests, arrivals, model/profile, bytes, physical rank map and topology
fixed. Under KV_FIRST, recurrent EP collectives occasionally wait behind
KV-class service. The 4,416 collective records have mean CCT 39.029 us,
p99 1,326.375 us and maximum 1,493.615 us, compared with FAIR mean 11.031 us
and p99 12.464 us. This propagates into the integrated seed-request token
interval distribution: pooled ITL mean rises from 6.045367 ms (FAIR) to
8.733147 ms (KV_FIRST), and pooled p99 from 8.164016 to 46.827701 ms.

EP_FIRST reduces CCT p99 to 11.020 us and mean seed ITL to 6.008587 ms; its
ITL p99 remains 8.164016 ms. Thus the FlowSim event chain does reach the
Decode iteration/token path when the simulator's strict class policy
starves recurrent EP work. The magnitude is not evidence that all deployment
networks exhibit the same delay: this exact result still needs packet-level
priority/transport validation.

## Causal interpretation and limits

The controlled intervention (FAIR / EP_FIRST / KV_FIRST) is matched, and
collective completion is fed back into the integrated scheduler in this
worktree. This supports a causal statement within the FlowSim model:
KV_FIRST allocation delays the recurrent EP barrier, which delays seed
Decode token progress. It does not prove physical switch queue causality.

No request-targeted flow-priority replay or TTFT/TBT SLO experiment was run;
the zero-TTFT bound is derived from critical-path ordering, not from a
schedule simulation. The most defensible conclusion is a
class-level asymmetry: recurrent EP has high token-barrier sensitivity;
layerwise P2D KV has substantial release slack in this fixture.
