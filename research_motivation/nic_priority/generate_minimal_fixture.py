#!/usr/bin/env python3
"""Generate small model-derived shared-NIC FlowSim fixtures.

Physical cluster: 4 Prefill + 2 Decode servers; 8 GPUs and 2 x 200G NICs
per server. Each independent EP4 group is pinned to one NIC rail; one P2D
cohort targets each rail. Bytes come from Qwen3 model/serving
semantics, never from a byte override.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research_motivation/nic_priority/generated"
MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"
HARDWARE = "RTXPRO6000"
P_SERVER_COUNTS = (8, 8, 8, 2)
GPU_BASES = (0, 8, 16, 24, 32, 40)
GPU_TO_NIC_GBPS = 7200
NIC_GBPS = 200

# Logical Decode instance IDs after the 26 Prefill instances.
D0A0, D0A1, D1A0, D1A1 = 26, 27, 28, 29
D0B0, D0B1, D1B0, D1B1 = 30, 31, 32, 33
DECODE_GPU = {
    # Pin all four ranks of group A to rail 0 and all four ranks of group B
    # to rail 1. Each rail still has two GPUs/server for its EP4 group.
    D0A0: 32, D0A1: 33, D1A0: 40, D1A1: 41,
    D0B0: 36, D0B1: 37, D1B0: 44, D1B1: 45,
}
DECODE_ORDER = (D0A0, D0A1, D1A0, D1A1, D0B0, D0B1, D1B0, D1B1)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def instance(role, ep_size=1, dp_group=None):
    result = {
        "model_name": MODEL, "hardware": HARDWARE,
        "npu_mem": {"mem_size": 96, "mem_bw": 1597, "mem_latency": 0},
        "pd_type": role, "num_npus": 1, "tp_size": 1, "ep_size": ep_size,
        "max_num_seqs": 8, "max_num_batched_tokens": 2048,
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


def prefill_gpu(prefill_id):
    offset = int(prefill_id)
    for server, count in enumerate(P_SERVER_COUNTS):
        if offset < count:
            return GPU_BASES[server] + offset
        offset -= count
    raise IndexError(prefill_id)


def pairing(candidate_count):
    # The first eight requests seed every rank of both independent EP4 groups.
    result = {
        0: D0A0, 1: D0A1, 2: D1A0, 3: D1A1,
        4: D0B0, 5: D0B1, 6: D1B0, 7: D1B1,
    }
    rail0_count = (candidate_count + 1) // 2 if candidate_count >= 16 else candidate_count
    # Keep every configured Prefill instance paired even when a particular
    # workload uses fewer than the maximum number of candidate requests.
    for offset in range(18):
        p = 8 + offset
        if offset < rail0_count:
            local = offset
            result[p] = D0A0 if local % 2 == 0 else D0A1
        else:
            local = offset - rail0_count
            result[p] = D0B0 if local % 2 == 0 else D0B1
    return result


def write_topology(path):
    nic_base, tor = 48, 60
    local_base, node_count = 61, 67
    switch_ids = list(range(48, 60)) + [60] + list(range(61, 67))
    edges = []
    for server in range(6):
        for local in range(8):
            gpu = GPU_BASES[server] + local
            nic = nic_base + 2 * server + local // 4
            local_switch = local_base + server
            edges.append((gpu, nic, GPU_TO_NIC_GBPS, "0.0001ms"))
            edges.append((gpu, local_switch, GPU_TO_NIC_GBPS, "0.0001ms"))
        edges.append((nic_base + 2 * server, nic_base + 2 * server + 1,
                      GPU_TO_NIC_GBPS, "0.0001ms"))
    for nic in range(nic_base, nic_base + 12):
        edges.append((nic, tor, NIC_GBPS, "0.005ms"))
    if len(edges) != 114:
        raise AssertionError("topology link count changed")
    with path.open("w", encoding="utf-8") as stream:
        stream.write("%d %d %d\n" % (node_count, len(switch_ids), len(edges)))
        stream.write("%s\n" % " ".join(map(str, switch_ids)))
        for src, dst, rate, latency in edges:
            stream.write("%d %d %dGbps %s 0\n" %
                         (src, dst, rate, latency))


def rank_map(pairs):
    ranks = []
    for p in range(26):
        ranks.extend((prefill_gpu(p), DECODE_GPU[pairs[p]]))
    ranks.extend(DECODE_GPU[index] for index in DECODE_ORDER)
    if len(ranks) != 60:
        raise AssertionError("expected 60 logical ranks")
    return ranks


def cluster_config(topology_path, rank_path, pairs):
    nodes = []
    for count in P_SERVER_COUNTS:
        nodes.append(node([instance("prefill") for _ in range(count)]))
    # Group-major D0/D1 node order; two TP1 instances per node form EP4.
    for group in ("ep_a", "ep_b"):
        nodes.append(node([instance("decode", ep_size=4, dp_group=group)
                           for _ in range(2)]))
        nodes.append(node([instance("decode", ep_size=4, dp_group=group)
                           for _ in range(2)]))
    return {
        "num_nodes": len(nodes), "link_bw": 25, "link_latency": 5000,
        "flowsim_topology": str(topology_path.relative_to(ROOT)),
        "flowsim_rank_map": str(rank_path.relative_to(ROOT)),
        "pd_pairing": {str(k): str(v) for k, v in pairs.items()},
        "nodes": nodes,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--candidate-arrival-ns", type=int, default=-1)
    parser.add_argument("--candidate-count", type=int,
                        choices=(0, 8, 9, 16, 18),
                        default=0)
    parser.add_argument("--medium-candidates-per-rail", type=int, default=0)
    parser.add_argument("--seed-output", type=int, default=64)
    parser.add_argument("--candidate-output", type=int, default=1)
    args = parser.parse_args()
    if args.candidate_count and args.candidate_arrival_ns < 0:
        raise ValueError("candidate arrival must be event-derived and nonnegative")
    if args.candidate_count not in (0, 8, 9, 16, 18):
        raise ValueError("candidate count must be 0, 8, 9, 16, or 18")
    rail0_count = ((args.candidate_count + 1) // 2
                   if args.candidate_count >= 16 else args.candidate_count)
    rail1_count = (args.candidate_count // 2
                   if args.candidate_count >= 16 else 0)
    if args.medium_candidates_per_rail > min(rail0_count,
                                              rail1_count or rail0_count):
        raise ValueError("medium-candidates-per-rail exceeds an active rail's request count")

    OUT.mkdir(parents=True, exist_ok=True)
    topology_path = OUT / "topology_4p2d_200g_single_tor.txt"
    rank_path = OUT / "logical_to_physical.json"
    config_path = OUT / "cluster_4p2d_ep4.json"
    workload_path = OUT / (args.name + ".jsonl")
    manifest_path = OUT / (args.name + "_manifest.json")
    pairs = pairing(args.candidate_count)
    write_topology(topology_path)
    rank_path.write_text(json.dumps({
        "semantics": (
            "Logical rank -> physical GPU endpoint; P2D shadow ranks alias "
            "their paired Decode GPU. EP group A uses D0/D1 rail 0; group B "
            "uses D0/D1 rail 1."),
        "logical_to_physical": rank_map(pairs),
    }, indent=2) + "\n", encoding="utf-8")
    config_path.write_text(json.dumps(
        cluster_config(topology_path, rank_path, pairs), indent=2) + "\n",
        encoding="utf-8")

    rows = [{"input_toks": 128, "output_toks": args.seed_output,
             "arrival_time_ns": 0} for _ in range(8)]
    if args.candidate_count:
        for offset in range(args.candidate_count):
            rail_count = rail0_count if offset < rail0_count else rail1_count
            local = offset if offset < rail0_count else offset - rail0_count
            is_medium = (
                args.medium_candidates_per_rail > 0 and
                local >= rail_count - args.medium_candidates_per_rail)
            rows.append({
                "input_toks": 1024 if is_medium else 2048,
                "output_toks": args.candidate_output,
                "arrival_time_ns": args.candidate_arrival_ns,
            })
    workload_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8")

    manifest = {
        "label": "CONTROLLED_MODEL_DERIVED_WORKLOAD",
        "model": MODEL, "hardware_profile": HARDWARE,
        "topology": str(topology_path.relative_to(ROOT)),
        "cluster_config": str(config_path.relative_to(ROOT)),
        "rank_map": str(rank_path.relative_to(ROOT)),
        "workload": str(workload_path.relative_to(ROOT)),
        "physical_servers": {"prefill": 4, "decode": 2},
        "gpus_per_server": 8, "nics_per_server": 2,
        "nic_gbps": 200, "gpus_per_nic": 4,
        "decode_ep_groups": 2, "ep_degree_each": 4,
        "seed_requests": 8, "candidate_requests": args.candidate_count,
        "candidate_arrival_ns": args.candidate_arrival_ns,
        "seed_input_toks": 128, "seed_output_toks": args.seed_output,
        "candidate_input_toks": 2048,
        "candidate_medium_input_toks": 1024,
        "medium_candidates_per_rail": args.medium_candidates_per_rail,
        "candidate_output_toks": args.candidate_output,
        "candidate_rail_split": [
            (args.candidate_count + 1) // 2
            if args.candidate_count >= 16 else args.candidate_count,
            args.candidate_count // 2 if args.candidate_count >= 16 else 0,
        ],
        "hashes": {
            "topology": sha256(topology_path), "rank_map": sha256(rank_path),
            "cluster_config": sha256(config_path),
            "workload": sha256(workload_path),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n",
                              encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
