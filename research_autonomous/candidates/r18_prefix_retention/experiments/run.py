#!/usr/bin/env python3
"""Run a two-source normal-capacity Decode prefix eviction threshold."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import random
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
PYTHON = "/home/lpm/.conda/envs/llmsim-flowsim/bin/python"
TARGET_NS = 4_800_000_000
SOURCE = (
    "serving/__main__.py", "serving/core/router.py",
    "serving/core/scheduler.py", "serving/core/kv_cache_manager.py",
    "serving/core/block_pool.py", "serving/core/trace_generator.py",
    "serving/core/graph_generator.py", "serving/core/flowsim_backend.py",
    "serving/core/flowsim_worker.py",
    "astra-sim/extern/graph_frontend/chakra/src/converter/llm_converter.py",
)
PROFILE = (
    "configs/model/meta-llama/Llama-3.1-8B.json",
    "profiler/models/llama.yaml",
    "profiler/perf/RTX4090/meta-llama/Llama-3.1-8B/bf16/meta.yaml",
    "profiler/perf/RTX4090/meta-llama/Llama-3.1-8B/bf16/tp1/dense.csv",
    "profiler/perf/RTX4090/meta-llama/Llama-3.1-8B/bf16/tp1/attention.csv",
    "profiler/perf/RTX4090/meta-llama/Llama-3.1-8B/bf16/tp1/per_sequence.csv",
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def instance(role):
    return {
        "model_name": "meta-llama/Llama-3.1-8B", "hardware": "RTX4090",
        "npu_mem": {"mem_size": 24, "mem_bw": 1008, "mem_latency": 0},
        "pd_type": role, "num_npus": 1, "tp_size": 1, "ep_size": 1,
    }


def row(length, output, arrival, tokens):
    return {
        "input_toks": length, "output_toks": output,
        "arrival_time_ns": arrival, "input_tok_ids": tokens,
        "output_tok_ids": [80_000 + j for j in range(output)],
        "paired_decode_instance_id": 2,
    }


def make_case(fillers, refresh=False, tag="", history_repeat=False,
              varied_fillers=False, eviction_policy="LRU"):
    if fillers not in (24, 28):
        raise ValueError("registered cases are 24 and 28 fillers")
    if refresh and fillers != 28:
        raise ValueError("refresh ablation is registered only after 28 fillers")
    if (history_repeat or varied_fillers) and (fillers != 28 or refresh):
        raise ValueError("Round-19 history/cost gate requires 28 fillers and no refresh")
    if tag and (not tag.isalnum() or len(tag) > 24):
        raise ValueError("tag must be one to 24 alphanumeric characters")
    suffix = "_refresh" if refresh else ""
    if history_repeat:
        suffix += "_history"
    if varied_fillers:
        suffix += "_varied"
    if eviction_policy != "LRU":
        suffix += "_" + eviction_policy.lower()
    case = HERE / ("filler_%02d%s%s" % (
        fillers, suffix, "_" + tag if tag else ""))
    if case.exists():
        raise FileExistsError("Refusing to overwrite " + str(case))
    case.mkdir()
    topology = case / "topology.txt"
    topology.write_text(
        "6 3 5\n3 4 5\n"
        "0 3 200Gbps 0.0001ms 0\n"
        "1 3 200Gbps 0.0001ms 0\n"
        "2 4 200Gbps 0.0001ms 0\n"
        "3 5 100Gbps 0.005ms 0\n"
        "4 5 100Gbps 0.005ms 0\n")
    rank_map = case / "rank_map.json"
    rank_map.write_text(json.dumps({
        "logical_to_physical": [0, 2, 1, 2, 2],
        "description": "two P GPUs share source 100G; one D GPU has independent 100G",
    }, indent=2) + "\n")
    cluster = case / "cluster.json"
    cluster.write_text(json.dumps({
        "num_nodes": 2, "link_bw": 100, "link_latency": 5000,
        "flowsim_topology": str(topology.relative_to(ROOT)),
        "flowsim_rank_map": str(rank_map.relative_to(ROOT)),
        "pd_pairing": {"0": "2", "1": "2"},
        "nodes": [{
            "num_instances": 2,
            "cpu_mem": {"mem_size": 512, "mem_bw": 256, "mem_latency": 0},
            "instances": [instance("prefill"), instance("prefill")],
        }, {
            "num_instances": 1,
            "cpu_mem": {"mem_size": 512, "mem_bw": 256, "mem_latency": 0},
            "instances": [instance("decode")],
        }],
    }, indent=2) + "\n")
    prefixes = []
    for source in range(2):
        prefix = [7_000 + source] + [1_000 + j for j in range(1983)]
        prefixes.append(prefix)
    workload_rows = [row(1984, 3, 0, prefix) for prefix in prefixes]
    if history_repeat:
        for prefix in prefixes:
            workload_rows.append(row(1984, 3, 100_000_000, prefix))
    for i in range(fillers):
        rng = random.Random(1516 + i)
        length = 3072 if varied_fillers and i % 2 else 2048
        tokens = [10_000 + i] + [rng.randrange(20_000, 120_000)
                               for _ in range(length - 1)]
        filler_arrival = ((i // 2 + 1) * 300_000_000 +
                          (100_000_000 if history_repeat else 0))
        workload_rows.append(row(length, 3, filler_arrival,
                                 tokens))
    if refresh:
        for source, prefix in enumerate(prefixes):
            workload_rows.append(row(
                2048, 3, 4_500_000_000,
                prefix + [60_000 + 64 * source + j for j in range(64)]))
    target_ns = 5_500_000_000 if history_repeat or varied_fillers else TARGET_NS
    for source, prefix in enumerate(prefixes):
        workload_rows.append(row(
            2048, 3, target_ns,
            prefix + [50_000 + 64 * source + j for j in range(64)]))
    workload = case / "workload.jsonl"
    workload.write_text("".join(json.dumps(item, sort_keys=True) + "\n"
                                for item in workload_rows))
    return case, cluster, workload, topology, rank_map, target_ns


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fillers", type=int, choices=(24, 28), required=True)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--tag", default="",
                        help="append a fresh alphanumeric case suffix")
    parser.add_argument("--history-repeat", action="store_true")
    parser.add_argument("--varied-fillers", action="store_true")
    parser.add_argument("--eviction-policy", choices=("LRU", "LFU"),
                        default="LRU")
    args = parser.parse_args()
    case, cluster, workload, topology, rank_map, target_ns = make_case(
        args.fillers, args.refresh, args.tag, args.history_repeat,
        args.varied_fillers, args.eviction_policy)
    env = dict(os.environ)
    env["PYTHONPATH"] = ":".join((
        str(ROOT), str(ROOT / "astra-sim/extern/graph_frontend")))
    env["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
    env["FLOWSIM_TELEMETRY_CLASSES"] = "KV_MOVEMENT"
    env["FLOWSIM_MAX_FLOW_TELEMETRY_ROWS"] = "4096"
    env["SERVING_BATCH_MISS_EVENT_LOG"] = str(case / "events.jsonl")
    command = [PYTHON, "-u", "-m", "serving",
               "--network-backend", "flowsim",
               "--cluster-config", str(cluster.relative_to(ROOT)),
               "--dataset", str(workload.relative_to(ROOT)),
               "--num-reqs", str(args.fillers + 4 +
                                  (2 if args.refresh else 0) +
                                  (2 if args.history_repeat else 0)),
               "--request-routing-policy", "RR", "--max-num-seqs", "8",
               "--max-num-batched-tokens", "2048",
               "--enable-prefix-caching", "--enable-chunked-prefill",
               "--destination-prefix-handoff", "DELTA",
               "--pd-handoff-capacity-reservation",
               "--decode-kv-eviction-policy", args.eviction_policy,
               "--pd-kv-transfer-mode", "LAYERWISE",
               "--flowsim-policy", "FAIR",
               "--flowsim-telemetry",
               str((case / "flows.jsonl").relative_to(ROOT)),
               "--output", str((case / "requests.csv").relative_to(ROOT)),
               "--run-id", "r18-prefix-%02d%s" % (
                   args.fillers, "-refresh" if args.refresh else "") +
               ("-history" if args.history_repeat else "") +
               ("-varied" if args.varied_fillers else "") +
               ("-" + args.eviction_policy.lower()) +
               ("-" + args.tag if args.tag else ""),
               "--log-level", "WARNING", "--log-interval", "60"]
    versions = {}
    for package in ("protobuf", "pandas", "networkx", "numpy"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    manifest = {
        "status": "STARTED", "command": command,
        "purpose": "controlled cache-eviction motivation threshold, no policy gain claim",
        "seed": "random.Random(1516+i) per filler; fixed token IDs otherwise",
        "fillers": args.fillers,
        "refresh": args.refresh,
        "history_repeat": args.history_repeat,
        "varied_fillers": args.varied_fillers,
        "eviction_policy": args.eviction_policy,
        "target_arrival_ns": target_ns,
        "python": sys.version, "dependencies": versions,
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "tracked_diff_sha256": hashlib.sha256(subprocess.check_output(
            ["git", "diff", "--binary"], cwd=ROOT)).hexdigest(),
        "source_sha256": {name: digest(ROOT / name) for name in SOURCE},
        "input_sha256": {str(path.relative_to(ROOT)): digest(path)
                         for path in (cluster, workload, topology, rank_map)},
        "profile_sha256": {name: digest(ROOT / name) for name in PROFILE},
        "runner_sha256": digest(Path(__file__)),
    }
    (case / "manifest.json").write_text(json.dumps(
        manifest, indent=2, sort_keys=True) + "\n")
    with (case / "serving.log").open("w") as stream:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, check=False,
                                timeout=900)
    manifest["exit_code"] = result.returncode
    manifest["status"] = "COMPLETE" if result.returncode == 0 else "INVALID"
    manifest["output_sha256"] = {
        name: digest(case / name)
        for name in ("requests.csv", "events.jsonl", "flows.jsonl")
        if (case / name).exists()}
    (case / "manifest.json").write_text(json.dumps(
        manifest, indent=2, sort_keys=True) + "\n")
    if result.returncode:
        raise RuntimeError("simulation failed: " + str(case / "serving.log"))
    print(case, "complete")


if __name__ == "__main__":
    main()
