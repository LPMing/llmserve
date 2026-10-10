#!/usr/bin/env python3
"""Generate a Clos topology with four GPU ranks sharing each 200-Gbps NIC.

The GPU-to-NIC links are modeled as a high-rate local attachment. Each NIC
aggregation node has one 200-Gbps scale-out uplink, which is the shared
resource for its four attached GPU ranks. Two NIC nodes in the same server
are joined by a high-rate local path so local collectives do not traverse the
scale-out fabric.
"""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _rank_gpu(row):
    return int(row["gpu_id"].rsplit("-G", 1)[-1])


def generate(rank_metadata, base_cluster, topology_out, cluster_out,
             mapping_out, gpus_per_nic=4, nic_rate_gbps=200,
             local_rate_gbps=7200, spine_count=2):
    with rank_metadata.open(encoding="utf-8", newline="") as stream:
        ranks = list(csv.DictReader(stream))
    if not ranks:
        raise ValueError("rank metadata is empty")

    ranks.sort(key=lambda row: int(row["astra_rank"]))
    actual = [int(row["astra_rank"]) for row in ranks]
    if actual != list(range(len(ranks))):
        raise ValueError("astra_rank must be contiguous from zero")

    servers = defaultdict(list)
    for row in ranks:
        servers[row["server_id"]].append(row)
    leaf_servers = defaultdict(set)
    for server, rows in servers.items():
        leaves = {row["leaf_id"] for row in rows}
        if len(leaves) != 1:
            raise ValueError("server %s maps to multiple leaves" % server)
        leaf_servers[next(iter(leaves))].add(server)

    gpu_count = len(ranks)
    next_nic = gpu_count
    nic_for_rank = {}
    nic_records = []
    server_nics = defaultdict(list)
    for server in sorted(servers):
        rows = sorted(servers[server], key=_rank_gpu)
        groups = defaultdict(list)
        for row in rows:
            groups[_rank_gpu(row) // gpus_per_nic].append(row)
        for group_id in sorted(groups):
            nic_id = next_nic
            next_nic += 1
            group_rows = groups[group_id]
            leaf = group_rows[0]["leaf_id"]
            if any(row["leaf_id"] != leaf for row in group_rows):
                raise ValueError("GPU group spans leaves")
            for row in group_rows:
                nic_for_rank[int(row["astra_rank"])] = nic_id
            server_nics[server].append(nic_id)
            nic_records.append({
                "nic_id": nic_id,
                "server_id": server,
                "leaf_id": leaf,
                "gpu_ids": ";".join(row["gpu_id"] for row in group_rows),
                "rank_ids": ";".join(row["astra_rank"] for row in group_rows),
                "shared_nic_capacity_gbps": nic_rate_gbps,
            })

    leaf_labels = sorted(leaf_servers)
    if len(leaf_labels) < 2:
        raise ValueError("at least two leaf groups are required")
    nic_count_by_leaf = defaultdict(int)
    for nic in nic_records:
        nic_count_by_leaf[nic["leaf_id"]] += 1
    counts = {nic_count_by_leaf[label] for label in leaf_labels}
    if len(counts) != 1:
        raise ValueError("leaf groups must have equal NIC uplink counts")
    nics_per_leaf = counts.pop()
    if nics_per_leaf % spine_count:
        raise ValueError("NIC uplinks per leaf must divide evenly across spines")

    leaf_base = next_nic
    spine_base = leaf_base + len(leaf_labels)
    switch_ids = list(range(gpu_count, spine_base + spine_count))
    leaf_id_map = {label: leaf_base + i for i, label in enumerate(leaf_labels)}

    edges = []
    for row in ranks:
        edges.append((int(row["astra_rank"]), nic_for_rank[int(row["astra_rank"])],
                      local_rate_gbps, "0.0001ms"))
    for server in sorted(server_nics):
        local_nics = server_nics[server]
        for i, src in enumerate(local_nics):
            for dst in local_nics[i + 1:]:
                edges.append((src, dst, local_rate_gbps, "0.0001ms"))
    for nic in nic_records:
        edges.append((nic["nic_id"], leaf_id_map[nic["leaf_id"]],
                      nic_rate_gbps, "0.005ms"))
    links_per_pair = nics_per_leaf // spine_count
    for leaf_offset, _label in enumerate(leaf_labels):
        leaf_id = leaf_base + leaf_offset
        for spine_offset in range(spine_count):
            spine_id = spine_base + spine_offset
            for _ in range(links_per_pair):
                edges.append((leaf_id, spine_id, nic_rate_gbps, "0.005ms"))

    topology_out.parent.mkdir(parents=True, exist_ok=True)
    with topology_out.open("w", encoding="utf-8") as stream:
        stream.write("%d %d %d\n" % (spine_base + spine_count,
                                      len(switch_ids), len(edges)))
        stream.write(" ".join(map(str, switch_ids)) + "\n")
        for src, dst, rate, latency in edges:
            stream.write("%d %d %dGbps %s 0\n" % (src, dst, rate, latency))

    mapping_out.parent.mkdir(parents=True, exist_ok=True)
    with mapping_out.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "nic_id", "server_id", "leaf_id", "gpu_ids", "rank_ids",
            "shared_nic_capacity_gbps"])
        writer.writeheader()
        writer.writerows(nic_records)

    with base_cluster.open(encoding="utf-8") as stream:
        cluster = json.load(stream)
    cluster["link_bw"] = 200
    cluster["ns3_topology"] = str(topology_out.resolve().relative_to(ROOT))
    cluster_out.parent.mkdir(parents=True, exist_ok=True)
    with cluster_out.open("w", encoding="utf-8") as stream:
        json.dump(cluster, stream, indent=2)
        stream.write("\n")

    report = {
        "rank_count": gpu_count,
        "server_count": len(servers),
        "gpus_per_nic": gpus_per_nic,
        "nic_count": len(nic_records),
        "nic_capacity_gbps": nic_rate_gbps,
        "nominal_per_gpu_share_gbps": nic_rate_gbps / gpus_per_nic,
        "gpu_to_nic_attachment_gbps": local_rate_gbps,
        "leaf_spine_physical_rate_gbps": nic_rate_gbps,
        "nics_per_leaf": nics_per_leaf,
        "leaf_spine_links_per_pair": links_per_pair,
        "leaf_downlink_capacity_gbps": nics_per_leaf * nic_rate_gbps,
        "leaf_uplink_capacity_gbps": spine_count * links_per_pair * nic_rate_gbps,
        "topology_path": str(topology_out.resolve()),
        "cluster_config": str(cluster_out.resolve()),
        "nic_mapping": str(mapping_out.resolve()),
    }
    if report["leaf_downlink_capacity_gbps"] != report["leaf_uplink_capacity_gbps"]:
        raise AssertionError("leaf fabric is not 1:1 by aggregate NIC capacity")
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rank-metadata", type=Path, required=True)
    parser.add_argument("--base-cluster", type=Path, required=True)
    parser.add_argument("--topology-out", type=Path, required=True)
    parser.add_argument("--cluster-out", type=Path, required=True)
    parser.add_argument("--mapping-out", type=Path, required=True)
    parser.add_argument("--gpus-per-nic", type=int, default=4)
    parser.add_argument("--nic-rate-gbps", type=int, default=200)
    parser.add_argument("--local-rate-gbps", type=int, default=7200)
    parser.add_argument("--spines", type=int, default=2)
    args = parser.parse_args()
    if min(args.gpus_per_nic, args.nic_rate_gbps,
           args.local_rate_gbps, args.spines) <= 0:
        parser.error("rates, GPU grouping, and spine count must be positive")
    generate(args.rank_metadata, args.base_cluster, args.topology_out,
             args.cluster_out, args.mapping_out, args.gpus_per_nic,
             args.nic_rate_gbps, args.local_rate_gbps, args.spines)


if __name__ == "__main__":
    main()
