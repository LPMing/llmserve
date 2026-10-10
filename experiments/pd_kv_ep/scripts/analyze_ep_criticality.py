#!/usr/bin/env python3
"""Analyze EP round criticality and emit offline oracle flow sets.

The input is the optional ``ep_flow_telemetry.jsonl`` emitted by FlowSim.
This script never treats a batch collective as per-request traffic: request
IDs are retained as a cohort annotation, and the oracle is built from exact
flow IDs and round completion order.
"""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


def _read_jsonl(path):
    rows = []
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip() and not line.startswith("#"):
                rows.append(json.loads(line))
    return rows


def _read_csv(path):
    if not path or not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _percentile(values, fraction):
    values = sorted(float(value) for value in values)
    if not values:
        return None
    index = min(len(values) - 1,
                max(0, int(math.ceil(fraction * len(values))) - 1))
    return values[index]


def _summary(values):
    values = [float(value) for value in values]
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "mean": sum(values) / len(values),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "max": max(values),
    }


def _write_csv(path, rows):
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields,
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _round_rows(flow_rows):
    groups = defaultdict(list)
    for row in flow_rows:
        groups[str(row.get("round_id"))].append(row)
    return groups


def _critical_set(rows, fraction=None):
    ordered = sorted(rows, key=lambda row: (
        int(row.get("end_ns", 0)), str(row.get("flow_id"))))
    if fraction is None:
        end_ns = max(int(row.get("end_ns", 0)) for row in ordered)
        return {row.get("flow_id") for row in ordered
                if int(row.get("end_ns", 0)) == end_ns}
    count = max(1, int(math.ceil(len(ordered) * fraction)))
    return {row.get("flow_id") for row in ordered[-count:]}


def _union_duration(rows):
    intervals = sorted((int(row.get("start_ns", 0) or 0),
                        int(row.get("end_ns", 0) or 0))
                       for row in rows)
    total = 0
    current_start = current_end = None
    for start, end in intervals:
        if current_start is None:
            current_start, current_end = start, end
        elif start > current_end:
            total += max(0, current_end - current_start)
            current_start, current_end = start, end
        else:
            current_end = max(current_end, end)
    if current_start is not None:
        total += max(0, current_end - current_start)
    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--requests", type=Path, default=None,
                        help="integrated request CSV for token-level attribution")
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    output = (args.output_dir or run_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)

    raw_flows = _read_jsonl(run_dir / "ep_flow_telemetry.jsonl")
    # A graph fixed-point replay can expose one exact flow twice before the
    # executor retires its compact completion state.  Keep the latest record
    # for a (round_id, flow_id) pair; counting the duplicate would fabricate
    # EP bytes and distort the critical-flow oracle.
    deduped = {}
    for row in raw_flows:
        key = (str(row.get("round_id")), str(row.get("flow_id")))
        previous = deduped.get(key)
        if previous is None or int(row.get("end_ns", 0)) >= int(
                previous.get("end_ns", 0)):
            deduped[key] = row
    flows = list(deduped.values())
    rounds = _round_rows(flows)
    round_rows = []
    critical_ids = set()
    oracle_ids = {"all_ep": set(), "critical": set(), "top_1pct": set(),
                  "top_5pct": set(), "top_10pct": set()}
    for round_id, items in sorted(rounds.items()):
        ordered = sorted(items, key=lambda row: (
            int(row.get("end_ns", 0)), str(row.get("flow_id"))))
        total_bytes = sum(int(row.get("bytes", 0)) for row in ordered)
        sizes = [int(row.get("bytes", 0)) for row in ordered]
        last_end = max(int(row.get("end_ns", 0)) for row in ordered)
        critical = [row for row in ordered
                    if int(row.get("end_ns", 0)) == last_end]
        critical_bytes = sum(int(row.get("bytes", 0)) for row in critical)
        critical_ids.update(row.get("flow_id") for row in critical)
        oracle_ids["all_ep"].update(row.get("flow_id") for row in ordered)
        oracle_ids["critical"].update(row.get("flow_id") for row in critical)
        for name, fraction in (("top_1pct", 0.01),
                               ("top_5pct", 0.05), ("top_10pct", 0.10)):
            oracle_ids[name].update(_critical_set(ordered, fraction))
        total_bytes = sum(int(row.get("bytes", 0)) for row in ordered)
        def _slowest_fraction(fraction):
            selected = _critical_set(ordered, fraction)
            return (sum(int(row.get("bytes", 0)) for row in ordered
                        if row.get("flow_id") in selected) /
                    float(total_bytes) if total_bytes else 0.0)
        first = ordered[0]
        round_rows.append({
            "round_id": round_id,
            "collective_id": first.get("collective_id"),
            "layer_id": first.get("layer_id"),
            "event_type": first.get("event_type"),
            "batch_id": first.get("batch_id"),
            "request_ids": json.dumps(first.get("request_ids", []),
                                       separators=(",", ":")),
            "start_ns": first.get("collective_start_ns"),
            "end_ns": last_end,
            "cct_ns": first.get("collective_cct_ns"),
            "flow_count": len(ordered),
            "total_bytes": total_bytes,
            "max_flow_bytes": max(sizes),
            "flow_size_p95": _percentile(sizes, 0.95),
            "flow_size_skew_max_over_p50": (
                max(sizes) / float(_percentile(sizes, 0.50))
                if _percentile(sizes, 0.50) else None),
            "critical_flow_count": len(critical),
            "critical_flow_bytes": critical_bytes,
            "critical_flow_byte_fraction": (
                critical_bytes / float(total_bytes) if total_bytes else 0.0),
            "critical_path": json.dumps(sorted({
                path for row in critical for path in row.get("path", [])
            })),
            "critical_flow_ids": json.dumps(
                [row.get("flow_id") for row in critical],
                separators=(",", ":")),
            "slowest_1pct_byte_fraction": _slowest_fraction(0.01),
            "slowest_5pct_byte_fraction": _slowest_fraction(0.05),
            "slowest_10pct_byte_fraction": _slowest_fraction(0.10),
        })

    _write_csv(output / "ep_round_criticality.csv", round_rows)
    _write_csv(output / "ep_flow_criticality.csv", flows)

    # For single-request EP rounds, scheduler batch_id is the available
    # frontend token-step anchor.  It is not invented as a token ID: rows that
    # belong to a multi-request cohort are excluded from this exact mapping.
    request_rows = _read_csv(args.requests.resolve() if args.requests else None)
    request_by_id = {
        str(row.get("request id", row.get("request_id", ""))): row
        for row in request_rows
    }
    by_request_batch = defaultdict(list)
    for row in round_rows:
        request_ids = json.loads(row.get("request_ids", "[]"))
        if len(request_ids) == 1:
            by_request_batch[(str(request_ids[0]),
                              str(row.get("batch_id")))].append(row)
    token_rows = []
    for request_id, request in request_by_id.items():
        try:
            tbt_values = json.loads(request.get("TBT", "[]"))
        except (TypeError, json.JSONDecodeError):
            tbt_values = []
        batches = sorted(
            ((batch, rows) for (rid, batch), rows in by_request_batch.items()
             if rid == request_id),
            key=lambda item: (int(item[0]) if str(item[0]).isdigit()
                              else str(item[0])))
        for index, tbt_ns in enumerate(tbt_values):
            batch_id = batches[index][0] if index < len(batches) else ""
            token_rounds = batches[index][1] if index < len(batches) else []
            critical_ep_ns = _union_duration(token_rounds)
            token_rows.append({
                "request_id": request_id,
                "token_index": index,
                "scheduler_batch_id": batch_id,
                "tbt_ns": int(float(tbt_ns)),
                "ep_round_count": len(token_rounds),
                "critical_ep_time_ns": critical_ep_ns,
                "critical_ep_fraction": (
                    critical_ep_ns / float(tbt_ns)
                    if float(tbt_ns) else None),
                "attribution": ("single_request_rounds" if token_rounds
                                else "no_exact_round_mapping"),
            })
    _write_csv(output / "ep_token_attribution.csv", token_rows)
    for name, ids in oracle_ids.items():
        (output / ("critical_flow_oracle_%s.txt" % name)).write_text(
            "# Offline EP critical-flow oracle; one exact flow_id per line\n" +
            "\n".join(sorted(ids)) + "\n", encoding="utf-8")

    critical_fractions = [float(row["critical_flow_byte_fraction"])
                          for row in round_rows]
    top_path_counts = defaultdict(int)
    for row in flows:
        if row.get("is_last_completing"):
            for path in row.get("path", []):
                top_path_counts[path] += 1
    summary = {
        "run_dir": str(run_dir),
        "flow_count": len(flows),
        "round_count": len(round_rows),
        "round_cct_ns": _summary(
            float(row["cct_ns"]) for row in round_rows),
        "flow_size_bytes": _summary(
            int(row.get("bytes", 0)) for row in flows),
        "critical_flow_byte_fraction": _summary(critical_fractions),
        "slowest_1pct_byte_fraction": _summary(
            row["slowest_1pct_byte_fraction"] for row in round_rows),
        "slowest_5pct_byte_fraction": _summary(
            row["slowest_5pct_byte_fraction"] for row in round_rows),
        "slowest_10pct_byte_fraction": _summary(
            row["slowest_10pct_byte_fraction"] for row in round_rows),
        "critical_path_frequency": dict(sorted(
            top_path_counts.items(), key=lambda item: (-item[1], item[0]))),
        "oracle_flow_counts": {name: len(ids)
                               for name, ids in oracle_ids.items()},
        "token_attribution": {
            "row_count": len(token_rows),
            "exact_row_count": sum(
                row["attribution"] == "single_request_rounds"
                for row in token_rows),
            "critical_ep_fraction_exact_only": _summary(
                row["critical_ep_fraction"] for row in token_rows
                if row["attribution"] == "single_request_rounds"
                and row["critical_ep_fraction"] is not None),
            "critical_ep_fraction_all_rows": _summary(
                row["critical_ep_fraction"] for row in token_rows
                if row["critical_ep_fraction"] is not None),
            "note": "critical EP time is the union of EP-round intervals within a scheduler batch; exact only for single-request rounds",
        },
        "oracle_semantics": {
            "all_ep": "all EP flows, equivalent to EP_FIRST",
            "critical": "all flows tied at the last completion timestamp",
            "top_1pct": "slowest 1% of flows in each round",
            "top_10pct": "slowest 10% of flows in each round",
        },
    }
    (output / "ep_criticality_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
