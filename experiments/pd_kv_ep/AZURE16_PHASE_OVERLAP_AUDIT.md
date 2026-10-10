# Azure16 Phase-Overlap Audit

Status: completed characterization of an existing run. This is not a new workload and not a closed-loop packet-level serving run.

## Workload and topology

- Trace: Azure LLM Inference 2024 `code`, selected 30-second source window `016812`; the integrated serving ledger contains its first 16 requests in original order and arrival spacing.
- Model: Qwen3-30B-A3B-Instruct-2507, 48 layers, TP2, EP32, layerwise P2D KV, model/routing-derived traffic.
- Network: S8, 4 Prefill + 4 Decode servers, 4 GPUs per NIC (16 scale-out NIC endpoints), 200-Gbps physical NIC/leaf-spine links; ns-3 packet payload 4 KiB; telemetry period 100 us.
- Packet replay policy: FAIR, ACK/NACK/CNP/PFC reserved in q0, policy data in q1 and ordinary data in q3. The replay configuration uses `CC_MODE=12`; treat it as the frozen queue/ECN telemetry baseline, not DCQCN rate-feedback evidence.
- Source ledger: `results/shared_nic_4p4d_ep32_azure16/flowsim_fair_ledger/requests.csv`. The packet replay uses fixed FlowSim issue timestamps; ns-3 completions do not feed back into request scheduling.

## Request arrivals

Times below are milliseconds relative to the first request. A large gap separates the first five arrivals, the mid-window group, and the final two requests; this is not a uniformly populated steady-state cohort.

| Request IDs | Arrival times (ms) |
|---|---|
| 0–4 | 0.000, 0.224, 0.762, 0.997, 1.303 |
| 5–10 | 24.722, 25.467, 25.670, 26.006, 26.193, 26.360 |
| 11–12 | 30.049, 31.971 |
| 13–15 | 62.964, 64.381, 64.643 |

Total arrival span is 64.643 ms; median inter-arrival gap is 335.872 us, p95 is 25.691 ms, and the maximum is 30.993 ms. At most five arrivals occur in any 1-ms interval. The 16 requests contain 49,890 input and 198 output tokens. Thus the trace does have short arrival bursts, but its small output-token population cannot sustain a large Decode cohort.

## Activity and overlap

Activity is reconstructed from the integrated request ledger and packet replay flow events. Decode active means scheduler admission through request completion. “Warm Decode” begins after the fourth emitted token, using the first token timestamp plus the first three recorded TBT intervals; it is a request-level proxy for recurrent Decode, not per-token EP attribution. The serving CSV has no true Prefill-compute start, so `arrival -> prefill_completion` is only a Prefill lifecycle proxy and is not reported as compute-active time.

| Quantity | Result |
|---|---:|
| Time-weighted active Decode requests, p50 / p95 / max / mean | 3 / 7 / 9 / 3.51 |
| Time-weighted active P2D requests, p50 / p95 / max / mean | 0 / 5 / 10 / 1.12 |
| Active P2D flows, p50 / p95 / max / mean | 0 / 7 / 14 / 1.38 |
| Active EP flows, p50 / p95 / max / mean | 0 / 48 / 91 / 11.36 |
| Active EP collectives, p50 / p95 / max / mean | 0 / 2 / 2 / 0.64 |
| Decode lifecycle overlapping a different request's P2D | 68.231 ms |
| Warm Decode overlapping a different request's P2D | 35.163 ms |
| Warm Decode EP and another request's P2D overlap | 24.910 ms |
| KV/EP flow-lifetime overlap / union-active time | 17.44% |
| KV/EP flow-lifetime overlap / observation span | 13.15% |
| Same-directed-link flow-lifetime overlap wall time / observation span | 33.369 ms / 10.55% |

Dispatch and combine collective start periods both have p50 98.664 us and p95 148.333 us. Shared directed-link overlap spans 29 links. The same-link statistic uses exported flow-lifetime paths; it is not proof that packets from both classes occupied a link at the exact same instant.

## Queue episodes and barrier attribution

The switch queue trace is sampled every 100 us and emits only egress queues at or above 1,000 bytes. Episode duration is therefore a sampled estimate, not exact occupancy time. In the full replay, estimated p50/p95/max episodes are:

| Queue region | p50 | p95 | max | Episodes |
|---|---:|---:|---:|---:|
| Decode ingress | 100 us | 800 us | 2.2 ms | 361 |
| Leaf-spine cut | 200 us | 600 us | 2.6 ms | 508 |

These durations are not uniformly shorter than the ~99-us recurrent EP period: some sampled queue episodes span multiple EP periods. However, queue snapshots are not traffic-class attributed and do not by themselves prove an EP critical-path collision.

The matched FULL/KV_ONLY/EP_ONLY analysis found 5,280 collective rounds and 6,126 critical/near-last peer rows; 550 rows (8.98%) had a KV overlap under the analysis's path/time criterion. The critical-flow delta versus its isolated counterpart has median 0, p95 0.834 us, p99 15.623 us; the median collective straggler gap is 0.165 us (p99 0.515 us). Most EP rounds therefore have little exposed last-peer delay despite recurrent collectives and queue episodes.

## Matched packet/network controls

All 1,536 P2D flows and 169,971 EP flows match their isolated controls exactly in exported route/link identity.

| Metric | FULL FAIR | Isolated baseline | Difference |
|---|---:|---:|---:|
| KV shard FCT mean | 284.876 us | 284.302 us (KV_ONLY) | +0.20% |
| KV shard FCT p99 | 1.155891 ms | 1.155891 ms (KV_ONLY) | 0.00% at rounded absolute p99; paired ratio-distribution p99 +2.33% |
| Request-level KV handoff p99 | 117.342448 ms | 117.336869 ms (KV_ONLY) | +5.579 us, +0.00475% |
| EP collective CCT mean | 38.461 us | 38.061 us (EP_ONLY) | +1.05% |
| EP collective CCT p99 | 66.724 us | 66.375 us (EP_ONLY) | +0.525% |

The p99 of paired per-collective slowdown ratios is +39.0%, while the ratio of absolute p99 CCTs is +0.525%. These answer different questions: the former captures a small upper tail of paired rounds, while the latter compares the aggregate p99 quantile. Neither should be substituted for the other.

Full and KV_ONLY each reach a 4.696-MB maximum sampled queue; full has 257,649 ECN marks on the physical 200G links versus 258,114 in KV_ONLY, while EP_ONLY has no ECN marks. PFC pauses and drops are zero. With the frozen `CC_MODE=12`, these counters do not establish sender-rate feedback or class-specific queue causality.

## Phase-A conclusion

Azure16 is **not a no-overlap workload**: distinct requests naturally have mature Decode EP and layerwise P2D activity at once, and sampled queues sometimes persist across several EP periods. It is also **not a sustained high-population steady-state point**: active Decode averages 3.51 (max 9), active P2D averages 1.12 (max 10), and total output is only 198 tokens. The most defensible classification is:

`REAL_CROSS_REQUEST_OVERLAP + SAMPLED_QUEUE_EPISODES + WEAK_BARRIER_EXPOSURE`

Likely explanations supported by the telemetry are limited concurrency/duty-cycle, relatively rare critical-peer path/time overlap, and very small last-peer straggler gaps. Queue/class causality remains unproven. The result does not justify a policy or scheduler claim.

## Artifacts and caveats

- Activity timeline and queue episode extraction: `results/steady_state/azure16/full_fair/`.
- Matched controls: `results/steady_state/azure16/matched_controls/matched_control_summary.json` and associated CSVs.
- Network replay: `results/shared_nic_4p4d_ep32_azure16/ns3_ack_reserved_fair/`.
- Serving metrics come only from the FlowSim integrated request CSV. Packet replay results are network counterfactuals on fixed issue times, not packet-feedback TTFT/TBT.
- Queue telemetry is physical ns-3 MMU egress queue sampling. In contrast, FlowSim residual queues in later runs must be called analytical/fluid backlog, never switch packet occupancy.
