#!/usr/bin/env python3
"""Generate the smallest 2P4D / EP32 FlowSim cluster artifact.

This is a physical-rank configuration, not a synthetic byte workload:
two 8-GPU Prefill servers and four 8-GPU Decode servers.  Each Decode
server contains four TP=2 instances; all 16 Decode instances participate in
one model-derived EP32 group (two local EP ranks per instance).
"""

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"
HARDWARE = "RTXPRO6000"
SERVER_COUNT = 6
PREFILL_SERVERS = 2
DECODE_SERVERS = 4
GPUS_PER_SERVER = 8
INSTANCES_PER_SERVER = 4
TP = 2
EP = 32
LINK_RATE = "200Gbps"
LINK_LATENCY = "0.005ms"


def _instance(pd_type, group=None):
    value = {
        "model_name": MODEL,
        "hardware": HARDWARE,
        "npu_mem": {"mem_size": 96, "mem_bw": 1597, "mem_latency": 0},
        "pd_type": pd_type,
        "num_npus": TP,
        "tp_size": TP,
        "ep_size": EP if group else 1,
    }
    if group:
        value["dp_group"] = group
    return value


def _node(instances):
    return {
        "num_instances": len(instances),
        "cpu_mem": {"mem_size": 512, "mem_bw": 256, "mem_latency": 0},
        "instances": instances,
    }


def _build_cluster(topology):
    instances = []
    for _ in range(PREFILL_SERVERS):
        instances.append(_node([_instance("prefill") for _ in range(INSTANCES_PER_SERVER)]))
    group = "decode_ep32_pool000"
    for _ in range(DECODE_SERVERS):
        instances.append(_node([
            _instance("decode", group) for _ in range(INSTANCES_PER_SERVER)
        ]))
    return {
        "num_nodes": SERVER_COUNT,
        "link_bw": 200,
        "link_latency": 5000,
        "ns3_topology": topology,
        "nodes": instances,
    }


def _rank_metadata():
    rows = []
    rank = 0
    instance_id = 0
    for server in range(SERVER_COUNT):
        role = "prefill" if server < PREFILL_SERVERS else "decode"
        group = "" if role == "prefill" else "decode_ep32_pool000"
        leaf = server // 3
        for local_instance in range(INSTANCES_PER_SERVER):
            gpu_start = local_instance * TP
            for tp_rank in range(TP):
                rows.append({
                    "astra_rank": rank,
                    "instance_id": instance_id,
                    "server_id": "S%02d" % server,
                    "gpu_id": "S%02d-G%d" % (server, gpu_start + tp_rank),
                    "unit_id": "P%d" % (server if role == "prefill" else 0)
                    if role == "prefill" else "D%d" % (server - PREFILL_SERVERS),
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


def _write_topology(path, rank_rows):
    endpoint_count = len(rank_rows)
    leaf_count = 2
    spine_count = 2
    leaf_base = endpoint_count
    spine_base = leaf_base + leaf_count
    edges = []
    per_leaf = {0: 0, 1: 0}
    for row in rank_rows:
        endpoint = int(row["astra_rank"])
        leaf = int(row["leaf_id"].replace("Leaf", ""))
        per_leaf[leaf] += 1
        edges.append((endpoint, leaf_base + leaf))
    for leaf in range(leaf_count):
        # Equal number of 200 Gbps leaf-to-spine uplinks.  The serial field is
        # retained for compatibility with the ns-3 topology format.
        for spine in range(spine_count):
            for _ in range(per_leaf[leaf] // spine_count):
                edges.append((leaf_base + leaf, spine_base + spine))
    switch_ids = [str(leaf_base + i) for i in range(leaf_count)]
    switch_ids += [str(spine_base + i) for i in range(spine_count)]
    with path.open("w", encoding="utf-8") as stream:
        stream.write("%d %d %d\n" % (
            endpoint_count + leaf_count + spine_count,
            leaf_count + spine_count,
            len(edges)))
        stream.write(" ".join(switch_ids) + "\n")
        for src, dst in edges:
            stream.write("%d %d %s %s 0\n" %
                         (src, dst, LINK_RATE, LINK_LATENCY))
    return {
        "endpoint_count": endpoint_count,
        "switch_count": leaf_count + spine_count,
        "edge_count": len(edges),
        "leaf_count": leaf_count,
        "spine_count": spine_count,
        "endpoint_links_per_leaf": per_leaf,
        "link_rate": LINK_RATE,
        "aggregate_uplink_downlink_ratio": "1:1",
    }


def main():
    out = ROOT / "experiments/pd_kv_ep/configs/large_scale"
    topo_dir = out / "ns3"
    topo_dir.mkdir(parents=True, exist_ok=True)
    topology_name = "s2p4d_6_servers_200g_clos.txt"
    topology_path = topo_dir / topology_name
    relative_topology = "experiments/pd_kv_ep/configs/large_scale/ns3/%s" % topology_name
    cluster = _build_cluster(relative_topology)
    cluster_path = out / "s2p4d_6_servers_qwen_ep32.json"
    cluster_path.write_text(json.dumps(cluster, indent=2) + "\n", encoding="utf-8")

    rows = _rank_metadata()
    metadata_path = out / "s2p4d_6_servers_rank_metadata.csv"
    with metadata_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    topology = _write_topology(topology_path, rows)
    manifest = {
        "scale": "s2p4d",
        "server_count": SERVER_COUNT,
        "prefill_servers": PREFILL_SERVERS,
        "decode_servers": DECODE_SERVERS,
        "gpus_per_server": GPUS_PER_SERVER,
        "physical_gpu_count": SERVER_COUNT * GPUS_PER_SERVER,
        "model": MODEL,
        "hardware": HARDWARE,
        "tp_per_instance": TP,
        "instances_per_server": INSTANCES_PER_SERVER,
        "decode_ep_degree": EP,
        "decode_instances_in_ep_group": DECODE_SERVERS * INSTANCES_PER_SERVER,
        "physical_endpoint_count": len(rows),
        "logical_rank_count": len(rows),
        "synthetic_prefill_companions": 0,
        "topology": topology,
        "cluster_config": str(cluster_path.relative_to(ROOT)),
        "rank_metadata": str(metadata_path.relative_to(ROOT)),
        "ns3_topology": str(topology_path.relative_to(ROOT)),
        "ep_profile_note": (
            "EP32 is represented by the model-derived Qwen3 routing matrix; "
            "MoE compute latency still comes from the checked-in TP2 profile."
        ),
    }
    manifest_path = out / "s2p4d_6_servers_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
