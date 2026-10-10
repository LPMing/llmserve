#!/usr/bin/env python3
"""Add one dedicated remote-KV endpoint per leaf to an existing Clos plan.

Serving GPU/rank IDs remain unchanged.  The added endpoints are NIC-level
cache nodes used only by the model-derived REMOTE_KV_FETCH replay.
"""

import argparse
import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def _load(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def build(scale, cache_endpoints_per_leaf):
    config_root = ROOT / "experiments/pd_kv_ep/configs/large_scale"
    manifest = _load(config_root / f"{scale}_{'64' if scale == 's64' else '256'}_servers_manifest.json")
    ledger_path = ROOT / manifest["rank_metadata"]
    rows = []
    with ledger_path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    physical = int(manifest["physical_endpoint_count"])
    leaves = int(manifest["topology"]["leaf_count"])
    spines = int(manifest["topology"]["spine_count"])
    if cache_endpoints_per_leaf <= 0:
        raise ValueError("cache_endpoints_per_leaf must be positive")
    endpoint_count = physical + leaves * cache_endpoints_per_leaf
    leaf_switch = endpoint_count
    spine_switch = leaf_switch + leaves
    edges = []
    endpoint_counts = {leaf: 0 for leaf in range(leaves)}
    for row in rows:
        endpoint = int(row["astra_rank"])
        leaf = int(row["leaf_id"].replace("Leaf", ""))
        endpoint_counts[leaf] += 1
        edges.append((endpoint, leaf_switch + leaf))
    cache_endpoints = {}
    for leaf in range(leaves):
        ids = []
        for ordinal in range(cache_endpoints_per_leaf):
            endpoint = physical + leaf * cache_endpoints_per_leaf + ordinal
            ids.append(endpoint)
            endpoint_counts[leaf] += 1
            edges.append((endpoint, leaf_switch + leaf))
        cache_endpoints[str(leaf)] = ids
    for leaf in range(leaves):
        total_uplinks = endpoint_counts[leaf]
        left = total_uplinks // spines
        per_spine = [left] * spines
        for index in range(total_uplinks - left * spines):
            per_spine[index] += 1
        serial = 0
        for spine_offset, count in enumerate(per_spine):
            for _ in range(count):
                edges.append((leaf_switch + leaf, spine_switch + spine_offset))
                serial += 1
    switch_ids = [str(leaf_switch + leaf) for leaf in range(leaves)]
    switch_ids.extend(str(spine_switch + spine) for spine in range(spines))
    topology_dir = config_root / "ns3"
    output_name = f"{scale}_{int(manifest['server_count'])}_servers_200g_clos_remote_cache{cache_endpoints_per_leaf}.txt"
    topology_path = topology_dir / output_name
    with topology_path.open("w", encoding="utf-8") as stream:
        stream.write(f"{endpoint_count + leaves + spines} {leaves + spines} {len(edges)}\n")
        stream.write(" ".join(switch_ids) + "\n")
        for src, dst in edges:
            stream.write(f"{src} {dst} 200Gbps 0.005ms 0\n")
    metadata = {
        "scale": scale,
        "base_manifest": str((config_root / f"{scale}_{manifest['server_count']}_servers_manifest.json").relative_to(ROOT)),
        "topology": str(topology_path.relative_to(ROOT)),
        "physical_serving_endpoints": physical,
        "cache_endpoints_per_leaf": cache_endpoints_per_leaf,
        "cache_endpoints_by_leaf": cache_endpoints,
        "endpoint_count": endpoint_count,
        "switch_count": leaves + spines,
        "edge_count": len(edges),
        "link_rate": "200Gbps",
        "placement": "dedicated_remote_cache_nic_per_leaf",
    }
    metadata_path = topology_path.with_suffix(".json")
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scales", nargs="+", choices=("s64", "s256"), default=("s64", "s256"))
    parser.add_argument("--cache-endpoints-per-leaf", type=int, default=1)
    args = parser.parse_args()
    for scale in args.scales:
        build(scale, args.cache_endpoints_per_leaf)


if __name__ == "__main__":
    main()
