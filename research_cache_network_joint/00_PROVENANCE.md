# Provenance and Reproduction Boundary

Date: 2026-10-14 (workspace-local date)  
Repository: `/home/dell/lpm/LLMServingSim`  
Git HEAD: `0c0839aff54ec0abb1810dc09cf3d66f06b1b078`  
Backend for the new runs: integrated FlowSim (fluid, directed-link max-min sharing)  
Native ns-3 for this cache-conditioned study: **not run**.

## Frozen input identity

| Input | SHA-256 |
|---|---|
| Dirty tracked diff (`git diff --binary`) | `e7df10df63f778fbb2e371156e5305190b8a64ee6d9dfd2f9f91fc3ed02da46f` |
| 4P1D config | `a75d43f50e1fff8365529e5f25130ca7b4ec2cd78df6a1bf10dabbb8e5f0a7fd` |
| 4P1D logical/physical map | `e5a9e74cc77feebbfa836ba19aa9e97fe0b9ec86131a2d10b75c5d611708c811` |
| 3P2D config | `c32b4f6b9c629d9943d74658b7e80f55ef2aff4390135ce8ce515704a45e6fd9` |
| 3P2D logical/physical map | `e4fde284347b9865db2ffdd6794ef9d1e4e0348c21bd451f57cd34d90160bca6` |
| Base four-session workload | `2261e7521b1844aa3186a1a78dcdac7407dab402ba4b9ebfa15be601f613faec` |
| 3P2D destination-miss workload | `9b827eade1448f3a5ddaf972854bb25de84d0307b5ada90d33ad17de06cd4762` |
| Partial-hit workload | `8e53304184f80ff4b5446d8df054feeb7b84811469f44b75864d65137ae7b6bf` |
| 4P1D physical topology | `4254141f11f0ea8d03a27f7b1fecbd04e0697327eed61ccb7ec5de3fd2ce2df7` |
| Qwen3 RTXPRO6000 TP2 profile `meta.yaml` | `e755433ea63a19e9d4a4919f04da412807aa520972dc97df3dfb8908b6a70f96` |

Model profile: `Qwen/Qwen3-30B-A3B-Instruct-2507`, BF16, TP2; 48 layers; 4 KV heads; head dimension 128. The request fixture has four full agentic sessions, each with a 4096-token warm-up and a 4105-token, three-output child. The child uses the same 4096-token prefix and adds nine tokens.

## Runtime and verification

Python executable: `/home/lpm/.conda/envs/llmsim-flowsim/bin/python`.  
Focused correctness commands rerun for this report:

```sh
PYTHONPATH=. /home/lpm/.conda/envs/llmsim-flowsim/bin/python research_cache_network_joint/test_decode_handoff_cache_accounting.py
PYTHONPATH=. /home/lpm/.conda/envs/llmsim-flowsim/bin/python research_cache_network_joint/test_destination_prefix_reservation.py
```

Both passed. `git diff --check` passed. The environment used for the simulator replay also set `PYTHONPATH=.:/tmp/llmsim-chakra-shim.TzDOXs`, `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python`, and `FLOWSIM_MAX_TELEMETRY_ROWS=100000`.

## Result files

| Run | Requests | Flows | Scheduler events | Purpose |
|---|---|---|---|---|
| A0 full transfer, 4P1D | `results/a0_4p1d_requests.csv` | `results/a0_4p1d_flows.jsonl` | `results/a0_4p1d_scheduler.jsonl` | Baseline complete-prefix P2D |
| A0 sampler instrumentation | `results/a0_sampler_debug_requests.csv` | `results/a0_sampler_debug_flows.jsonl` | `results/a0_sampler_debug.jsonl` | Distinguish sampler compute completion from P2D graph completion |
| A1 query-only, valid replay | `results/a1r2_4p1d_requests.csv` | `results/a1r2_4p1d_flows.jsonl` | `results/a1r2_4p1d_scheduler.jsonl` | Destination lookup without byte suppression |
| A2 delta, valid replay | `results/a2r1_4p1d_requests.csv` | `results/a2r1_4p1d_flows.jsonl` | `results/a2r1_4p1d_scheduler.jsonl` | Reserve destination prefix and send missing KV |
| A2 sampler instrumentation | `results/a2_sampler_debug_requests.csv` | `results/a2_sampler_debug_flows.jsonl` | `results/a2_sampler_debug.jsonl` | Same first-token semantic audit under DELTA |
| A3 partial hit | `results/a3_partial_requests.csv` | `results/a3_partial_flows.jsonl` | `results/a3_partial_scheduler.jsonl` | 2048-token destination hit |
| A4 destination miss | `results/a4_miss_requests.csv` | `results/a4_miss_flows.jsonl` | `results/a4_miss_scheduler.jsonl` | Full-transfer fallback |
| B1 full-session 3P2D | `results/b1_3p2d_requests.csv` | `results/b1_3p2d_flows.jsonl` | `results/b1_3p2d_scheduler.jsonl` | Static 3P2D from root sessions |
| B2 3P2D DELTA | `results/b2_3p2d_delta_requests.csv` | `results/b2_3p2d_delta_flows.jsonl` | — | Static 3P2D with destination prefix reuse |
| B2 sampler instrumentation | `results/b2_sampler_debug_requests.csv` | `results/b2_sampler_debug_flows.jsonl` | `results/b2_sampler_debug.jsonl` | Verify sampler/P2D ordering in B2 |

The first A1/A2 attempts produced incomplete artifacts and are not used; valid reruns are explicitly named `a1r2` and `a2r1`. Per-run shell command lines were not embedded in the original result artifacts. We therefore identify commands at the replay-family level rather than claim an unrecoverable exact shell transcript. Reproducibility is strong for frozen inputs and outputs, but command-level provenance is incomplete.

## Scope and exclusions

- FlowSim fluid backlog is not packet queue occupancy and provides no ECN/CNP/PFC/DCQCN claim.
- No ns-3 packet replay was run for these configurations; no packet-level result is inferred.
- Four sessions are a controlled correctness/mechanism fixture, not a production trace; no P95/P99 or SLO claim is made.
- The hardware config describes 8-GPU servers with two shared 200-Gbps NICs, but these experiments activate TP2 ranks per instance and map them to the modeled rails. They do **not** exercise all eight GPUs contending for two NICs.
- Existing dirty workspace changes were preserved. No historical result files were removed or overwritten.
