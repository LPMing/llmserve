#!/usr/bin/env python3
"""Generate a tiny integrated fixture with two independent EP4 groups.

The serving frontend uses separate logical memory-node entries to keep each
DP group's member ranks contiguous.  ``flowsim_rank_map`` is authoritative for
the physical network placement: four logical Decode TP2 instances share the
same two physical Decode servers and their 2x200-Gbps NIC fabric.
"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "experiments/pd_kv_ep/configs/ep_ep_minimal"
MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"
TOPOLOGY = ROOT / (
    "experiments/pd_kv_ep/configs/large_scale/flowsim/"
    "minimal_1p2d_ep16_single_tor_nvlink.txt")
WORKLOADS = ROOT / "experiments/pd_kv_ep/workloads"


def instance(role, ep_size=1, dp_group=None):
    result = {
        "model_name": MODEL,
        "hardware": "RTXPRO6000",
        "npu_mem": {"mem_size": 96, "mem_bw": 1597, "mem_latency": 0},
        "pd_type": role,
        "num_npus": 2,
        "tp_size": 2,
        "ep_size": ep_size,
    }
    if dp_group is not None:
        result["dp_group"] = dp_group
    return result


def node(instances):
    return {
        "num_instances": len(instances),
        "cpu_mem": {"mem_size": 512, "mem_bw": 256, "mem_latency": 0},
        "instances": instances,
    }


def p2d_logical_map(prefill_count, group_count):
    """Map actual/shadow P ranks and Decode ranks to 24 physical GPU endpoints."""
    result = []
    for index in range(prefill_count):
        # Each TP2 Prefill instance has two sender ranks followed by two legacy
        # P2D receiver/shadow ranks.  The latter alias its paired Decode GPUs.
        decode_group = index // 2
        member = index % 2
        if decode_group >= group_count:
            raise ValueError("Each Decode group needs exactly two Prefill pairs")
        decode_gpu = ((8 if member == 0 else 16) + 2 * decode_group)
        result.extend((2 * index, 2 * index + 1,
                       decode_gpu, decode_gpu + 1))

    for group_index in range(group_count):
        # EP4 = TP2 x two DP members.  Each group spans D0 and D1.
        d0_gpu = 8 + 2 * group_index
        d1_gpu = 16 + 2 * group_index
        result.extend((d0_gpu, d0_gpu + 1, d1_gpu, d1_gpu + 1))
    return result


def build_fixture(name, prefill_count, group_names, paired_group_by_prefill):
    if not TOPOLOGY.is_file():
        raise FileNotFoundError(TOPOLOGY)
    if prefill_count != 2 * len(group_names):
        raise ValueError("Use two Prefill instances per independent EP4 group")

    prefill = [instance("prefill") for _ in range(prefill_count)]
    nodes = [node(prefill)]
    for group_index, group_name in enumerate(group_names):
        # Separate logical nodes preserve group-major instance/rank order.
        # The physical map below places member 0 on D0 and member 1 on D1.
        for member in range(2):
            entry = instance("decode", ep_size=4, dp_group=group_name)
            nodes.append(node([entry]))

    instance_id_by_group = {
        group_name: [prefill_count + 2 * index,
                     prefill_count + 2 * index + 1]
        for index, group_name in enumerate(group_names)
    }
    pairing = {
        str(prefill_id): str(instance_id_by_group[group][member])
        for prefill_id, (group, member) in enumerate(paired_group_by_prefill)
    }

    rank_map = p2d_logical_map(prefill_count, len(group_names))
    total_ranks = 4 * prefill_count + 4 * len(group_names)
    if len(rank_map) != total_ranks:
        raise AssertionError((len(rank_map), total_ranks))

    OUT.mkdir(parents=True, exist_ok=True)
    rank_map_path = OUT / (name + "_logical_to_physical.json")
    rank_map_path.write_text(json.dumps({
        "semantics": (
            "FlowSim logical rank to physical GPU endpoint. Prefill shadow "
            "receiver ranks alias the paired Decode GPU endpoint. Four "
            "logical Decode instances occupy the same physical D0/D1 servers."),
        "logical_to_physical": rank_map,
    }, indent=2) + "\n", encoding="utf-8")

    config_path = OUT / (name + ".json")
    config = {
        "num_nodes": len(nodes),
        "link_bw": 25,
        "link_latency": 5000,
        "flowsim_topology": str(TOPOLOGY.relative_to(ROOT)),
        "flowsim_rank_map": str(rank_map_path.relative_to(ROOT)),
        "pd_pairing": pairing,
        "nodes": nodes,
    }
    config_path.write_text(json.dumps(config, indent=2) + "\n",
                           encoding="utf-8")
    return config_path


def write_workload(path, count, input_tokens=128, output_tokens=32):
    rows = [
        {"input_toks": input_tokens, "output_toks": output_tokens,
         "arrival_time_ns": 0}
        for _ in range(count)
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows),
                    encoding="utf-8")


def main():
    full_path = build_fixture(
        "two_ep4_groups_full", 4, ["ep_a", "ep_b"],
        [("ep_a", 0), ("ep_a", 1), ("ep_b", 0), ("ep_b", 1)])
    control_path = build_fixture(
        "two_ep4_groups_a_only", 2, ["ep_a"],
        [("ep_a", 0), ("ep_a", 1)])

    WORKLOADS.mkdir(parents=True, exist_ok=True)
    write_workload(WORKLOADS / "two_ep4_groups_full_8req.jsonl", 8)
    write_workload(WORKLOADS / "two_ep4_groups_a_only_4req.jsonl", 4)
    write_workload(WORKLOADS / "two_ep4_groups_full_4req.jsonl", 4)
    write_workload(WORKLOADS / "two_ep4_groups_a_only_2req.jsonl", 2)
    print(json.dumps({
        "full_config": str(full_path.relative_to(ROOT)),
        "a_only_config": str(control_path.relative_to(ROOT)),
        "topology": str(TOPOLOGY.relative_to(ROOT)),
        "workloads": [
            "experiments/pd_kv_ep/workloads/two_ep4_groups_full_8req.jsonl",
            "experiments/pd_kv_ep/workloads/two_ep4_groups_a_only_4req.jsonl",
            "experiments/pd_kv_ep/workloads/two_ep4_groups_full_4req.jsonl",
            "experiments/pd_kv_ep/workloads/two_ep4_groups_a_only_2req.jsonl",
        ],
        "input_tokens": 128,
        "output_tokens": 32,
        "all_bytes_model_derived": True,
    }, indent=2))


if __name__ == "__main__":
    main()
