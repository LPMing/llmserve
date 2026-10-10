#!/usr/bin/env python3
"""Generate a balanced 4P4D / EP32 cluster with four GPU ranks per 200G NIC."""

import csv
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "experiments/pd_kv_ep/scripts"))
from generate_shared_nic_topology import generate as generate_shared_topology


MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"
HARDWARE = "RTXPRO6000"
TP = 2
INSTANCES_PER_SERVER = 4
GPUS_PER_SERVER = 8
SERVERS_PER_ROLE = 4
EP = 32
LEAVES = 4


def _instance(role, dp_group=""):
    value = {
        "model_name": MODEL,
        "hardware": HARDWARE,
        "npu_mem": {"mem_size": 96, "mem_bw": 1597, "mem_latency": 0},
        "pd_type": role,
        "num_npus": TP,
        "tp_size": TP,
        "ep_size": EP if role == "decode" else 1,
    }
    if dp_group:
        value["dp_group"] = dp_group
    return value


def _leaf(role, role_server):
    # Keep the two P leaves and two D leaves distinct so every P2D transfer
    # crosses the Clos fabric and the EP32 group spans both Decode leaves.
    if role == "prefill":
        return role_server // 2
    return 2 + role_server // 2


def build():
    config_dir = ROOT / "experiments/pd_kv_ep/configs/large_scale"
    topology_dir = config_dir / "ns3"
    topology_dir.mkdir(parents=True, exist_ok=True)

    cluster_nodes = []
    rank_rows = []
    instance_id = 0
    rank = 0
    ep_rank = 0
    for role in ("prefill", "decode"):
        dp_group = "decode_ep32_pool000" if role == "decode" else ""
        for role_server in range(SERVERS_PER_ROLE):
            server_index = role_server + (SERVERS_PER_ROLE if role == "decode" else 0)
            server_id = "S%02d" % server_index
            leaf_id = "Leaf%d" % _leaf(role, role_server)
            instances = []
            for local_instance in range(INSTANCES_PER_SERVER):
                instances.append(_instance(role, dp_group))
                for tp_rank in range(TP):
                    gpu_index = local_instance * TP + tp_rank
                    rank_rows.append({
                        "astra_rank": rank,
                        "instance_id": instance_id,
                        "server_id": server_id,
                        "gpu_id": "%s-G%d" % (server_id, gpu_index),
                        "unit_id": ("P%d" if role == "prefill" else "D%d") % role_server,
                        "rack_id": "R00",
                        "leaf_id": leaf_id,
                        "role": role,
                        "tp_rank": tp_rank,
                        "ep_rank": ep_rank if role == "decode" else "",
                        "dp_group": dp_group,
                        "physical_gpu": "true",
                        "companion_of": "",
                    })
                    rank += 1
                    if role == "decode":
                        ep_rank += 1
                instance_id += 1
            cluster_nodes.append({
                "num_instances": INSTANCES_PER_SERVER,
                "cpu_mem": {"mem_size": 512, "mem_bw": 256, "mem_latency": 0},
                "instances": instances,
            })

    base_config = config_dir / "s8_4p4d_ep32_base.json"
    base_config.write_text(json.dumps({
        "num_nodes": 8,
        "link_bw": 200,
        "link_latency": 5000,
        "nodes": cluster_nodes,
    }, indent=2) + "\n", encoding="utf-8")

    metadata_path = config_dir / "s8_4p4d_ep32_rank_metadata.csv"
    with metadata_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rank_rows[0]))
        writer.writeheader()
        writer.writerows(rank_rows)

    topology_path = topology_dir / "s8_4p4d_ep32_4gpu_per_200g_nic_200g_clos.txt"
    cluster_path = config_dir / "s8_4p4d_ep32_4gpu_per_200g_nic.json"
    nic_map_path = config_dir / "s8_4p4d_ep32_gpu_to_nic.csv"
    generate_shared_topology(
        metadata_path, base_config, topology_path, cluster_path, nic_map_path,
        gpus_per_nic=4, nic_rate_gbps=200, local_rate_gbps=7200, spine_count=2)

    manifest = {
        "scale": "S8_4P4D_EP32_SHARED_NIC",
        "server_count": 8,
        "prefill_servers": 4,
        "decode_servers": 4,
        "prefill_decode_server_ratio": "1:1",
        "gpus_per_server": GPUS_PER_SERVER,
        "physical_gpu_count": 64,
        "physical_endpoint_count": 64,
        "logical_rank_count": 64,
        "prefill_gpu_count": 32,
        "decode_gpu_count": 32,
        "model": MODEL,
        "hardware": HARDWARE,
        "tp_per_instance": TP,
        "instances_per_server": INSTANCES_PER_SERVER,
        "decode_ep_degree": EP,
        "decode_instances_in_ep_group": EP,
        "gpus_per_shared_nic": 4,
        "shared_nic_count": 16,
        "shared_nic_capacity_gbps": 200,
        "nominal_per_gpu_share_gbps": 50,
        "leaf_spine_physical_link_gbps": 200,
        "topology": {
            "rank_endpoint_count": 64,
            "nic_aggregation_nodes": 16,
            "leaf_count": LEAVES,
            "spine_count": 2,
            "parallel_links_per_leaf_spine_pair": 2,
            "aggregate_leaf_downlink_gbps": 800,
            "aggregate_leaf_uplink_gbps": 800,
            "oversubscription_ratio": "1:1",
            "p_and_d_on_distinct_leaf_groups": True,
        },
        "cluster_config": str(cluster_path.relative_to(ROOT)),
        "rank_metadata": str(metadata_path.relative_to(ROOT)),
        "gpu_to_nic_mapping": str(nic_map_path.relative_to(ROOT)),
        "ns3_topology": str(topology_path.relative_to(ROOT)),
        "model_semantics": {
            "layers": 48,
            "experts": 128,
            "top_k": 8,
            "experts_per_ep_rank": 4,
        },
        "synthetic_byte_override": False,
    }
    manifest_path = config_dir / "s8_4p4d_ep32_shared_nic_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    build()
