#!/usr/bin/env python3
"""Generate auditable S1/S2 server-level Clos and LLMServingSim configs.

The model profile available in this checkout is Qwen3-30B-A3B at TP=2.  Each
physical server therefore hosts four independent TP=2 instances (8 GPUs).
Decode instances are grouped eight-at-a-time into EP=16 pools: 8 instances x
2 local ranks.  This keeps the EP degree tied to the model's 128 experts and
the simulator's profiled TP=2 path instead of claiming an unprofiled EP=64
configuration.

The default P/D representation uses only physical serving ranks.  A legacy
shadow-rank mode remains available in the simulator for compatibility, but it
is not part of these large-scale cluster or topology artifacts.
"""

import argparse
import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"
HARDWARE = "RTXPRO6000"
GPUS_PER_SERVER = 8
INSTANCES_PER_SERVER = 4
TP_PER_INSTANCE = 2
EP_PER_POOL = 16
DECODE_INSTANCES_PER_POOL = 8
SERVERS_PER_LEAF = 8
SPINES = 2
LINK_RATE = "200Gbps"
LINK_LATENCY = "0.005ms"


def _instance(model=MODEL, pd_type=None, dp_group=None):
    value = {
        "model_name": model,
        "hardware": HARDWARE,
        "npu_mem": {"mem_size": 96, "mem_bw": 1597, "mem_latency": 0},
        "pd_type": pd_type,
        "num_npus": TP_PER_INSTANCE,
        "tp_size": TP_PER_INSTANCE,
        "ep_size": EP_PER_POOL if dp_group else 1,
    }
    if dp_group:
        value["dp_group"] = dp_group
    return value


def _build_cluster(server_count, topology_path):
    if server_count % 2:
        raise ValueError("server_count must be even for a 1:1 P:D deployment")
    prefill_servers = server_count // 2
    decode_servers = server_count // 2
    nodes = []
    decode_instance_ordinal = 0
    for server in range(server_count):
        role = "prefill" if server < prefill_servers else "decode"
        instances = []
        for _ in range(INSTANCES_PER_SERVER):
            if role == "decode":
                pool = decode_instance_ordinal // DECODE_INSTANCES_PER_POOL
                group = f"decode_ep{EP_PER_POOL}_pool{pool:03d}"
                instances.append(_instance(pd_type="decode", dp_group=group))
                decode_instance_ordinal += 1
            else:
                instances.append(_instance(pd_type="prefill"))
        nodes.append({
            "num_instances": INSTANCES_PER_SERVER,
            "cpu_mem": {"mem_size": 512, "mem_bw": 256, "mem_latency": 0},
            "instances": instances,
        })
    return {
        "num_nodes": server_count,
        "link_bw": 25,
        "link_latency": 5000,
        "ns3_topology": topology_path,
        "nodes": nodes,
    }


def _rank_ledger(server_count):
    rows = []
    rank = 0
    instance_id = 0
    prefill_servers = server_count // 2
    decode_instance_ordinal = 0
    for server in range(server_count):
        role = "prefill" if server < prefill_servers else "decode"
        leaf = server // SERVERS_PER_LEAF
        for local_instance in range(INSTANCES_PER_SERVER):
            if role == "decode":
                pool = decode_instance_ordinal // DECODE_INSTANCES_PER_POOL
                group = f"decode_ep{EP_PER_POOL}_pool{pool:03d}"
                decode_instance_ordinal += 1
            else:
                group = ""
            gpu_start = local_instance * TP_PER_INSTANCE
            for tp_rank in range(TP_PER_INSTANCE):
                gpu_id = f"S{server:03d}-G{gpu_start + tp_rank}"
                rows.append({
                    "astra_rank": rank,
                    "instance_id": instance_id,
                    "server_id": f"S{server:03d}",
                    "gpu_id": gpu_id,
                    "unit_id": "P0" if role == "prefill" else "D0",
                    "rack_id": f"R{server // (SERVERS_PER_LEAF * 4):02d}",
                    "leaf_id": f"Leaf{leaf:03d}",
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


def _write_topology(path, ledger, server_count):
    endpoint_count = len(ledger)
    leaf_count = (server_count + SERVERS_PER_LEAF - 1) // SERVERS_PER_LEAF
    switch_count = leaf_count + SPINES
    leaf_switch = endpoint_count
    spine_switch = endpoint_count + leaf_count
    edges = []
    endpoint_counts = {leaf: 0 for leaf in range(leaf_count)}
    for row in ledger:
        endpoint = int(row["astra_rank"])
        leaf = int(row["leaf_id"].replace("Leaf", ""))
        endpoint_counts[leaf] += 1
        edges.append((endpoint, leaf_switch + leaf, LINK_RATE, LINK_LATENCY, 0))
    for leaf in range(leaf_count):
        total_uplinks = endpoint_counts[leaf]
        left = total_uplinks // SPINES
        per_spine = [left] * SPINES
        for i in range(total_uplinks - left * SPINES):
            per_spine[i] += 1
        serial = 0
        for spine_offset, count in enumerate(per_spine):
            for _ in range(count):
                edges.append((leaf_switch + leaf, spine_switch + spine_offset,
                              LINK_RATE, LINK_LATENCY, serial))
                serial += 1
    switch_ids = [str(leaf_switch + i) for i in range(leaf_count)]
    switch_ids += [str(spine_switch + i) for i in range(SPINES)]
    # The ns-3 topology reader's first field is the total number of nodes,
    # including switches.  The logical ASTRA endpoint count is still exactly
    # ``endpoint_count`` and is recorded separately in the manifest.
    total_node_count = endpoint_count + switch_count
    with path.open("w", encoding="utf-8") as output:
        output.write(f"{total_node_count} {switch_count} {len(edges)}\n")
        output.write(" ".join(switch_ids) + "\n")
        for src, dst, rate, latency, _ in edges:
            output.write(f"{src} {dst} {rate} {latency} 0\n")
    return {
        "endpoint_count": endpoint_count,
        "switch_count": switch_count,
        "edge_count": len(edges),
        "leaf_count": leaf_count,
        "spine_count": SPINES,
        "endpoint_links_per_leaf": endpoint_counts,
        "aggregate_uplink_downlink_ratio": "1:1",
    }


def generate(server_count):
    out_root = ROOT / "experiments/pd_kv_ep/configs/large_scale"
    out_root.mkdir(parents=True, exist_ok=True)
    topo_dir = out_root / "ns3"
    topo_dir.mkdir(parents=True, exist_ok=True)
    scale = f"s{server_count}"
    topo_name = f"{scale}_{server_count}_servers_200g_clos.txt"
    topo_path = topo_dir / topo_name
    relative_topo = f"experiments/pd_kv_ep/configs/large_scale/ns3/{topo_name}"
    cluster = _build_cluster(server_count, relative_topo)
    cluster_path = out_root / f"{scale}_{server_count}_servers_qwen_ep16.json"
    with cluster_path.open("w", encoding="utf-8") as output:
        json.dump(cluster, output, indent=2)
        output.write("\n")

    ledger = _rank_ledger(server_count)
    ledger_path = out_root / f"{scale}_{server_count}_servers_rank_metadata.csv"
    fields = list(ledger[0])
    with ledger_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(ledger)
    topology = _write_topology(topo_path, ledger, server_count)
    manifest = {
        "scale": scale,
        "server_count": server_count,
        "prefill_servers": server_count // 2,
        "decode_servers": server_count // 2,
        "gpus_per_server": GPUS_PER_SERVER,
        "physical_gpu_count": server_count * GPUS_PER_SERVER,
        "model": MODEL,
        "hardware": HARDWARE,
        "tp_per_instance": TP_PER_INSTANCE,
        "instances_per_server": INSTANCES_PER_SERVER,
        "decode_ep_degree": EP_PER_POOL,
        "decode_instances_per_ep_pool": DECODE_INSTANCES_PER_POOL,
        "physical_endpoint_count": len(ledger),
        "synthetic_prefill_companions": 0,
        "logical_rank_count": len(ledger),
        "topology": topology,
        "cluster_config": str(cluster_path.relative_to(ROOT)),
        "rank_metadata": str(ledger_path.relative_to(ROOT)),
        "ns3_topology": str(topo_path.relative_to(ROOT)),
        "ep_profile_note": (
            "EP=16 is the largest cross-instance degree in this generated plan; "
            "it uses the Qwen3 model's 128 experts and TP=2 profile. It is not "
            "a claim of native EP=64 profiling."
        ),
    }
    manifest_path = out_root / f"{scale}_{server_count}_servers_manifest.json"
    with manifest_path.open("w", encoding="utf-8") as output:
        json.dump(manifest, output, indent=2)
        output.write("\n")
    print(json.dumps(manifest, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--servers", type=int, nargs="+", default=[64, 256])
    args = parser.parse_args()
    for server_count in args.servers:
        generate(server_count)


if __name__ == "__main__":
    main()
