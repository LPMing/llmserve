# 03 — Rank / GPU / server / NIC / path audit

## S16 artifact inspection

Files inspected:

- `experiments/pd_kv_ep/configs/large_scale/s16_8p8d_ep64_shared_2nic_qwen.json`
- `experiments/pd_kv_ep/configs/large_scale/s16_8p8d_ep64_shared_2nic_manifest.json`
- `experiments/pd_kv_ep/configs/large_scale/s16_8p8d_ep64_shared_2nic_rank_metadata.csv`
- `experiments/pd_kv_ep/configs/large_scale/generate_s16_8p8d_ep64_shared_2nic.py`
- `experiments/pd_kv_ep/configs/large_scale/ns3/s16_8p8d_ep64_shared_2nic_200g_clos.txt`
- `serving/core/config_builder.py::_resolve_dp_groups()` and config rank assignment;
- `serving/__main__.py` backend selection and FlowSim topology/map requirements.

The manifest's physical topology description is internally coherent as a
physical graph: 128 GPU IDs, 32 NIC nodes, six switches, 208 directed-listed
physical links; four GPU ranks attach to each 200-Gbps NIC through high-rate
local links; two 200-Gbps NICs/server provide 400 Gbps aggregate; leaf-spine
parallel links are preserved. The aggregate is server/NIC capacity, not a
per-GPU 400-Gbps claim.

## Logical rank-count mismatch

`config_builder.py` expands every Prefill instance to `2 * num_npus` ASTRA
ranks, reserving shadow ranks for the legacy P/D representation. For the
artifact above:

| Resource count | Derived value |
|---|---:|
| Prefill instances | 32 × 2 GPUs × 2 (compute + shadow) = 128 logical ranks |
| Decode instances | 32 × 2 GPUs = 64 logical ranks |
| ASTRA logical rank count | **192** |
| Physical GPU endpoints in topology | **128** (IDs 0–127) |
| Physical NIC node IDs | 128–159 |
| Leaf/spine switch node IDs | 160–165 |

The cluster JSON has `ns3_topology`, but no `flowsim_topology` or
`flowsim_rank_map`. The FlowSim CLI requires both (unless supplied separately
on its command line); `ns3_topology` is not automatically a FlowSim topology
fallback. The physical topology file is a graph with GPU nodes 0–127 and NIC
nodes starting at 128; it is not a valid identity map for 192 ASTRA ranks.
Without an explicit, audited mapping, logical ranks 128+ can alias NIC/switch
nodes or lie outside the intended GPU endpoint set. This blocks a claim that
the S16 artifact's EP/P2D traffic was routed over its declared GPU/NIC map.

The rank metadata generator also writes `ep_rank = gpu` for Decode ranks. This
repeats values 0–7 on every server; it is a local GPU index, not a unique EP64
ordinal. The unique ordinal could be derived from Decode instance order and
TP rank, but the generated column does not encode that mapping and must not be
treated as authoritative EP-rank provenance.

## Path and capacity status

| Mapping property | Status |
|---|---|
| GPU→server / role / local TP rank | Present in generated metadata |
| GPU→shared NIC | Explicit in topology generator (`gpu // 4`) |
| NIC→leaf physical scale-out link | Explicit, 200 Gbps/NIC |
| Leaf→spine parallel links | Explicit, four physical 200-Gbps links per leaf/spine pair |
| EP global rank→physical GPU | **NOT_VALIDATED**; repeated local `ep_rank` metadata and 192-vs-128 logical/physical count mismatch |
| P2D sender/receiver rank→physical NIC path | **NOT_VALIDATED** for S16 artifact without explicit logical-rank map |
| FlowSim chosen path | FlowSim uses its own graph path selection and requires explicit topology and rank-map inputs; not ECMP/packet hashing |
| Physical packet path/ECMP | Not inferred from this fluid-topology file; requires packet backend validation |

**Gate:** physical NIC/topology resource definition is auditable; the
end-to-end logical-to-physical rank mapping needed for a sparse MoE result is
not. This audit does not repair or rewrite historical topology artifacts.
