#!/usr/bin/env python3
"""Reproducible P4 request-barrier statistics from native ns-3 comm_events.csv."""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


def percentile(values, q):
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] + weight * (ordered[upper] - ordered[lower])


def parse_int(row, key, default=0):
    value = row.get(key, "")
    if value in ("", "-1", None):
        return default
    return int(value)


def load_remote_events(comm_path):
    events = []
    with comm_path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row.get("phase") != "END":
                continue
            if row.get("event_type") != "1":
                continue
            if row.get("serving_role") != "remote_kv":
                continue
            request_id = parse_int(row, "request_id", -1)
            if request_id < 0:
                continue
            start_ns = parse_int(row, "network_start_ns")
            end_ns = parse_int(row, "network_end_ns")
            if end_ns < start_ns:
                raise ValueError(f"negative duration in {comm_path}: {row}")
            events.append({
                "request_id": request_id,
                "event_id": parse_int(row, "event_id", -1),
                "src": parse_int(row, "src"),
                "dst": parse_int(row, "dst"),
                "port": parse_int(row, "port"),
                "bytes": parse_int(row, "bytes"),
                "network_start_ns": start_ns,
                "network_end_ns": end_ns,
                "duration_ns": end_ns - start_ns,
                "path": row.get("path", ""),
                "directed_link_ids": row.get("directed_link_ids", ""),
            })
    return events


def aggregate(events):
    grouped = defaultdict(list)
    for event in events:
        grouped[event["request_id"]].append(event)
    requests = []
    for request_id, flows in sorted(grouped.items()):
        critical = max(flows, key=lambda row: (row["network_end_ns"], row["event_id"]))
        first_start = min(row["network_start_ns"] for row in flows)
        requests.append({
            "request_id": request_id,
            "flow_count": len(flows),
            "first_network_start_ns": first_start,
            "last_network_end_ns": critical["network_end_ns"],
            "barrier_ns": critical["network_end_ns"] - first_start,
            "last_flow_fct_ns": critical["duration_ns"],
            "critical_event_id": critical["event_id"],
            "critical_src": critical["src"],
            "critical_dst": critical["dst"],
            "critical_port": critical["port"],
            "critical_bytes": critical["bytes"],
            "critical_path": critical["path"],
            "critical_directed_link_ids": critical["directed_link_ids"],
        })
    return requests


def stats(values):
    return {
        "count": len(values),
        "mean_ns": sum(values) / len(values) if values else None,
        "p50_ns": percentile(values, 0.50),
        "p95_ns": percentile(values, 0.95),
        "p99_ns": percentile(values, 0.99),
        "max_ns": max(values) if values else None,
        "percentile_method": "linear_interpolation_sorted_(n-1)*q",
        "small_sample_warning": len(values) < 20,
    }


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def analyze_run(label, run_dir, output_dir):
    comm_path = run_dir / "comm_events.csv"
    if not comm_path.is_file():
        raise FileNotFoundError(comm_path)
    events = load_remote_events(comm_path)
    requests = aggregate(events)
    output_dir.mkdir(parents=True, exist_ok=True)
    request_rows = []
    for row in requests:
        request_rows.append({
            "run": label,
            "request_id": row["request_id"],
            "flow_count": row["flow_count"],
            "first_network_start_ns": row["first_network_start_ns"],
            "last_network_end_ns": row["last_network_end_ns"],
            "barrier_ns": row["barrier_ns"],
            "barrier_ms": row["barrier_ns"] / 1e6,
            "last_flow_fct_ns": row["last_flow_fct_ns"],
            "critical_event_id": row["critical_event_id"],
            "critical_src": row["critical_src"],
            "critical_dst": row["critical_dst"],
            "critical_port": row["critical_port"],
            "critical_bytes": row["critical_bytes"],
            "critical_path": row["critical_path"],
            "critical_directed_link_ids": row["critical_directed_link_ids"],
        })
    flow_rows = [{**event, "run": label, "duration_ms": event["duration_ns"] / 1e6}
                 for event in events]
    write_csv(
        output_dir / f"{label}_request_barrier_samples.csv",
        request_rows,
        list(request_rows[0]) if request_rows else [
            "run", "request_id", "flow_count", "first_network_start_ns",
            "last_network_end_ns", "barrier_ns", "barrier_ms",
            "last_flow_fct_ns", "critical_event_id", "critical_src",
            "critical_dst", "critical_port", "critical_bytes",
            "critical_path", "critical_directed_link_ids"])
    write_csv(
        output_dir / f"{label}_remote_flow_samples.csv",
        flow_rows,
        list(flow_rows[0]) if flow_rows else [
            "request_id", "event_id", "src", "dst", "port", "bytes",
            "network_start_ns", "network_end_ns", "duration_ns", "path",
            "directed_link_ids", "run", "duration_ms"])
    barrier_values = [row["barrier_ns"] for row in requests]
    fct_values = [row["last_flow_fct_ns"] for row in requests]

    def to_ms(stat):
        return {
            key.replace("_ns", "_ms") if key.endswith("_ns") else key:
                value / 1e6 if key.endswith("_ns") and value is not None else value
            for key, value in stat.items()
        }

    result = {
        "run": label,
        "run_dir": str(run_dir),
        "remote_flow_count": len(events),
        "remote_request_count": len(requests),
        "request_barrier_ms": to_ms(stats(barrier_values)),
        "last_flow_fct_ms": to_ms(stats(fct_values)),
        "request_barrier_samples_ms": [value / 1e6 for value in barrier_values],
    }
    (output_dir / f"{label}_metrics.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="append", required=True,
                        help="label=/path/to/native-run directory")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    results = []
    for item in args.run:
        if "=" not in item:
            raise SystemExit("--run must use label=directory")
        label, raw_path = item.split("=", 1)
        results.append(analyze_run(label, Path(raw_path), args.output_dir))
    (args.output_dir / "summary.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8")
    fieldnames = [
        "run", "remote_flow_count", "remote_request_count",
        "barrier_mean_ms", "barrier_p50_ms", "barrier_p95_ms",
        "barrier_p99_ms", "barrier_max_ms", "barrier_small_sample_warning",
        "fct_mean_ms", "fct_p50_ms", "fct_p95_ms", "fct_p99_ms",
        "fct_max_ms", "fct_small_sample_warning",
    ]
    rows = []
    for result in results:
        barrier = result["request_barrier_ms"]
        fct = result["last_flow_fct_ms"]
        rows.append({
            "run": result["run"],
            "remote_flow_count": result["remote_flow_count"],
            "remote_request_count": result["remote_request_count"],
            "barrier_mean_ms": barrier["mean_ms"],
            "barrier_p50_ms": barrier["p50_ms"],
            "barrier_p95_ms": barrier["p95_ms"],
            "barrier_p99_ms": barrier["p99_ms"],
            "barrier_max_ms": barrier["max_ms"],
            "barrier_small_sample_warning": barrier["small_sample_warning"],
            "fct_mean_ms": fct["mean_ms"],
            "fct_p50_ms": fct["p50_ms"],
            "fct_p95_ms": fct["p95_ms"],
            "fct_p99_ms": fct["p99_ms"],
            "fct_max_ms": fct["max_ms"],
            "fct_small_sample_warning": fct["small_sample_warning"],
        })
    write_csv(args.output_dir / "summary.csv", rows, fieldnames)


if __name__ == "__main__":
    main()
