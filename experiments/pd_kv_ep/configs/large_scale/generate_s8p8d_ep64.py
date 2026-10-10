#!/usr/bin/env python3
"""Generate a balanced 8P8D Qwen3 EP64 FlowSim cluster.

The configuration keeps the physical Prefill:Decode server ratio at 1:1.
Each server has four TP=2 instances, so the eight Decode servers contribute
32 instances and 64 physical EP ranks.  The model has 128 experts, making
EP64 a valid expert partition with two experts per rank.
"""

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"
HARDWARE = "RTXPRO6000"
PREFILL_SERVERS = 8
DECODE_SERVERS = 8
SERVERS = PREFILL_SERVERS + DECODE_SERVERS
GPUS_PER_SERVER = 8
INSTANCES_PER_SERVER = 4
TP = 2
EP = 64
LEAVES = 4
SPINES = 2
LINK_RATE = "200Gbps"
LINK_LATENCY = "0.005ms"


def _instance(pd_type, group=None):
    result = {
        "model_name": MODEL,
        "hardware": HARDWARE,
        "npu_mem": {"mem_size": 96, "mem_bw": 1597, "mem_latency": 0},
        "pd_type": pd_type,
        "num_npus": TP,
        "tp_size": TP,
        "ep_size": EP if group else 1,
    }
    if group:
        result["dp_group"] = group
    return result


def _node(instances):
    return {
        "num_instances": len(instances),
        "cpu_mem": {"mem_size": 512, "mem_bw": 256, "mem_latency": 0},
        "instances": instances,
    }


def _leaf_for_server(server):
    # P0-P3 use Leaf0/Leaf1; D0-D3 use Leaf2 and D4-D7 use Leaf3.
    if server < PREFILL_SERVERS:
        return server // 4
    return 2 + (server - PREFILL_SERVERS) // 4


def _rank_rows():
    rows = []
    rank = 0
    instance_id = 0
    for server in range(SERVERS):
        role = "prefill" if server < PREFILL_SERVERS else "decode"
        group = "" if role == "prefill" else "decode_ep64_pool000"
        leaf = _leaf_for_server(server)
        for local_instance in range(INSTANCES_PER_SERVER):
            for tp_rank in range(TP):
                gpu = local_instance * TP + tp_rank
                rows.append({
                    "astra_rank": rank,
                    "instance_id": instance_id,
                    "server_id": "S%02d" % server,
                    "gpu_id": "S%02d-G%d" % (server, gpu),
                    "unit_id": "P%d" % server if role == "prefill" else "D%d" % (server - PREFILL_SERVERS),
                    "rack_id": "R00",
                    "leaf_id": "Leaf%d" % leaf,
                    "role": role,
                    "tp_rank": tp_rank,
                    "ep_rank": tp_rank if role == "decode" else "",
                    "dp_group": group,
                    "physical_gpu": "true",
                    "companion_of": "",
                })
                rank += 1
            instance_id += 1
    return rows


def _write_topology(path, rows):
    endpoint_count = len(rows)
    leaf_base = endpoint_count
    spine_base = leaf_base + LEAVES
    edges = []
    per_leaf = {leaf: 0 for leaf in range(LEAVES)}

    for row in rows:
        endpoint = int(row["astra_rank"])
        leaf = int(row["leaf_id"].replace("Leaf", ""))
        per_leaf[leaf] += 1
        edges.append((endpoint, leaf_base + leaf))

    # Keep the leaf-spine fabric 1:1 in aggregate bandwidth.  Every leaf has
    # per_leaf endpoint links and the same number of uplinks split evenly over
    # the two spines.  Links are directed by the FlowSim parser in both
    # directions from this undirected topology description.
    for leaf in range(LEAVES):
        uplinks_per_spine = per_leaf[leaf] // SPINES
        for spine in range(SPINES):
            for _ in range(uplinks_per_spine):
                edges.append((leaf_base + leaf, spine_base + spine))

    switch_ids = [str(leaf_base + leaf) for leaf in range(LEAVES)]
    switch_ids += [str(spine_base + spine) for spine in range(SPINES)]
    with path.open("w", encoding="utf-8") as stream:
        stream.write("%d %d %d\n" % (
            endpoint_count + LEAVES + SPINES,
            LEAVES + SPINES,
            len(edges)))
        stream.write(" ".join(switch_ids) + "\n")
        for src, dst in edges:
            stream.write("%d %d %s %s 0\n" % (
                src, dst, LINK_RATE, LINK_LATENCY))

    return {
        "endpoint_count": endpoint_count,
        "switch_count": LEAVES + SPINES,
        "edge_count": len(edges),
        "leaf_count": LEAVES,
        "spine_count": SPINES,
        "endpoint_links_per_leaf": per_leaf,
        "link_rate": LINK_RATE,
        "aggregate_uplink_downlink_ratio": "1:1",
    }


def main():
    out = ROOT / "experiments/pd_kv_ep/configs/large_scale"
    topo_dir = out / "ns3"
    topo_dir.mkdir(parents=True, exist_ok=True)
    topology_name = "s16_8p8d_ep64_200g_clos.txt"
    topology_path = topo_dir / topology_name
    topology_value = "experiments/pd_kv_ep/configs/large_scale/ns3/%s" % topology_name

    nodes = []
    for _ in range(PREFILL_SERVERS):
        nodes.append(_node([_instance("prefill") for _ in range(INSTANCES_PER_SERVER)]))
    for _ in range(DECODE_SERVERS):
        nodes.append(_node([
            _instance("decode", "decode_ep64_pool000")
            for _ in range(INSTANCES_PER_SERVER)
        ]))

    cluster = {
        "num_nodes": SERVERS,
        "link_bw": 200,
        "link_latency": 5000,
        "ns3_topology": topology_value,
        "nodes": nodes,
    }
    cluster_path = out / "s16_8p8d_ep64_qwen.json"
    cluster_path.write_text(json.dumps(cluster, indent=2) + "\n", encoding="utf-8")

    rows = _rank_rows()
    metadata_path = out / "s16_8p8d_ep64_rank_metadata.csv"
    with metadata_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    topology = _write_topology(topology_path, rows)

    manifest = {
        "scale": "s16_8p8d",
        "server_count": SERVERS,
        "prefill_servers": PREFILL_SERVERS,
        "decode_servers": DECODE_SERVERS,
        "gpus_per_server": GPUS_PER_SERVER,
        "physical_gpu_count": SERVERS * GPUS_PER_SERVER,
        "model": MODEL,
        "hardware": HARDWARE,
        "tp_per_instance": TP,
        "instances_per_server": INSTANCES_PER_SERVER,
        "decode_ep_degree": EP,
        "decode_instances_in_ep_group": DECODE_SERVERS * INSTANCES_PER_SERVER,
        "physical_endpoint_count": len(rows),
        "prefill_decode_server_ratio": "1:1",
        "prefill_decode_gpu_ratio": "1:1",
        "synthetic_prefill_companions": 0,
        "topology": topology,
        "cluster_config": str(cluster_path.relative_to(ROOT)),
        "rank_metadata": str(metadata_path.relative_to(ROOT)),
        "ns3_topology": str(topology_path.relative_to(ROOT)),
        "model_semantics": {
            "experts": 128,
            "top_k": 8,
            "layers": 48,
            "expert_partition": "2 experts per EP rank at EP64",
        },
        "synthetic_byte_override": False,
    }
    manifest_path = out / "s16_8p8d_ep64_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
