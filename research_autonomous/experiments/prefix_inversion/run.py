#!/usr/bin/env python3
"""Run a small P/D prefix-hit experiment on an eight-GPU/one-NIC topology."""

import argparse
import csv
import hashlib
import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
PYTHON = "/home/lpm/.conda/envs/llmsim-flowsim/bin/python"
MODEL = "meta-llama/Llama-3.1-8B"
PROMPT = 2048
TARGET_ARRIVAL_NS = 350_000_000


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_case(m, hit, destination):
    case = HERE / ("p%d_hit%d_%s" % (m, hit, destination))
    case.mkdir(parents=True, exist_ok=True)
    instances = []
    for role, count in (("prefill", m), ("decode", 2 * m)):
        for _ in range(count):
            instances.append({
                "model_name": MODEL,
                "hardware": "RTX4090",
                "npu_mem": {"mem_size": 24, "mem_bw": 1008,
                            "mem_latency": 0},
                "pd_type": role,
                "num_npus": 1,
                "tp_size": 1,
                "ep_size": 1,
            })

    # Endpoint IDs 0..m-1 share the Prefill node. Place half of each Decode
    # cohort on each of two independent 100G nodes.
    node_labels = {1: [], 2: []}
    for i in range(m):
        warm_node = 1 + i % 2
        cold_node = 3 - warm_node
        node_labels[warm_node].append(("warm", i))
        node_labels[cold_node].append(("cold", i))
    assert all(len(labels) == m for labels in node_labels.values())
    decode_ids = {}
    for node in (1, 2):
        for local_index, label in enumerate(node_labels[node]):
            decode_ids[label] = m * node + local_index
    rank_map = []
    for i in range(m):
        rank_map.extend((i, decode_ids[("warm", i)]))
    rank_map.extend(range(m, 3 * m))
    rank_path = case / "rank_map.json"
    rank_path.write_text(json.dumps({
        "logical_to_physical": rank_map,
        "description": "Prefill source node has one 100G uplink; two Decode nodes have independent 100G uplinks",
    }, indent=2) + "\n")

    switch_base = 3 * m
    core = switch_base + 3
    lines = ["%d 4 %d" % (core + 1, 3 * m + 3),
             "%d %d %d %d" % (switch_base, switch_base + 1,
                                switch_base + 2, core)]
    for endpoint in range(3 * m):
        node = endpoint // m
        lines.append("%d %d 200Gbps 0.0001ms 0" %
                     (endpoint, switch_base + node))
    for node in range(3):
        lines.append("%d %d 100Gbps 0.005ms 0" %
                     (switch_base + node, core))
    topology_path = case / "topology.txt"
    topology_path.write_text("\n".join(lines) + "\n")

    config = {
        "num_nodes": 3,
        "link_bw": 100,
        "link_latency": 5000,
        "flowsim_topology": str(topology_path.relative_to(ROOT)),
        "flowsim_rank_map": str(rank_path.relative_to(ROOT)),
        "pd_pairing": {str(i): str(decode_ids[("warm", i)])
                       for i in range(m)},
        "nodes": [{
            "num_instances": m,
            "cpu_mem": {"mem_size": 512, "mem_bw": 256,
                        "mem_latency": 0},
            "instances": instances[:m],
        }, {
            "num_instances": m,
            "cpu_mem": {"mem_size": 512, "mem_bw": 256,
                        "mem_latency": 0},
            "instances": instances[m:2 * m],
        }, {
            "num_instances": m,
            "cpu_mem": {"mem_size": 512, "mem_bw": 256,
                        "mem_latency": 0},
            "instances": instances[2 * m:],
        }],
    }
    config_path = case / "cluster.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n")

    prefix = [1000 + i for i in range(PROMPT)]
    workload = []
    for i in range(m):
        if hit:
            workload.append({
                "input_toks": hit,
                "output_toks": 3,
                "arrival_time_ns": 0,
                "input_tok_ids": prefix[:hit],
                "output_tok_ids": [10000 + i * 3 + j for j in range(3)],
                "paired_decode_instance_id": decode_ids[("warm", i)],
            })
    for i in range(m):
        tokens = (prefix if hit else
                  [20000 + i * PROMPT + j for j in range(PROMPT)])
        target = decode_ids[("warm", i)] if destination == "resident" else \
            decode_ids[("cold", i)]
        workload.append({
            "input_toks": PROMPT,
            "output_toks": 3,
            "arrival_time_ns": TARGET_ARRIVAL_NS,
            "input_tok_ids": tokens,
            "output_tok_ids": [50000 + i * 3 + j for j in range(3)],
            "paired_decode_instance_id": target,
        })
    workload_path = case / "workload.jsonl"
    workload_path.write_text("".join(json.dumps(row) + "\n"
                                    for row in workload))
    return case, config_path, workload_path


def run_case(m, hit, destination):
    case, config, workload = make_case(m, hit, destination)
    output = case / "requests.csv"
    log = case / "serving.log"
    events = case / "events.jsonl"
    flows = case / "flows.jsonl"
    for path in (output, log, events, flows, case / "link_telemetry.jsonl",
                 case / "collective_telemetry.jsonl",
                 case / "kv_event_telemetry.jsonl"):
        path.unlink(missing_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = ":".join((
        str(ROOT), str(ROOT / "astra-sim/extern/graph_frontend")))
    env["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
    env["FLOWSIM_TELEMETRY_CLASSES"] = "KV_MOVEMENT"
    env["FLOWSIM_MAX_FLOW_TELEMETRY_ROWS"] = "4096"
    env["SERVING_BATCH_MISS_EVENT_LOG"] = str(events)
    cmd = [PYTHON, "-m", "serving",
           "--cluster-config", str(config.relative_to(ROOT)),
           "--dataset", str(workload.relative_to(ROOT)),
           "--network-backend", "flowsim",
           "--pd-kv-transfer-mode", "LAYERWISE",
           "--flowsim-policy", "FAIR",
           "--request-routing-policy", "RR",
           "--dtype", "bfloat16",
           "--max-num-seqs", "8",
           "--max-num-batched-tokens", "2048",
           "--enable-prefix-caching",
           "--destination-prefix-handoff", "DELTA",
           "--flowsim-telemetry", str(flows.relative_to(ROOT)),
           "--output", str(output.relative_to(ROOT)),
           "--run-id", "prefix-inversion-p%d-h%d-%s" %
                       (m, hit, destination),
           "--log-level", "WARNING"]
    with log.open("w") as stream:
        result = subprocess.run(cmd, cwd=ROOT, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        raise RuntimeError("case exited %d: %s" % (result.returncode, log))
    with output.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    manifest = {
        "command": cmd,
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "tracked_diff_sha256": hashlib.sha256(subprocess.check_output(
            ["git", "diff", "--binary"], cwd=ROOT)).hexdigest(),
        "inputs_sha256": {str(path.relative_to(ROOT)): digest(path)
                          for path in (config, workload,
                                       case / "rank_map.json",
                                       case / "topology.txt")},
        "request_count": len(rows),
    }
    (case / "manifest.json").write_text(json.dumps(
        manifest, indent=2, sort_keys=True) + "\n")
    targets = [row for row in rows if int(row["arrival"]) ==
               TARGET_ARRIVAL_NS]
    if len(targets) != m:
        raise AssertionError("expected %d target requests, found %d" %
                             (m, len(targets)))
    print("case", m, hit, destination,
          "P-hit", [row["total_prefix_cache_hit_tokens"]
                   for row in targets],
          "ready_ms", [round(int(row["p2d_kv_ready_time_ns"]) / 1e6, 3)
                       for row in targets], flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--m", type=int, choices=(1, 2, 4, 8), required=True)
    parser.add_argument("--hit", type=int, choices=(0, 1024, 1536, 1792,
                                                    1920, 1984), required=True)
    parser.add_argument("--destination", choices=("miss", "resident"),
                        required=True)
    args = parser.parse_args()
    if args.hit == 0 and args.destination == "resident":
        parser.error("a destination cannot hold a prefix with no warmup")
    run_case(args.m, args.hit, args.destination)


if __name__ == "__main__":
    main()
