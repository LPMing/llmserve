# Source and metric audit

Date: 2026-10-14. Scope: the frozen four-session cache-conditioned FlowSim fixture in `research_cache_network_joint/`, not a new serving replay.

## Frozen evidence and provenance

- Repository HEAD: `0c0839aff54ec0abb1810dc09cf3d66f06b1b078`. The worktree is broadly dirty; it was preserved. The experiment's frozen tracked-diff hash is `e7df10df63f778fbb2e371156e5305190b8a64ee6d9dfd2f9f91fc3ed02da46f` as recorded in `research_cache_network_joint/00_PROVENANCE.md`.
- Model/profile: Qwen3-30B-A3B-Instruct-2507, BF16, 48 layers, 4 KV heads, head dimension 128, TP2, RTX PRO 6000 profile. The audited `research_prefix_exposure/4p1d_tp2_flowsim.json` sets `ep_size=1`; MoE expert compute is present, but this is **not** a cross-node Decode EP collective workload. Four target child requests have input 4105, output 3, a 4096-token prefix hit, and nine new tokens.
- Backend: integrated FlowSim, directed-fluid/max-min service. FlowSim's residual fluid backlog is not a packet queue and these results provide no ECN/CNP/PFC/DCQCN claims. Native ns-3 was not run.
- Frozen inputs/results are listed in `research_cache_network_joint/00_PROVENANCE.md`; target request rows are in `02_BASELINE_EVENT_TIMELINE.csv`, integrated request CSVs, and flow JSONL. This audit adds no new integrated B2 run.

Evidence hashes for the artifacts consumed by the recomputation script:

| Artifact | SHA-256 |
|---|---|
| `results/a0_sampler_debug_flows.jsonl` | `b02ff95352c018964d2342348941046d78d02555292960079264a19184ed0531` |
| `02_BASELINE_EVENT_TIMELINE.csv` | `2730f134843c32df7189e1f27e79a22349729bac2235c2fec935273f3689d43d` |
| Decode rank 16 Chakra graph `llm.16.et` | `c9c916226b350fe172083d9ff60760a1dda0841c958c6ab132e9ed2064ae06c0` |
| Decode rank 17 Chakra graph `llm.17.et` | `28cb39081a65001b5aa99209eeed8e1befd6072d2b2ec126e2e77e8228e2735e` |
| `results/collective_telemetry.jsonl` | `37b7220271707f9f6847353ea3ff4dff84ce6da25b206b627600ad82323368dc` |
| `recompute_gate.py` | `802d136b444ada6008a915e8a244cd46ab5bfa62d3a80660c120f35bcaac8f05` |
| Generated `03_LAYER_CONSUMPTION_TIMELINE.csv` | `e5582720154576f41e99d236c0d22db6728be1bb386fbdfb51f4e87c492768de` |
| Generated `04_DECODE_ORACLE_RESULTS.csv` | `9e60c60d8ce61bf6e945e27ebb969e4237e62897ff61a8cd2fdd106f6877b08a` |

## Event meanings in the code

The relevant serving path is:

1. `serving/core/trace_generator.py::_emit_sequence()` emits one model-derived P2D KV send after each layer's `qkv_proj` when `pd_kv_transfer_mode == LAYERWISE` (around lines 1237–1280). It does not wait for that send to finish before generating subsequent Prefill layers.
2. The Chakra graph contains the sampler compute node, and the Prefill graph completion callback reaches `Scheduler.add_done()` (`serving/core/scheduler.py`, around lines 649–730). `req.first_token_visible_ns` is assigned at the Prefill graph completion callback, not from an independently modeled client-output callback. The source comment says the first token exists after the prefill graph ran through lm_head and sampler, but this simulator callback also waits for the graph's communication nodes.
3. Decode handoff emits `P2D_READY` at the request's handoff-ready time (`scheduler.py`, around lines 860–900); Decode admission follows that full handoff. The current path therefore has a request-level barrier even though KV sends were released layerwise.
4. A subsequent Decode graph is generated as a whole graph. The serialized Chakra node durations come from the profile/trace generator. For this run there is aggregate graph timing and token completion, but no observed per-node Decode start/finish or per-layer KV-commit callback ledger.

`SAMPLER_READY != CLIENT_TOKEN_EMITTED`. The scheduler/request CSV fields named `first_token_visible` and `TTFT` are simulator-defined timestamps; the current path does not separately model asynchronous client delivery. In A0, the request CSV's `TTFT=32.539480 ms` is arrival-to-full-P2D-ready, not a separately verified client TTFT. Do not call sampler-anchored intervals actual client ITL.

## Gate 0: same-source metric correction

For each of the four matched children, the source timeline gives:

| Event | A0 full KV | A2 DELTA |
|---|---:|---:|
| Child arrival | 150.107 ms | 150.107 ms |
| Sampler ready | 177.175 ms | 177.175 ms |
| P2D ready / first-token event recorded by this simulator | 182.646480 ms | 177.175 ms |
| Second token | 197.041480 ms | 191.570 ms |
| Third/final token | 211.436480 ms | 205.965 ms |

Correct interpretations:

- Simulator-recorded first-token-to-second-token interval: A0 `197.041480 - 182.646480 = 14.395 ms`; A2 `191.570 - 177.175 = 14.395 ms`. **No first-ITL improvement is observed on this event definition.**
- The simulator CSV ITL arrays are `[14.395, 14.395] ms` for both A0 and A2; the corresponding simulator-event mean is 14.395 ms in both. This still is not client-measured ITL because the first event is not a separate network/client emission callback.
- Sampler-anchored second-token interval (a proxy, not client ITL): A0 `19.866480 ms`; A2 `14.395 ms`; arithmetic reduction `27.5413%`. This is the source of the quoted 27.54%, but its start point is not an observed client token-emission event.
- Two-interval sampler-anchored mean through token 3: A0 `17.130740 ms`, A2 `14.395 ms`, proxy reduction `15.97%`.
- Arrival-to-second-token simulator timestamp: A0 `46.934480 ms`, A2 `41.463 ms`.
- Child arrival-to-final-token: A0 `61.329480 ms`, A2 `55.858 ms`, reduction `8.92%`.
- Full session from root arrival at time zero to child final token: A0 `211.436480 ms`, A2 `205.965 ms`, reduction `2.59%`.

These are four controlled sessions, not a sample for P95/P99 or SLO claims. The A2 result changes transfer bytes (403,537,920 to 884,736 bytes/request), so it is not a same-byte scheduling comparison.

## Gate 2 evidence availability

The A0 sampler-debug flow ledger has 384 target flows: 4 requests × 48 layers × TP2. It records request IDs, layer IDs, endpoints, directed paths, requested start, actual start, finish, and bytes. The A0 child flows total 403,537,920 bytes/request. The per-flow and per-layer network finish events are **SIMULATED** by the integrated FlowSim run.

The sampler-debug P2D JSONL embeds `graph_path` values under `cachejoint-a0-sampler-debug-retry`, but that generated input directory is not retained in the current workspace. Decode layer compute was therefore reconstructed from the retained matched A0 configuration's batch-1 Chakra graphs at:

```text
research_cache_network_joint/inputs/cachejoint-a0-4p1d/workload/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/instance4_batch1/llm.16.et
research_cache_network_joint/inputs/cachejoint-a0-4p1d/workload/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/instance4_batch1/llm.17.et
```

encode the profile-derived compute nodes, with integer-microsecond durations. Their critical rank totals are 14,395 us, matching the integrated A0 Decode batch duration `197.041480 - 182.646480 ms`; this is a cross-artifact consistency check, not a byte-identical run-input binding. Each rank graph has 48 TP `ALLREDUCE` nodes with zero `duration_micros`; the frozen `results/collective_telemetry.jsonl` contains only its header. There is therefore no measured collective-join/CCT timeline for the Decode batch. There is also no Decode EP collective because the configured EP degree is one. The ET encodes a model/trace dependency graph, not runtime per-layer completion callbacks. The Decode layer start/finish timestamps in `03_LAYER_CONSUMPTION_TIMELINE.csv` are **ORACLE-MODELED**, not observed; the oracle preserves the encoded zero-duration TP-collective semantics, not physical collective latency.

## Reproduction

From the repository root:

```sh
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_token_consumption_scheduling/recompute_gate.py
```

This parses the frozen FlowSim JSONL and Chakra length-delimited protobuf streams, verifies 384 flows and byte conservation, then regenerates the layer timeline and comparison table. It does not launch the serving simulator or change old results.

