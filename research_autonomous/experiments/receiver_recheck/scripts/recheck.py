#!/usr/bin/env python3
"""Recheck the historical receiver gate after EP1 TP graph repair."""

import csv
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
CASE = Path(__file__).resolve().parents[1]
HISTORICAL = ROOT / "research_receiver_matching/run_exhaustive_gate.py"


def write_manifest():
    paths = [
        Path(__file__),
        HISTORICAL,
        ROOT / "serving/core/flowsim_worker.py",
        ROOT / "astra-sim/extern/graph_frontend/chakra/src/converter/llm_converter.py",
        ROOT / "research_cache_network_joint/3p2d_tp2_flowsim.json",
        ROOT / "research_receiver_matching/cohort_3x2048.jsonl",
        ROOT / "configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json",
        ROOT / "profiler/perf/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/bf16/tp1/moe.csv",
        ROOT / "profiler/perf/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/bf16/tp2/dense.csv",
        ROOT / "profiler/perf/RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/bf16/tp2/attention.csv",
        CASE / "processed/post_moe_fix_assignments.csv",
    ]
    base = json.loads((ROOT / "research_cache_network_joint/3p2d_tp2_flowsim.json").read_text())
    paths.extend((ROOT / base["flowsim_topology"],
                  ROOT / base["flowsim_rank_map"]))
    manifest = {
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "invocation": ("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python "
                       "PYTHONPATH=.:astra-sim/extern/graph_frontend "
                       "/home/lpm/.conda/envs/llmsim-flowsim/bin/python "
                       "research_autonomous/experiments/receiver_recheck/"
                       "scripts/recheck.py"),
        "source_and_result_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(
                path.read_bytes()).hexdigest() for path in paths
        },
        "note": "The imported historical runner saves the exact per-case "
                "command inputs in configs and immutable per-case raw files. "
                "This recheck never overwrites the historical runs.",
    }
    (CASE / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n")


def main():
    spec = importlib.util.spec_from_file_location("receiver_gate", HISTORICAL)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    gate.RUNS = CASE / "raw"
    gate.RUNS.mkdir(parents=True, exist_ok=True)
    base = json.loads(gate.BASE.read_text())
    rows = [gate.run_one(mode, format(number, "03b"), base)
            for mode in gate.MODES for number in range(8)]
    output = CASE / "processed" / "post_moe_fix_assignments.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    write_manifest()

    for mode in gate.MODES:
        subset = [row for row in rows if row["mode"] == mode]
        greedy = next(row for row in subset if row["assignment"] == "010")
        best = min(subset, key=lambda row: row["mean_token2_ms"])
        gain = ((greedy["mean_token2_ms"] - best["mean_token2_ms"]) /
                greedy["mean_token2_ms"] * 100)
        print(mode, "greedy", greedy["mean_token2_ms"],
              "best", best["assignment"], best["mean_token2_ms"],
              "gain_percent", gain)


if __name__ == "__main__":
    main()
