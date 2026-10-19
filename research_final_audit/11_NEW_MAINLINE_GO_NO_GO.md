# 11 — New-mainline GO/NO-GO

## Decision for the evidence currently available

```text
SPARSE_A2A_MODEL_NOT_VALIDATED
```

The proposed new question—sparse MoE A2A route geometry and collective-tail
exposure—was selected after the old KV/EP flow-priority line reached
`FINAL_KV_EP_FLOW_SCHEDULING_NO_GO`. One bounded screen was run. Its apparent
same-byte CCT gap is invalid as motivation: the counterfactual changes expert
destinations/work, the effect is already present in EP_ONLY, the 48-layer
barrier is coalesced, and no serving completion feedback exists.

This is **not** a proof that sparse-A2A tail scheduling can never matter. It is
a no-go for advancing to an algorithm or paper claim on current evidence, and a
fail of this screen's semantic validity gate. The bounded task stops here; no
more load or request scaling is justified.

## Gate status

| Gate | Status | Reason |
|---|---|---|
| Correct route/expert work held fixed | `FAIL` | The “uniform” matrix assigns bytes to different destinations and changes expert work. |
| Faithful Decode EP barriers | `FAIL` | 48 layers are coalesced into one network phase per time bin. |
| P2D-specific interaction | `FAIL_FOR_THIS_SCREEN` | P2D changes only one of 336 exact phases by at most 1.341 µs and one of 336 counterfactual phases by at most 3.787 µs; P95/P99 delta is zero. |
| Integrated TTFT/TBT effect | `NOT_RUN / NOT_AVAILABLE` | Replay timestamps are fixed independently from network completions. |
| Packet-level confirmation | `NOT_RUN` | No ns-3/HTSim replay was run. |
| Novelty / algorithm headroom | `NOT_ESTABLISHED` | FAST and SwiftEP are strong prior art; no valid deployable comparator exists yet. |

## Stop/resume rule

Do not run an algorithm matrix, packet replay, or larger topology from this
artifact. Resume only if a bounded builder correction can emit actual legal
token-to-expert routes and independent per-layer/per-round dispatch/combine
barriers while preserving model work. Then one EP_ONLY/FULL pair and one
non-shared-cut negative control can decide whether there is a real P2D
interaction. If that prerequisite cannot be met, close the candidate as
unavailable in the current simulator.

## Overall status

Old KV/EP flow-priority line: `FINAL_KV_EP_FLOW_SCHEDULING_NO_GO`.

New sparse-A2A candidate: `SPARSE_A2A_MODEL_NOT_VALIDATED`.

Neither supports a GO-to-paper decision today.

