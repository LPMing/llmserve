#!/usr/bin/env python3
"""Enumerate fixed-resource 3P2D P2D assignments on a small Qwen cohort."""

import csv
import hashlib
import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
PYTHON = "/home/lpm/.conda/envs/llmsim-flowsim/bin/python"
BASE = ROOT / "research_cache_network_joint/3p2d_tp2_flowsim.json"
WORKLOAD = HERE / "cohort_3x2048.jsonl"
MODES = ("POST_PREFILL", "LAYERWISE")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_one(mode, bits, base):
    case = f"{mode.lower()}_{bits}"
    config = json.loads(json.dumps(base))
    config["pd_pairing"] = {
        str(index): str(3 + int(bit)) for index, bit in enumerate(bits)
    }
    config_path = RUNS / f"{case}.json"
    csv_path = RUNS / f"{case}.csv"
    log_path = RUNS / f"{case}.log"
    events_path = RUNS / f"{case}_events.jsonl"
    flows_path = RUNS / f"{case}_flows.jsonl"
    events_path.unlink(missing_ok=True)
    flows_path.unlink(missing_ok=True)
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    command = [
        PYTHON, "-m", "serving",
        "--cluster-config", str(config_path.relative_to(ROOT)),
        "--dataset", str(WORKLOAD.relative_to(ROOT)),
        "--network-backend", "flowsim",
        "--pd-kv-transfer-mode", mode,
        "--flowsim-policy", "FAIR",
        "--request-routing-policy", "RR",
        "--dtype", "bfloat16",
        "--max-num-seqs", "8",
        "--max-num-batched-tokens", "2048",
        "--no-enable-prefix-caching",
        "--flowsim-telemetry", str(flows_path.relative_to(ROOT)),
        "--output", str(csv_path.relative_to(ROOT)),
        "--run-id", "receiver-gate-" + case,
        "--log-level", "WARNING",
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = ":".join((
        str(ROOT), str(ROOT / "astra-sim/extern/graph_frontend")))
    env["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
    env["SERVING_BATCH_MISS_EVENT_LOG"] = str(events_path)
    env["FLOWSIM_TELEMETRY_CLASSES"] = "KV_MOVEMENT"
    with log_path.open("w") as stream:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        raise RuntimeError(f"{case} failed ({result.returncode}): {log_path}")
    with csv_path.open(newline="") as stream:
        requests = list(csv.DictReader(stream))
    if len(requests) != 3 or {int(row["request id"]) for row in requests} != {0, 1, 2}:
        raise RuntimeError(f"{case}: expected three completed requests")
    by_id = sorted(requests, key=lambda row: int(row["request id"]))
    if any(int(row["second_token_visible_ns"]) < 0 for row in by_id):
        raise RuntimeError(f"{case}: missing independently computed token 2")
    return {
        "mode": mode, "assignment": bits,
        "decode_instances": "|".join(row["instance id"] for row in by_id),
        "mean_p2d_ready_ms": sum(int(row["p2d_kv_ready_time_ns"])
                                  for row in by_id) / 3e6,
        "mean_token2_ms": sum(int(row["second_token_visible_ns"])
                               for row in by_id) / 3e6,
        "max_token2_ms": max(int(row["second_token_visible_ns"])
                             for row in by_id) / 1e6,
        "mean_completion_ms": sum(int(row["end_time"])
                                   for row in by_id) / 3e6,
        "max_completion_ms": max(int(row["end_time"])
                                 for row in by_id) / 1e6,
        "csv_sha256": digest(csv_path),
        "config_sha256": digest(config_path),
    }


def main():
    RUNS.mkdir(exist_ok=True)
    base = json.loads(BASE.read_text())
    rows = []
    for mode in MODES:
        for number in range(8):
            bits = format(number, "03b")
            row = run_one(mode, bits, base)
            rows.append(row)
            print(mode, bits, f"token2={row['mean_token2_ms']:.6f} ms",
                  f"completion={row['mean_completion_ms']:.6f} ms", flush=True)
    summary = HERE / "01_EXHAUSTIVE_ASSIGNMENT_RESULTS.csv"
    with summary.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    paths = [
        BASE, WORKLOAD,
        ROOT / base["flowsim_topology"],
        ROOT / base["flowsim_rank_map"],
        ROOT / "configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json",
        ROOT / "profiler/perf/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/bf16/meta.yaml",
        ROOT / "profiler/perf/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/bf16/tp2/dense.csv",
        ROOT / "profiler/perf/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/bf16/tp2/attention.csv",
        ROOT / "profiler/perf/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/bf16/tp2/per_sequence.csv",
        ROOT / "profiler/perf/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/bf16/tp1/moe.csv",
        ROOT / "serving/__main__.py", ROOT / "serving/core/router.py",
        ROOT / "serving/core/scheduler.py",
        ROOT / "serving/core/trace_generator.py",
        ROOT / "serving/core/flowsim_worker.py",
        ROOT / "serving/core/flowsim_backend.py",
    ]
    provenance = {
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "tracked_diff_sha256": hashlib.sha256(subprocess.check_output(
            ["git", "diff", "--binary"], cwd=ROOT)).hexdigest(),
        "python": PYTHON,
        "sha256": {str(path.relative_to(ROOT)): digest(path) for path in paths},
    }
    (HERE / "00_PROVENANCE.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
