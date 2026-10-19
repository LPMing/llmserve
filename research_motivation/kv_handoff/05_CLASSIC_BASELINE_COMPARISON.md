# Fixed-resource network scheduling comparison

## Compared policies and scope

`analyze_handoff_replay.py` replays the actual P2D release anchors, model-derived shard bytes, source/destination endpoints, and saved topology. FAIR is the current persistent-fluid allocator. REQUEST_GROUPED prioritizes one request at a time on shared minimum-capacity links; its ordering is FIFO by request ID among equal arrivals. This is an offline network-only counterfactual, not an integrated scheduler implementation.

For this case all requests have equal total size and equal request arrival. Therefore request-level SRPT ties and uses the same request-ID tie break as FIFO; COFLOW_FIFO has the same ordering. There is no predeclared request deadline, so EDF is not run. EP_FIRST is inapplicable to this KV-only network replay, and no active Decode EP is present during P2D.

## Results

| Replay | FAIR mean handoff span | grouped/FIFO/SRPT/coflow mean | mean change | maximum/P99 ready |
|---|---:|---:|---:|---:|
| N1, one request | 55.252732 ms | 55.252732 ms | 0% | unchanged, 68.749732 ms ready |
| N2, two requests on one rail, actual releases | 59.279264 ms | 57.265998 ms | −3.396% | unchanged, 72.776264 ms ready |
| N4, two requests per each of two rails, actual releases | 59.279264 ms | 57.265998 ms | −3.396% | unchanged, 72.776264 ms ready |

For N4, mean absolute ready time falls by 2.013266 ms (2.766% of FAIR mean ready time), but the last request on each resource group remains at the same ready time. The simultaneous-release theoretical bound is larger (24.984% mean for two complete equal requests sharing one rail) but is not the observed release pattern and is not a Serving prediction.

## Interpretation

1. Flow-level FAIR does share service across requests, and with actual integrated release anchors it delays each same-rail request's last-wave shard relative to the one-request run.
2. A grouped order can let one selected request finish at its standalone-ready time in the network replay, but it transfers waiting to the other request. The completion maximum does not improve.
3. FIFO, SRPT and coflow-FIFO are indistinguishable here because request sizes/releases tie. No evidence supports a new priority formula.
4. Since the max handoff timestamp is unchanged, this experiment does not demonstrate P95/P99 Serving headroom. The n=2/4 maximum is only a tiny deterministic cohort statistic.
5. An integrated REQUEST_GROUPED run was intentionally not executed: the actual-anchor network-only gate did not improve the maximum and only changed mean network completion by 3.4%; the existing four-request Serving run also has no active EP background during the KV interval. Network-only completion deltas are not converted into TTFT/TTST.

## Gate outcome

Network-level request-order sensitivity: **observed, modest, with mean-only benefit**. A distinctive request-coflow scheduling opportunity: **not demonstrated**. Classic policies already produce the same replay ordering here. End-to-end sufficiency of an integrated classic scheduler is **not measured** and is not claimed.
