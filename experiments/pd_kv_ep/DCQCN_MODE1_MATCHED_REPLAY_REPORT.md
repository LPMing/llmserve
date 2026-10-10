# Matched DCQCN (`CC_MODE=1`) replay report

Date: 2026-10-08
Status: all three packet replays PASS; network/barrier characterization only, not ns-3 integrated serving.

## Experiment

The same immutable 16-request Azure 2024 window-16812 event ledger was replayed with `CC_MODE=1` under FAIR, EP_FIRST, and KV_FIRST. Setup: Qwen3-30B-A3B-Instruct-2507, 48 layers, TP2, EP32, LAYERWISE P2D; S8 (4 Prefill + 4 Decode servers), 200-Gbps physical scale-out links, four GPU ranks per shared NIC, 4-KiB payload, 0.1-ms link/queue telemetry, 32-MiB switch buffer, and `ACK_HIGH_PRIO=1`. Bytes and issue times are model/request-derived; no override or added delay.

The source is [`ns3_issue_events`](./results/shared_nic_4p4d_ep32_azure16/ns3_issue_events/). Its `events.csv` is byte-identical to the source used by the previous mode-12 packet replays. The new `CC_MODE=1` output directories are [`ns3_cc1_fair`](./results/shared_nic_4p4d_ep32_azure16/ns3_cc1_fair/), [`ns3_cc1_ep_first`](./results/shared_nic_4p4d_ep32_azure16/ns3_cc1_ep_first/), and [`ns3_cc1_kv_first`](./results/shared_nic_4p4d_ep32_azure16/ns3_cc1_kv_first/). All ran serially and passed all 171,507 events in 329.43 s, 321.76 s, and 322.97 s, respectively. Each emitted `cc_events.csv` with CNP/rate events.

The older matched runs used `CC_MODE=12`, inherited from a legacy `config_clos.txt` with no documented meaning in this backend. It is not one of the implemented modes; these runs had ECN marking but no sender rate-response branch. Therefore the comparisons below are accurately described as **mode-1 DCQCN versus legacy unsupported mode-12/no-rate-response behavior**, not as a comparison against a documented production controller-off mode. For a paper-grade CC causal control, repeat the identical triplet under explicit `CC_MODE=0` and retain the existing mode-1 triplet.

## Results

All deltas compare each policy's new mode-1 replay against that policy's earlier mode-12 replay. Flow and collective sets are paired by event/collective identity; for every policy, all 171,507 events retain identical request, bytes, issue time, endpoint, priority, path, and directed-link identity.

| Policy | KV shard FCT mean, mode12 → mode1 | KV shard FCT P99, mode12 → mode1 | Request handoff mean, mode12 → mode1 | Request handoff P99, mode12 → mode1 | EP CCT mean, mode12 → mode1 | EP CCT P99, mode12 → mode1 |
|---|---:|---:|---:|---:|---:|---:|
| FAIR | 284.876 → 791.018 µs (+177.7%) | 1,155.891 → 3,342.118 µs (+189.1%) | 72.784 → 72.961 ms (+0.244%) | 117.342 → 118.275 ms (+0.795%) | 38.461 → 38.267 µs (−0.50%) | 66.724 → 66.379 µs (−0.52%) |
| EP_FIRST | 284.887 → 787.974 µs (+176.6%) | 1,155.891 → 3,461.324 µs (+199.5%) | 72.784 → 72.918 ms (+0.184%) | 117.343 → 117.821 ms (+0.408%) | 38.067 → 38.068 µs (~0%) | 66.379 → 66.379 µs (~0%) |
| KV_FIRST | 284.307 → 795.977 µs (+180.0%) | 1,155.891 → 3,454.031 µs (+198.8%) | 72.780 → 72.879 ms (+0.136%) | 117.337 → 117.460 ms (+0.105%) | 71.339 → 46.978 µs (−34.2%) | 635.865 → 295.723 µs (−53.5%) |

For all three policies, CC=1 substantially increases individual KV shard FCT, while request handoff changes by less than 1%. Mean post-last-layer-release KV drain rises from 206–210 µs under mode 12 to 306–387 µs under mode 1. It remains tiny relative to the roughly 72.8-ms first-release-to-last-completion span, so most shard slowdown remains hidden by the layerwise release/barrier structure in this window.

KV_FIRST's EP CCT tail is much smaller under mode 1 than under mode 12, but still far above FAIR/EP_FIRST: mode-1 KV_FIRST CCT P99 is 295.723 µs versus 66.379 µs for EP_FIRST. This is consistent with DCQCN limiting the effective injection of high-priority KV and thereby relieving some EP pressure, while worsening KV shard FCT. It is not yet a clean causal attribution because mode 12 is an unsupported mode; validate with a matched mode-0 no-rate-response run before making that claim.

## Congestion-control telemetry and queues

| Policy | CNP events | Rate-decrease events | Rate-recovery events | ECN marks / physical-link TX observations | Max queue on 200-Gbps physical links |
|---|---:|---:|---:|---:|---:|
| FAIR | 20,876 | 10,353 | 570 | 79,026 / 10,258,104 (0.770%) | 3,243,620 B |
| EP_FIRST | 21,346 | 10,402 | 558 | 80,924 / 10,258,104 (0.789%) | 3,169,244 B |
| KV_FIRST | 22,136 | 10,720 | 566 | 84,112 / 10,258,104 (0.820%) | 3,607,236 B |

Mode-12 marks were about 2.51% of physical-link TX observations for each policy, and maximum physical queue was 4,696,072 B. Thus mode 1 reduces marking observations by about 67–69% and lowers the max queue in these runs, while increasing KV shard FCT. Marks are link-transmission observations (a packet may be observed at multiple hops), not unique-packet or request probabilities. PFC pauses and drops remain zero. The CC telemetry counts prove rate feedback was exercised; this report intentionally does not infer a CNP-to-rate latency distribution from the dense multi-flow log.

## Interpretation

1. **ECN marking and ECN-driven rate control are separate.** Mode 12 produced marks but no implemented rate reaction. Mode 1 produced CNP and rate changes.
2. **FCT is not request handoff.** DCQCN can significantly slow individual layerwise shards while the request barrier moves less than 1%, because the request waits for the maximum completion and earlier shards have release/barrier slack.
3. **The exact last shard remains decisive.** A delayed early shard changes handoff only if it becomes the last required shard; the current model still allows later layers to release without waiting for prior KV network completion.
4. **No serving metrics come from this replay.** The ns-3 issue schedule is fixed and packet completion is not fed back to the serving scheduler. Do not report these values as TTFT, TPOT, TBT, or SLO.
5. **Priority and congestion control interact.** The mode-1 KV_FIRST EP tail is improved relative to mode 12, but the valid next control is mode 0 under the same ledger and policy trio. The previous mode-12 run is preserved as historical comparison only.

## Artifacts and reproduction

- New config: [`replay_template_dcqcn.conf`](./configs/ns3/replay_template_dcqcn.conf).
- Runner now emits `cc_events.csv` when the chosen template declares `CC_TELEMETRY_FILE`: [`run_model_derived_replay.py`](./scripts/run_model_derived_replay.py).
- Analyzer: [`analyze_dcqcn_priority_replays.py`](./scripts/analyze_dcqcn_priority_replays.py).
- Machine-readable summary: [`dcqcn_policy_summary.json`](./results/shared_nic_4p4d_ep32_azure16/ns3_cc1_analysis/dcqcn_policy_summary.json).
- Paired summaries: [`dcqcn_paired_metric_summary.csv`](./results/shared_nic_4p4d_ep32_azure16/ns3_cc1_analysis/dcqcn_paired_metric_summary.csv), [`dcqcn_request_handoffs.csv`](./results/shared_nic_4p4d_ep32_azure16/ns3_cc1_analysis/dcqcn_request_handoffs.csv), [`dcqcn_collective_ccts.csv`](./results/shared_nic_4p4d_ep32_azure16/ns3_cc1_analysis/dcqcn_collective_ccts.csv).
