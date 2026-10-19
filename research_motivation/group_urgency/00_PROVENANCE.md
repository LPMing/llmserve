# Provenance and reproduction record

Audit date: 2026-10-12 (UTC date). This package is a bounded retrospective ledger audit and profile-derived theory screen. It does not contain a new FlowSim, ASTRA-Sim, or ns-3 run.

## Source identity and worktree

| Item | Value |
|---|---|
| Repository | `/home/dell/lpm/LLMServingSim` |
| Branch | `main` |
| HEAD | `0c0839aff54ec0abb1810dc09cf3d66f06b1b078` |
| Worktree | Dirty before and during this audit; many simulator, experiment, and research-audit files are modified/untracked. They are preserved and were not reset. |
| This package | New, untracked directory `research_motivation/group_urgency/`; its scripts and reports are part of this work. |
| Simulator code changed by this package | None. |
| New serving/network simulations | None. |

The historical runs predate this package and were produced from a dirty worktree. The exact state is not recoverable as an immutable commit from the retained repository. Accordingly, the results are labeled historical/retrospective and are not presented as a clean-checkout reproduction.

## Model, profile, topology and workload hashes

| Input | SHA-256 |
|---|---|
| `configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json` | `0736f3bafb95cc658776c92ab34f5f98d8169634a3a36b84892d71448a1f19d3` |
| `profiler/perf/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/bf16/meta.yaml` | `e755433ea63a19e9d4a4919f04da412807aa520972dc97df3dfb8908b6a70f96` |
| EP–EP full config `two_ep4_groups_full.json` | `2a91e26179b8e2bace307bde4f8a118d32f984531426e7b120173f679fb3c1fa` |
| Physical rank map `two_ep4_groups_full_logical_to_physical.json` | `d5c18ecd573480f2dc28e1c7f95e09a88f6f70e88197ea9ce3e9d0c9e3e62f54` |
| Single-ToR topology `minimal_1p2d_ep16_single_tor_nvlink.txt` | `3fa000e6ff3b26fb77f00645a0ddac82f993ca0e831e4abd5cd208baa14995ca` |
| EP–EP 8-request workload | `8e6280ae241494e412553dbf6f3dd57221d6a799bb38f1914e0338e09f6ad4f8` |

The named cluster fixture/topology hashes identify retained setup artifacts; they do not imply that the EP–EP run used every generated physical topology artifact as a packet-level topology. The experiment was an integrated FlowSim fixture with the documented logical-to-physical mapping and shared directed cut.

## Historical raw source and compact derivative

The raw full-run FlowSim telemetry was still present in `/tmp` at audit time; it is transient scratch, not a repository archival artifact.

| Artifact | SHA-256 | Use |
|---|---|---|
| `/tmp/ep_ep_minimal_full_telemetry.jsonl` | `8cac497c4cadb960a5c1015114ac1a82bfc75e4ea0ad1508ca75e79cfeb8764d` | 71,424 EP P2P flow events plus P2D events; source for the compact flow and collective ledgers |
| `/tmp/ep_ep_minimal_full_requests.csv` | `fa9340a771c4ad7ca5710cefc735a3b682aafa010e69832d682bded52553ee30` | Request-level serving outputs |

| Durable derived artifact | SHA-256 |
|---|---|
| `01_EP_FLOW_LEDGER.csv` | `21c6a96ef769c6df04c2b93cabb078e322967c45e3e91a2a7d1f9a0220d45e88` |
| `01_EP_PER_GROUP.csv` | `4786e6c7cdd1686c345e1dbbcb1581bb8104d119eb810b9a3706a02ec83c5011` |
| `01_EP_GROUP_REQUESTS.csv` | `3000e19a104fa66eab86a075e79179e18b9571df26d4c65deeee8aa51a2748fd` |
| `01_KV_PER_REQUEST.csv` | `978d85c6f1e3b062435b867befeb28ff79a657d187620885d8f3c9be62c64750` |
| `01_KV_LAYER_EVENTS.csv` | `4f1eefac4598665de0565f193ecdf5b793088b79e21eb93c9cb8d76b1d5d9b94` |
| `02_EP_BATCH_CAPACITY_TABLE.csv` | `565b487cb298919a365f4088c763ffa18d8e2a6eb9ee4b77791da8fff0ecc8b4` |
| `02_EP_CONTEXT_PHASE_OVERLAP.csv` | `dbf9d3ba98b99bfb67525a0134bb2d34906128000046affb294089f5d38eceda` |
| `02_EP_HETEROGENEOUS_GROUP_SCREEN.csv` | `6fe0d1243dd6d8191b6eea40ffe861e38d131aff7e2bcb14afce2d1a407ac934` |
| `08_KV_REQUEST_RESULTS.csv` | `a459470ec79e558437f67c9f5e8c8ce444d5b794bf931d8306626ec6c46997e3` |

The compact per-group CSV contains 11,904 rows plus header across the retained two- and four-request/group experiments; the compact flow CSV contains 71,424 rows plus header. Rebuild commands below regenerate these compact tables from the still-available scratch inputs; once `/tmp` is cleaned, the compact CSVs remain the retained data, but exact re-extraction from raw JSONL will require restoring that raw source.

## Analysis source hashes and commands

| Script | SHA-256 |
|---|---|
| `analyze_existing_ledgers.py` | `ccf57346046fbcde93f5016b013eaac70b7ec4a97470ed602a28fac2ef65e7c7` |
| `compute_ep_batch_capacity.py` | `b105325abfd7ef1ccbec79b3e8c9147694605b4ec78d63a5164cdbf4a3ee71f4` |
| `compute_kv_delay_bounds.py` | `ac8351dee72dff57384e5bdafd6761930a6c01732a8e66d35726d8735db144c3` |

Commands used for the deterministic analyses (the first consumes retained `/tmp` telemetry and requests; the other two consume repository inputs and the existing profile):

```bash
cd /home/dell/lpm/LLMServingSim
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_motivation/group_urgency/analyze_existing_ledgers.py
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_motivation/group_urgency/compute_ep_batch_capacity.py
/home/lpm/.conda/envs/llmsim-flowsim/bin/python research_motivation/group_urgency/compute_kv_delay_bounds.py
```

These are data extraction/profile/arithmetic scripts; none launches a network or serving simulator. The final two produce the recorded profile screens and arithmetic KV-ready bounds. The package also includes `04_SLO_DEFINITION.md`, which records that no externally sourced TBT SLO was available and prevents retrospective threshold selection.

## Physical and collective scope

- Per-server scale-out resources in the fixture: 2 × 200-Gbps NIC-facing rails. The EP–EP flows under study share a 200-Gbps **directed** D0↔D1 ToR-facing cut; the two opposite directions are separate full-duplex resources.
- Two independent EP4 Decode groups; TP2 members on two Decode servers, local EP2 per member. The groups have separate batch/barrier ownership.
- The retained collective realization is ALLGATHER dispatch + REDUCESCATTER combine with BALANCED routing. It is **not** strict sparse GateRouter A2A.
- One group collective has 4 participants and 12 peer flows. Do not infer a separate collective per request.
- FlowSim queue values in this package are analytical residual-fluid backlog, never packet queue occupancy, ECN, PFC, or drops.

## Evidence and reproducibility limitations

1. The historical raw telemetry was a `/tmp` file, not originally committed. This package preserves a compact flow ledger and its checksum, but not the 54-MiB raw JSONL itself.
2. Group B-alone is absent. The matched isolated control exists only for A; a B-alone slowdown must not be invented.
3. EP_FIRST was not run for the two-EP-group scenario. In the code, class-level EP_FIRST cannot distinguish two EP collectives because both belong to the same EP class, but that implementation observation is not a measured EP–EP policy result.
4. No external token SLO was supplied. SLO miss counts and attainment are not measurable from these records.
5. No group-priority network oracle, SRPT/EDF/LLF, or integrated priority policy was run because G1 failed. Their results are `NOT_RUN`, not zero and not inferred.
6. These results support bounded negative motivation evidence for the tested profile, collective, and topology only; they do not prove no such opportunity can exist in all MoE implementations or deployments.
