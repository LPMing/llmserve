#!/usr/bin/env python3
"""Generate the controlled 1P2D / EP16 two-NIC-per-server testbed."""

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "experiments/pd_kv_ep/configs/large_scale"
MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"
GPU_TO_NIC_GBPS = 7200
NIC_GBPS = 200
GPUS_PER_NIC = 4


def _instance(role, tp_size, num_npus, ep_size=1, dp_group=None):
    instance = {
        "model_name": MODEL,
        "hardware": "RTXPRO6000",
        "npu_mem": {"mem_size": 96, "mem_bw": 1597, "mem_latency": 0},
        "pd_type": role,
        "num_npus": num_npus,
        "tp_size": tp_size,
        "ep_size": ep_size,
    }
    if dp_group is not None:
        instance["dp_group"] = dp_group
    return instance


def _node(instances):
    return {
        "num_instances": len(instances),
        "cpu_mem": {"mem_size": 512, "mem_bw": 256, "mem_latency": 0},
        "instances": instances,
    }


def _cluster_config(topology_path):
    prefill = [_instance("prefill", tp_size=1, num_npus=1)
               for _ in range(8)]
    decode_d0 = [_instance("decode", tp_size=2, num_npus=2,
                           ep_size=16, dp_group="decode_ep")
                 for _ in range(4)]
    decode_d1 = [_instance("decode", tp_size=2, num_npus=2,
                           ep_size=16, dp_group="decode_ep")
                 for _ in range(4)]
    return {
        "num_nodes": 3,
        # ASTRA fallback bandwidth is 50 GB/s = 400 Gbps aggregate/server.
        # FlowSim and ns-3 use the explicit two 200-Gbps NIC links below.
        "link_bw": 50,
        "link_latency": 5000,
        "ns3_topology": str(topology_path.resolve().relative_to(ROOT)),
        "nodes": [_node(prefill), _node(decode_d0), _node(decode_d1)],
    }


def _rank_rows():
    rows = []
    rank = 0
    instance_id = 0
    servers = (("P0", "prefill", 8, 1),
               ("D0", "decode", 8, 2),
               ("D1", "decode", 8, 2))
    ep_rank = 0
    for server, role, gpu_count, instance_width in servers:
        for local_gpu in range(gpu_count):
            nic_index = local_gpu // GPUS_PER_NIC
            nic_id = 24 + 2 * (len(rows) // gpu_count) + nic_index
            if role == "prefill":
                owner_instance = local_gpu
                logical_ep_rank = ""
            else:
                owner_instance = local_gpu // instance_width
                logical_ep_rank = ep_rank
                ep_rank += 1
            rows.append({
                "astra_rank": rank,
                "gpu_id": "%s-G%d" % (server, local_gpu),
                "server_id": server,
                "role": role,
                "instance_id": instance_id + owner_instance,
                "tp_rank": local_gpu % instance_width,
                "logical_ep_rank": logical_ep_rank,
                "nic_id": nic_id,
                "nic_rate_gbps": NIC_GBPS,
                "gpus_per_nic": GPUS_PER_NIC,
                "server_aggregate_nic_gbps": 2 * NIC_GBPS,
            })
            rank += 1
        instance_id += gpu_count // instance_width
    if len(rows) != 24 or ep_rank != 16:
        raise AssertionError("rank placement must contain 24 GPUs and EP16")
    return rows


def _topology(rows):
    edges = []
    server_nics = {"P0": (24, 25), "D0": (26, 27), "D1": (28, 29)}
    for row in rows:
        edges.append((int(row["astra_rank"]), int(row["nic_id"]),
                      GPU_TO_NIC_GBPS, "0.0001ms"))
    for nic0, nic1 in server_nics.values():
        edges.append((nic0, nic1, GPU_TO_NIC_GBPS, "0.0001ms"))
    for nic in range(24, 30):
        edges.append((nic, 30, NIC_GBPS, "0.005ms"))
    if len(edges) != 33:
        raise AssertionError("expected 24 GPU attachments, 3 local rails, 6 NIC uplinks")

    topology_path = OUT / "ns3/minimal_1p2d_ep16_2x200g_single_tor.txt"
    topology_path.parent.mkdir(parents=True, exist_ok=True)
    with topology_path.open("w", encoding="utf-8") as stream:
        stream.write("31 1 33\n30\n")
        for src, dst, rate, latency in edges:
            stream.write("%d %d %dGbps %s 0\n" % (src, dst, rate, latency))
    return topology_path


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = _rank_rows()
    topology_path = _topology(rows)

    mapping_path = OUT / "minimal_1p2d_ep16_rank_to_nic.csv"
    with mapping_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    cluster_path = OUT / "minimal_1p2d_ep16_shared_400g.json"
    cluster_path.write_text(json.dumps(_cluster_config(topology_path), indent=2) + "\n",
                            encoding="utf-8")

    pairing = {str(index): str(8 + index) for index in range(8)}
    pairing_path = OUT / "minimal_1p2d_ep16_pairing.json"
    pairing_path.write_text(json.dumps(pairing, indent=2) + "\n", encoding="utf-8")

    manifest = {
        "purpose": "controlled minimal P2D KV versus Decode EP shared-fabric gate",
        "physical_servers": {"P0": 1, "D0": 1, "D1": 1},
        "gpus_per_server": 8,
        "scaleout_nics_per_server": 2,
        "scaleout_nic_rate_gbps": NIC_GBPS,
        "aggregate_scaleout_rate_gbps_per_server": 2 * NIC_GBPS,
        "average_gbps_per_gpu": 2 * NIC_GBPS / 8,
        "gpu_to_nic_group_size": GPUS_PER_NIC,
        "decode_ep_size": 16,
        "logical_ep_ranks_D0": list(range(0, 8)),
        "logical_ep_ranks_D1": list(range(8, 16)),
        "astra_decode_ranks_D0": list(range(8, 16)),
        "astra_decode_ranks_D1": list(range(16, 24)),
        "astra_receiver_mode": "ACTUAL",
        "astra_rank_count": 24,
        "topology": "one ToR, no spine; six independent 200-Gbps NIC uplinks",
        "local_collective_links_gbps": GPU_TO_NIC_GBPS,
        "synthetic_communication_byte_override": False,
        "model": MODEL,
        "model_layers": 48,
        "experts": 128,
        "top_k": 8,
        "cluster_config": str(cluster_path.resolve().relative_to(ROOT)),
        "rank_to_nic": str(mapping_path.resolve().relative_to(ROOT)),
        "ns3_topology": str(topology_path.resolve().relative_to(ROOT)),
        "pd_pairing_map": str(pairing_path.resolve().relative_to(ROOT)),
    }
    manifest_path = OUT / "minimal_1p2d_ep16_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
