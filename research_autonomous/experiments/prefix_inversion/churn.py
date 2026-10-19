#!/usr/bin/env python3
"""Test whether normal Decode KV eviction creates a real P-hit/D-miss case."""

import argparse
import csv
import hashlib
import json
import os
import random
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
PYTHON = "/home/lpm/.conda/envs/llmsim-flowsim/bin/python"
P_COUNT = 8
TARGET_ARRIVAL_NS = 2_700_000_000


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_case(waves, distinct):
    case = HERE / ("churn%d%s" % (
        waves, "_distinct" if distinct else ""))
    case.mkdir(parents=True, exist_ok=True)
    topology = case / "topology.txt"
    links = ["14 4 13", "10 11 12 13"]
    for endpoint in range(10):
        switch = 10 if endpoint < 8 else endpoint + 3
        links.append("%d %d 200Gbps 0.0001ms 0" %
                     (endpoint, switch))
    for switch in (10, 11, 12):
        links.append("%d 13 100Gbps 0.005ms 0" % switch)
    topology.write_text("\n".join(links) + "\n")
    rank_map = []
    for i in range(P_COUNT):
        rank_map.extend((i, 8 if i < 4 else 9))
    rank_map.extend((8, 9))
    rank_path = case / "rank_map.json"
    rank_path.write_text(json.dumps({
        "logical_to_physical": rank_map,
        "description": "8 Prefill GPUs share source 100G; two Decode GPUs have independent 100G uplinks",
    }, indent=2) + "\n")

    def instance(role):
        return {
            "model_name": "meta-llama/Llama-3.1-8B",
            "hardware": "RTX4090",
            "npu_mem": {"mem_size": 24, "mem_bw": 1008,
                        "mem_latency": 0},
            "pd_type": role,
            "num_npus": 1,
            "tp_size": 1,
            "ep_size": 1,
        }

    config = {
        "num_nodes": 3,
        "link_bw": 100,
        "link_latency": 5000,
        "flowsim_topology": str(topology.relative_to(ROOT)),
        "flowsim_rank_map": str(rank_path.relative_to(ROOT)),
        "pd_pairing": {str(i): str(8 if i < 4 else 9)
                       for i in range(P_COUNT)},
        "nodes": [{
            "num_instances": count,
            "cpu_mem": {"mem_size": 512, "mem_bw": 256,
                        "mem_latency": 0},
            "instances": [instance(role) for _ in range(count)],
        } for role, count in (("prefill", P_COUNT),
                              ("decode", 1), ("decode", 1))],
    }
    config_path = case / "cluster.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n")

    def prefix_for(index):
        common = [1000 + value for value in range(1984)]
        if distinct:
            common[0] = 7000 + index
        return common

    rows = []
    for i in range(P_COUNT):
        rows.append({
            "input_toks": 1984,
            "output_toks": 3,
            "arrival_time_ns": 0,
            "input_tok_ids": prefix_for(i),
            "output_tok_ids": [9000 + 3 * i + j for j in range(3)],
            "paired_decode_instance_id": 8 if i < 4 else 9,
        })
    for wave in range(waves):
        for i in range(P_COUNT):
            unique_id = wave * P_COUNT + i
            rng = random.Random(unique_id + 1516)
            rows.append({
                "input_toks": 2048,
                "output_toks": 3,
                "arrival_time_ns": 300_000_000 * (wave + 1),
                "input_tok_ids": [rng.randrange(10_000, 120_000)
                                  for _ in range(2048)],
                "output_tok_ids": [12_000 + 3 * unique_id + j
                                   for j in range(3)],
                "paired_decode_instance_id": 8 if i < 4 else 9,
            })
    for i in range(P_COUNT):
        rows.append({
            "input_toks": 2048,
            "output_toks": 3,
            "arrival_time_ns": TARGET_ARRIVAL_NS,
            "input_tok_ids": prefix_for(i) + [5000 + j for j in range(64)],
            "output_tok_ids": [20_000 + 3 * i + j for j in range(3)],
            "paired_decode_instance_id": 8 if i < 4 else 9,
        })
    workload = case / "workload.jsonl"
    workload.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return case, config_path, workload


def run_case(waves, distinct):
    case, config, workload = make_case(waves, distinct)
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
           "--run-id", "prefix-churn-%d%s" % (
               waves, "-distinct" if distinct else ""),
           "--log-level", "WARNING"]
    with log.open("w") as stream:
        result = subprocess.run(cmd, cwd=ROOT, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        raise RuntimeError("churn case exited %d: %s" %
                           (result.returncode, log))
    with output.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    targets = [row for row in rows if int(row["arrival"]) ==
               TARGET_ARRIVAL_NS]
    if len(targets) != P_COUNT:
        raise AssertionError("expected eight target completions")
    manifest = {
        "command": cmd,
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "tracked_diff_sha256": hashlib.sha256(subprocess.check_output(
            ["git", "diff", "--binary"], cwd=ROOT)).hexdigest(),
        "inputs_sha256": {str(path.relative_to(ROOT)): digest(path)
                          for path in (config, workload, case / "rank_map.json",
                                       case / "topology.txt")},
        "request_count": len(rows),
    }
    (case / "manifest.json").write_text(json.dumps(
        manifest, indent=2, sort_keys=True) + "\n")
    print("churn", waves, "distinct", distinct, "requests", len(rows),
          "target_P_hits", [row["total_prefix_cache_hit_tokens"]
                            for row in targets],
          "target_ready_elapsed_ms", [
              round((int(row["p2d_kv_ready_time_ns"]) -
                     TARGET_ARRIVAL_NS) / 1e6, 3) for row in targets],
          flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--waves", type=int, choices=(0, 8), required=True)
    parser.add_argument("--distinct", action="store_true")
    args = parser.parse_args()
    run_case(args.waves, args.distinct)


if __name__ == "__main__":
    main()
