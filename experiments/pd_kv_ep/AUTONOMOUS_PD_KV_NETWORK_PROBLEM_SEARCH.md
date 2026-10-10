# Autonomous PD KV Network Problem Search

## Baseline

Authoritative source: `results/natural_ecn_baseline_v1/attempts/s8_d8_k2_i8192_do64_gap5ms/packet_input`.
The immutable `events.csv` SHA-256 is
`5109434562416c911ec749a2e57f1eea682cab0f2e40659a306c30d2cbb6cb61`.

| Item | Frozen value |
|---|---|
| Model | Qwen/Qwen3-30B-A3B-Instruct-2507 |
| Cluster | S8: 4 Prefill + 4 Decode servers; 4 GPUs share each 200-Gbps NIC |
| MoE | EP32 |
| Serving requests | 8 Decode warm-up + 2 new 8192-token P2D requests; K spacing 5 ms |
| P2D | model-derived, LAYERWISE |
| Packet replay | 200 Gbps; 4096-byte payload; FAIR; CC_MODE=1 |
| Source events | 499,776 total; P2D 1,536 flows / 1.711 GB; EP 498,240 events / 2.041 GB, of which 1.545 GB crosses servers |

Packet replays hold the original serving-issued timestamps fixed. They do not
feed packet completion back to the scheduler and cannot produce integrated
TTFT, TPOT, or TBT.

## ECN semantics audit

See [`ECN_MARK_SEMANTICS_AUDIT.md`](ECN_MARK_SEMANTICS_AUDIT.md) for source
locations, exact mark provenance, and the standards-fidelity caveat.

- `link_summary.csv::ecn_marks` counts transmissions of packets carrying CE
  on each directed link; it is not a local mark count. A packet can be counted
  again at downstream hops.
- The 25,670 per-link CE observations represent 5,134 local non-CE→CE marking
  decisions propagated across links.
- Every local mark occurred on Prefill NIC uplink link 152 (`68→81`), a
  KV-only link. Requests 8 and 9 account for 2,812 and 2,322 marks
  respectively; the Decode warm-up cohort accounts for none.
- Links 169 and 203 had 5,134 and 1,368 carried-CE observations, but zero local
  marks. Their sampled peak queues (74,376 B and 53,716 B) were below Kmin
  600,000 B, so this is not contradictory.
- In this fork, data packets begin Not-ECT (`TOS=0`) and the switch changes
  Not-ECT→CE; the receiver then feeds nonzero ECN bits into ACK/CNP handling.
  This is a simulator-fidelity limitation. Conclusions below describe this
  fork's behavior, not standards-faithful RoCE ECN eligibility.

## Cross-class counterfactual — FINAL FAIL for this baseline

Matched FULL / KV_ONLY / EP_ONLY CC_MODE=1 runs use the same immutable event
ledger, topology, flow bytes, issue timestamps, and retained-flow routes. No
matched flow route mismatches were observed.

| Metric | FULL | Isolated control | Relative change |
|---|---:|---:|---:|
| EP peer-flow FCT P99 | 44.213 us | 44.213 us (EP_ONLY) | 0.00% |
| EP collective CCT P99 | 67.365 us | 67.364 us (EP_ONLY) | +0.0015% |
| All KV shard-flow FCT P99 | 1.602 ms | 1.386 ms (KV_ONLY) | +15.59% |
| K request 8 handoff proxy | 293.618 ms | 293.992 ms (KV_ONLY) | -0.127% |
| K request 9 handoff proxy | 293.488 ms | 293.607 ms (KV_ONLY) | -0.041% |

Within K request 8, shard-flow FCT P99 increased 64.18%; for request 9 it
increased 14.78%. Yet both request handoff proxies were slightly lower in FULL,
and the last required shard stayed on layer 472. The layerwise generation span
dominates handoff; isolated shard-tail changes are not exposed to this request
barrier. Therefore this is not a ≥10% cross-class barrier effect, much less the
target ≥20% paper motivation. Do not resume priority-policy sweeps from this
result.

Classification: `CROSS_CLASS_CONTENTION_FINAL_FAIL` for this frozen operating
point. This does not claim all topologies/workloads are universally contention
free; the current approved search now tests KV self-contention in the same
baseline rather than escalating load.

## KV self-contention — shard-level effect, request barrier hidden

Two new K requests have IDs 8 and 9, each with 384 model-derived P2D events.
The isolation implementation suppresses only the other request's P2D events
inside the native replay while retaining all 499,776 source events and
advancing the source-port counter for suppressed events. This preserves the
original issue schedule and route hashes for retained events.

Matched matrix, all from the same ledger and frozen packet settings:

| Run family | Retained traffic | CC mode | State |
|---|---|---:|---|
| FULL | all events | 1 | existing authoritative run |
| KV_ONLY | all P2D; EP suppressed | 1 | existing matched control |
| EP_ONLY | all EP; KV suppressed | 1 | existing matched control |
| K8_ISO / K9_ISO | all original traffic except other K request's P2D | 1 and 0 | complete |
| FULL / KV_ONLY | same respective traffic as above | 0 | complete |

Both CC_MODE=1 per-request isolation replays completed (221.66 s and 226.73 s).
Each retained the same 499,776-event source ledger and suppressed exactly the
other K request's 384 P2D events. All 384 target shards matched the FULL run
with zero path mismatches.

| Target request | Shard FCT mean, K2 → isolated | Shard FCT P99, K2 → isolated | Request handoff, K2 → isolated | Last-shard result |
|---|---:|---:|---:|---|
| K8 | 413.522 → 272.874 us (+51.5%) | 2.249 → 1.117 ms (+101.3%) | 293.618 → 293.606 ms (+11.637 us, +0.0040%) | same layer 472 shard/path |
| K9 | 439.035 → 271.484 us (+61.7%) | 2.226 → 1.166 ms (+90.9%) | 293.488 → 293.529 ms (−41.312 us, −0.0141%) | same layer 472 shard/path |

Combined K2 produces more local CE/CNP and rate reductions than isolation:
K8 has 2,812 CNP / 1,193 rate decreases in K2 vs 1,145 / 734 isolated; K9
has 2,322 / 1,227 vs 1,166 / 734. This confirms a real K-vs-K shared-Prefill-NIC
load/feedback effect at shard level. It does **not** translate to a handoff
penalty in this LAYERWISE workload: the sign is tiny and differs across the two
requests.

Per-shard attribution on isolated K8 shows 383/384 shards finish by the time
the final-layer shards are released. 360 shards are CNP-hit and rate-reduced,
yet their mean slack to the request's last completion is about 165.5 ms. The
last required layer-472 shard is itself CNP-hit/rate-reduced, but its CC_MODE=1
completion is 246.155 us. Thus DCQCN does affect a barrier-critical shard, but
the measured absolute increase over CC_MODE=0 for that shard is only 119.677 us
and the request handoff increase is 0.0408%. The CC_MODE=0 paired replay still
has CNP observations but no rate decreases, as intended by the current fork.

For clarity, `CC_MODE=1` is the DCQCN configuration. `CC_MODE=0` is not another
DCQCN mode and is not used as a realistic deployment result: it is a matched
ablation that disables DCQCN rate feedback while keeping the same event ledger,
packet paths, and offered traffic. The fork still records incoming CNP/ECN-
related events at CC_MODE=0, but it emits zero `RATE_DECREASE` events.

| Comparison | Request | Handoff change | Shard-flow FCT P99 change | Interpretation |
|---|---:|---:|---:|---|
| FULL CC1 vs FULL CC0 | K8 | +131.314 us (+0.0447%) | 2.249 vs 0.279 ms (about 8.1×) | DCQCN stretches shard tail, not request barrier |
| FULL CC1 vs FULL CC0 | K9 | 0 us (0%) | 2.226 vs 0.265 ms (about 8.4×) | same barrier masking |
| K8 isolated CC1 vs CC0 | K8 | +119.677 us (+0.0408%) | 1.117 vs 0.211 ms (about 5.3×) | feedback affects critical shard, small absolute delta |
| K9 isolated CC1 vs CC0 | K9 | +41.312 us (+0.0141%) | 1.166 vs 0.211 ms (about 5.5×) | small absolute last-shard effect |
| FULL CC1 vs K-isolated CC1 | K8 | +11.637 us (+0.0040%) | 2.249 vs 1.117 ms (+101.3%) | K2 worsens shard tail, not handoff |
| FULL CC1 vs K-isolated CC1 | K9 | −41.312 us (−0.0141%) | 2.226 vs 1.166 ms (+90.9%) | no request-level self-contention penalty |
| FULL CC0 vs K-isolated CC0 | K8 / K9 | +1.085 / +2.334 us (<0.001%) | P99 +1.03% / +1.02% | queueing-only K-vs-K effect is small here |

The CC1-vs-CC0 comparison confirms that DCQCN feedback amplifies shard-level
tails in this replay. It does not show a serving-critical amplification:
request handoff moves by at most 131.314 us (about 0.045%), and K2 vs
per-request isolation moves it by less than 0.02% in either direction. This
separates “DCQCN changes flow service” from “DCQCN changes the request barrier.”

## Flow-to-barrier and serving boundary

For every request, handoff is computed from the last required P2D shard
completion; `residual_drain = last_finish - last_layer_release`. These are
network replay barrier proxies, not a sum of shard FCTs. The two-K sample is
too small for a request-population tail distribution. A serving critical-path
estimate may only be labeled offline/oracle; integrated TTFT/TBT requires
packet-completion feedback to the scheduler, which is not part of these runs.

## Root cause assessment

1. CE/DCQCN trigger origin is KV self-contention at the shared Prefill NIC
   uplink, not an EP-generated mark on a shared KV+EP link.
2. Cross-class EP collective P99 is essentially unchanged in the matched
   packet replay.
3. Some KV shard FCT tails move substantially, but request handoff does not
   increase in FULL vs KV_ONLY because earlier layer release slack absorbs
   those delays.
4. Two simultaneous K requests create a real self-contention/DCQCN effect on
   shard FCT and CE/CNP activity, but it is hidden by layerwise release slack
   at the request max-shard barrier. The largest measured CC1-vs-CC0 handoff
   change is +0.045%, far below the 10% stop gate.
5. These are fixed-issue-time packet replays. They contain no scheduler
   completion feedback, so they do not produce integrated TTFT/TBT/TPOT. The
   handoff effect is already below the prescribed threshold; packet-to-serving
   feedback is not justified for this branch.

## Final decision for the frozen baseline

Generic bulk-flow contention, a high CE count, or a shard-level P99 change is
not sufficient motivation. A candidate must expose a causal resource/feedback
effect to the last-shard request barrier and have meaningful serving critical-
path headroom. The current work does not pass that gate. Cross-class EP effects
are negligible at the request/collective barrier; K-vs-K and DCQCN effects are
visible in per-shard FCT but remain below 0.05% at request handoff.
Classification: `KV_NETWORK_EFFECT_BARRIER_HIDDEN`. Per the agreed stop rule,
do not increase concurrency, alter workload, infer TTFT/TBT from network-only
measurements, or build packet-to-serving feedback for this baseline. This is a
scoped negative result for the immutable S8 operating point, not a universal
claim that all PD-MoE fabrics are contention-free.

Overall status for this study branch: `PD_KV_NETWORK_RESEARCH_FINAL_NO_GO` —
the tested cross-class and K-self-contention mechanisms show network-level
effects, but no stable request/barrier or serving headroom was found under the
frozen, model-derived 200-Gbps workload.
