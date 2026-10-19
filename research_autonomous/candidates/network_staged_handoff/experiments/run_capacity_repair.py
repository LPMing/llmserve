#!/usr/bin/env python3
"""Exercise normal 24-GB Decode KV exhaustion with a finite 2P:1D burst."""

import argparse
import csv
import hashlib
import json
import os
import subprocess
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
CASE = HERE / "normal_capacity_30req"
PYTHON = "/home/lpm/.conda/envs/llmsim-flowsim/bin/python"
SOURCE = (
    ROOT / "serving/__main__.py", ROOT / "serving/core/router.py",
    ROOT / "serving/core/scheduler.py", ROOT / "serving/core/kv_cache_manager.py",
    ROOT / "serving/core/trace_generator.py",
    ROOT / "serving/core/flowsim_backend.py",
    ROOT / "serving/core/flowsim_worker.py",
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def instance(role):
    return {
        "model_name": "meta-llama/Llama-3.1-8B", "hardware": "RTX4090",
        "npu_mem": {"mem_size": 24, "mem_bw": 1008, "mem_latency": 0},
        "pd_type": role, "num_npus": 1, "tp_size": 1, "ep_size": 1,
    }


def main():
    global CASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunked", action="store_true")
    args = parser.parse_args()
    if args.chunked:
        CASE = HERE / "normal_capacity_30req_chunked"
    if CASE.exists():
        raise FileExistsError("Refusing to overwrite %s" % CASE)
    CASE.mkdir(parents=True)
    topology = CASE / "topology.txt"
    topology.write_text("6 3 5\n3 4 5\n"
                        "0 3 200Gbps 0.0001ms 0\n"
                        "1 3 200Gbps 0.0001ms 0\n"
                        "2 4 200Gbps 0.0001ms 0\n"
                        "3 5 100Gbps 0.005ms 0\n"
                        "4 5 100Gbps 0.005ms 0\n")
    rank_map = CASE / "rank_map.json"
    rank_map.write_text(json.dumps({
        "logical_to_physical": [0, 2, 1, 2, 2],
        "description": "two RTX4090 P GPUs on one100G node and one D GPU on another100G node",
    }, indent=2) + "\n")
    cluster = CASE / "cluster.json"
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
    workload = CASE / "workload.jsonl"
    workload.write_text("".join(json.dumps({
        "input_toks": 2048, "output_toks": 300,
        "arrival_time_ns": 0, "paired_decode_instance_id": 2,
    }, sort_keys=True) + "\n" for _ in range(30)))

    env = dict(os.environ)
    env["PYTHONPATH"] = ":".join((
        str(ROOT), str(ROOT / "astra-sim/extern/graph_frontend")))
    env["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
    env["FLOWSIM_TELEMETRY_CLASSES"] = "KV_MOVEMENT"
    env["FLOWSIM_MAX_FLOW_TELEMETRY_ROWS"] = "4096"
    env["SERVING_BATCH_MISS_EVENT_LOG"] = str(CASE / "events.jsonl")
    cmd = [PYTHON, "-u", "-m", "serving", "--network-backend", "flowsim",
           "--cluster-config", str(cluster.relative_to(ROOT)),
           "--dataset", str(workload.relative_to(ROOT)), "--num-reqs", "30",
           "--request-routing-policy", "RR", "--max-num-seqs", "8",
           "--max-num-batched-tokens", "2048",
           "--no-enable-prefix-caching",
           "--enable-chunked-prefill" if args.chunked else
           "--no-enable-chunked-prefill",
           "--pd-kv-transfer-mode", "LAYERWISE",
           "--pd-handoff-capacity-reservation", "--flowsim-policy", "FAIR",
           "--flowsim-telemetry", str((CASE / "flows.jsonl").relative_to(ROOT)),
           "--output", str((CASE / "requests.csv").relative_to(ROOT)),
           "--run-id", "r16-normal-capacity-30req-chunked" if args.chunked else
           "r16-normal-capacity-30req", "--log-level", "WARNING",
           "--log-interval", "60"]
    manifest = {
        "command": cmd, "seed": "deterministic identical lengths, no RNG",
        "purpose": "correctness-only normal-capacity backpressure; no policy gain claim",
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "input_sha256": {str(path.relative_to(ROOT)): digest(path)
                          for path in (cluster, topology, rank_map, workload,
                                       ROOT / "configs/model/meta-llama/Llama-3.1-8B.json",
                                       ROOT / "profiler/perf/RTX4090/meta-llama/Llama-3.1-8B/bf16/meta.yaml")},
        "source_sha256": {str(path.relative_to(ROOT)): digest(path)
                          for path in SOURCE},
        "runner_sha256": digest(Path(__file__)),
        "status": "STARTED",
    }
    (CASE / "manifest.json").write_text(json.dumps(
        manifest, indent=2, sort_keys=True) + "\n")
    with (CASE / "serving.log").open("w") as stream:
        result = subprocess.run(cmd, cwd=ROOT, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, check=False,
                                timeout=900)
    manifest["exit_code"] = result.returncode
    manifest["status"] = "COMPLETE" if result.returncode == 0 else "FAILED"
    manifest["output_sha256"] = {path.name: digest(path)
                                 for path in (CASE / "requests.csv",
                                              CASE / "events.jsonl",
                                              CASE / "flows.jsonl")
                                 if path.exists()}
    (CASE / "manifest.json").write_text(json.dumps(
        manifest, indent=2, sort_keys=True) + "\n")
    if result.returncode:
        raise RuntimeError("capacity repair run failed; see %s" %
                           (CASE / "serving.log"))
    rows = list(csv.DictReader((CASE / "requests.csv").open()))
    counts = Counter(json.loads(line)["event"]
                     for line in (CASE / "events.jsonl").open()
                     if line.startswith("{"))
    if len(rows) != 30:
        raise AssertionError("expected all30 requests to complete")
    print("complete", len(rows), "capacity_wait_events",
          counts["HANDOFF_CAPACITY_WAIT"], flush=True)


if __name__ == "__main__":
    main()
