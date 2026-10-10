#!/usr/bin/env python3
"""Generate an S16 EP64 topology with two shared 200-Gbps NICs per server.

Each four-GPU group shares one NIC. GPU-to-NIC and same-server NIC-to-NIC
links model the fast local fabric; only NIC-to-leaf links are scale-out
200-Gbps links. This is a FlowSim fluid topology, not a packet/ECMP model.
"""

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
BASE = ROOT / "experiments/pd_kv_ep/configs/large_scale"
MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"
PREFILL_SERVERS = 8
DECODE_SERVERS = 8
SERVERS = PREFILL_SERVERS + DECODE_SERVERS
GPUS_PER_SERVER = 8
NICS_PER_SERVER = 2
GPUS_PER_NIC = 4
NIC_GBPS = 200
LOCAL_GBPS = 7200
LEAVES = 4
SPINES = 2


def _leaf(server):
    return server // 4


def _rank_rows():
    rows = []
    for server in range(SERVERS):
        role = "prefill" if server < PREFILL_SERVERS else "decode"
        for gpu in range(GPUS_PER_SERVER):
            rank = server * GPUS_PER_SERVER + gpu
            instance_local = gpu // 2
            rows.append({
                "astra_rank": rank,
                "server_id": "S%02d" % server,
                "gpu_id": "S%02d-G%d" % (server, gpu),
                "unit_id": ("P%d" % server if role == "prefill"
                            else "D%d" % (server - PREFILL_SERVERS)),
                "leaf_id": "Leaf%d" % _leaf(server),
                "role": role,
                "instance_id": server * 4 + instance_local,
                "tp_rank": gpu % 2,
                "ep_rank": (gpu if role == "decode" else ""),
                "dp_group": ("decode_ep64_pool000" if role == "decode" else ""),
                "nic_id": 128 + server * NICS_PER_SERVER + gpu // GPUS_PER_NIC,
                "nic_local_id": gpu // GPUS_PER_NIC,
                "gpus_per_nic": GPUS_PER_NIC,
                "nic_rate_gbps": NIC_GBPS,
            })
    return rows


def _write_topology(path, rows):
    nic_base = 128
    leaf_base = nic_base + SERVERS * NICS_PER_SERVER
    spine_base = leaf_base + LEAVES
    edges = []

    # GPU-rank attachment to the shared NIC; these are local, high-rate links.
    for row in rows:
        edges.append((int(row["astra_rank"]), int(row["nic_id"]),
                      LOCAL_GBPS, "0.0001ms"))

    # The two NICs in a server share the local GPU fabric, not the ToR fabric.
    for server in range(SERVERS):
        nic0 = nic_base + server * NICS_PER_SERVER
        edges.append((nic0, nic0 + 1, LOCAL_GBPS, "0.0001ms"))

    # Each physical NIC has its own 200-Gbps switch-facing link.
    for server in range(SERVERS):
        leaf = leaf_base + _leaf(server)
        for rail in range(NICS_PER_SERVER):
            nic = nic_base + server * NICS_PER_SERVER + rail
            edges.append((nic, leaf, NIC_GBPS, "0.005ms"))

    # Four servers (eight NICs) per leaf: 1.6 Tbps endpoint capacity.
    # Four 200-Gbps links to each of two spines preserve 1:1 Clos capacity.
    for leaf in range(LEAVES):
        for spine in range(SPINES):
            for _ in range(4):
                edges.append((leaf_base + leaf, spine_base + spine,
                              NIC_GBPS, "0.005ms"))

    node_count = spine_base + SPINES
    switches = [leaf_base + i for i in range(LEAVES)]
    switches += [spine_base + i for i in range(SPINES)]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        stream.write("%d %d %d\n" % (node_count, len(switches), len(edges)))
        stream.write(" ".join(str(node) for node in switches) + "\n")
        for src, dst, rate, latency in edges:
            stream.write("%d %d %dGbps %s 0\n" %
                         (src, dst, rate, latency))
    return {
        "node_count": node_count,
        "gpu_rank_count": len(rows),
        "nic_count": SERVERS * NICS_PER_SERVER,
        "switch_count": len(switches),
        "physical_edge_count": len(edges),
        "gpus_per_nic": GPUS_PER_NIC,
        "nics_per_server": NICS_PER_SERVER,
        "nic_rate_gbps": NIC_GBPS,
        "server_aggregate_scaleout_gbps": NICS_PER_SERVER * NIC_GBPS,
        "nic_endpoints_per_leaf": 8,
        "leaf_scaleout_capacity_gbps": 8 * NIC_GBPS,
        "leaf_spine_physical_links_per_pair": 4,
        "leaf_spine_aggregate_capacity_gbps_per_spine": 4 * NIC_GBPS,
        "leaf_oversubscription": 1.0,
    }


def main():
    topology_rel = Path(
        "experiments/pd_kv_ep/configs/large_scale/ns3/"
        "s16_8p8d_ep64_shared_2nic_200g_clos.txt")
    topology_path = ROOT / topology_rel
    cluster_path = BASE / "s16_8p8d_ep64_shared_2nic_qwen.json"
    metadata_path = BASE / "s16_8p8d_ep64_shared_2nic_rank_metadata.csv"
    manifest_path = BASE / "s16_8p8d_ep64_shared_2nic_manifest.json"

    rows = _rank_rows()
    topology = _write_topology(topology_path, rows)
    with metadata_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    source = json.loads((BASE / "s16_8p8d_ep64_qwen.json").read_text(
        encoding="utf-8"))
    source["link_bw"] = 50  # 400 Gbps/server in ASTRA's GB/s fallback units.
    source["ns3_topology"] = topology_rel.as_posix()
    cluster_path.write_text(json.dumps(source, indent=2) + "\n",
                            encoding="utf-8")

    manifest = {
        "scale": "s16_8p8d_ep64_shared_2nic",
        "server_count": SERVERS,
        "prefill_servers": PREFILL_SERVERS,
        "decode_servers": DECODE_SERVERS,
        "gpus_per_server": GPUS_PER_SERVER,
        "gpu_count": SERVERS * GPUS_PER_SERVER,
        "nics_per_server": NICS_PER_SERVER,
        "nic_rate_gbps": NIC_GBPS,
        "server_aggregate_scaleout_gbps": NICS_PER_SERVER * NIC_GBPS,
        "gpus_per_nic": GPUS_PER_NIC,
        "model": MODEL,
        "decode_ep_degree": 64,
        "decode_ep_instances": DECODE_SERVERS * 4,
        "prefill_decode_server_ratio": "1:1",
        "physical_scaleout_link_rate": "200Gbps",
        "topology": topology,
        "cluster_config": str(cluster_path.relative_to(ROOT)),
        "rank_metadata": str(metadata_path.relative_to(ROOT)),
        "topology_file": str(topology_path.relative_to(ROOT)),
        "parallel_link_semantics": (
            "FlowSim aggregates parallel physical links as directed fluid "
            "capacity; endpoint NIC links still cap each rank's path."),
        "queue_semantics": "analytical fluid backlog, not packet queue",
        "synthetic_byte_override": False,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n",
                             encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
