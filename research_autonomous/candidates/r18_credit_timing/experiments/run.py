#!/usr/bin/env python3
"""Run the normal-pool four-Prefill Decode-credit threshold."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
PYTHON = "/home/lpm/.conda/envs/llmsim-flowsim/bin/python"
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


def make_case(prompt_tokens, tag="", admission="EARLY_LAYERWISE",
              shape="UNIFORM", flow_policy="FAIR", first_id=None):
    if prompt_tokens not in (12000, 14000):
        raise ValueError("registered lengths are 12000 and 14000")
    if tag and (not tag.isalnum() or len(tag) > 24):
        raise ValueError("tag must be one to 24 alphanumeric characters")
    suffix = ""
    if admission != "EARLY_LAYERWISE":
        suffix += "_" + admission.lower()
    if shape != "UNIFORM":
        suffix += "_" + shape.lower()
    if flow_policy != "FAIR":
        suffix += "_requestfirst%d" % first_id
    case = HERE / ("prompt_%05d%s%s" % (
        prompt_tokens, suffix, "_" + tag if tag else ""))
    if case.exists():
        raise FileExistsError("Refusing to overwrite " + str(case))
    case.mkdir()
    topology = case / "topology.txt"
    topology.write_text(
        "8 3 7\n5 6 7\n"
        "0 5 200Gbps 0.0001ms 0\n"
        "1 5 200Gbps 0.0001ms 0\n"
        "2 5 200Gbps 0.0001ms 0\n"
        "3 5 200Gbps 0.0001ms 0\n"
        "4 6 200Gbps 0.0001ms 0\n"
        "5 7 100Gbps 0.005ms 0\n"
        "6 7 100Gbps 0.005ms 0\n")
    rank_map = case / "rank_map.json"
    rank_map.write_text(json.dumps({
        "logical_to_physical": [0, 4, 1, 4, 2, 4, 3, 4, 4],
        "description": "four P GPUs share source 100G; D on independent100G",
    }, indent=2) + "\n")
    cluster = case / "cluster.json"
    cluster.write_text(json.dumps({
        "num_nodes": 2, "link_bw": 100, "link_latency": 5000,
        "flowsim_topology": str(topology.relative_to(ROOT)),
        "flowsim_rank_map": str(rank_map.relative_to(ROOT)),
        "pd_pairing": {str(i): "4" for i in range(4)},
        "nodes": [{
            "num_instances": 4,
            "cpu_mem": {"mem_size": 512, "mem_bw": 256, "mem_latency": 0},
            "instances": [instance("prefill") for _ in range(4)],
        }, {
            "num_instances": 1,
            "cpu_mem": {"mem_size": 512, "mem_bw": 256, "mem_latency": 0},
            "instances": [instance("decode")],
        }],
    }, indent=2) + "\n")
    workload = case / "workload.jsonl"
    if shape == "UNIFORM":
        jobs = [(prompt_tokens, 64, 0)] * 4
    elif shape == "HETERO":
        if prompt_tokens != 14000:
            raise ValueError("registered heterogeneous gate uses prompt-tokens 14000")
        jobs = [(12000, 32, 0), (14000, 96, 200_000_000),
                (14000, 48, 400_000_000), (16000, 64, 600_000_000)]
    else:
        raise ValueError("unknown shape")
    workload.write_text("".join(json.dumps({
        "input_toks": length, "output_toks": output,
        "arrival_time_ns": arrival, "paired_decode_instance_id": 4,
    }, sort_keys=True) + "\n" for length, output, arrival in jobs))
    return case, cluster, workload, topology, rank_map


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-tokens", type=int,
                        choices=(12000, 14000), required=True)
    parser.add_argument("--tag", default="",
                        help="append a fresh alphanumeric case suffix")
    parser.add_argument("--admission", choices=(
        "EARLY_LAYERWISE", "EARLY_POST", "TWO_STAGE_FIFO"),
        default="EARLY_LAYERWISE")
    parser.add_argument("--shape", choices=("UNIFORM", "HETERO"),
                        default="UNIFORM")
    parser.add_argument("--flow-policy", choices=("FAIR", "KV_REQUEST_FIRST"),
                        default="FAIR")
    parser.add_argument("--first-id", type=int, default=None)
    args = parser.parse_args()
    if args.flow_policy == "KV_REQUEST_FIRST" and args.first_id not in range(4):
        parser.error("KV_REQUEST_FIRST requires --first-id in 0..3")
    case, cluster, workload, topology, rank_map = make_case(
        args.prompt_tokens, args.tag, args.admission, args.shape,
        args.flow_policy, args.first_id)
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
               "--num-reqs", "4",
               "--request-routing-policy", "RR", "--max-num-seqs", "8",
               "--max-num-batched-tokens", "2048",
               "--no-enable-prefix-caching", "--enable-chunked-prefill",
               "--pd-handoff-capacity-reservation",
               "--pd-kv-transfer-mode", (
                   "LAYERWISE" if args.admission == "EARLY_LAYERWISE"
                   else "POST_PREFILL"),
               "--pd-handoff-admission", (
                   "TWO_STAGE_FIFO" if args.admission == "TWO_STAGE_FIFO"
                   else "EARLY"),
               "--flowsim-policy", args.flow_policy,
               "--flowsim-telemetry",
               str((case / "flows.jsonl").relative_to(ROOT)),
               "--output", str((case / "requests.csv").relative_to(ROOT)),
               "--run-id", "r18-credit-%05d-%s-%s-%s%s" % (
                   args.prompt_tokens, args.admission.lower(),
                   args.shape.lower(),
                   ("fair" if args.flow_policy == "FAIR" else
                    "requestfirst%d" % args.first_id),
                   "-" + args.tag if args.tag else ""),
               "--log-level", "WARNING", "--log-interval", "60"]
    if args.flow_policy == "KV_REQUEST_FIRST":
        position = command.index("--flowsim-policy") + 2
        command[position:position] = [
            "--flowsim-request-first-id", str(args.first_id)]
    versions = {}
    for package in ("protobuf", "pandas", "networkx", "numpy"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    manifest = {
        "status": "STARTED", "command": command,
        "purpose": "matched P/D capacity-credit admission comparison",
        "admission": args.admission,
        "shape": args.shape,
        "flow_policy": args.flow_policy,
        "first_id": args.first_id,
        "seed": "four deterministic length-only requests, no token ID cache",
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
