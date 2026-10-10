#!/usr/bin/env python3
"""Summarize bounded FlowSim trace replays without loading all flow rows."""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


def _p99(values):
    ordered = sorted(values)
    if not ordered:
        return None
    return ordered[max(0, math.ceil(.99 * len(ordered)) - 1)]


def _read_metrics(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _summarize(path):
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    counts = defaultdict(int)
    bytes_by_class = defaultdict(int)
    fct_by_class = defaultdict(list)
    for row in _read_metrics(path / "flows.csv"):
        traffic_class = row.get("traffic_class", "UNKNOWN")
        counts[traffic_class] += 1
        bytes_by_class[traffic_class] += int(row["bytes"])
        fct_by_class[traffic_class].append(float(row["fct_ns"]))

    req = _read_metrics(path / "request_metrics.csv")
    kv_p99 = _p99(float(row["kv_completion_time_ns"]) for row in req)
    ttft_p99 = _p99(float(row["ttft_data_plane_proxy_ns"]) for row in req)
    max_util = None
    max_queue = None
    telemetry_path = path / "link_telemetry.jsonl"
    if telemetry_path.is_file():
        max_util = 0.0
        max_queue = 0
        with telemetry_path.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                max_util = max(max_util, float(row.get("utilization", 0.0)))
                max_queue = max(max_queue, int(row.get("queue_bytes", 0)))

    return {
        "run": path.name,
        "policy": manifest.get("policy"),
        "request_count": manifest.get("request_count"),
        "flow_count": manifest.get("completed_flow_count"),
        "coalesce_ep_window_us": manifest.get("coalesce_ep_window_us"),
        "kv_flow_count": counts.get("KV_MOVEMENT", 0),
        "ep_flow_count": counts.get("EP", 0),
        "kv_bytes": bytes_by_class.get("KV_MOVEMENT", 0),
        "ep_bytes": bytes_by_class.get("EP", 0),
        "kv_flow_fct_p99_ms": (_p99(fct_by_class["KV_MOVEMENT"]) / 1e6
                                if fct_by_class["KV_MOVEMENT"] else None),
        "ep_aggregate_fct_p99_ms": (_p99(fct_by_class["EP"]) / 1e6
                                     if fct_by_class["EP"] else None),
        "kv_completion_p99_ms": kv_p99 / 1e6 if kv_p99 is not None else None,
        "ttft_data_plane_proxy_p99_ms": ttft_p99 / 1e6 if ttft_p99 is not None else None,
        "telemetry_rows": manifest.get("telemetry_rows"),
        "telemetry_truncated": manifest.get("telemetry_truncated"),
        "max_sampled_link_utilization": max_util,
        "max_sampled_queue_bytes": max_queue,
        "metric_note": "EP values are aggregate-flow FCT under temporal coalescing; no per-request EP CCT is inferred",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    for path in sorted(args.root.iterdir()):
        if path.is_dir() and (path / "manifest.json").is_file():
            rows.append(_summarize(path))
    fields = list(rows[0]) if rows else []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        if fields:
            writer.writeheader()
            writer.writerows(rows)
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
