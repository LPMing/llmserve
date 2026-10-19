# Run provenance and reproduction

## Source identity

- Repository: `/home/dell/lpm/LLMServingSim`
- Git HEAD: `0c0839aff54ec0abb1810dc09cf3d66f06b1b078`
- Worktree: dirty before and during this study; unrelated existing edits were preserved.
- Tracked `git diff --binary HEAD` SHA-256 at the time of the simulation runs: `bffce36e4015d9fbcf484dc78ebed4c658f7365297a672230127331cba0986db`.
- Environment: `/home/lpm/.conda/envs/llmsim-flowsim/bin/python`; protobuf implementation `python`; `PYTHONPATH=/home/dell/lpm/LLMServingSim/astra-sim/extern/graph_frontend`.
- Final dirty-tree content manifest (status + tracked diff digest + hashes/sizes of tracked changes and non-ignored untracked files; this provenance file is excluded to avoid self-reference): `27f8dbe8561061a65466e2d53fac0a1706d694d79200351bf481b790535e78e2`.
- The repository already contained unrelated dirty changes before this study; the manifest intentionally captures them without claiming they belong to this experiment. Git HEAD alone is not the experiment version.

Relevant serving/network source SHA-256 at report finalization:

| Source | SHA-256 |
|---|---|
| `serving/__main__.py` | `efcf058a00605187531b5173b2866825aa45f3ab736eae82fb722452bb19fe5f` |
| `serving/core/flowsim_backend.py` | `89028c7c75d1eb8fa181647f3de82dc01fa55be4ff3f108e79676fa251fc35aa` |
| `serving/core/flowsim_worker.py` | `36435f5ac8f8e0a78ae34eed3ca6a37cd01fbfccb45e8e0d8a35c377f7cad866` |
| `serving/core/flowsim_groups.py` | `8387281181ce5ff84ae34eed3ca6a37cd01fbfccb45e8e0d8a35c377f7cad866` |
| `serving/core/controller.py` | `cd22e7179d31bd86161dd3c62b4287a0b3033f437e9ae996b17253ea0b55da5c` |
| `serving/core/graph_generator.py` | `7ea96c919d9b6198e69a9bf27a12004cd6074711b1556e0233c4de30fcfcac23` |
| `serving/core/scheduler.py` | `7c125aa693a2734567a0ff9432131fc1f1875bf305d08526619dd36de66d9aaf` |
| `serving/core/request.py` | `4a537d9dec7d7d059f812aaa8cd92abbaace4aa4891669bd2cf40737bbe8ff4e` |
| `astra-sim/.../llm_converter.py` | `e65d863eac39da5ffa2c76cf8300a8b3b54b2e5ddd8b270421d805329ccfb76f` |

## Input hashes

| Input | SHA-256 |
|---|---|
| `decode_opportunity_2p2d_tp2.json` | `08a1091175210fff1219e5310442701904a9c052a354361873b9d605348bff6a` |
| `rank_map_2p2d_tp2_cross_cut.json` | `bbb23547f3d75f1162388e1b7482bbefef8172a3c1f9b7033bcee205a1ece548` |
| `two_prefill_two_decode_shared_cut_200g.txt` | `b3f03af21156e41230400d8630500419cc8703cd4715f35c0b38e28033d8fc7f` |
| `seed_plus_two_targets_crosscut.jsonl` | `ed1d5c0467aafbbbc8dd2886af90d4baa032e80828c8ca5ca228a19ae288bf9a` |
| `seed_plus_two_targets_crosscut_d0_o11.jsonl` | `a753ab90f55e5a40afb375060b9c0eceb5a8822ecf66a01c44e1c70bfbbf110b` |
| `seed_plus_two_targets_crosscut_d0_o13.jsonl` | `bc66c8f98e126ceffbc667ae003571de8c15ee5f42cbb99c75b2680bc43fc619` |
| `configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json` | `0736f3bafb95cc658776c92ab34f5f98d8169634a3a36b84892d71448a1f19d3` |
| `profiler/perf/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/bf16/meta.yaml` | `e755433ea63a19e9d4a4919f04da412807aa520972dc97df3dfb8908b6a70f96` |

## Workload and placement

Main request order in `seed_plus_two_targets_crosscut.jsonl`:

| ID | Role | Input/output tokens | Pairing |
|---:|---|---|---|
| 0 | active Decode seed | 128 / 64 | D1 / instance 3 |
| 1 | active Decode seed | 128 / 12 | D0 / instance 2 |
| 2 | new P2D target | 2048 / 2 | D1 / instance 3 |
| 3 | new P2D target | 2048 / 2 | D0 / instance 2 |

All arrivals are at 0 ns. This is `CONTROLLED_MODEL_DERIVED_WORKLOAD`, not a production trace. Qwen KV bytes are derived from 48 layers × K/V × 4 KV heads × 128 head_dim × BF16 2 B/token = 98,304 B/token; each 2048-token request carries 201,326,592 B across TP2 (two 100,663,296-B shards). No KV/EP byte override is used.

The topology has a single directed cross-leaf edge each way at 200 Gbps, endpoint attachment links at 200 Gbps, and 0.5 μs per link. Logical Decode TP ranks are split across leaves to ensure generated EP flows and one shard of each new P2D request share `12->13`. See the topology JSON's rank-map semantics; do not substitute the earlier `rank_map_2p2d_tp2.json` for this shared-cut experiment.

## Commands

Run from repository root. Full integrated DAG is rerun for each policy. The output root must be a new scratch directory; the completed artifacts summarized here were under `/tmp/decodeopp-linkwindow-*` and `/tmp/decodeopp-neighbor-*`.

```bash
export PYTHONPATH=/home/dell/lpm/LLMServingSim/astra-sim/extern/graph_frontend
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python
export FLOWSIM_TELEMETRY_LINK_IDS='12->13,13->12'
export FLOWSIM_TELEMETRY_START_NS=70000000
export FLOWSIM_TELEMETRY_END_NS=81000000
export FLOWSIM_MAX_TELEMETRY_ROWS=4096
export SERVING_BATCH_MISS_EVENT_LOG=/tmp/<case>-events.jsonl

/home/lpm/.conda/envs/llmsim-flowsim/bin/python -m serving \
  --cluster-config research_motivation/decode_opportunity/decode_opportunity_2p2d_tp2.json \
  --dataset research_motivation/decode_opportunity/seed_plus_two_targets_crosscut.jsonl \
  --network-backend flowsim \
  --flowsim-topology research_motivation/decode_opportunity/two_prefill_two_decode_shared_cut_200g.txt \
  --flowsim-rank-map research_motivation/decode_opportunity/rank_map_2p2d_tp2_cross_cut.json \
  --flowsim-policy <FAIR|EP_FIRST|KV_REQUEST_FIRST|EP_THEN_KV_REQUEST_FIRST> \
  [--flowsim-request-first-id <2|3>] \
  --request-routing-policy RR --pd-kv-transfer-mode POST_PREFILL \
  --dtype bfloat16 --max-num-seqs 1 --max-num-batched-tokens 2048 \
  --log-interval 1000 \
  --flowsim-telemetry /tmp/<case>-telemetry.jsonl \
  --output /tmp/<case>-requests.csv --run-id <case>
```

For `C0_KV_ONLY_NETWORK`, set `FLOWSIM_NETWORK_CLASSES=KV_MOVEMENT`, policy FAIR, and omit request-first ID. For full-service runs use `FLOWSIM_NETWORK_CLASSES=KV_MOVEMENT,EP`. Main labels/controls are: FAIR; KV_REQUEST_FIRST id 3; EP_FIRST; EP_THEN_KV_REQUEST_FIRST id 2; EP_THEN_KV_REQUEST_FIRST id 3. The latter is an offline characterization upper bound. The network-only controls can be regenerated with:

```bash
PYTHONPATH="$PYTHONPATH:$PWD" PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
  /home/lpm/.conda/envs/llmsim-flowsim/bin/python \
  research_motivation/decode_opportunity/run_network_controls.py
```

Neighbor validation replaces the dataset path with `seed_plus_two_targets_crosscut_d0_o11.jsonl` or `_d0_o13.jsonl` and reruns FAIR plus EP_THEN_KV_REQUEST_FIRST id 3. The analyzer in `analyze_decode_opportunity_results.py` exports the durable compact request and network ledgers from the completed scratch runs; it does not change simulation results. `run_integrated_controls.sh` is a durable wrapper added for future replay; the historical runs used equivalent CLI arguments and explicit run labels.

## Telemetry completeness and semantics

The default link sidecar cap of 4096 rows truncated earlier broad-window runs before the target transfer. Those rows are excluded from target-link analysis. The authoritative link results are the targeted re-runs with explicit link IDs and time window above; they contain 3,726 retained link intervals across controls. Flow-level/request/collective exports contain 48 P2D shard rows, 36,480 EP collective rows and 1,536 Decode-batch rows. `queue_bytes` is analytical residual fluid work, not a switch packet-buffer queue. Targeted files are `ledgers/P2D_REQUEST_FLOW_LEDGER.csv`, `EP_COLLECTIVE_LEDGER.csv`, `DECODE_BATCH_EVENT_LEDGER.csv`, `SHARED_LINK_TIMESERIES.csv`, and `SHARED_LINK_SUMMARY.csv`.

## Tests / unrun work

The focused simulator regression suite (FlowSim group collective ownership/scope, rank mapping, Decode receiver/pairing/capacity, and request-first policy) passed: 31 tests. Re-run with:

```bash
PYTHONPATH=/home/dell/lpm/LLMServingSim/astra-sim/extern/graph_frontend:/home/dell/lpm/LLMServingSim \
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
/home/lpm/.conda/envs/llmsim-flowsim/bin/python -m unittest \
  research_motivation.decode_opportunity.test_flowsim_kv_request_first \
  experiments.pd_kv_ep.scripts.test_flowsim_group_queue_ownership \
  experiments.pd_kv_ep.scripts.test_flowsim_collective_scope \
  experiments.pd_kv_ep.scripts.test_flowsim_rank_mapping \
  experiments.pd_kv_ep.scripts.test_pd_decode_receiver_mapping \
  experiments.pd_kv_ep.scripts.test_pd_request_pairing \
  experiments.pd_kv_ep.scripts.test_pd_decode_capacity_admission -v
```

Not run: packet-level ns-3/HTSim validation, a real trace, a client-visible prefill sampler callback, statistical repeats, SLO attainment, a complete EDF/LLF/Varys/Nuska implementation, sparse GateRouter A2A, or production-scale deployment. These are omissions, not zero-valued results.
