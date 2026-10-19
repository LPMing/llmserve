# 12 — Reproducibility commands and artifact hashes

## Source/config provenance

| Artifact | SHA-256 / value |
|---|---|
| Repository HEAD at audit | `0c0839aff54ec0abb1810dc09cf3d66f06b1b078` |
| Pre-existing tracked diff snapshot | `bffce36e4015d9fbcf484dc78ebed4c658f7365297a672230127331cba0986db` |
| Qwen3 model config | `0736f3bafb95cc658776c92ab34f5f98f8169634a3a36b84892d71448a1f19d3` |
| BF16 profile meta | `e755433ea63a19e9d4a4919f04da412807aa520972dc97df3dfb8908b6a70f96` |
| S16 EP64 manifest | `507a0ae4bc6fd04e63e8b5d4d829aed10fd2aaae9301b68701441084b8b982e0` |
| S16 EP64 200G Clos topology | `cc105c3b3aa6452d31ea6df586e221f20d568eec54d17f5628cffa77017d1ba7` |
| BurstGPT source slice | `ed609a5edcec5b06fa89985b601b008e426e8885c3aef2c9f7e75af7be2bb7a1` |
| Replay builder at run | `029b4d975854c24a7f64dc94039bb511a7aa7aa8e5c31f59c6c2da93acd0ecbb` |
| Replay runner at run | `d81907c86d84a9bd82d4c36729d4b5d1ef728f0067b8d37eb05b2169741797da` |
| Integrated headroom CSV | `c1194c8108de728eda20342bf6423250df05d8532a2bde45d560f80659730e42` |
| Exact events CSV | `9f7f90c35276fdaebf7c7f568daaf3dd49c29a946b4ff42521a46018f832bb10` |
| Counterfactual events CSV | `37e8868171016f4371dea76ff08d14af60b59a0517407cbbb6db6d3f3692a700` |

The worktree was already dirty. No reset, checkout, or cleanup was performed.
Historical result files do not all have immutable Git-SHA bindings; use the
per-experiment source records and do not claim every historical number was
reproduced from the current tree.

## New replay commands

The valid event-build command (the preceding `--ep-bin-us 0` attempt was
rejected and is not a result):

```bash
/home/lpm/.conda/envs/llmsim-flowsim/bin/python \
  experiments/pd_kv_ep/scripts/build_model_derived_replay.py \
  --trace experiments/pd_kv_ep/workloads/real/slices/burstgpt/30s__window_148333.jsonl \
  --scale S16_EP64 \
  --output-dir research_final_audit/sparse_a2a_minimal/exact \
  --num-reqs 16 --request-offset 0 --load-scale 1.0 --ep-bin-us 1 \
  --pd-kv-transfer-mode LAYERWISE \
  --ep-realization GATE_ROUTER_A2A_P2P
```

The counterfactual was generated with the same command and
`--ep-realization UNIFORM_A2A_SAME_BYTES`, outputting to
`research_final_audit/sparse_a2a_minimal/uniform`.

Representative FlowSim replay command:

```bash
/home/lpm/.conda/envs/llmsim-flowsim/bin/python \
  experiments/pd_kv_ep/scripts/run_flowsim_replay.py \
  --events research_final_audit/sparse_a2a_minimal/exact/events.csv \
  --requests research_final_audit/sparse_a2a_minimal/exact/requests.csv \
  --topology experiments/pd_kv_ep/configs/large_scale/ns3/s16_8p8d_ep64_200g_clos.txt \
  --output-dir research_final_audit/sparse_a2a_minimal/exact_full \
  --policy FAIR --traffic-class FULL --parallel-link-model AGGREGATE
```

Corresponding EP_ONLY and KV_ONLY runs change `--traffic-class`; exact/counterfactual
runs select the respective events and requests directory. The scripts, manifests
and per-run outputs are retained in `sparse_a2a_minimal/`.

## Targeted regression command

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

Result: **31 tests passed** in 0.017 s. This validates the selected current
FlowSim/P2D path only; it is not a full repository test suite or a validation of
the sparse replay's event semantics.

## Retained evidence and known limits

- `02_PER_REQUEST_HEADROOM.csv`: 24 rows parsed from existing integrated
  Decode-opportunity results; not a new execution.
- `02_PER_COLLECTIVE_HEADROOM.csv`: 336 matched coalesced phases from the new
  network-only screen.
- `03_NATURAL_EXPOSURE_LEDGER.csv`: prior Azure joins plus the new BurstGPT
  screen; explicitly distinguishes natural serving evidence from non-integrated
  network-only output.
- Each new run marks telemetry truncated at 4,096 rows. Queue telemetry is
  residual fluid backlog. No packet-level or complete link-timeseries claim is
  made.

