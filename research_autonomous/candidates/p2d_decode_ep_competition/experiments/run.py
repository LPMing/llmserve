#!/usr/bin/env python3
"""Run a bounded P2D/Decode-EP overlap falsification case."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
PYTHON = "/home/lpm/.conda/envs/llmsim-flowsim/bin/python"
CONFIG = ROOT / "experiments/pd_kv_ep/configs/ep_ep_minimal/two_ep4_groups_full.json"
RANK_MAP = ROOT / "experiments/pd_kv_ep/configs/ep_ep_minimal/two_ep4_groups_full_logical_to_physical.json"
TOPOLOGY = ROOT / "experiments/pd_kv_ep/configs/large_scale/flowsim/minimal_1p2d_ep16_single_tor_nvlink.txt"
PROFILE = ROOT / "profiler/perf/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/bf16/meta.yaml"
MODEL = ROOT / "configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json"
SOURCE_FILES = (
    ROOT / "serving/__main__.py",
    ROOT / "serving/core/router.py",
    ROOT / "serving/core/scheduler.py",
    ROOT / "serving/core/trace_generator.py",
    ROOT / "serving/core/graph_generator.py",
    ROOT / "serving/core/flowsim_backend.py",
    ROOT / "serving/core/flowsim_worker.py",
    ROOT / "astra-sim/extern/graph_frontend/chakra/src/converter/llm_converter.py",
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_workload(control=False):
    rows = []
    for _ in range(8):
        rows.append({"input_toks": 128, "output_toks": 32,
                     "arrival_time_ns": 0})
    if not control:
        for arrival_ms in (100, 180, 260, 340):
            for _ in range(4):
                rows.append({"input_toks": 2048, "output_toks": 3,
                             "arrival_time_ns": arrival_ms * 1_000_000})
    assert len(rows) == (8 if control else 24)
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", choices=("FAIR", "EP_FIRST", "KV_FIRST"),
                        required=True)
    parser.add_argument("--control", action="store_true",
                        help="run only the eight incumbent Decode requests")
    args = parser.parse_args()
    case = HERE / (("control_" if args.control else "") +
                   args.policy.lower())
    if case.exists():
        raise FileExistsError("Refusing to overwrite an existing run: %s" % case)
    case.mkdir(parents=True)
    count = 8 if args.control else 24
    workload = HERE / ("workload_%d.jsonl" % count)
    content = make_workload(args.control)
    if workload.exists() and workload.read_text() != content:
        raise RuntimeError("Existing workload differs from planned requests")
    if not workload.exists():
        workload.write_text(content)
    for source in (CONFIG, RANK_MAP, TOPOLOGY, PROFILE, MODEL):
        shutil.copy2(source, case / source.name)

    output = case / "requests.csv"
    flows = case / "flows.jsonl"
    events = case / "events.jsonl"
    log = case / "serving.log"
    env = dict(os.environ)
    env["PYTHONPATH"] = ":".join((str(ROOT),
                                  str(ROOT / "astra-sim/extern/graph_frontend")))
    env["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
    env["FLOWSIM_TELEMETRY_CLASSES"] = "KV_MOVEMENT,EP"
    env["FLOWSIM_MAX_FLOW_TELEMETRY_ROWS"] = "250000"
    env["FLOWSIM_MAX_TELEMETRY_ROWS"] = "250000"
    env["SERVING_BATCH_MISS_EVENT_LOG"] = str(events)
    cmd = [PYTHON, "-u", "-m", "serving",
           "--cluster-config", str(CONFIG.relative_to(ROOT)),
           "--dataset", str(workload.relative_to(ROOT)),
           "--num-reqs", str(count), "--network-backend", "flowsim",
           "--pd-kv-transfer-mode", "LAYERWISE",
           "--flowsim-policy", args.policy,
           "--request-routing-policy", "RR",
           "--max-num-seqs", "8", "--max-num-batched-tokens", "2048",
           "--no-enable-prefix-caching", "--no-enable-chunked-prefill",
           "--flowsim-telemetry", str(flows.relative_to(ROOT)),
           "--output", str(output.relative_to(ROOT)),
           "--run-id", "r15-p2d-ep-%s%s" % (
               "control-" if args.control else "", args.policy.lower()),
           "--log-level", "WARNING", "--log-interval", "60"]
    manifest = {
        "command": cmd,
        "environment": {key: env[key] for key in (
            "PYTHONPATH", "PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION",
            "FLOWSIM_TELEMETRY_CLASSES", "FLOWSIM_MAX_FLOW_TELEMETRY_ROWS",
            "FLOWSIM_MAX_TELEMETRY_ROWS", "SERVING_BATCH_MISS_EVENT_LOG")},
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "tracked_diff_sha256": hashlib.sha256(subprocess.check_output(
            ["git", "diff", "--binary"], cwd=ROOT)).hexdigest(),
        "input_sha256": {str(path.relative_to(ROOT)): digest(path)
                          for path in (CONFIG, RANK_MAP, TOPOLOGY, PROFILE,
                                       MODEL, workload)},
        "simulator_source_sha256": {
            str(path.relative_to(ROOT)): digest(path) for path in SOURCE_FILES},
        "runner_sha256": digest(Path(__file__)),
        "seed": "deterministic fixed arrival sequence; no RNG",
        "status": "STARTED",
    }
    (case / "manifest.json").write_text(json.dumps(
        manifest, indent=2, sort_keys=True) + "\n")
    with log.open("w") as stream:
        result = subprocess.run(cmd, cwd=ROOT, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, check=False,
                                timeout=600)
    manifest["exit_code"] = result.returncode
    manifest["status"] = "COMPLETE" if result.returncode == 0 else "FAILED"
    manifest["output_sha256"] = {path.name: digest(path)
                                 for path in (output, flows, events)
                                 if path.exists()}
    (case / "manifest.json").write_text(json.dumps(
        manifest, indent=2, sort_keys=True) + "\n")
    if result.returncode:
        raise RuntimeError("Simulation failed; inspect %s" % log)
    print("completed", args.policy, output, flush=True)


if __name__ == "__main__":
    main()
