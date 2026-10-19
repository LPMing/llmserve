# Theory ↔ packet discrepancy log

| Item | Prediction / invariant | Packet observation | Classification and resolution |
|---|---|---|---|
| N0 payload serialization | 201,326,592 B / 25 GB/s = 8.05306368ms | 8.151317ms | **PACKET_PROTOCOL_OVERHEAD.** Packet payload is segmented at 4KiB and RDMA startup/RTT/header behavior is included. Difference is +98.253µs; no capacity violation. |
| N2 four-sender receiver cut | Equal-share lower bound 4 × 8.05306368ms = 32.21225472ms | 32.481310ms mean; max 32.481557ms | **PACKET_PROTOCOL_OVERHEAD / implementation detail.** +0.84% vs payload-only lower bound. All four use one measured 200G receiver egress; bytes and path are conserved. |
| Parallel spines vs receiver rate | Four independent source paths do not increase one Decode NIC's 200G receive service | N2 queue at one Decode leaf→NIC egress, while source paths are distinct | **THEORY_SIM_MATCH.** The receiver egress remains the cut. |
| First calibrated DCQCN attempt | QP initial rate must match endpoint/NIC resource | An earlier topology let GPU rank QPs start at 7.2T and drop to 3.64T | **TOPOLOGY_MAPPING_ERROR.** Rejected. Calibrated fixture caps rank access to 200G; N0 CC1 then matches CC0 and starts at 200G. |
| ECN counts across links | A CE-marked packet can be counted at downstream telemetry hops | `link_summary.ecn_marks` repeats observations; local mark CSV is smaller and local | **TELEMETRY_SEMANTICS.** Use only first local CE transitions for local-mark counts; never sum link observations as unique marks. |
| Layerwise release order | Every layer's 2MiB/rank P2D shard releases after its profiled QKV; next compute chunk does not wait for prior KV drain | 768 events, byte invariant 1.6106GB; releases span 133.68ms | **THEORY_SIM_MATCH for the frozen release ledger.** Fixed replay does not prove integrated graph feedback. |
| Layerwise queue vs barrier | If final KV-ready precedes Prefill compute end, this KV wait is hidden | CC0 134.059112ms and CC1 134.963180ms; compute end 135.319248ms | **DECODE_BARRIER_MASKING in this modeled profile window.** Exposed wait is 0ms; do not infer TTFT/TBT. |
| Cross-wave carry | A later layer wave can overlap an unfinished earlier wave if its release arrives first | All 95 measured wave gaps are positive: min 959.943µs CC0, 55.255µs CC1 | **NO_CROSS_WAVE_ACTIVE_FLOW_OVERLAP in this fixture.** Queue episodes/CE repeat, but each event wave finishes first. |
| DCQCN state inheritance | Persistent QP could carry a reduced rate to later messages | 768 QP starts for 768 KV events, each starts 200G; this replay uses fresh KV QPs | **NOT_TESTED / backend limitation.** No persistent KV-QP claim. |
| Serving feedback | Fixed event completion should update online Serving schedule only if callback is connected | `KVEPReplay` uses no-op completion handler and pre-schedules all events | **PACKET_SERVING_FEEDBACK_MISSING in this replay.** Integrated ASTRA/ns-3 source path has callbacks but custom-topology runtime is NOT_RUN. |

## Analysis correction

The first analyzer grouped both 2048-token chunks by `layer_id`, which repeats
0–47, and paired the maximum finish with the minimum release of that repeated
layer. This overstated the “last-layer residual drain.” The analyzer was fixed
to identify the exact last-completing event and compare it with the latest
release. Correct final release→ready values are approximately 0.379ms (CC0)
and 1.28ms (CC1), not ~71ms. The request elapsed time from its first layer
release is ~134ms and includes the Prefill pipeline span; it is not a flow FCT.

The replay-runner's initial CC1 setup failures were due to missing empty
`flow.txt`/`trace.txt` config inputs and occurred before simulation. A corrected
runner creates the sentinels and records run provenance; CC1 v3 passed.
