#!/usr/bin/env python3
"""Summarize offline CRITICAL_ONLY matched FlowSim replays.

The script deliberately reports request KV barriers and collective EP CCTs
separately.  It never treats the replay TTFT proxy as integrated TTFT.
"""
import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * fraction
    low = int(math.floor(position))
    high = int(math.ceil(position))
    return values[low] + (position - low) * (values[high] - values[low])


def stats(values):
    return {
        "count": len(values),
        "mean_ns": sum(values) / len(values) if values else None,
        "p50_ns": percentile(values, 0.50),
        "p95_ns": percentile(values, 0.95),
        "p99_ns": percentile(values, 0.99),
        "max_ns": max(values) if values else None,
    }


def summarize(path):
    with (path / "flows.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    kv_by_request = defaultdict(list)
    for row in rows:
        if row.get("traffic_class") == "KV_MOVEMENT":
            kv_by_request[row.get("request_id", "")].append(row)
    kv_barriers = [
        max(int(row["end_ns"]) for row in request_rows)
        - min(int(row["requested_start_ns"]) for row in request_rows)
        for request_rows in kv_by_request.values()
        if request_rows
    ]
    with (path / "collectives.csv").open(newline="", encoding="utf-8") as stream:
        ccts = [int(row["cct_ns"]) for row in csv.DictReader(stream)]
    return {
        "path": str(path),
        "flow_count": len(rows),
        "request_count_with_kv": len(kv_barriers),
        "kv_handoff_ns": stats(kv_barriers),
        "ep_cct_ns": stats(ccts),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", nargs=2, metavar=("LABEL", "DIR"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {label: summarize(Path(directory)) for label, directory in args.case}
    reference = result.get("EP_FIRST")
    if reference:
        for value in result.values():
            for metric, key in (("ep_cct_ns", "p99_ns"), ("kv_handoff_ns", "p99_ns"), ("kv_handoff_ns", "mean_ns")):
                current = value[metric][key]
                baseline = reference[metric][key]
                value.setdefault("delta_vs_ep_first_pct", {})[metric + "." + key] = (
                    (current / baseline - 1.0) * 100.0 if current is not None and baseline else None
                )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
