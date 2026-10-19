#!/usr/bin/env python3
"""Run a fixed 4P1D PP2 profile-domain P2D coflow sanity gate."""

import csv
import hashlib
import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
CASE = Path(__file__).resolve().parents[1]
CONFIG_DIR = CASE / "configs"
RAW = CASE / "raw"
PYTHON = "/home/lpm/.conda/envs/llmsim-flowsim/bin/python"
BASE_CONFIG = ROOT / "research_prefix_exposure/4p1d_tp2_flowsim.json"
TOPOLOGY = ROOT / ("research_ns3_incast/fixtures_rankcap200g/fixtures/"
                   "4p1d_unique_spines/topology.txt")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    config = json.loads(BASE_CONFIG.read_text())
    for node in config["nodes"]:
        instance = node["instances"][0]
        instance["num_npus"] = 4
        instance["tp_size"] = 2
        instance["pp_size"] = 2
        instance["ep_size"] = 1
    rank_map = []
    decode_ranks = [32, 36, 33, 37]
    for source in range(4):
        base = 8 * source
        rank_map.extend([base, base + 4, base + 1, base + 5])
        rank_map.extend(decode_ranks)
    rank_map.extend(decode_ranks)
    assert len(rank_map) == 36
    rank_map_path = CONFIG_DIR / "rank_map.json"
    rank_map_path.write_text(json.dumps({
        "semantics": "four 4-GPU Prefill servers; one 4-GPU Decode server; "
                     "PP stages share each server's two 200G NIC rails",
        "logical_to_physical": rank_map,
    }, indent=2) + "\n")
    config["flowsim_rank_map"] = str(rank_map_path.relative_to(ROOT))
    config_path = CONFIG_DIR / "cluster.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    workload_path = CONFIG_DIR / "four_2048x3.jsonl"
    workload_path.write_text("".join(
        json.dumps({"input_toks": 2048, "output_toks": 3,
                    "arrival_time_ns": 0}) + "\n"
        for _ in range(4)))
    return config_path, rank_map_path, workload_path


def main():
    config_path, rank_map_path, workload_path = prepare()
    csv_path = RAW / "requests.csv"
    log_path = RAW / "serving.log"
    event_path = RAW / "events.jsonl"
    flows_path = RAW / "flows.jsonl"
    for path in (csv_path, log_path, event_path, flows_path,
                 RAW / "debug.jsonl"):
        path.unlink(missing_ok=True)
    cmd = [
        PYTHON, "-m", "serving",
        "--cluster-config", str(config_path.relative_to(ROOT)),
        "--dataset", str(workload_path.relative_to(ROOT)),
        "--network-backend", "flowsim",
        "--pd-kv-transfer-mode", "LAYERWISE",
        "--flowsim-policy", "FAIR",
        "--request-routing-policy", "RR",
        "--dtype", "bfloat16",
        "--max-num-seqs", "8",
        "--max-num-batched-tokens", "2048",
        "--no-enable-prefix-caching",
        "--flowsim-telemetry", str(flows_path.relative_to(ROOT)),
        "--output", str(csv_path.relative_to(ROOT)),
        "--run-id", "autonomous-pp2-coflow-gate",
        "--log-level", "WARNING",
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = ":".join((
        str(ROOT), str(ROOT / "astra-sim/extern/graph_frontend")))
    env["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
    env["SERVING_BATCH_MISS_EVENT_LOG"] = str(event_path)
    env["FLOWSIM_TELEMETRY_CLASSES"] = "KV_MOVEMENT"
    env["FLOWSIM_MAX_FLOW_TELEMETRY_ROWS"] = "4096"
    tracked_diff = subprocess.check_output(
        ["git", "diff", "--binary"], cwd=ROOT)
    manifest = {
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "tracked_diff_sha256": hashlib.sha256(tracked_diff).hexdigest(),
        "cmd": cmd,
        "env_overrides": {key: env[key] for key in (
            "PYTHONPATH", "PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION",
            "SERVING_BATCH_MISS_EVENT_LOG", "FLOWSIM_TELEMETRY_CLASSES",
            "FLOWSIM_MAX_FLOW_TELEMETRY_ROWS")},
        "sha256": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in (
                Path(__file__),
                BASE_CONFIG, config_path, rank_map_path, workload_path,
                TOPOLOGY,
                ROOT / "configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json",
                ROOT / "profiler/perf/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/bf16/meta.yaml",
                ROOT / "profiler/perf/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/bf16/tp1/moe.csv",
                ROOT / "profiler/perf/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/bf16/tp2/dense.csv",
                ROOT / "profiler/perf/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/bf16/tp2/attention.csv",
                ROOT / "profiler/perf/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/bf16/tp2/per_sequence.csv",
                ROOT / "serving/core/trace_generator.py",
                ROOT / "serving/core/flowsim_worker.py",
                ROOT / "serving/core/flowsim_backend.py",
                ROOT / "serving/core/scheduler.py",
                ROOT / "astra-sim/extern/graph_frontend/chakra/src/converter/llm_converter.py",
            )
        },
        "randomness": "deterministic RR and FAIR; no synthetic routing seed",
    }
    (RAW / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    with log_path.open("w") as stream:
        result = subprocess.run(cmd, cwd=ROOT, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        raise RuntimeError("Serving exited %d; inspect %s" %
                           (result.returncode, log_path))
    with csv_path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 4:
        raise RuntimeError("expected four completed requests, got %d" % len(rows))
    for row in rows:
        print("request", row["request id"],
              "ready_ms", int(row["p2d_kv_ready_time_ns"]) / 1e6,
              "token2_ms", int(row["second_token_visible_ns"]) / 1e6,
              "finish_ms", int(row["end_time"]) / 1e6)


if __name__ == "__main__":
    main()
