#!/usr/bin/env python3
"""Generate a model-derived multi-Prefill fixture for Batch-Miss validation.

Physical topology: four Prefill servers and two Decode servers, each with
8 GPUs and two 200-Gbps NIC rails (four GPUs per rail).  The configured
workload uses 26 Prefill instances and eight TP1 Decode instances arranged as
two independent EP4 groups.  The first 32 requests seed Decode; the next
candidate cohort is routed to four D0 Decode instances on the same 200G rail.

No communication bytes are overridden.  A negative candidate-arrival value
emits only the calibration cohort; otherwise it appends model-derived P2D
requests at the requested serving-layer arrival time.
"""

import argparse
import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research_motivation/batch_miss/multiserver_200g"
MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"
HARDWARE = "RTXPRO6000"
GPU_TO_NIC_GBPS = 7200
NIC_GBPS = 200
SERVER_GPU_BASES = (0, 8, 16, 24, 32, 40)
P_SERVER_COUNTS = (8, 8, 8, 2)
P_COUNT = sum(P_SERVER_COUNTS)

# Decode instance IDs follow the 26 Prefill instances.  Each EP4 group has
# two D0 members followed by two D1 members; the rank map places both D0
# members on D0 rail 0 and both D1 members on D1 rail 0.
D0_A0, D0_A1, D1_A0, D1_A1 = 26, 27, 28, 29
D0_B0, D0_B1, D1_B0, D1_B1 = 30, 31, 32, 33
DECODE_PHYSICAL_GPU = {
    D0_A0: 32, D0_A1: 33, D1_A0: 40, D1_A1: 41,
    D0_B0: 34, D0_B1: 35, D1_B0: 42, D1_B1: 43,
}


def _instance(role, ep_size=1, dp_group=None):
    result = {
        "model_name": MODEL,
        "hardware": HARDWARE,
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


def _prefill_gpu(instance_id):
    server_index = 0
    local_gpu = instance_id
    for count in P_SERVER_COUNTS:
        if local_gpu < count:
            return SERVER_GPU_BASES[server_index] + local_gpu
        local_gpu -= count
        server_index += 1
    raise IndexError(instance_id)


def _pairing():
    pairing = {}
    # Initial requests 0..5 are directed to D1 and repeat twice because the
    # 32-request seed cohort wraps RR over 26 Prefill schedulers.
    for p_id, d_id in ((0, D1_A0), (1, D1_A0),
                       (2, D1_A1), (3, D1_A1),
                       (4, D1_B0), (5, D1_B1)):
        pairing[p_id] = d_id

    # Candidate request IDs 32..40 start at Prefill scheduler 6 (32 mod 26)
    # and map to D0 as 3/2/2/2 requests across four scheduler instances.
    for p_id in (6, 7, 8):
        pairing[p_id] = D0_A0
    for p_id in (9, 10):
        pairing[p_id] = D0_A1
    for p_id in (11, 12):
        pairing[p_id] = D0_B0
    for p_id in (13, 14):
        pairing[p_id] = D0_B1

    # Remaining seed schedulers target D1.  Their request counts are balanced
    # over the four D1 members, while preserving the same two EP4 groups.
    for p_id in (15, 16, 17):
        pairing[p_id] = D1_A0
    for p_id in (18, 19, 20):
        pairing[p_id] = D1_A1
    for p_id in (21, 22, 23):
        pairing[p_id] = D1_B0
    for p_id in (24, 25):
        pairing[p_id] = D1_B1
    if sorted(pairing) != list(range(P_COUNT)):
        raise AssertionError("pairing must cover every Prefill instance")
    return pairing


def _rank_map(pairing):
    ranks = []
    for p_id in range(P_COUNT):
        ranks.append(_prefill_gpu(p_id))
        ranks.append(DECODE_PHYSICAL_GPU[pairing[p_id]])
    ranks.extend(DECODE_PHYSICAL_GPU[index] for index in (
        D0_A0, D0_A1, D1_A0, D1_A1,
        D0_B0, D0_B1, D1_B0, D1_B1))
    if len(ranks) != 2 * P_COUNT + 8:
        raise AssertionError("logical map has wrong rank count")
    return ranks


def _write_topology(path):
    gpu_count = 48
    nic_base = gpu_count
    tor = nic_base + 12
    local_base = tor + 1
    node_count = local_base + 6
    switch_ids = list(range(nic_base, nic_base + 12)) + [tor]
    switch_ids += list(range(local_base, local_base + 6))
    edges = []
    for server in range(6):
        for local_gpu in range(8):
            gpu = SERVER_GPU_BASES[server] + local_gpu
            nic = nic_base + 2 * server + local_gpu // 4
            local_switch = local_base + server
            edges.append((gpu, nic, GPU_TO_NIC_GBPS, "0.0001ms"))
            edges.append((gpu, local_switch, GPU_TO_NIC_GBPS, "0.0001ms"))
        edges.append((nic_base + 2 * server,
                      nic_base + 2 * server + 1,
                      GPU_TO_NIC_GBPS, "0.0001ms"))
    for nic in range(nic_base, nic_base + 12):
        edges.append((nic, tor, NIC_GBPS, "0.005ms"))
    if len(edges) != 114 or len(switch_ids) != 19:
        raise AssertionError((len(edges), len(switch_ids)))
    with path.open("w", encoding="utf-8") as stream:
        stream.write("%d %d %d\n" % (node_count, len(switch_ids), len(edges)))
        stream.write("%s\n" % " ".join(map(str, switch_ids)))
        for src, dst, rate, latency in edges:
            stream.write("%d %d %dGbps %s 0\n" %
                         (src, dst, rate, latency))


def _cluster_config(topology_path, rank_map_path, pairing):
    nodes = []
    for count in P_SERVER_COUNTS:
        nodes.append(_node([_instance("prefill") for _ in range(count)]))
    # Group-major ordering is required by the simulator's communicator layout.
    nodes.extend((
        _node([_instance("decode", ep_size=4, dp_group="ep_a")
               for _ in range(2)]),
        _node([_instance("decode", ep_size=4, dp_group="ep_a")
               for _ in range(2)]),
        _node([_instance("decode", ep_size=4, dp_group="ep_b")
               for _ in range(2)]),
        _node([_instance("decode", ep_size=4, dp_group="ep_b")
               for _ in range(2)]),
    ))
    return {
        "num_nodes": len(nodes),
        "link_bw": 50,
        "link_latency": 5000,
        "flowsim_topology": str(topology_path.relative_to(ROOT)),
        "flowsim_rank_map": str(rank_map_path.relative_to(ROOT)),
        "pd_pairing": {str(k): str(v) for k, v in pairing.items()},
        "nodes": nodes,
    }


def _write_workload(path, candidate_arrival_ns, candidate_count,
                    seed_count, seed_output, candidate_input, candidate_output):
    rows = [{"input_toks": 128, "output_toks": seed_output,
             "arrival_time_ns": 0} for _ in range(seed_count)]
    if candidate_arrival_ns >= 0:
        rows.extend({"input_toks": candidate_input,
                     "output_toks": candidate_output,
                     "arrival_time_ns": candidate_arrival_ns}
                    for _ in range(candidate_count))
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-arrival-ns", type=int, default=-1,
                        help="negative emits only R0 calibration requests")
    parser.add_argument("--candidate-count", type=int, default=9)
    parser.add_argument("--seed-count", type=int, default=32)
    parser.add_argument("--seed-output", type=int, default=64)
    parser.add_argument("--candidate-input", type=int, default=2048)
    parser.add_argument("--candidate-output", type=int, default=8)
    parser.add_argument("--name", default="admission_miss")
    args = parser.parse_args()
    if args.seed_count != 32 or P_COUNT != 26 or args.candidate_count > 9:
        raise ValueError(
            "The audited request-to-instance map requires seed-count=32, "
            "26 Prefill instances, and candidate-count<=9")

    OUT.mkdir(parents=True, exist_ok=True)
    topology_path = OUT / "six_server_200g_single_tor.txt"
    pairing = _pairing()
    rank_map_path = OUT / "logical_to_physical.json"
    config_path = OUT / "cluster.json"
    manifest_path = OUT / "manifest.json"
    workload_path = OUT / (args.name + ".jsonl")

    _write_topology(topology_path)
    rank_map_path.write_text(json.dumps({
        "semantics": (
            "FlowSim logical rank to physical GPU endpoint; each prefill "
            "shadow receiver aliases its paired Decode GPU"),
        "logical_to_physical": _rank_map(pairing),
    }, indent=2) + "\n", encoding="utf-8")
    config_path.write_text(json.dumps(_cluster_config(
        topology_path, rank_map_path, pairing), indent=2) + "\n",
        encoding="utf-8")
    _write_workload(
        workload_path, args.candidate_arrival_ns, args.candidate_count,
        args.seed_count, args.seed_output, args.candidate_input,
        args.candidate_output)

    manifest = {
        "purpose": "quantitative, integrated Network-Induced Decode Batch Admission Miss gate",
        "model": MODEL,
        "hardware_profile": HARDWARE,
        "physical_servers": {"prefill": 4, "decode": 2},
        "physical_gpus": 48,
        "gpus_per_server": 8,
        "nics_per_server": 2,
        "nic_rate_gbps": NIC_GBPS,
        "gpus_per_nic": 4,
        "server_aggregate_scaleout_gbps": 400,
        "prefill_instances": P_COUNT,
        "decode_instances": 8,
        "decode_ep_groups": 2,
        "ep_degree_per_group": 4,
        "decode_group_physical_ranks": {
            "ep_a": [DECODE_PHYSICAL_GPU[x] for x in
                     (D0_A0, D0_A1, D1_A0, D1_A1)],
            "ep_b": [DECODE_PHYSICAL_GPU[x] for x in
                     (D0_B0, D0_B1, D1_B0, D1_B1)],
        },
        "rank_count": 2 * P_COUNT + 8,
        "rank_map": str(rank_map_path.relative_to(ROOT)),
        "topology": str(topology_path.relative_to(ROOT)),
        "cluster_config": str(config_path.relative_to(ROOT)),
        "workload": str(workload_path.relative_to(ROOT)),
        "pairing": {str(k): str(v) for k, v in pairing.items()},
        "candidate_arrival_ns": args.candidate_arrival_ns,
        "candidate_count": args.candidate_count,
        "seed_count": args.seed_count,
        "all_communication_bytes_model_derived": True,
        "network_model": "FlowSim directed fluid max-min, shared 200-Gbps NIC uplinks; no packet queue/ECN/PFC claims",
        "candidate_routing": (
            "RR sends seed request indices 0..31 across 26 prefill schedulers; "
            "candidate indices 32..40 map to P6..P14, all paired to D0"),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n",
                             encoding="utf-8")
    print(json.dumps({
        "manifest": str(manifest_path.relative_to(ROOT)),
        "config": str(config_path.relative_to(ROOT)),
        "topology": str(topology_path.relative_to(ROOT)),
        "rank_map_length": len(_rank_map(pairing)),
        "workload_requests": args.seed_count + (
            args.candidate_count if args.candidate_arrival_ns >= 0 else 0),
    }, indent=2))


if __name__ == "__main__":
    main()
