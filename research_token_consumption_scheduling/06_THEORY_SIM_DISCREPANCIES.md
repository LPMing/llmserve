# Theory / simulation discrepancy ledger

| Prediction or question | Evidence | Finding | Classification |
|---|---|---|---|
| Historical 27.54% first-ITL improvement is a client-visible result | A0 sampler-ready is 177.175 ms, full P2D/recorded first-token event is 182.646480 ms, token2 is 197.041480 ms; A2 sampler and recorded first token are both 177.175 ms, token2 191.570 ms | 27.54% is only the arithmetic change in a sampler-anchored proxy interval. On simulator-recorded first-token timestamps, first ITL is 14.395 ms in both. Client emission is not separately recorded. | Metric semantics / missing instrumentation |
| Full P2D request barrier might leave a large network scheduler opportunity | Four 201,768,960-B shards per TP receiver rail, 200 Gbps; release 150.125 ms; sampler 177.175 ms | Capacity lower bound leaves ≥130,825,840 B outstanding at sampler and implies full ready no earlier than 182.408034 ms. Observed 182.646480 ms is within 0.238446 ms of the bound. | Theory and FlowSim consistent; little flow-order headroom |
| Layerwise readiness might permit consuming KV before last-layer drain | Per-layer FlowSim finish rows and profile-derived Decode layer times, gated for all four requests and both TP ranks | The modeled decode cursor is already beyond each layer's completion. All 5.471480 ms post-sampler drain is hidden; modeled token2 reaches 191.570 ms. | Profile-derived independent oracle positive, not integrated simulation |
| Per-layer Decode/TP DAG and collective join can be reconstructed as measured | Each rank ET has 48 zero-duration TP ALLREDUCE nodes; the collective telemetry file is header-only; only whole graph completion is logged | Compute dependency/cost can be reconstructed from the profile graph, but runtime collective joins/CCT and layer completion are not observed. The B2 oracle inherits a zero-duration TP collective abstraction. | Instrumentation / model boundary |
| New layer-aware control might improve on the best current system baseline | A2 DELTA integrated run reaches token2/3 at 191.570/205.965 ms | B2 oracle reaches the same timestamps but uses full bytes; DELTA uses 884,736 B/request. No incremental serving headroom over A2 is demonstrated. | Strong-baseline failure |
| Could lower overhead or more requests expose a win? | B2 excludes commit/synchronization cost; fixture is 4 controlled requests | Do not scale this experiment to chase a positive: direct layer-streaming execution is already an established mechanism, and the oracle has no gain over A2. The open unknown is implementation overhead, not evidence for a network scheduling problem. | Stop per requested gate |

## Overall status

`THEORY_SIM_CONSISTENT_FOR_FULL_BARRIER`

`LAYER_CONSUMPTION_ORACLE_MECHANISM_VISIBLE_BUT_NOT_INTEGRATED`

`NO_INCREMENTAL_NETWORK_SCHEDULING_HEADROOM_DEMONSTRATED`

