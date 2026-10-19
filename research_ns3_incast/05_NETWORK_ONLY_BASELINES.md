# Network-only request ordering and headroom

## Matched fixed-byte experiment

`RC_FULL4_cc0` and `ORDER8P2MS_cc0` use the same four requests, same eight
required TP2 shard flows, same endpoint pairs, same 1,610,612,736 application
bytes, same topology and packet settings. The only change is fixed event issue
time: FULL releases all messages at time zero; ORDER releases each request's
two-rail bundle every 8.2ms.

| Metric | Simultaneous FAIR | 8.2ms bundle pacing | Change |
|---|---:|---:|---:|
| Mean absolute P2D-ready from t=0 | 32.481310ms | 20.451317ms | −37.04% |
| Makespan / last request ready | 32.481557ms | 32.751317ms | +0.83% |
| Peak receiver egress queue | 3,148,584 B | 4,132 B | queue removed between bundles |
| Local ECN first marks | 391,792 across both rails | 0 | no threshold crossing |
| CC1 CNP/rate effects in matched CC1 replay | Present under simultaneous FULL | None under pacing | no congestion signal when not congested |

This is a network-only fixed-timestamp coflow/pacing baseline. It redistributes
completion time toward earlier requests and slightly worsens the last request;
it is not an online scheduler, a Serving-scheduler decision, or an end-to-end
gain. With equal-size jobs, SJF/SRPT is a tie. The ideal non-preemptive
single-cut order has 37.5% mean-completion improvement and unchanged
makespan; the packet pacing result is close to that mean bound.

## Baseline coverage and limits

| Baseline | Status | Why |
|---|---|---|
| Simultaneous FAIR | **Run** | Native ns-3 equal-priority competing RDMA QPs. |
| Fixed request-bundle pacing/order | **Run** | 8.2ms spacing; offline issue timestamps, not signal driven. |
| Ideal network-only request order | **Calculated** | Independent single-cut upper bound; no implementation claim. |
| SRPT | **No distinct run** | All four request shards are equal size, so SRPT reduces to a tie/order choice. |
| Per-request hardware priority | **Not run** | Current class policy has only KV-vs-EP distinction; it cannot give same-class KV requests separate priority. |
| Online coflow on completion callback | **Not run** | Current fixed replay schedules all timestamps up front; no completion-to-new-flow controller. |
| Serving-local best order | **Not run** | The tested workload has one active Prefill request on each of four separate Prefill instances and no alternative ready request/work item. |

For this fixed set, the network-only baseline already captures the available
mean-ready reordering benefit. The layerwise profile replay has a different
result: packet completions occur during Prefill computation, and latest KV
readiness precedes compute completion even under CC1. Thus the 37% network-only
mean number must not be translated into TTFT/TBT or into a network-feedback
Serving opportunity.
