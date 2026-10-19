#!/usr/bin/env python3
"""Replay a prior under-capacity case with receiver KV credit enabled."""

import hashlib
import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
PRIOR = ROOT / "research_autonomous/experiments/prefix_inversion/p2_hit1984_miss"
CASE = HERE / "under_capacity_credit"
PYTHON = "/home/lpm/.conda/envs/llmsim-flowsim/bin/python"
SOURCE = (
    ROOT / "serving/__main__.py", ROOT / "serving/core/scheduler.py",
    ROOT / "serving/core/kv_cache_manager.py",
    ROOT / "serving/core/router.py",
    ROOT / "serving/core/trace_generator.py",
    ROOT / "serving/core/flowsim_backend.py",
    ROOT / "serving/core/flowsim_worker.py",
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if CASE.exists():
        raise FileExistsError("Refusing to overwrite %s" % CASE)
    CASE.mkdir(parents=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = ":".join((
        str(ROOT), str(ROOT / "astra-sim/extern/graph_frontend")))
    env["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
    env["FLOWSIM_TELEMETRY_CLASSES"] = "KV_MOVEMENT"
    env["SERVING_BATCH_MISS_EVENT_LOG"] = str(CASE / "events.jsonl")
    cmd = [PYTHON, "-m", "serving", "--cluster-config",
           str((PRIOR / "cluster.json").relative_to(ROOT)), "--dataset",
           str((PRIOR / "workload.jsonl").relative_to(ROOT)),
           "--network-backend", "flowsim",
           "--pd-kv-transfer-mode", "LAYERWISE",
           "--flowsim-policy", "FAIR", "--request-routing-policy", "RR",
           "--dtype", "bfloat16", "--max-num-seqs", "8",
           "--max-num-batched-tokens", "2048",
           "--enable-prefix-caching", "--destination-prefix-handoff", "DELTA",
           "--pd-handoff-capacity-reservation",
           "--flowsim-telemetry", str((CASE / "flows.jsonl").relative_to(ROOT)),
           "--output", str((CASE / "requests.csv").relative_to(ROOT)),
           "--run-id", "r16-credit-under-capacity", "--log-level", "WARNING"]
    manifest = {
        "command": cmd, "seed": "prior deterministic workload",
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "input_sha256": {str(path.relative_to(ROOT)): digest(path)
                          for path in (PRIOR / "cluster.json",
                                       PRIOR / "workload.jsonl",
                                       PRIOR / "rank_map.json",
                                       PRIOR / "topology.txt")},
        "source_sha256": {str(path.relative_to(ROOT)): digest(path)
                          for path in SOURCE},
        "prior_requests_sha256": digest(PRIOR / "requests.csv"),
        "status": "STARTED",
    }
    (CASE / "manifest.json").write_text(json.dumps(
        manifest, indent=2, sort_keys=True) + "\n")
    with (CASE / "serving.log").open("w") as stream:
        result = subprocess.run(cmd, cwd=ROOT, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, check=False,
                                timeout=300)
    manifest["exit_code"] = result.returncode
    manifest["status"] = "COMPLETE" if result.returncode == 0 else "FAILED"
    manifest["output_sha256"] = {path.name: digest(path)
                                 for path in (CASE / "requests.csv",
                                              CASE / "flows.jsonl",
                                              CASE / "events.jsonl")
                                 if path.exists()}
    (CASE / "manifest.json").write_text(json.dumps(
        manifest, indent=2, sort_keys=True) + "\n")
    if result.returncode:
        raise RuntimeError("Credit control failed; see serving.log")
    print("credit control complete")


if __name__ == "__main__":
    main()
