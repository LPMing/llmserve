# S8 Natural-ECN Baseline Audit

## Decision

**`S8_ECN_BASELINE_REPRO_FAIL` — exact replay was not run.** The archived summaries show that an S8, 16-request, `CC_MODE=1` replay previously completed and generated ECN/CNP/rate-decrease activity. However, the immutable communication-event inputs and the replay's detailed outputs are absent. Reconstructing an approximate event list from aggregate counts would violate the matched-workload requirement, so the fresh-vs-persistent EP-QP experiment is stopped at its reproduction gate.

This is an **artifact-availability failure**, not evidence that the historical baseline failed to congest or that persistent QP state has no effect.

## Archived experiment identity

| Item | Archived value |
|---|---|
| Scale / topology label | `S8_4P4D_EP32_SHARED_NIC` |
| Workload | 16-request `FULL` replay; model `Qwen/Qwen3-30B-A3B-Instruct-2507` |
| EP | EP32; 169,971 communication events; 696,201,216 bytes |
| P2D KV | 1,536 communication events; 4,904,386,560 bytes |
| Total | 171,507 events; 5,600,587,776 bytes across the two classes |
| Packet payload | 4,096 bytes |
| Endpoint/link profile | 200-Gbps scale-out links in the archived S8 topology |
| Topology file | `configs/large_scale/ns3/s8_4p4d_ep32_4gpu_per_200g_nic_200g_clos.txt` |
| CC mode | `CC_MODE=1` (DCQCN implementation selected by this replay configuration) |
| ECN threshold map | At 200 Gbps, archived config values are Kmin 600 KB and Kmax 2,400 KB |
| Other replay settings | `ACK_HIGH_PRIO=1`; 0.1-ms link telemetry interval; `BUFFER_SIZE=32` |
| Archived FAIR replay | `results/shared_nic_4p4d_ep32_azure16/ns3_cc1_fair/` |

The replay manifest reports `status=PASS`, exit code 0, 329.43 s wall time, 16 requests, 171,507 events, and 31,799 CC telemetry rows. Its source manifest says timestamps are requested network issue times and packet delivery/completion was recomputed by ns-3; it did not feed packet completions back into the serving scheduler. Thus archived handoff/CCT values are replay/network metrics, not integrated TTFT/TBT.

## Historical FAIR / CC_MODE=1 observations

These are **archived aggregate results, not a rerun in this validation**. Source: `results/shared_nic_4p4d_ep32_azure16/ns3_cc1_analysis/dcqcn_policy_summary.json`.

| Metric | Historical FAIR result |
|---|---:|
| Physical-link ECN-mark observations | 79,026 / 10,258,104 TX observations (0.7704% of observations) |
| CNP events | 20,876 |
| RATE events | 10,923 |
| RATE_DECREASE events | 10,353 |
| Maximum physical-link queue | 3,243,620 bytes (about 3.24 MB decimal) |
| EP collective CCT | mean 38.267 µs; P99 66.379 µs; 5,280 collectives |
| Request KV handoff | mean 72.961 ms; P99 118.275 ms; 16 requests |
| KV shard FCT | mean 0.791 ms; P99 3.342 ms; 1,536 shards |

The archived CC counters are aggregate across the replay. They do **not** identify which QP or traffic class received each CNP or rate transition. In particular, the 20,876 CNP count cannot be presented as an EP-QP CNP count. The archived outputs also do not establish whether the historical EP-QP lifecycle was fresh-per-message in the exact sense required for this new matched comparison.

## Exact replay inputs and output availability

The archived source manifest records the intended inputs:

- Schedule: `results/shared_nic_4p4d_ep32_azure16/flowsim_fair_ledger/requests.csv` — **missing**.
- Flow issue ledger: `astra-sim/inputs/runs/shared-nic-4p4d-ep32-azure16-flowsim-fair-ledger/flowsim/flow_telemetry.jsonl` — **missing**.
- Intended replay source directory: `results/shared_nic_4p4d_ep32_azure16/ns3_issue_events/` — contains only `network_run_manifest.json`, `replay.conf`, and `replay_manifest.json`; no flow/event input file.
- Archived FAIR run directory: `results/shared_nic_4p4d_ep32_azure16/ns3_cc1_fair/` — contains only `network_run_manifest.json` and `replay.conf`; `flow.txt`, `cc_events.csv`, `comm_events.csv`, FCT, queue, and link telemetry outputs are missing.

The aggregate `dcqcn_policy_summary.json` is present, but it is not sufficient to reconstruct the 171,507 original events, their exact timestamps, routes, per-flow bytes, or QP identities. Neither the fresh baseline nor the persistent-QP treatment can therefore be run as a strict matched replay from the remaining artifacts.

## Permitted D64 POST_PREFILL fallback audit

The existing `capacity_calibrated_kv_ep` D64 POST_PREFILL artifacts were also checked. They preserve serving request rows, KV event rows, collective-level summaries, and FlowSim fluid-link telemetry. The collective file records collective start/end and aggregate byte/flow counts, plus a subset of critical-flow IDs; it does not preserve the complete EP peer-message list with per-message issue time, bytes, route, and QP identity needed for an exact packet replay. The KV event ledger alone cannot fill in the missing EP messages. Therefore this fallback is **not packet-replay-ready** and was not used to create approximate EP traffic.

## Historical artifact gate result

For the **historical** run, stop before modifying QP lifetime. Do not synthesize a replacement schedule or infer historical per-class CNP values from aggregate counters. The historical exact-replay status remains `S8_ECN_BASELINE_REPRO_FAIL`.

## New regenerated candidate (separate from historical run)

A separately identified, fully regenerated candidate is now available at `results/natural_ecn_baseline_v1/attempts/s8_d8_k2_i8192_do64_gap5ms/`. It uses the corrected S8 4P4D/EP32 topology, an event-derived D warmup followed by two 8,192-token P2D requests, and an integrated model-derived LAYERWISE/GateRouter event ledger. Native ns-3 replay completed with the existing 200-Gbps and ECN/DCQCN configuration; exact QP-start joins covered all 378,816 network QPs.

Results for this **new** candidate: 25,670 link ECN-mark events, 5,134 CNPs, and 2,420 rate decreases. All CNPs and decreases mapped to P2D KV QPs (721 distinct QPs affected); EP QPs had zero CNP and zero rate decrease. It therefore meets the natural-ECN regeneration gate but yields `NATURAL_CONGESTION_DOES_NOT_REDUCE_EP_QP`; the persistent-EP-QP branch stops here. It is not an exact reproduction of the missing 16-request historical workload. Full provenance and hashes: `results/natural_ecn_baseline_v1/BASELINE_MANIFEST.json`; class attribution: `results/natural_ecn_baseline_v1/NATURAL_ECN_CNP_BY_CLASS.csv`.
