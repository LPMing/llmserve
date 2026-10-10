# Natural ECN Reproduction and Persistent-QP Gate

## Executive result

The original S8/16-request event ledger remains unavailable, so the historical run was **not exactly reproduced**. A new, complete candidate was generated from an integrated model-derived serving execution and replayed successfully in native ns-3 with the existing 200-Gbps topology and `CC_MODE=1` (DCQCN).

The new candidate naturally produced queue buildup, link-level ECN marks, CNPs, and DCQCN rate decreases. Exact QP-to-serving-event attribution found that all CNPs and rate decreases targeted **P2D KV QPs**; no Decode EP QP received a CNP or rate decrease. The required gate is therefore:

```text
NATURAL_CONGESTION_DOES_NOT_REDUCE_EP_QP
```

Per protocol, stop the persistent-EP-QP state-amplification branch here. Do not run persistent-vs-fresh EP-QP comparisons and do not increase load to hunt for an EP-QP CNP. This is not evidence that EP is immune to packet queueing; it says only that this reproduced operating point did not invoke DCQCN rate reduction on an EP QP.

## Historical S8 evidence and recovery

The archived historical summary records 16 requests, EP32, 200 Gbps, `CC_MODE=1`, 79,026 link ECN observations, 20,876 CNPs, 10,353 rate decreases, and a 3,243,620-byte maximum queue. The complete request schedule, 171,507 communication-event ledger, original replay input, per-QP CC telemetry, and queue outputs were not found in the checkout, Git history/unreachable objects, submodule, or inspected temporary artifacts. Those historical aggregate counters cannot identify which QPs received feedback and were not used to reconstruct traffic.

The new D8+K2 run below is a **new baseline**, not an exact recreation of the historical Azure16 workload. See [S8_ARTIFACT_RECOVERY_AUDIT.md](S8_ARTIFACT_RECOVERY_AUDIT.md) and [S8_NATURAL_ECN_BASELINE_AUDIT.md](S8_NATURAL_ECN_BASELINE_AUDIT.md).

## New model-derived candidate

| Item | Value |
|---|---|
| Topology | Corrected S8 4P+4D Clos; EP32; 8 servers × 8 GPUs; 4 GPUs share each 200-Gbps NIC; scale-out links 200 Gbps |
| Model | Qwen3-30B-A3B-Instruct-2507; native model/routing-derived communication |
| P2D | `LAYERWISE`, actual Decode receiver; 2 new requests × 8,192 prompt tokens, 5 ms inter-arrival |
| Decode background | 8 requests; 128 input / 64 output tokens; K injection derived from actual warmup events after all D requests were admitted and completed four token boundaries |
| K first arrival | 70.798649 ms; the second K arrives at 75.798649 ms |
| EP | EP32; GateRouter-derived `A2A_P2P`; balanced expert routing |
| FlowSim serving policy | FAIR; request routing RR; prefix cache disabled |
| Packet replay | Native ns-3; fresh QPs; `CC_MODE=1`; 4,096-byte payload; ACK high priority enabled; FAIR data traffic; same existing ECN/queue/link settings |
| Synthetic override | None |

The integrated FlowSim ledger contains **499,776** communication events: 1,536 P2D KV flows / 1,711,276,032 bytes and 498,240 EP flows / 2,040,791,040 bytes. Of EP traffic, 120,960 same-server events are local and do not enter the scale-out network. ns-3 replayed 378,816 network QPs: all 1,536 KV QPs plus 377,280 cross-server EP QPs. The cross-server EP QPs carried 1,545,338,880 bytes; the remaining 495,452,160 model-generated EP bytes were intra-server/local. The replay issued every scheduled network event; `suppressed=0`.

The detailed immutable input and output inventory, row counts, byte sizes, and SHA-256 hashes are in [BASELINE_MANIFEST.json](results/natural_ecn_baseline_v1/BASELINE_MANIFEST.json). The compact serving-side per-request table is [SERVING_METRICS_FROM_FLOWSIM.csv](results/natural_ecn_baseline_v1/attempts/s8_d8_k2_i8192_do64_gap5ms/SERVING_METRICS_FROM_FLOWSIM.csv). The complete network files remain under that attempt's `packet_input/`, `integrated_full/`, and `packet_fresh_cc1_rankfix1/` directories.

## Packet-level gate result

The QP join uses `(src rank, dst rank, source port, bytes, QP-start timestamp)` to match each ns-3 `QP_START` against the integrated communication `START`, then associates subsequent CNP/RATE records with that QP identity. **All 378,816 QP starts matched; unmatched starts and unmatched feedback were zero.** This is a traffic-class attribution from per-QP telemetry, not an inference from aggregate CNP counts.

| QP traffic class | Network QP starts | QP-start bytes | QPs with CNP | CNP events | RATE events | Rate-decrease events | QPs with rate decrease |
|---|---:|---:|---:|---:|---:|---:|---:|
| P2D KV | 1,536 | 1,711,276,032 | 721 | 5,134 | 2,514 | 2,420 | 721 |
| Decode EP | 377,280 | 1,545,338,880 | 0 | 0 | 0 | 0 | 0 |
| OTHER | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Thus 46.9% of this run's KV QPs received at least one CNP and all 721 of those QPs had at least one recorded rate decrease. No EP QP had either event. Link summaries reported **25,670 link ECN-mark events across 14 directed links**. This is the sum of final per-link mark counters; the cumulative time-series counter was not summed, avoiding repeated counting of prior marks.

Queue evidence is consistent with a real congestion episode: the maximum link/device queue was **3,636,160 B** (link 152, node 68→81); the switch-port monitor recorded **3,603,104 B** on node 68 port 6 at 81.4 ms. The replay's 200-Gbps `KMIN_MAP` value is 600 × 1,000 = **600,000 B** (the implementation multiplies configured Kmin/Kmax values by 1,000); `KMAX` is 2,400,000 B. PFC pauses and packet drops were both zero.

The mapped GPU/NIC metadata identifies node 68 as the shared NIC for Prefill server S02/P2; link 68→81 is its 200-Gbps leaf uplink. That heavily queued link carried P2D KV flows and no EP flows in the recorded flow paths. Separately, cross-class P2D/EP active intervals did overlap on marked directed links 169 (83→76) and 203 (84→83): respectively 45.802 ms and 46.598 ms, with peak simultaneous active-flow counts of 16 KV + 14 EP and 16 KV + 32 EP. This proves actual path/time coexistence in the replay, but does not prove that EP caused the large queue on link 152 or caused the observed KV QP feedback. The available run has no matched isolated replay, so it cannot quantify a causal KV-vs-EP slowdown.

Per-link ECN values and marked-link class/path intersections are in [NATURAL_ECN_PACKET_ANALYSIS.json](results/natural_ecn_baseline_v1/attempts/s8_d8_k2_i8192_do64_gap5ms/packet_fresh_cc1_rankfix1/NATURAL_ECN_PACKET_ANALYSIS.json); the required class table is [NATURAL_ECN_CNP_BY_CLASS.csv](results/natural_ecn_baseline_v1/NATURAL_ECN_CNP_BY_CLASS.csv).

## Integrated serving metrics — separate from packet replay

The following values come from the integrated **FlowSim scheduler run**, not from ns-3 packet completion. They are a single FULL/FAIR candidate run, not deltas against KV-only/EP-only controls, and no SLO thresholds were configured.

| Cohort | Requests | TTFT mean / P50 / P95 / P99 | TPOT mean / P50 / P95 / P99 | Token TBT samples; mean / P50 / P95 / P99 |
|---|---:|---|---|---|
| Existing Decode background (128 input, 64 output) | 8 | 49.988 / 49.988 / 49.988 / 49.988 ms | 6.843 / 6.843 / 6.843 / 6.843 ms | 504; 6.953 / 6.937 / 6.939 / 7.417 ms |
| New P2D cohort (8,192 input, 2 output) | 2 | 306.957 / 305.748 / 308.165 / 308.165 ms | recorded as 0 by the simulator for this two-token cohort; not interpreted as a zero-cost decode | 2; 11.629 / 10.420 / 12.837 / 12.837 ms |

For the two K requests, `arrival → p2d_kv_ready` was 295.328 ms. These numbers describe this FlowSim workload execution only. The subsequent ns-3 replay consumed its model-derived event issue schedule but did **not** send packet completion back to the serving scheduler; therefore the report makes no ns-3 TTFT/TPOT/TBT/SLO claim and no congestion-attributed serving-level claim.

The K cohort has only two requests, so its P95/P99 are simply the observed maximum under the nearest-rank convention and are descriptive, not statistically stable tail estimates. No SLO attainment is computed.

## Interpretation and decision

1. **Can a legal model-derived workload naturally generate ECN/CNP/DCQCN activity without network tuning?** Yes, for this new S8 D8+K2 candidate: the unmodified 200-Gbps replay produced queues above Kmin, 25,670 link ECN-mark events, 5,134 CNPs, and 2,420 rate decreases.
2. **Do recurrent EP QPs receive CNP and retain reduced DCQCN state?** The prerequisite is absent here: EP QPs received zero CNPs and had zero rate decreases. No persistence claim can be tested from this run. The prescribed branch outcome is `NATURAL_CONGESTION_DOES_NOT_REDUCE_EP_QP`; do not run persistent EP-QP variants.

This outcome is not `NATURAL_ECN_REGEN_FAIL`: natural congestion and KV DCQCN response did occur. It is also not a mechanism-wide proof that EP is unaffected by packet queueing. It closes only the **persistent EP-QP state-inheritance hypothesis at this candidate operating point**. Establishing whether EP collective completion changed would require a matched no-KV/network counterfactual, which is outside this gate and must not be inferred from CNP attribution alone.

## Reproduction commands and artifacts

The workload generator and replay conversion are documented in the candidate manifest. Re-run the class/path/queue analysis with:

```bash
python3 experiments/pd_kv_ep/scripts/analyze_natural_ecn_packet_run.py \
  experiments/pd_kv_ep/results/natural_ecn_baseline_v1/attempts/s8_d8_k2_i8192_do64_gap5ms
```

The first two aborted packet attempts had a topology endpoint bug (logical GPU ranks were remapped to intermediate NIC aggregation nodes without RDMA drivers). They are retained as debugging evidence and are **not results**. The successful `packet_fresh_cc1_rankfix1` run keeps rank endpoints on RDMA hosts and models NIC sharing through the configured GPU-to-NIC aggregation topology.
