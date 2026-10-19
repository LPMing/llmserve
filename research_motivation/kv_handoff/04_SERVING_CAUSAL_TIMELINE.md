# Integrated Serving causal timeline

All times below are simulated milliseconds relative to request arrival at 0. The simulator's wall-clock runtime was about 43 s for each corrected run; these are simulated times, not wall-clock delays.

## One request, POST_PREFILL + FAIR

| Event | Time | Meaning |
|---|---:|---|
| first TP shard released | 13.497000 | Prefill rank 1 reaches its full-graph transfer marker |
| first shard completed | 17.533732 | 96 MiB flow; 4.036732 ms service+path |
| last TP shard released | 64.713000 | Prefill rank 0 reaches its marker |
| last required shard completed | 68.749732 | 96 MiB flow; request barrier closes |
| P2D ready / Decode eligible / admitted | 68.749732 | Decode capacity is available immediately |
| first visible token | 68.749732 | Prefill sampler result becomes visible after graph/send completion |
| second visible token | 71.376820 | first Decode-side token completion |
| TTST / first TBT / TPOT | 2.627088 | second visible token minus first visible token |
| request complete | 87.139348 | 8 output tokens accounted |

The handoff span is 55.252732 ms from first release to last completion, but only 4.036732 ms of post-last-release network drain. The remainder is primarily source-rank release skew.

## Four requests, POST_PREFILL + FAIR

All requests arrive at 0 and are routed RR to four distinct Prefill TP2 instances. Each has 2 × 96-MiB shards. Per request, the early shard is released at 13.497 ms and the later shard at 64.713 ms. On each of two independent rails, two requests' early shards share 200 Gbps, and their later shards share 200 Gbps.

| Event | Time | Meaning |
|---|---:|---|
| early-wave release | 13.497000 | two active 96-MiB flows per resource group |
| early-wave completion | 21.560264 | 8.063264 ms after release; per flow receives 100 Gbps under FAIR |
| late-wave release | 64.713000 | two active 96-MiB flows per resource group |
| all four last shards complete | 72.776264 | full request KV barrier closes |
| P2D ready / Decode admission / first visible token | 72.776264 | no Decode capacity wait |
| first EP dispatch | 72.818264 | 42 us after handoff, so no active EP overlaps P2D |
| first EP dispatch CCT | 16.099 us | collective-level last-peer completion minus start |
| first EP combine CCT | 10.856 us | collective-level last-peer completion minus start |
| second visible token / TTST | 75.403352 / 2.627088 ms | same Decode token latency as one-request run |
| request complete | 91.165880 | same output length and per-token timing |

All four per-request rows are identical. With n=4, the displayed percentile fields are merely descriptive; they are not robust tail estimates.

## Matched request effect and causal scope

Request 0 is matched between N1 and N4: same request length, arrival, Prefill instance, paired Decode instance, model bytes, source-rank anchors, and physical paths. Adding a second request to the same rail changes the last-wave service from one 96-MiB flow at 200 Gbps to two such flows under FAIR. Completion shifts from 68.749732 to 72.776264 ms, an additional 4.026532 ms or +5.8568% TTFT.

Thus a cross-request KV–KV shared-NIC/link slowdown propagates into this POST_PREFILL request barrier and TTFT. This does not show KV–EP overlap: the Decode EP starts only after all four handoffs. It also does not show that a policy can improve the maximum TTFT; the offline grouped replay leaves the maximum ready timestamp unchanged under the actual release skew.

`decode_first_batch_start_ns` is -1 in both request CSVs. `decode_first_batch_decision_ns` is the eligible/decision timestamp, not a measured start timestamp, and is not substituted here.
