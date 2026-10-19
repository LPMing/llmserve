#!/usr/bin/env python3
"""Build model-derived native-ns-3 receiver-incast fixtures.

The primary topology has four Prefill servers and one Decode server. Each
server has eight GPU-rank hosts behind two shared 200-Gbps NIC aggregation
nodes. Two physically independent rails carry TP2 shards. On each rail, every
Prefill NIC has a sender-specific 200-Gbps spine path to the Decode NIC; the
Decode NIC uplink is therefore the only intentionally shared bottleneck.

This creates packet-replay inputs only. It does not claim integrated serving
metrics or alter existing experiment artifacts.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research_ns3_incast"
P_SERVERS = 4
GPUS_PER_SERVER = 8
GPUS_PER_NIC = 4
NICS_PER_SERVER = 2
NIC_GBPS = 200
LOCAL_GBPS = 7200
SPINES_PER_RAIL = P_SERVERS
KV_BYTES_PER_TOKEN = 98_304
LAYERS = 48
INPUT_TOKENS = 4096
TP = 2
KV_BYTES_REQUEST = KV_BYTES_PER_TOKEN * INPUT_TOKENS
KV_BYTES_SHARD = KV_BYTES_REQUEST // TP


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_topology(directory, decode_servers=1, multipath=False,
                   local_gbps=LOCAL_GBPS):
    directory.mkdir(parents=True, exist_ok=True)
    server_count = P_SERVERS + decode_servers
    host_count = server_count * GPUS_PER_SERVER
    nic_base = host_count
    nic_count = server_count * NICS_PER_SERVER
    leaf_base = nic_base + nic_count
    leaf_count = nic_count  # one rail leaf per NIC
    spine_base = leaf_base + leaf_count
    spine_count = 2 * SPINES_PER_RAIL

    def nic_id(server_index, rail):
        return nic_base + server_index * NICS_PER_SERVER + rail

    def leaf_id(server_index, rail):
        return leaf_base + server_index * NICS_PER_SERVER + rail

    def spine_id(rail, prefill_index):
        return spine_base + rail * SPINES_PER_RAIL + prefill_index

    edges = []
    ranks = []
    receiver_links = {}
    for server_index in range(server_count):
        role = "prefill" if server_index < P_SERVERS else "decode"
        logical_server = (f"P{server_index}" if role == "prefill" else
                          f"D{server_index - P_SERVERS}")
        for gpu in range(GPUS_PER_SERVER):
            rank = server_index * GPUS_PER_SERVER + gpu
            rail = gpu // GPUS_PER_NIC
            ranks.append({
                "astra_rank": rank,
                "gpu_id": f"{logical_server}-G{gpu}",
                "server_id": logical_server,
                "role": role,
                "gpu_local_id": gpu,
                "nic_id": nic_id(server_index, rail),
                "nic_local_id": rail,
                "nic_rate_gbps": NIC_GBPS,
                "rank_access_rate_gbps": local_gbps,
                "gpus_per_nic": GPUS_PER_NIC,
            })
            edges.append((rank, nic_id(server_index, rail), local_gbps,
                          "0.0001ms"))

    for server_index in range(server_count):
        for rail in range(NICS_PER_SERVER):
            nic = nic_id(server_index, rail)
            leaf = leaf_id(server_index, rail)
            edges.append((nic, leaf, NIC_GBPS, "0.005ms"))
            if server_index < P_SERVERS:
                if multipath:
                    spines = [spine_id(rail, p) for p in range(P_SERVERS)]
                else:
                    # Unique spine per Prefill server and rail: no ECMP choice
                    # or path collision is possible in the primary gate.
                    spines = [spine_id(rail, server_index)]
            else:
                spines = [spine_id(rail, p) for p in range(P_SERVERS)]
            for spine in spines:
                edges.append((leaf, spine, NIC_GBPS, "0.005ms"))
            if role_is_decode(server_index):
                receiver_links[f"D{server_index - P_SERVERS}-NIC{rail}"] = {
                    "nic_node": nic,
                    "leaf_node": leaf,
                    "capacity_gbps": NIC_GBPS,
                }

    switch_ids = list(range(nic_base, spine_base + spine_count))
    topology_path = directory / "topology.txt"
    with topology_path.open("w", encoding="utf-8") as stream:
        stream.write(f"{spine_base + spine_count} {len(switch_ids)} {len(edges)}\n")
        stream.write(" ".join(map(str, switch_ids)) + "\n")
        for src, dst, rate, latency in edges:
            stream.write(f"{src} {dst} {rate}Gbps {latency} 0\n")

    rank_map_path = directory / "rank_to_nic.csv"
    with rank_map_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(ranks[0]))
        writer.writeheader()
        writer.writerows(ranks)

    return {
        "topology_path": topology_path,
        "rank_map_path": rank_map_path,
        "server_count": server_count,
        "gpu_hosts": host_count,
        "nic_nodes": nic_count,
        "leaf_nodes": leaf_count,
        "spine_nodes": spine_count,
        "switch_count": len(switch_ids),
        "physical_link_count": len(edges),
        "decode_servers": decode_servers,
        "multipath": multipath,
        "receiver_links": receiver_links,
        "edges": edges,
    }


def role_is_decode(server_index):
    return server_index >= P_SERVERS


def rank(server_index, gpu):
    return server_index * GPUS_PER_SERVER + gpu


def event(event_id, request_id, src_server, src_gpu, dst_server, dst_gpu,
          rail, start_ns=0):
    return {
        "start_ns": start_ns,
        "src": rank(src_server, src_gpu),
        "dst": rank(dst_server, dst_gpu),
        "bytes": KV_BYTES_SHARD,
        "event_type": 1,  # NETWORK_EVENT_P2D_KV
        "request_id": request_id,
        "collective_id": 0,
        "layer_id": LAYERS - 1,  # POST_PREFILL aggregate shard payload
        "tag": event_id,
        "active_request_ids": str(request_id),
        "serving_role": "prefill",
        "rail": rail,
    }


def scenarios(decode_servers=1, multipath=False):
    d0 = P_SERVERS
    result = {}
    result["N0_SINGLE_SHARD"] = [event(0, 0, 0, 0, d0, 0, 0)]
    result["N1_TWO_TO_ONE_RECEIVER_NIC"] = [
        event(i, i, i, 0, d0, 0, 0) for i in range(2)]
    result["N2_FOUR_TO_ONE_RECEIVER_NIC"] = [
        event(i, i, i, 0, d0, 0, 0) for i in range(4)]
    result["N3_FOUR_TO_TWO_RECEIVER_NICS"] = [
        event(0, 0, 0, 0, d0, 0, 0),
        event(1, 1, 1, 0, d0, 1, 0),
        event(2, 2, 2, 4, d0, 4, 1),
        event(3, 3, 3, 4, d0, 5, 1),
    ]
    if decode_servers >= 2:
        d1 = d0 + 1
        result["N4_FOUR_TO_FOUR_RECEIVER_NICS"] = [
            event(0, 0, 0, 0, d0, 0, 0),
            event(1, 1, 1, 0, d1, 0, 0),
            event(2, 2, 2, 4, d0, 4, 1),
            event(3, 3, 3, 4, d1, 4, 1),
        ]
    result["N5_FOUR_PATHS_NO_RECEIVER_COLLISION"] = list(
        result["N2_FOUR_TO_ONE_RECEIVER_NIC"])
    result["FULL_FOUR_REQUESTS_TWO_REQUIRED_SHARDS"] = [
        item
        for request in range(4)
        for item in (
            event(request * 2, request, request, 0, d0, request, 0),
            event(request * 2 + 1, request, request, 4, d0, 4 + request, 1),
        )
    ]
    return result


def write_replay(directory, topology, events, case_name):
    directory.mkdir(parents=True, exist_ok=True)
    event_path = directory / "events.csv"
    columns = ["start_ns", "src", "dst", "bytes", "event_type",
               "request_id", "collective_id", "layer_id", "tag",
               "active_request_ids", "serving_role"]
    with event_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows({key: row[key] for key in columns} for row in events)
    manifest = {
        "case": case_name,
        "status": "INPUT_READY",
        "request_count": len({row["request_id"] for row in events}),
        "event_count": len(events),
        "traffic": "model-derived Qwen3-30B-A3B P2D KV, POST_PREFILL shard messages",
        "model": "Qwen3-30B-A3B-Instruct-2507",
        "input_tokens": INPUT_TOKENS,
        "kv_bytes_per_token_all_layers": KV_BYTES_PER_TOKEN,
        "kv_bytes_per_request": KV_BYTES_REQUEST,
        "kv_bytes_per_tp_rank": KV_BYTES_SHARD,
        "total_event_bytes": sum(row["bytes"] for row in events),
        "ns3_topology": str(topology["topology_path"].resolve()),
        "rank_to_nic_map": str(topology["rank_map_path"].resolve()),
        "release_pattern": "all listed messages released at start_ns; default 0",
        "packet_level_only": True,
        "serving_metrics": "NOT_AVAILABLE: fixed event replay has no serving feedback",
    }
    manifest_path = directory / "replay_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n",
                             encoding="utf-8")
    return {"events": event_path, "manifest": manifest_path}


def build(out=OUT, local_gbps=LOCAL_GBPS):
    fixture_root = out / "fixtures"
    main = build_topology(fixture_root / "4p1d_unique_spines", decode_servers=1,
                          local_gbps=local_gbps)
    two_decode = build_topology(fixture_root / "4p2d_receiver_spread",
                                decode_servers=2, local_gbps=local_gbps)
    multipath = build_topology(fixture_root / "4p1d_multipath", decode_servers=1,
                               multipath=True, local_gbps=local_gbps)
    outputs = {}
    for name, event_rows in scenarios(decode_servers=1).items():
        outputs[name] = write_replay(fixture_root / "events" / name, main,
                                     event_rows, name)
    spread = scenarios(decode_servers=2)["N4_FOUR_TO_FOUR_RECEIVER_NICS"]
    outputs["N4_FOUR_TO_FOUR_RECEIVER_NICS"] = write_replay(
        fixture_root / "events" / "N4_FOUR_TO_FOUR_RECEIVER_NICS",
        two_decode, spread, "N4_FOUR_TO_FOUR_RECEIVER_NICS")
    n5 = scenarios(decode_servers=1, multipath=True)[
        "N5_FOUR_PATHS_NO_RECEIVER_COLLISION"]
    outputs["N5_MULTIPATH_ROUTE_AUDIT"] = write_replay(
        fixture_root / "events" / "N5_MULTIPATH_ROUTE_AUDIT", multipath,
        n5, "N5_MULTIPATH_ROUTE_AUDIT")
    summary = {
        "model": "Qwen3-30B-A3B-Instruct-2507",
        "physical_rate_gbps": 200,
        "rank_access_rate_gbps": local_gbps,
        "payload_bytes": 4096,
        "cc_modes_to_test": [0, 1],
        "kv_bytes_per_token": KV_BYTES_PER_TOKEN,
        "input_tokens": INPUT_TOKENS,
        "request_kv_bytes": KV_BYTES_REQUEST,
        "tp2_required_shard_bytes": KV_BYTES_SHARD,
        "single_shard_serialization_lower_bound_ms": (
            KV_BYTES_SHARD * 8 / (NIC_GBPS * 1e9) * 1000),
        "main_topology": {
            key: value for key, value in main.items()
            if key not in ("topology_path", "rank_map_path", "edges")
        },
        "inputs": {
            name: {key: str(path.resolve()) for key, path in files.items()}
            for name, files in outputs.items()
        },
        "limitations": [
            "Packet replay only; no integrated serving scheduler feedback.",
            "No compute events are represented in these correctness cases.",
            "N4 changes receiver-server count and is a network capacity control, not the target deployment.",
            "N5 route balance is only established after inspecting actual link telemetry.",
        ],
    }
    (out / "fixture_manifest.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--local-gbps", type=int, default=LOCAL_GBPS,
                        help="rank-to-shared-NIC access cap; default preserves the 7.2-Tbps legacy topology")
    args = parser.parse_args()
    if args.local_gbps <= 0:
        parser.error("--local-gbps must be positive")
    print(json.dumps(build(args.out, args.local_gbps), indent=2))


if __name__ == "__main__":
    main()
