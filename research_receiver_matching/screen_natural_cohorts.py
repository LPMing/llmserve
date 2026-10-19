#!/usr/bin/env python3
"""Screen trace arrivals for overlapping profile-derived Prefill completions."""

import csv
import json
import os
import subprocess
from bisect import bisect_right
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
OUT = HERE / "calibration"
PYTHON = "/home/lpm/.conda/envs/llmsim-flowsim/bin/python"
CONFIG = HERE / "runs/layerwise_010.json"
TRACE = ROOT / "workloads/sharegpt-qwen3-30b-a3b-300-sps10.jsonl"
GRID = (256, 512, 768, 1024, 1536, 2048)
WINDOWS_NS = (4_036_732, 8_053_064, 16_106_127)


def calibrate(tokens):
    workload = OUT / f"input_{tokens}.jsonl"
    csv_path = OUT / f"input_{tokens}.csv"
    log_path = OUT / f"input_{tokens}.log"
    flows_path = OUT / f"input_{tokens}_flows.jsonl"
    workload.write_text(json.dumps({
        "input_toks": tokens, "output_toks": 1, "arrival_time_ns": 0
    }) + "\n")
    command = [
        PYTHON, "-m", "serving",
        "--cluster-config", str(CONFIG.relative_to(ROOT)),
        "--dataset", str(workload.relative_to(ROOT)),
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
        "--run-id", f"receiver-calibration-{tokens}",
        "--log-level", "WARNING",
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = ":".join((
        str(ROOT), str(ROOT / "astra-sim/extern/graph_frontend")))
    env["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
    env["FLOWSIM_TELEMETRY_CLASSES"] = "KV_MOVEMENT"
    with log_path.open("w") as stream:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        raise RuntimeError(f"Calibration {tokens} failed: {log_path}")
    with csv_path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 1:
        raise RuntimeError(f"Calibration {tokens}: expected one request")
    ready = int(rows[0]["p2d_kv_ready_time_ns"])
    with flows_path.open() as stream:
        flows = [json.loads(line) for line in stream if line.startswith("{")]
    last_flow = max(int(flow["end_ns"]) for flow in flows)
    if last_flow >= ready:
        raise RuntimeError(f"Calibration {tokens} is network-limited")
    return ready, last_flow


def interpolate(value, points):
    positions = [x for x, _ in points]
    index = bisect_right(positions, value)
    if index == 0:
        left, right = points[:2]
    elif index == len(points):
        left, right = points[-2:]
    else:
        left, right = points[index - 1:index + 1]
    return round(left[1] + (right[1] - left[1]) *
                 (value - left[0]) / (right[0] - left[0]))


def main():
    OUT.mkdir(exist_ok=True)
    calibration = [(tokens, *calibrate(tokens)) for tokens in GRID]
    points = [(tokens, ready) for tokens, ready, _ in calibration]
    with (HERE / "04_PROFILE_PREFILL_CALIBRATION.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("input_tokens", "single_request_p2d_ready_ns",
                         "last_p2d_flow_finish_ns", "compute_slack_ns"))
        writer.writerows((tokens, ready, last_flow, ready - last_flow)
                         for tokens, ready, last_flow in calibration)
    requests = [json.loads(line) for line in TRACE.read_text().splitlines()]
    last_finish = [0, 0, 0]
    timeline = []
    excluded = 0
    for index, request in enumerate(requests):
        tokens = int(request["input_toks"])
        if tokens > 2048:
            excluded += 1
            continue
        # This FCFS per-Prefill projection is a theory screen. It has no
        # Decode feedback and does not represent integrated Serving results.
        prefill = index % 3
        arrival = int(request["arrival_time_ns"])
        start = max(arrival, last_finish[prefill])
        finish = start + interpolate(tokens, points)
        last_finish[prefill] = finish
        timeline.append({
            "trace_index": index, "prefill_instance": prefill,
            "input_tokens": tokens, "output_tokens": int(request["output_toks"]),
            "arrival_ns": arrival, "projected_prefill_start_ns": start,
            "projected_prefill_finish_ns": finish,
        })
    timeline.sort(key=lambda row: row["projected_prefill_finish_ns"])
    with (HERE / "05_NATURAL_COHORT_SCREEN.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(timeline[0]))
        writer.writeheader()
        writer.writerows(timeline)
    print("calibration_ms", [(n, round(t / 1e6, 3)) for n, t in points])
    print("included", len(timeline), "excluded_gt_profile_limit", excluded)
    for window in WINDOWS_NS:
        triples = []
        for i, row in enumerate(timeline):
            cohort = [other for other in timeline[i + 1:]
                      if other["projected_prefill_finish_ns"] -
                         row["projected_prefill_finish_ns"] <= window]
            if len(cohort) >= 2:
                triples.append((row, *cohort[:2]))
        print("window_ms", window / 1e6, "three_or_more_cohorts", len(triples),
              "first_trace_ids", [r["trace_index"] for r in triples[0]]
              if triples else [])


if __name__ == "__main__":
    main()
