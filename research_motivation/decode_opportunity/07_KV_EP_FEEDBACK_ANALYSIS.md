# 07 — KV/EP feedback and shared-cut analysis

## What was actually shared

In the final map, each target request has two required model-derived KV shards of 100,663,296 B. For each request, one shard traverses a same-leaf path and one traverses directed link `12->13`. The Decode TP2/EP2 collective traffic traverses the cross-leaf fabric; flows on `12->13` therefore overlap with the P2D cut traffic. The reverse direction `13->12` carries EP traffic but not the target P2D flows. The ledger records both directions and the actual endpoint paths.

The EP implementation in this TP2/EP2 configuration is the simulator's `ALLGATHER`/`REDUCESCATTER` representation. It is not a GateRouter sparse A2A peer matrix. The result establishes a shared modeled cut for generated EP traffic, not a high-degree production MoE all-to-all result.

## Target-window fluid telemetry

The targeted telemetry window is 70.0–81.0 ms, with link IDs `12->13,13->12`. The durable data is in `ledgers/SHARED_LINK_TIMESERIES.csv` and `SHARED_LINK_SUMMARY.csv`. The measured link is fully allocated during intervals when active traffic traverses it; that does not mean it is continuously busy over the entire 11-ms wall-clock window. Under FAIR, the time fraction with both KV and EP active on `12->13` is about 0.955%; under EP_FIRST it is 0.421%; under the selected-request EP-then-KV control it is 0.535%. KV remains present much longer than the brief EP bursts.

During the FAIR target window, the link summary reports about 201,326,592 KV bytes and 1,213,952 EP bytes released on `12->13`. Time-weighted allocated rates over the link's recorded activity are about 24.85 GB/s KV and 0.15 GB/s EP. The P2D cross-cut flow takes 8.088567 ms from its release to the request barrier, compared with 8.054564 ms in the counterfactual with only KV network service: approximately 34 μs, or 0.42% additional handoff. This explains why EP has little measured effect on KV in this case: its active network bytes and overlap are small relative to the long KV shard.

| Policy on `12->13` | Both-class-active share of recorded event duration | KV bytes released | EP bytes released | Max residual fluid work (not a packet queue) |
|---|---:|---:|---:|---:|
| FAIR | 0.955% | 201.327 MB | 1.214 MB | 199.571 MB |
| KV_REQUEST_FIRST (request 3) | 48.698% | 201.327 MB | 0.922 MB | 199.571 MB |
| EP_FIRST | 0.421% | 201.327 MB | 1.218 MB | 199.571 MB |
| EP then request 3 | 0.535% | 201.327 MB | 1.387 MB | 199.571 MB |

The “both-active share” denominator is the captured link event coverage, not the full wall-clock experiment duration. The large residual-work value reflects remaining bytes in active fluid flows and must never be described as a 200-MB switch queue.

Under the request-KV-first policy, EP/KV overlap persists across about 48.7% of the selected event interval. Both active Decode groups have one collective delayed to about 3.907315 ms (the same global collective sequence/layer can appear in each independent instance's telemetry); both seed request rows therefore show a max EP CCT near 3.907 ms. Their one extreme interval raises max TBT to 8.543354 ms versus a low-load interval around 4.626624 ms. The nearest-rank P99 does not capture this one outlier among thousands of collectives; report mean, P99 and max together. This is a real simulator consequence of strict KV priority, but it is not evidence that all natural loads have this behavior.

For target request 3, EP CCT under FAIR is mean 1.630 μs / nearest-rank P99 1.757 μs / max 1.757 μs; under EP_FIRST and the request-3 opportunity control it is about mean 1.629 μs / P99 1.675 μs / max 1.675 μs. Under KV_REQUEST_FIRST the target's own EP groups remain around that level, but the two active seed groups each have one ~3.907-ms dispatch straggler. Looking only at target EP percentiles would hide collateral harm.

## Full DAG feedback

The offline `EP_THEN_KV_REQUEST_FIRST` policy first preserves active EP traffic, then gives all KV shards of one selected request precedence over other KV, and finally serves the remainder. In the request-3 variant, request 3 becomes Decode-active near the D0 slot release, so its subsequent EP rounds begin earlier while request 2's remaining P2D is still active. EP bytes released in the target window rise from about 1.214 MB under FAIR to 1.387 MB in this variant. Request 2's P2D handoff is 9.382 μs slower than FAIR; this is small (about 0.12%) and does not create a second large barrier penalty. This is the observed network-to-serving feedback in this setup, but not a material EP-feedback coupling result.

The KV_FIRST counterexample is more important than the weak feedback: selecting request 3 makes its KV-ready time earlier (74.905849 ms), but starves active EP collectives. D0 frees its slot only at 79.502411 ms (and D1's seed completes around 319.448 ms), so the target misses the 75.585681-ms opportunity and starts its first Decode batch at 79.502411 ms. Thus “KV ready sooner” is not equivalent to “serving progresses sooner”; active EP can control the downstream lane's availability.

## Interpretation and telemetry limit

FlowSim's `queue_bytes` is the sum of residual bytes of active fluid flows traversing a link. It is **not** physical switch-buffer occupancy, a packet queue, ECN, PFC or drops. Link allocation/utilization is analytical fluid telemetry. No packet-level backend was used in this phase.

The causal chain supported here is:

`request-group order -> P2D request barrier -> Decode capacity wait -> next batch start -> second-token/request-completion event`.

The EP feedback chain is weaker:

`earlier Decode admission -> earlier EP rounds -> small increase in concurrent EP bytes -> ~9 μs extra other-request KV handoff`.

No target-request TBT distribution or SLO attainment is established because each target has only one decode interval and the simulator lacks a client-visible callback at the sampler boundary.
