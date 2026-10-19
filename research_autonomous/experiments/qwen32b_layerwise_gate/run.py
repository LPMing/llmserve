#!/usr/bin/env python3
"""Check the Qwen3-32B layerwise P/D exposure theory on a small cohort."""

import csv
import hashlib
import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
BASE = ROOT / "research_prefix_exposure/4p1d_tp2_flowsim.json"
PYTHON = "/home/lpm/.conda/envs/llmsim-flowsim/bin/python"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    HERE.mkdir(parents=True, exist_ok=True)
    config = json.loads(BASE.read_text())
    for node in config["nodes"]:
        instance = node["instances"][0]
        instance["model_name"] = "Qwen/Qwen3-32B"
        instance["ep_size"] = 1
        instance["pp_size"] = 1
    config_path = HERE / "cluster.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    profile = ROOT / "profiler/perf/RTXPRO6000/Qwen/Qwen3-32B/bf16"
    sources = [
        ROOT / "configs/model/Qwen/Qwen3-32B.json",
        profile / "meta.yaml",
        profile / "tp2/dense.csv",
        profile / "tp2/attention.csv",
        profile / "tp2/per_sequence.csv",
        ROOT / "research_prefix_exposure/logical_to_physical.json",
        ROOT / "research_ns3_incast/fixtures_rankcap200g/fixtures/4p1d_unique_spines/topology.txt",
        ROOT / "serving/core/scheduler.py",
        ROOT / "serving/core/trace_generator.py",
        ROOT / "serving/core/flowsim_worker.py",
        ROOT / "astra-sim/extern/graph_frontend/chakra/src/converter/llm_converter.py",
        Path(__file__).resolve(),
        config_path,
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = ":".join((
        str(ROOT), str(ROOT / "astra-sim/extern/graph_frontend")))
    env["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
    env["FLOWSIM_TELEMETRY_CLASSES"] = "KV_MOVEMENT"
    env["FLOWSIM_MAX_FLOW_TELEMETRY_ROWS"] = "4096"
    manifest = {
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "tracked_diff_sha256": hashlib.sha256(subprocess.check_output(
            ["git", "diff", "--binary"], cwd=ROOT)).hexdigest(),
        "sources": {str(p.relative_to(ROOT)): digest(p) for p in sources},
        "scenarios": {},
        "seed": "none; RR and FAIR deterministic",
    }
    for n in (1, 4):
        case = HERE / ("p%d" % n)
        case.mkdir(exist_ok=True)
        workload = case / "workload.jsonl"
        workload.write_text("".join(json.dumps({
            "input_toks": 2048, "output_toks": 3,
            "arrival_time_ns": 0}) + "\n" for _ in range(n)))
        output = case / "requests.csv"
        log = case / "serving.log"
        events = case / "events.jsonl"
        flows = case / "flows.jsonl"
        for generated in (output, log, events, flows,
                          case / "link_telemetry.jsonl",
                          case / "collective_telemetry.jsonl",
                          case / "kv_event_telemetry.jsonl",
                          case / "PROGRESSIVE_PUSH_EVENTS.csv",
                          case / "PROGRESSIVE_PUSH_REQUESTS.csv"):
            generated.unlink(missing_ok=True)
        cmd = [PYTHON, "-m", "serving",
               "--cluster-config", str(config_path.relative_to(ROOT)),
               "--dataset", str(workload.relative_to(ROOT)),
               "--network-backend", "flowsim",
               "--pd-kv-transfer-mode", "LAYERWISE",
               "--flowsim-policy", "FAIR",
               "--request-routing-policy", "RR",
               "--dtype", "bfloat16",
               "--max-num-seqs", "8",
               "--max-num-batched-tokens", "2048",
               "--no-enable-prefix-caching",
               "--flowsim-telemetry", str(flows.relative_to(ROOT)),
               "--output", str(output.relative_to(ROOT)),
               "--run-id", "qwen32b-p%d-layerwise" % n,
               "--log-level", "WARNING"]
        env["SERVING_BATCH_MISS_EVENT_LOG"] = str(events)
        manifest["scenarios"][str(n)] = {
            "command": cmd, "workload_sha256": digest(workload),
            "events": str(events.relative_to(ROOT)),
        }
        with log.open("w") as stream:
            result = subprocess.run(cmd, cwd=ROOT, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, check=False)
        if result.returncode:
            raise RuntimeError("case %d exited %d: %s" %
                               (n, result.returncode, log))
        with output.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        if len(rows) != n:
            raise AssertionError("case %d returned %d requests" % (n, len(rows)))
        print("case", n, "ready_ms", [round(int(row[
            "p2d_kv_ready_time_ns"]) / 1e6, 6) for row in rows],
              "token2_ms", [round(int(row[
                  "second_token_visible_ns"]) / 1e6, 6) for row in rows])
    (HERE / "manifest.json").write_text(json.dumps(
        manifest, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
