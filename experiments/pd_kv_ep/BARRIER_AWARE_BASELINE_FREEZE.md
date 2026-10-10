# Barrier-aware packet baseline freeze

Date: 2026-10-08
Repository revision: `a4053bc1161872420e1e0607cb3409ef659b828e` (`main`)
Status: corrected ACK/data priority semantics; matched ns-3 controls complete. This is a fixed-issue-time network replay, not packet-feedback serving.

## Scope and immutable interpretation

This freeze covers the 16-request Azure 2024 window `16812` on the 1:1 P:D shared-NIC topology, Qwen3-30B-A3B-Instruct-2507, 48 layers, TP2, EP32, LAYERWISE P2D, 4-KiB packet payload, and physical scale-out links of 200 Gbps. There are 8 servers (4 Prefill + 4 Decode), 64 GPU ranks, 16 NIC endpoints, four GPU ranks per NIC, and a 4-leaf/2-spine Clos with two parallel 200-Gbps physical links per leaf/spine pair. The switch shared buffer is configured as 32 MiB. At a 200-Gbps port, ECN uses Kmin=600,000 B, Kmax=2,400,000 B, and Pmax=0.2.

The policy mapping under test is:

| Traffic | Host/switch treatment | Data-plane accounting |
|---|---|---|
| ACK/NACK, CNP, PFC | Dedicated control queue q0; ACK/NACK promoted with `ACK_HIGH_PRIO=1` | Reserved control path; q0 intentionally bypasses ordinary data MMU/ECN |
| Policy-selected data (KV under KV_FIRST, EP under EP_FIRST) | q1, strict over ordinary data | Ingress/egress MMU admission, ECN and PFC eligible |
| FAIR/other data | q3 | Ingress/egress MMU admission, ECN and PFC eligible |

The NIC checks its separate ACK queue before data, then serves ready q1 data before q3. Switch q0 control priority does not imply that KV_FIRST occupies q0: it does not. The old experiments that placed policy data in q0 are invalid for congestion/ECN interpretation and are excluded from every result below.

## Matched replay and controls

All three policy replays use the same 171,507 model/request-derived issue events and complete. The matched-control replays suppress the opposite traffic class while preserving issue timestamps, event identity, source-port progression, endpoints and packet-derived path. Exact flow/path/link-set matching passed for 1,536/1,536 KV flows and 169,971/169,971 EP flows.

| Replay | Result directory | Wall time | Retained class |
|---|---|---:|---|
| FULL / FAIR | [`ns3_ack_reserved_fair`](./results/shared_nic_4p4d_ep32_azure16/ns3_ack_reserved_fair/) | 329.23 s | KV + EP |
| FULL / EP_FIRST | [`ns3_ack_reserved_ep_first`](./results/shared_nic_4p4d_ep32_azure16/ns3_ack_reserved_ep_first/) | 330.42 s | KV + EP |
| FULL / KV_FIRST | [`ns3_ack_reserved_kv_first`](./results/shared_nic_4p4d_ep32_azure16/ns3_ack_reserved_kv_first/) | 329.45 s | KV + EP |
| KV_ONLY | [`ns3_ack_reserved_kv_only_retry`](./results/shared_nic_4p4d_ep32_azure16/ns3_ack_reserved_kv_only_retry/) | 265.07 s | KV |
| EP_ONLY | [`ns3_ack_reserved_ep_only`](./results/shared_nic_4p4d_ep32_azure16/ns3_ack_reserved_ep_only/) | 70.04 s | EP |

The first KV_ONLY attempt in `ns3_ack_reserved_kv_only/` was partial and is not used. The complete retry above is authoritative. The compact matched analysis is in [`matched_control_summary.json`](./results/shared_nic_4p4d_ep32_azure16/ns3_ack_reserved_analysis/matched_controls/matched_control_summary.json); policy attribution is in [`ep_collective_policy_summary.json`](./results/shared_nic_4p4d_ep32_azure16/ns3_ack_reserved_analysis/ep_policy_attribution/ep_collective_policy_summary.json).

## Frozen network results

Traffic volume: 4,904,386,560 model-derived P2D bytes across 1,536 shards (96/request), and 696,201,216 model/routing-derived EP bytes across 169,971 P2P flows / 5,280 collectives. P2D is 7.04x EP payload in this window. No byte override was used.

| Scenario | KV shard FCT mean / P99 (µs) | Request KV handoff mean / P99 (ms) | EP CCT mean / P99 (µs) |
|---|---:|---:|---:|
| KV_ONLY | 284.302 / 1,155.891 | 72.7804 / 117.3369 | — |
| EP_ONLY | — | — | 38.061 / 66.375 |
| FULL / FAIR | 284.876 / 1,155.891 | 72.7839 / 117.3424 | 38.461 / 66.724 |
| FULL / EP_FIRST | 284.887 / 1,155.891 | 72.7841 / 117.3426 | 38.067 / 66.379 |
| FULL / KV_FIRST | 284.307 / 1,155.891 | 72.7804 / 117.3369 | 71.339 / 635.865 |

Under FAIR, FULL vs KV_ONLY changes mean shard FCT by +0.574 µs (+0.176%) and mean request handoff by +3.516 µs; absolute handoff P99 changes by +5.579 µs (+0.00475%). FULL vs EP_ONLY changes absolute EP CCT P99 by +0.525%. These are the marginal effects for this one matched window, not universal estimates.

The request handoff is `last required shard completion - first P2D shard issue`, not the sum of shard FCTs. In this window, the mean layerwise release span is about 72.574 ms and the mean post-last-release drain is about 0.210 ms. All 16 requests' last shard is from the final exported layer position (ordinal 47); those exact-last shards account for 1.0417% of KV bytes. The observed handoff is therefore dominated by release timing and barrier slack, which can hide meaningful delays on early, noncritical shards.

Shard-size quartiles do **not** show that small shards are more sensitive to EP. Under FAIR, FULL vs KV_ONLY mean shard-FCT increases are approximately +0.065% in the smallest quartile and +0.383% in the largest. Under EP_FIRST vs FAIR the quartile mean effects are both negligible (+0.004% and +0.008%). These are layer/shard bins, not request-total-KV size classes. The only warranted conclusion is that this particular replay does not support the proposed “small KV is more EP-sensitive” claim.

## ECN and congestion-control validity

On the 64 physical 200-Gbps scale-out directed links, FULL/FAIR recorded 257,649 ECN-marked link-transmission observations out of 10,258,104 TX observations (2.51%). KV_ONLY recorded 258,114 / 9,583,104 (2.69%); EP_ONLY recorded zero marks. A transmitted packet can be counted on multiple hops, so these are link-TX observations, not unique packets or a request-level ECN probability. Maximum observed link utilization reached 1.0; maximum queue was 4,696,072 B (about 4.48 MiB). PFC pauses and reported drops were zero in these runs. The small FULL-vs-KV_ONLY ECN-count difference is not monotonic; one run per case cannot support a fine-grained ECN comparison.

Critical implementation caveat for **these five matched replays**: their copied config says `CC_MODE 12`, but the checked-in ns-3 RDMA receive/rate-control implementation has handlers for modes 1/3/7/8/10 and no mode-12 CNP rate-response path. ECN marks and control packets are observable, but these runs do **not** establish DCQCN/HPCC/TIMELY/DCTCP rate reduction. Interpret them as packet queueing + static data-priority experiments with marking telemetry, not as congestion-controller experiments. This is specific to this replay set: the repository separately contains a correct `CC_MODE=1` DCQCN study in [`PACKET_LEVEL_AUTONOMOUS_RESEARCH.md`](./PACKET_LEVEL_AUTONOMOUS_RESEARCH.md), and the same Azure ledger has since been rerun under mode 1 in [`DCQCN_MODE1_MATCHED_REPLAY_REPORT.md`](./DCQCN_MODE1_MATCHED_REPLAY_REPORT.md); do not conflate either mode-1 result with these historical mode-12 controls.

Each `send_flow` currently allocates a new source port/QP and completion deletes that QP. Therefore even after enabling a supported controller, any rate response is presently scoped to the active QP/flow unless the implementation explicitly models persistent QP reuse. Do not infer that one layer's CNP state slows the next layer's P2D flow without measuring or modeling that lifecycle.

## Serving-metric boundary

The ns-3 replay takes fixed communication issue times from the FlowSim event ledger. ns-3 completion is not fed back to the serving scheduler; hence these packet runs produce no valid policy-specific TTFT, TPOT, TBT, or SLO. Existing integrated FlowSim TTFT/TBT results are separate analytical-fluid results and must not be presented as ns-3 packet-level serving outcomes. Full provenance and this distinction are recorded in [`ACK_RESERVED_HIGH_CONCURRENCY_REPORT.md`](./results/shared_nic_4p4d_ep32_azure16/ACK_RESERVED_HIGH_CONCURRENCY_REPORT.md).

## Reproduction entry points

- Run configs and `network_run_manifest.json`: the result directories linked above.
- Analysis: [`analyze_ack_reserved_controls.py`](./scripts/analyze_ack_reserved_controls.py) and [`analyze_ns3_ep_policy_attribution.py`](./scripts/analyze_ns3_ep_policy_attribution.py).
- Detailed size/barrier analysis: [`KV_SIZE_X_CRITICALITY.md`](./results/shared_nic_4p4d_ep32_azure16/ns3_ack_reserved_analysis/kv_size_criticality/KV_SIZE_X_CRITICALITY.md).
