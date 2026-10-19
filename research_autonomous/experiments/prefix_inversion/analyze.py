#!/usr/bin/env python3
"""Audit prefix-hit P2D bytes, physical cuts, and Serving causal metrics."""

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TARGET_ARRIVAL_NS = 350_000_000
BYTES_PER_TOKEN = 131_072


def load_case(case):
    parts = case.name.split("_")
    m = int(parts[0][1:])
    hit = int(parts[1][3:])
    destination = parts[2]
    rows = list(csv.DictReader((case / "requests.csv").open(newline="")))
    targets = {int(row["request id"]): row for row in rows
               if int(row["arrival"]) == TARGET_ARRIVAL_NS}
    warmups = [row for row in rows
               if int(row["arrival"]) != TARGET_ARRIVAL_NS]
    assert len(targets) == m
    assert len(warmups) == (m if hit else 0)
    assert all(int(row["end_time"]) < TARGET_ARRIVAL_NS
               for row in warmups)
    assert all(int(row["total_prefix_cache_hit_tokens"]) == hit
               for row in targets.values())
    assert all(int(row["decode_capacity_queue_wait_ns"]) == 0
               for row in targets.values())

    flows = [json.loads(line) for line in (case / "flows.jsonl").open()
             if line.startswith("{")]
    flows = [flow for flow in flows
             if flow.get("traffic_subtype") == "P2D" and
             set(flow["request_ids"]) & set(targets)]
    by_request = defaultdict(list)
    source_edge = "%d->%d" % (3 * m, 3 * m + 3)
    for flow in flows:
        assert len(flow["request_ids"]) == 1
        assert source_edge in flow["path"]
        by_request[flow["request_ids"][0]].append(flow)
    expected_bytes = (2048 - hit if destination == "resident" else
                      2048) * BYTES_PER_TOKEN
    assert len(by_request) == m
    assert all(len(by_request[request_id]) == 32
               for request_id in targets)
    assert all(sum(flow["bytes"] for flow in by_request[request_id]) ==
               expected_bytes for request_id in targets)

    events = [json.loads(line) for line in (case / "events.jsonl").open()]
    queries = {event["request_id"]: event
               for event in events if event["event"] ==
               "DEST_PREFIX_QUERY" and event["request_id"] in targets}
    assert len(queries) == m
    expected_query_status = "HIT" if destination == "resident" else "MISS"
    assert all(event["status"] == expected_query_status
               for event in queries.values())
    if destination == "resident":
        assert all(int(event["hit_tokens"]) == hit
                   for event in queries.values())
    result = {
        "sources": m,
        "hit_tokens": hit,
        "destination": destination,
        "case": case.name,
        "target_count": m,
        "warmup_count": len(warmups),
        "source_edge": source_edge,
        "source_edge_capacity_gbps": 100,
        "target_destination_nodes": sorted({
            int(row["instance id"]) // m for row in targets.values()}),
        "bytes_per_target": expected_bytes,
        "aggregate_target_bytes": sum(flow["bytes"] for flow in flows),
        "flows_per_target": 32,
        "per_request": {},
    }
    for request_id, row in sorted(targets.items()):
        request_flows = by_request[request_id]
        last_flow = max(flow["end_ns"] for flow in request_flows)
        ready = int(row["p2d_kv_ready_time_ns"])
        admit = int(row["decode_admit_time_ns"])
        token2 = int(row["second_token_visible_ns"])
        assert last_flow <= ready <= admit <= token2
        result["per_request"][str(request_id)] = {
            "prefill_hit_tokens": int(
                row["total_prefix_cache_hit_tokens"]),
            "destination_query": queries[request_id]["status"],
            "destination_instance": int(row["instance id"]),
            "first_kv_release_ms": min(
                flow["start_ns"] for flow in request_flows) / 1e6,
            "last_kv_release_ms": max(
                flow["start_ns"] for flow in request_flows) / 1e6,
            "last_kv_finish_ms": last_flow / 1e6,
            "max_per_layer_flow_fct_ms": max(
                flow["end_ns"] - flow["start_ns"]
                for flow in request_flows) / 1e6,
            "p2d_ready_elapsed_ms": (ready - TARGET_ARRIVAL_NS) / 1e6,
            "last_flow_to_ready_slack_ms": (ready - last_flow) / 1e6,
            "decode_admit_elapsed_ms": (admit - TARGET_ARRIVAL_NS) / 1e6,
            "token2_elapsed_ms": (token2 - TARGET_ARRIVAL_NS) / 1e6,
            "completion_elapsed_ms": (
                int(row["end_time"]) - TARGET_ARRIVAL_NS) / 1e6,
        }
    return result


def main():
    cases = {}
    for case in sorted(HERE.glob("p*_hit*_*")):
        if not (case / "requests.csv").exists():
            continue
        result = load_case(case)
        cases[case.name] = result
    comparisons = {}
    for m in (1, 2, 4, 8):
        miss = cases.get("p%d_hit1984_miss" % m)
        resident = cases.get("p%d_hit1984_resident" % m)
        if miss is None or resident is None:
            continue
        miss_values = [item["p2d_ready_elapsed_ms"]
                       for item in miss["per_request"].values()]
        resident_values = [item["p2d_ready_elapsed_ms"]
                           for item in resident["per_request"].values()]
        miss_mean = sum(miss_values) / len(miss_values)
        resident_mean = sum(resident_values) / len(resident_values)
        comparisons[str(m)] = {
            "miss_ready_elapsed_ms": miss_mean,
            "resident_ready_elapsed_ms": resident_mean,
            "miss_minus_resident_ms": miss_mean - resident_mean,
            "conditional_alignment_reduction_fraction": (
                (miss_mean - resident_mean) / miss_mean),
            "status": "controlled cache-state comparison, not online-policy gain",
        }
    summary = {
        "cases": cases,
        "hot_cache_alignment_comparisons": comparisons,
        "provenance": {
            "source_sha256": {
                str(path.relative_to(ROOT)): hashlib.sha256(
                    path.read_bytes()).hexdigest()
                for path in (
                    HERE / "run.py", HERE / "analyze.py",
                    ROOT / "serving/core/router.py",
                    ROOT / "serving/core/scheduler.py",
                    ROOT / "serving/core/graph_generator.py",
                    ROOT / "serving/core/flowsim_backend.py",
                    ROOT / "serving/core/flowsim_worker.py",
                    ROOT / "configs/model/meta-llama/Llama-3.1-8B.json",
                    ROOT / "profiler/perf/RTX4090/meta-llama/"
                           "Llama-3.1-8B/bf16/tp1/dense.csv",
                    ROOT / "profiler/perf/RTX4090/meta-llama/"
                           "Llama-3.1-8B/bf16/tp1/attention.csv",
                )
            },
            "case_output_sha256": {
                name: {
                    filename: hashlib.sha256(
                        (HERE / name / filename).read_bytes()).hexdigest()
                    for filename in ("requests.csv", "flows.jsonl",
                                     "events.jsonl")
                }
                for name in cases
            },
        },
        "limit": (
            "Conditioned warm cache-state experiments. Results do not "
            "establish natural D-miss incidence or an improvement over "
            "cache-aware Decode selection, local Prefill, or replica "
            "placement baselines."),
    }
    target = HERE / "summary.json"
    target.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    for name, item in sorted(cases.items()):
        vals = [row["p2d_ready_elapsed_ms"]
                for row in item["per_request"].values()]
        print(name, "ready_elapsed_ms", round(sum(vals) / len(vals), 3),
              "bytes_per_target", item["bytes_per_target"])
    print("conditional comparisons", json.dumps(comparisons, indent=2))


if __name__ == "__main__":
    main()
