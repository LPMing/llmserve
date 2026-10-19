# Native ns-3 receiver-incast study — provenance

## Scope and outcome

This directory records the packet-level receiver-incast gate and the follow-up
network-only / profile-release tests for the congestion-feedback Serving
scheduling question. It does **not** contain an integrated Serving run or
TTFT/TBT/SLO measurements. Fixed-event replay outputs are network evidence only.

## Code and environment

| Item | Value |
|---|---|
| Repository | `/home/dell/lpm/LLMServingSim` |
| Main repository HEAD | `0c0839aff54ec0abb1810dc09cf3d66f06b1b078` |
| Pre-existing tracked dirty-diff SHA-256 (audited before this task) | `089f3d35d5740b889d4906da48d4ccbf88b1b8ba5d5a048ec16f52806584cfa9` |
| ns-3 replay binary | `astra-sim/extern/network_backend/ns-3/build/scratch/ns3.42-KVEPReplay-optimized` |
| Replay binary SHA-256 | `79f8f6e6dd2fbc6af061e1a11f08dd3431f58bb61a162f06d452beb2589eadea` |
| Python used for audit scripts | Python 3.8.10; `llmsim-flowsim` conda Python 3.10.21 used to build profile-derived events |
| Model config SHA-256 | `0736f3bafb95cc658776c92ab34f5f98d8169634a3a36b84892d71448a1f19d3` |
| Profile `meta.yaml` SHA-256 | `e755433ea63a19e9d4a4919f04da412807aa520972dc97df3dfb8908b6a70f96` |
| Profile TP2 dense CSV SHA-256 | `710f04261d67ec53639095cec91751c9a9dc1aa6f5b335c9decaee4802407633` |

The worktree was already substantially dirty before this task. Those user
changes were preserved. New scripts, fixtures, and reports from this study are
under `research_ns3_incast/`; no unrelated experiment directory was modified or
deleted.

## Authoritative inputs

| Artifact | SHA-256 / notes |
|---|---|
| Calibrated 4P1D topology | `fixtures_rankcap200g/fixtures/4p1d_unique_spines/topology.txt`; `4254141f11f0ea8d03a27f7b1fecbd04e0697327eed61ccb7ec5de3fd2ce2df7` |
| Rank→GPU/server/NIC map | `fixtures_rankcap200g/fixtures/4p1d_unique_spines/rank_to_nic.csv`; `0b4ed9676e19070670a4a164753597cad1e625fbbe40ab80bafa970bc07c9c56` |
| Profile-derived LAYERWISE event ledger | `fixtures_rankcap200g/network_only/layerwise_profiled_4p_v7/events.csv`; `00ba29302252239323840c27d17b9cfcb8feadbf1d4bd3bb84836316625e32b7` |
| Independent theory calculator | `theory_network_bounds.py`; SHA-256 `56c260f0b2d3f11f9c1eb8dc75cb7f2fca215096fa9d3dfc39f2372f37b1fbd4` |
| Event builder | `build_layerwise_profile_replay.py`; SHA-256 `f5a8f4d7f5c7c0ada5f8a534fbaefb9a1f052ed7ecf7c7a9f9a10a02a1b8a36e` |

The model is Qwen3-30B-A3B-Instruct-2507, BF16, 48 layers, 128 experts,
top-k 8, TP2 for P/D KV. The profile-derived ledger uses two 2048-token
Prefill chunks because 2048 is the profiled max-batched-token bound. It creates
768 layer/shard events (4 requests × 48 layers × 2 chunks × 2 TP ranks),
1,610,612,736 application bytes total. Per request, each TP rank sends
201,326,592 B; each layer/chunk/rank event carries 2,097,152 B.

## Topology interpretation

Four Prefill servers and one Decode server each have 8 rank endpoints, mapped
to two shared 200-Gbps NIC aggregation nodes (4 GPU ranks per NIC). Each source
server uses a distinct spine per rail; the four source paths converge only at
the selected Decode leaf→NIC egress. Decode ranks 0–3 use rail 0, ranks 4–7
use rail 1; each of four TP2 Decode instances pairs one rank from each rail.
The GPU-rank→NIC attachment is capped at 200 Gbps in the calibrated fixture so
the RDMA QP's initial rate is the NIC line rate. The four ranks still share
one 200-Gbps NIC uplink; this is not four independent NICs.

Main bottleneck links are link 113 (Decode leaf node 58→NIC node 48) and link
123 (leaf 59→NIC 49), each 200 Gbps. The primary topology has unique source
spines, so its receiver-incast result does not rely on ECMP hash collision.

## Run provenance

Every successful native replay writes a `network_run_manifest.json` with the
binary/config/topology/rank-map/event hashes, exact command, CC mode, packet
size, and wall time. Representative runs:

- `results/RC_N0_cc0`, `RC_N0_cc1`
- `results/RC_N1_TWO_TO_ONE_RECEIVER_NIC_cc0_local`, `...cc1_local`
- `results/RC_N2_cc0`, `RC_N2_cc1`
- `results/RC_N3_FOUR_TO_TWO_RECEIVER_NICS_cc0_local`, `...cc1_local`
- `results/RC_N4_cc0`, `RC_N5_multipath_cc0`
- `results/RC_FULL4_cc0`, `RC_FULL4_cc1`
- `results/ORDER8P2MS_cc0`, `ORDER8P2MS_cc1`
- `results/LAYERWISE4_CC0`, `results/LAYERWISE4_CC1_v3`

The first two attempts to launch the LAYERWISE CC1 wrapper failed before
simulation because the ns-3 config parser requires empty `flow.txt` and
`trace.txt` sentinel files even when the event ledger creates QPs and packet
tracing is disabled. They are retained as failed wrapper attempts; the fixed
runner created a fresh `LAYERWISE4_CC1_v3` directory and completed successfully.
This was not a simulation-result failure.

## Reproduction

Build the profiled event ledger in the configured environment, then run the
network-only CC variants:

```bash
conda run -n llmsim-flowsim python research_ns3_incast/build_layerwise_profile_replay.py \
  --output research_ns3_incast/fixtures_rankcap200g/network_only/layerwise_profiled_4p_v7_rebuilt
python3 research_ns3_incast/run_packet_replay.py \
  --events research_ns3_incast/fixtures_rankcap200g/network_only/layerwise_profiled_4p_v7/events.csv \
  --topology research_ns3_incast/fixtures_rankcap200g/fixtures/4p1d_unique_spines/topology.txt \
  --rank-map research_ns3_incast/fixtures_rankcap200g/fixtures/4p1d_unique_spines/rank_to_nic.csv \
  --output research_ns3_incast/results/NEW_LAYERWISE_CC1 --cc-mode 1
```

The baseline CC0 run used the same runner with `--cc-mode 0`. The independent
single-cut bound is reproduced with:

```bash
python3 research_ns3_incast/theory_network_bounds.py
```

The `NEW_LAYERWISE_CC1` output name must not already exist; the runner refuses
to overwrite it.
