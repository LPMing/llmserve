# Shared NIC (50G/GPU average) with 200G switch-fabric validation

## Result in brief

The shared-NIC model is straightforward to represent in this simulator and is now implemented as a topology abstraction: four GPU rank endpoints attach to one NIC aggregation node, whose scale-out uplink is a single **200 Gbps** link. When all four GPUs are active and share that uplink fairly, their nominal share is 50 Gbps each; 50 Gbps is not configured as a physical switch-link rate. The leaf/spine links remain physical 200 Gbps links.

Both integrated FlowSim and native ns-3 runs completed on the bounded four-request gate. The packet-level run verified a shared NIC-uplink queue and ECN marks. This small workload did **not** establish a large serving-level benefit or penalty: request KV handoff and EP CCT tails changed little, and FlowSim's P2D-ready timestamp equaled Prefill completion for every request. Treat this as topology/backend validation, not paper motivation.

## Topology model

The generated configuration is based on the existing six-server S2P4D cluster: 2 Prefill servers + 4 Decode servers, 8 GPUs/server, 48 GPU rank endpoints total, EP32. The P:D server ratio is 1:2 in this gate; it is not presented as the final balanced production topology.

| Resource | Configuration | Interpretation |
|---|---:|---|
| GPU rank endpoints | 48 | Remain distinct endpoints; no server-level endpoint collapse |
| GPU ranks per NIC | 4 | Two 200G NICs per 8-GPU server |
| NIC aggregation nodes | 12 | One logical node per shared NIC |
| NIC scale-out uplink | 200 Gbps each | The common constrained resource for its four GPU ranks |
| Nominal per-GPU share | 50 Gbps | Only when all four attached GPUs are simultaneously backlogged and share fairly |
| GPU/NIC local attachment | 7.2 Tbps abstract local link | Deliberately non-bottleneck attachment; not a claim that a GPU has a 7.2T NIC |
| Leaf/spine physical links | 200 Gbps each | Three parallel physical links per leaf/spine pair, 600 Gbps aggregate per pair |
| Leaf scale-out capacity | 1.2 Tbps down / 1.2 Tbps up | Six 200G NIC uplinks per leaf; 1:1 aggregate leaf fabric |

The path is `GPU rank -> shared NIC node -> leaf -> spine/peer leaf -> destination NIC -> GPU rank`. Same-leaf transfers need not traverse a spine. The NIC node is an explicit shared resource, so the model does not statically cap each GPU at 50G: one active GPU may use more, up to the common 200G uplink capacity, subject to other active flows and the backend's sharing/queue behavior.

Artifacts:

- Topology generator: `experiments/pd_kv_ep/scripts/generate_shared_nic_topology.py`
- GPU-to-NIC map: `experiments/pd_kv_ep/configs/large_scale/s2p4d_6_servers_gpu_to_nic.csv`
- Cluster config: `experiments/pd_kv_ep/configs/large_scale/s2p4d_6_servers_shared_nic_200g.json`
- Rank/topology manifest: `experiments/pd_kv_ep/configs/large_scale/s2p4d_6_servers_shared_nic_manifest.json`
- Physical topology: `experiments/pd_kv_ep/configs/large_scale/ns3/s2p4d_6_servers_4gpu_per_200g_nic_200g_clos.txt`

## Workload and replay discipline

The bounded gate used Qwen3-30B-A3B-Instruct-2507 model-derived traffic, 48 layers, top-k 8, EP32, A2A_P2P, actual P2D receiver ranks, and LAYERWISE KV transfer. The four-request workload is a small synthetic request *schedule* for correctness (input lengths 128, 128, 512, 2048; output lengths 8, 8, 1, 1; arrivals 0, 0, 2ms, 2ms); it contains no byte override. KV and expert traffic sizes/routing are generated from the model and simulator.

The integrated FlowSim run generated 12,576 flow events: 384 P2D layer/rank flows carrying 276,824,064 bytes and 12,192 EP P2P flows carrying 49,938,432 bytes. For packet-level matched controls, the FlowSim FAIR run's `requested_start_ns` values were converted to a fixed issue-time event ledger and replayed through native ns-3. ns-3 recomputed packet delivery/completion, queueing, and ECN/PFC behavior; the packet-level result was **not** fed back into the serving scheduler. Thus ns-3 below provides packet/network metrics only, not packet-level TTFT/TBT.

ns-3 used 4,096-byte packet payloads, QCN enabled, dynamic PFC thresholds enabled, and 0.1ms queue/link sampling. Every run completed all 12,576 events (12,576 START + 12,576 END records). Host wall time was 15.76s for shared-NIC FAIR, 15.65s for shared-NIC EP_FIRST, 15.45s for shared-NIC KV_FIRST, and 9.79s for dedicated-NIC FAIR.

## Native ns-3 results

Request-level P2D handoff span is calculated as `max(flow finish) - min(flow start)` across that request's required layer/rank P2D events. It is a request-level barrier span, not the sum of per-flow FCTs. EP CCT is collective-level `last participant completion - collective start` across 768 collectives.

| Topology / policy | P2D handoff mean | P2D P99 | EP CCT mean | EP CCT P99 | EP CCT max |
|---|---:|---:|---:|---:|---:|
| Shared 4-GPU/200G NIC, FAIR | 48.486 ms | 62.733 ms | 38.391 us | 63.909 us | 64.862 us |
| Shared 4-GPU/200G NIC, EP_FIRST | 48.486 ms | 62.733 ms | 38.388 us | 63.909 us | 64.074 us |
| Shared 4-GPU/200G NIC, KV_FIRST | 48.486 ms | 62.733 ms | 38.708 us | 63.909 us | 124.933 us |
| Dedicated 200G per GPU, FAIR | 48.483 ms | 62.733 ms | 40.606 us | 63.336 us | 63.336 us |

The dedicated-NIC comparison uses the same event bytes and issue timestamps, changing only the topology. In this particular four-request schedule, shared-NIC FAIR raised the maximum 200G-link queue from 33,056 bytes to 1,061,924 bytes (about 32x) and produced 160 ECN marks on the shared-NIC topology versus zero on the dedicated-NIC topology. Yet P2D P99 differed by less than 0.001%, and EP CCT P99 increased by about 0.9%. There were no PFC pauses or packet drops. This is evidence that the added shared resource is exercised, while also showing that the observed queue increase does not automatically translate to a large barrier penalty at this offered load.

With the fixed event schedule, EP_FIRST and FAIR had the same EP CCT P99; KV_FIRST also had the same P99 but a single larger maximum (124.933us). P2D request handoff statistics were unchanged to the displayed precision across policies. Do not infer serving policy effects from this fixed-issue packet replay.

Relevant ns-3 artifacts:

- Shared NIC FAIR: `experiments/pd_kv_ep/results/shared_nic_50g_integrated/ns3_fair_retry/`
- Shared NIC EP_FIRST: `experiments/pd_kv_ep/results/shared_nic_50g_integrated/ns3_ep_first/`
- Shared NIC KV_FIRST: `experiments/pd_kv_ep/results/shared_nic_50g_integrated/ns3_kv_first/`
- Dedicated 200G/GPU FAIR control: `experiments/pd_kv_ep/results/shared_nic_50g_integrated/ns3_dedicated_fair/`
- Joined network analysis: `experiments/pd_kv_ep/results/shared_nic_50g_integrated/ns3_analysis/`

## Integrated FlowSim serving results

These are valid scheduler-generated serving metrics from FlowSim, separate from the ns-3 replay. Four requests are a diagnostic sample; formal SLO attainment is not meaningful at this sample size.

| FlowSim topology / policy | TTFT P99 | TPOT P99 | Token TBT P99 | P2D-ready minus Prefill completion |
|---|---:|---:|---:|---:|
| Dedicated 200G/GPU, FAIR | 68.489 ms | 3.108 ms | 8.728 ms | 0 for all requests |
| Shared 4-GPU/200G NIC, FAIR | 68.000 ms | 3.112 ms | 8.753 ms | 0 for all requests |
| Shared 4-GPU/200G NIC, EP_FIRST | 67.999 ms | 3.112 ms | 8.753 ms | 0 for all requests |
| Shared 4-GPU/200G NIC, KV_FIRST | 68.070 ms | 3.122 ms | 8.823 ms | 0 for all requests |

The small differences (under 1% here) are not evidence of a robust policy ordering. In this workload the layerwise P2D transfers drain before Prefill completion, so the Decode handoff barrier adds no extra time after Prefill. This explains why a visible packet/fluid queue can coexist with almost unchanged TTFT.

FlowSim artifacts:

- Requests: `experiments/pd_kv_ep/results/shared_nic_50g_integrated/*.requests.csv`
- Diagnostic comparison: `experiments/pd_kv_ep/results/shared_nic_50g_integrated/serving_comparison.md`
- Integrated run manifests/logs: same result directory, `*.manifest.json` and `*.sim.log`

## Implementation notes and limits

The first ns-3 topology attempt stopped immediately because the existing QCN `KMIN_MAP` had no entry for the 7.2Tbps abstract local attachment rate. The replay template now includes a 7.2Tbps threshold-map entry matching the previous highest-rate tier; the 200G scale-out links retain their original 200G thresholds. The rerun passed. The local link tier did not become a bottleneck in this workload. This threshold extension is a backend configuration accommodation, not new calibration data.

Implementation effort was low-to-moderate and did not require rewriting the serving scheduler or network solver:

1. Add explicit NIC aggregation nodes and emit a GPU-to-NIC map/topology.
2. Extend the ns-3 replay rate-threshold map for the abstract high-rate local links.
3. Add `flowsim_telemetry_to_ns3_replay.py` to preserve the integrated FlowSim issue schedule and model-generated flow records while letting ns-3 recompute packet behavior.

This is a shared-uplink/resource model, not a device-level ConnectX/NIC implementation. It models aggregate bandwidth sharing and the egress queue at the NIC aggregation node. It does not model PCIe bandwidth, GPU DMA staging, NIC firmware arbitration, per-QP hardware queues, or a vendor-specific NIC scheduler. Adding those details would be a substantially larger extension; they are not required to answer the first-order question “do multiple GPU ranks share one 200G scale-out resource?”

FlowSim queues are analytical fluid backlog; they are not used as packet queue/ECN/PFC evidence. Packet queue, ECN, PFC and drop statements above come only from native ns-3 output.

## Conclusion and next validation

The correction is implemented: **50G/GPU is the average share of four GPUs behind one 200G NIC; the switch fabric remains 200G per physical link.** The topology is accepted by both FlowSim and native ns-3, and ns-3 produced packet-level queue/ECN evidence on the intended shared NIC uplinks.

This gate does not demonstrate a ≥20% serving effect. The next useful experiment is not to lower switch bandwidth; it is to use the same shared-NIC model in a realistic, 1:1 P:D request mix with enough simultaneous layerwise P2D senders and active EP collectives to keep the shared 200G NIC uplinks busy, then check whether the last-shard/collective barriers—not just link queues—move. Keep the network link rate at 200G and preserve request/model-derived byte accounting.
