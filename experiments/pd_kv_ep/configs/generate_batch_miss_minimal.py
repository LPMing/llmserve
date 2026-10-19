#!/usr/bin/env python3
"""Generate the minimal rank-mapped 1P2D / EP4 FlowSim fixture.

The physical topology is the already-audited 3-server, 8-GPU/server,
2x200-Gbps-rail topology. Four active Prefill GPUs use P0 rail 0; four Decode
EP ranks are split across D0 and D1 on rail 0. The other physical GPUs/rails
remain represented in the topology but are not assigned simulator ranks.
"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "research_motivation/batch_miss"
MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"
TOPOLOGY = ROOT / (
    "experiments/pd_kv_ep/configs/large_scale/flowsim/"
    "minimal_1p2d_ep16_single_tor_nvlink.txt")


def _instance(role, node_id, ep_size=1, dp_group=None):
    result = {
        "model_name": MODEL,
        "hardware": "RTXPRO6000",
        "npu_mem": {"mem_size": 96, "mem_bw": 1597, "mem_latency": 0},
        "pd_type": role,
        "num_npus": 1,
        "tp_size": 1,
        "ep_size": ep_size,
        "max_num_seqs": 8,
        "max_num_batched_tokens": 2048,
    }
    if dp_group is not None:
        result["dp_group"] = dp_group
    return result


def _node(instances):
    return {
        "num_instances": len(instances),
        "cpu_mem": {"mem_size": 512, "mem_bw": 256, "mem_latency": 0},
        "instances": instances,
    }


def main():
    if not TOPOLOGY.is_file():
        raise FileNotFoundError(TOPOLOGY)
    OUT.mkdir(parents=True, exist_ok=True)

    # Logical ranks 0..7 are four TP1 Prefill instances, each followed by its
    # legacy P2D shadow receiver. Ranks 8..11 are one four-member EP group.
    logical_to_physical = [0, 8, 1, 9, 2, 16, 3, 17, 8, 9, 16, 17]
    rank_map_path = OUT / "minimal_1p2d_ep4_rank_map.json"
    rank_map_path.write_text(json.dumps({
        "semantics": (
            "logical rank to physical GPU endpoint; P2D shadow ranks alias "
            "their paired Decode GPU and do not add a NIC or GPU"),
        "logical_to_physical": logical_to_physical,
    }, indent=2) + "\n", encoding="utf-8")

    prefill = [_instance("prefill", 0) for _ in range(4)]
    decode = [_instance("decode", node_id, ep_size=4,
                        dp_group="decode_ep4")
              for node_id in (1, 1, 2, 2)]
    config = {
        "num_nodes": 3,
        "link_bw": 50,
        "link_latency": 5000,
        "flowsim_topology": str(TOPOLOGY.relative_to(ROOT)),
        "flowsim_rank_map": str(rank_map_path.relative_to(ROOT)),
        "pd_pairing": {"0": "4", "1": "5", "2": "6", "3": "7"},
        "nodes": [
            _node(prefill),
            _node(decode[:2]),
            _node(decode[2:]),
        ],
    }
    config_path = OUT / "minimal_1p2d_ep4_config.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps({
        "config": str(config_path.relative_to(ROOT)),
        "rank_map": str(rank_map_path.relative_to(ROOT)),
        "topology": str(TOPOLOGY.relative_to(ROOT)),
        "logical_ranks": 12,
        "physical_gpu_endpoints_used": sorted(set(logical_to_physical)),
        "rank_dims_expected": [1, 4, 3],
        "ep_group": "4 TP1 instances across D0/D1",
        "physical_scaleout": "2 x 200 Gbps per server; four GPUs/rail",
    }, indent=2))


if __name__ == "__main__":
    main()
