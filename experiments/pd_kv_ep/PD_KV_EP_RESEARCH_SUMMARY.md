# PD KV–EP Research Summary

This is the compact reproducibility record for the current PD-disaggregated
KV versus Decode-EP study. Detailed replay CSVs, event ledgers, telemetry
logs, and obsolete result directories are intentionally not retained.

## Authoritative experiment configuration

| item | value |
|---|---|
| topology | S16, 16 servers, 128 logical GPUs |
| placement | 64 Prefill GPUs + 64 Decode GPUs; 32 P instances + 32 D instances; TP2 per instance |
| model | Qwen/Qwen3-30B-A3B-Instruct-2507 |
| model MoE | 128 experts, top-k 8, 48 layers |
| EP | EP64, GateRouter-derived A2A_P2P |
| scale-out link | 200 Gbps per endpoint NIC |
| parallel leaf-spine representation | 16 x 200 Gbps aggregate directional fluid capacity per parallel pair; one endpoint flow remains limited by its 200 Gbps endpoint path |
| P2D mode | LAYERWISE, 48 layers x 2 TP shards per P2D request |
| topology policy | DEFAULT_RR / spread P2D destination placement |
| FlowSim policy | FAIR, EP_FIRST, KV_FIRST only |
| EP timing | 5 ms EP bin; no additional FlowSim EP window coalescing |
| byte source | model-derived from input tokens and GateRouter routing |
| synthetic byte override | false |
| queue semantics | analytical residual fluid backlog; not packet-buffer occupancy, ECN, PFC, drops, or DCQCN |

The topology and model configuration are retained under
`experiments/pd_kv_ep/configs/large_scale/`.  The workload generator and the
three source workload manifests are retained under
`experiments/pd_kv_ep/scripts/` and `experiments/pd_kv_ep/workloads/autonomous/`.

## Heterogeneous 512-request workload

Every workload has 256 active Decode requests and 256 new P2D requests.
Decode requests use 128 input tokens and 64 output tokens. P2D requests arrive
at 20 ms and use either 2,048 or 8,192 input tokens. The KV bytes are derived
by the replay builder; they are not specified directly.

Exact integer ratios for 256 P2D requests are:

| profile | 2,048-token small KV | 8,192-token large KV |
|---|---:|---:|
| small-majority | 205 (80.08%) | 51 (19.92%) |
| mixed | 128 (50%) | 128 (50%) |
| large-majority | 51 (19.92%) | 205 (80.08%) |

Source files:

- `workloads/autonomous/ep64_512_heterogeneous_small_majority.jsonl`
- `workloads/autonomous/ep64_512_heterogeneous_mixed.jsonl`
- `workloads/autonomous/ep64_512_heterogeneous_large_majority.jsonl`
- corresponding `.manifest.json` files

## FlowSim network results

Each row reports the arithmetic mean and P99. EP metrics are over recorded
collective CCT rows. KV metrics are request-level FCTs over P2D requests only;
Decode-only requests are excluded. A request KV FCT is the last required KV
flow completion minus the first requested KV start, not a sum of flow delays.

### Small-KV-majority: 205 small / 51 large

| policy | EP mean (ms) | EP P99 (ms) | all-KV mean | all-KV P99 | small-KV mean | small-KV P99 | large-KV mean | large-KV P99 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| FAIR | 1.313173 | 3.718516 | 85.679816 | 144.465193 | 71.105697 | 72.062017 | 144.262057 | 144.465193 |
| EP_FIRST | 0.677393 | 1.026633 | 86.083806 | 144.465193 | 71.610192 | 72.074511 | 144.262057 | 144.465193 |
| KV_FIRST | 25.412900 | 108.200026 | 78.736237 | 144.465193 | 62.434692 | 62.651571 | 144.262057 | 144.465193 |

### Mixed: 128 small / 128 large

| policy | EP mean (ms) | EP P99 (ms) | all-KV mean | all-KV P99 | small-KV mean | small-KV P99 | large-KV mean | large-KV P99 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| FAIR | 1.699319 | 2.952889 | 125.706364 | 183.275966 | 68.136762 | 68.136762 | 183.275966 | 183.275966 |
| EP_FIRST | 0.677393 | 1.026633 | 125.710350 | 183.275975 | 68.144725 | 68.144725 | 183.275975 | 183.275975 |
| KV_FIRST | 66.822957 | 179.878423 | 110.603943 | 159.620088 | 61.587799 | 61.587799 | 159.620088 | 159.620088 |

### Large-KV-majority: 51 small / 205 large

| policy | EP mean (ms) | EP P99 (ms) | all-KV mean | all-KV P99 | small-KV mean | small-KV P99 | large-KV mean | large-KV P99 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| FAIR | 3.174256 | 4.996715 | 213.519424 | 258.344897 | 68.509166 | 68.760764 | 249.595147 | 258.344897 |
| EP_FIRST | 0.677393 | 1.026633 | 213.051352 | 258.421862 | 68.546264 | 68.881190 | 249.001398 | 258.421862 |
| KV_FIRST | 132.734165 | 256.230500 | 187.982125 | 228.616859 | 62.307233 | 62.546429 | 219.247586 | 228.616859 |

## Interpretation

1. Heterogeneous request lengths create a real request-level KV FCT
   distribution. The earlier homogeneous workload had one positive KV FCT
   value because all P2D requests had identical size and timing.
2. Increasing the large-KV population increases both the aggregate KV FCT and
   FAIR EP CCT. The effect is visible in the means as well as the tail.
3. EP_FIRST protects EP strongly, but in these spread runs it has little
   additional KV cost relative to FAIR. This remains a network-level result;
   it is not an integrated TTFT claim.
4. KV_FIRST improves KV completion, especially for the large-KV population,
   but produces a large EP CCT penalty. In the large-majority workload its EP
   mean is 132.734 ms versus 3.174 ms for FAIR.
5. The preferred static policy therefore depends on whether the workload is
   Decode/EP critical or KV critical, but the current experiment is still a
   FlowSim network replay and must not be reported as TTFT/TBT/SLO evidence.

## Prior high-concurrency network conclusion retained

The previous homogeneous S16-512 fan-in16 control used the same requests and
bytes but concentrated P2D destinations on one Decode leaf. Under FAIR it
changed EP CCT P99 from 4.385 ms to 13.212 ms and KV FCT P99 from 74.511 ms to
148.277 ms. The candidate mechanism is high-concurrency P2D receiver/path
polarization amplifying both the last-KV-shard barrier and the Decode EP
collective barrier. This is a network-level motivation candidate, not yet a
serving-level PASS.

## Reproduction commands

Generate each workload:

```bash
python3 experiments/pd_kv_ep/scripts/generate_heterogeneous_ep64_workload_exact.py \
  --profile small_majority \
  --output experiments/pd_kv_ep/workloads/autonomous/ep64_512_heterogeneous_small_majority.jsonl \
  --manifest experiments/pd_kv_ep/workloads/autonomous/ep64_512_heterogeneous_small_majority.manifest.json
```

Use the same command with `mixed` and `large_majority`. Build the replay with
`build_model_derived_replay.py --scale S16_EP64 --num-reqs 512
--pd-kv-transfer-mode LAYERWISE --ep-realization GATE_ROUTER_A2A_P2P
--traffic-class FULL`, then run `run_flowsim_replay.py` three times with
`--policy FAIR`, `--policy EP_FIRST`, and `--policy KV_FIRST`.

## Cleanup policy

The raw contents of `experiments/pd_kv_ep/results/` are disposable artifacts:
event ledgers, per-flow CSVs, telemetry JSONL, ASTRA logs, old small-scale
experiments, and duplicate policy runs. They are removed after this summary is
written. Source code, topology/model configs, the three heterogeneous input
workloads, workload manifests, and real source traces are retained.
