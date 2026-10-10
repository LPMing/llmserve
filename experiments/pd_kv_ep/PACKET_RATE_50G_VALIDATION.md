# 50G Packet-Level Rate Sensitivity Validation

## Scope

This document records the supplemental 50-Gbps experiment requested after the
historical 200-Gbps motivation attempts failed to expose a stable serving-level
opportunity.  The packet results are authoritative only for the completed native
ns-3 network-only replays listed below.  The integrated serving runs that timed
out are not used to fill or infer TTFT/TBT values.

The completed replay uses:

- Qwen3-30B-A3B-Instruct-2507 model-derived communication;
- S16/EP64 rank ledger (8 prefill and 8 decode servers in the S16 manifest,
  128 physical GPU endpoints, 1:1 P:D GPU ratio);
- LAYERWISE P2D events;
- GateRouter-derived A2A_P2P EP events;
- 4-KB packet payload;
- native ns-3 packet backend and its packet queue/ECN/PFC telemetry;
- the same event ledger, request set, timing anchors, and routing for 50G and
  200G controls;
- no synthetic byte override.

The 50G topology is a rate sensitivity configuration in which the endpoint and
scale-out links are explicitly 50 Gbps.  It is **not** a model of four GPUs
sharing one physical 200-Gbps NIC.  That alternative requires an explicit
shared-NIC resource in the packet topology and is a separate experiment.

## Completed model-derived packet replay

The replay contains four requests: three short Decode-cohort requests and one
8192-token KV-only request.  The builder generated:

| item | value |
|---|---:|
| request count | 4 |
| P2D bytes | 805,306,368 B |
| EP bytes | 1,157,627,904 B |
| P2D event count | 96 |
| EP event count | 5,888 |
| total event count | 5,984 |
| EP degree | 64 |
| packet payload | 4,096 B |
| policies | FAIR, EP_FIRST, KV_FIRST |

All four runs completed with 100% event coverage.  The network-only replay does
not report TTFT, TPOT, TBT, or SLO.

### Large-KV packet result

| rate / policy | EP CCT mean | EP CCT P99 | KV request FCT mean/P99 | ECN marks | PFC | drops |
|---|---:|---:|---:|---:|---:|---:|
| 200G / FAIR | 112.38 us | 112.25 us | 143.48 / 143.48 ms | 4,985 | 0 | 0 |
| 50G / FAIR | 324.79 us | 324.63 us | 144.50 / 144.50 ms | 50,495 | 0 | 0 |
| 50G / EP_FIRST | 324.50 us | 324.57 us | 144.50 / 144.50 ms | 318 | 0 | 0 |
| 50G / KV_FIRST | 427.09 us | 1,873.32 us | 144.50 / 144.50 ms | 49,535 | 0 | 0 |

Relative to 200G/FAIR, 50G/FAIR increases EP CCT P99 by approximately
189.2%, while KV FCT P99 increases by approximately 0.7%.  Within the 50G
case, KV_FIRST increases EP CCT P99 by approximately 476.5% over FAIR, while
EP_FIRST does not improve the EP P99 beyond FAIR for this particular packet
ledger.  This is a valid negative result for the claim that a static EP-first
priority always recovers the EP tail.

The largest directed-link overlap grows from about 12.05 ms at 200G to about
79.24 ms at 50G under FAIR.  The maximum residual packet queue is about 1.42
MB in both cases, while the maximum mean queue over links grows from about
1.45 KB to about 4.51 KB.  Queue values here are native ns-3 telemetry; unlike
FlowSim residual backlog, they may be interpreted as packet-level queue
telemetry.  No PFC pause or packet drop was observed in this bounded window.

## Small cross-request rate gate

A smaller three-request model-derived ledger contained 75.5 MB P2D and 191.5
MB EP bytes.  It completed in both rates:

| rate / policy | EP CCT mean | EP CCT P99 | KV FCT mean | KV FCT P99 |
|---|---:|---:|---:|---:|
| 200G / FAIR | 91.71 us | 92.20 us | 8.072 ms | 12.870 ms |
| 50G / FAIR | 314.05 us | 321.31 us | 8.140 ms | 12.943 ms |
| 50G / EP_FIRST | 313.83 us | 316.37 us | 8.276 ms | 12.949 ms |
| 50G / KV_FIRST | 314.06 us | 321.25 us | 8.105 ms | 12.934 ms |

This smaller case shows the same direction: EP is much more rate-sensitive
than the large KV request barrier.  Policy differences are small because the
window is short and the collective service time itself dominates.

## Integrated packet-serving boundary

The following are recorded as execution limits, not performance results:

- The original 4-request integrated 50G case with one 8192-token request
  produced packet events but initially failed in frontend shutdown due to an
  `IndexError` in `Controller.check_end()`.  That frontend bug was fixed.
- The next run reached the serving loop and exposed a second bug: a native DP
  padding batch has an empty `Batch.fired` list, while the noninteractive
  dispatch path unconditionally accessed `batch.fired[0]`.  The owner fallback
  now assigns such a dummy graph to the instance start rank.
- After these fixes, the same integrated 4-request case exceeded a 900-second
  bound at 50G.  It produced no completed serving CSV and is therefore not a
  TTFT/TBT result.
- A smaller integrated 3-request case exceeded 600 seconds, and even a
  one-request 128-token/32-output case exceeded 300 seconds.  A minimal
  8-token/1-output gate also exceeded 180 seconds.  These runs are all marked
  `TIMEOUT` and excluded from metric analysis.

The completed network-only replay is therefore the valid packet-level
alternative for rate sensitivity, while integrated 50G serving validation is
currently not computationally tractable with this native ASTRA/ns-3 path.

## Interpretation

The 50G experiments do not establish a new serving paper by themselves.  They
establish a useful packet-level boundary:

```text
lower endpoint/cut rate
    -> longer shared-link exposure and many more ECN marks
    -> much larger Decode EP collective tail
    -> only a small change in the last-completing large-KV request FCT
```

The result supports investigating an effective per-GPU rate below 200G, but it
does not justify claiming that 50G solves the prior motivation.  In particular:

1. `EP_FIRST` is not automatically beneficial in every 50G window; it was
   nearly identical to FAIR in the large-KV replay.
2. `KV_FIRST` can create a severe EP tail, especially at 50G, but this is a
   control-policy tradeoff already observed at higher level and is not yet a
   complete CCF-A contribution.
3. No integrated TTFT/TBT/SLO improvement is claimed from these packet replays.
4. A realistic shared-NIC experiment remains necessary if “50 Gbps per GPU” is
   intended to mean four GPUs sharing a 200-Gbps NIC rather than four
   independent 50-Gbps endpoints.

## Artifacts

- `results/packet_rate_sensitivity/replay_s16_cross3_200g/`
- `results/packet_rate_sensitivity/replay_s16_cross3_50g/`
- `results/packet_rate_sensitivity/replay_s16_largekv_200g/`
- `results/packet_rate_sensitivity/replay_s16_largekv_50g/`
- `results/packet_rate_sensitivity/replay_s16_largekv_50g_ep_first/`
- `results/packet_rate_sensitivity/replay_s16_largekv_50g_kv_first/`
- `results/packet_rate_sensitivity/analysis_cross3_policies/`
- `results/packet_rate_sensitivity/analysis_largekv_policies/`

The consolidated list of earlier failed or bounded research directions is in
`FAILED_RESEARCH_ATTEMPTS.md`.
