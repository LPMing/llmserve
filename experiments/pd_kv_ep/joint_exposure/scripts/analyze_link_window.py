#!/usr/bin/env python3
"""Summarize bounded integrated FlowSim link telemetry for one time window.

``queue_bytes`` is FlowSim residual fluid outstanding on paths using a link;
it is not a packet queue or switch-buffer occupancy.
"""

import argparse
import csv
import json
import math
import pathlib
import sys


def percentile(values, q):
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return ""
    index = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return ordered[index]


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields,
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--telemetry", type=pathlib.Path, required=True)
    parser.add_argument("--topology", type=pathlib.Path, required=True)
    parser.add_argument("--start-ns", type=int, required=True)
    parser.add_argument("--end-ns", type=int, required=True)
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    args = parser.parse_args()
    if args.end_ns <= args.start_ns:
        parser.error("--end-ns must be greater than --start-ns")

    repo = pathlib.Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(repo / "serving" / "core"))
    from flowsim_backend import FluidFlowNetwork

    network = FluidFlowNetwork(str(args.topology), policy="FAIR")
    rows = []
    metadata = []
    with args.telemetry.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            if line.lstrip().startswith("{"):
                record = json.loads(line)
                if record.get("record_type") == "metadata":
                    metadata.append(record)
                    continue
                if record.get("record_type") != "link_timeseries":
                    continue
                left = max(args.start_ns, int(record["interval_start_ns"]))
                right = min(args.end_ns, int(record["timestamp_ns"]))
                if right <= left:
                    continue
                record["window_start_ns"] = left
                record["window_end_ns"] = right
                record["window_duration_ns"] = right - left
                record["window_utilization"] = record.get("utilization", 0.0)
                record["window_kv_gbps"] = (
                    float(record.get("kv_allocated_rate_Bps", 0.0)) * 8 / 1e9)
                record["window_ep_gbps"] = (
                    float(record.get("ep_allocated_rate_Bps", 0.0)) * 8 / 1e9)
                record["fluid_outstanding_bytes"] = int(
                    record.get("fluid_outstanding_bytes",
                               record.get("queue_bytes", 0)))
                rows.append(record)

    by_link = {}
    for row in rows:
        by_link.setdefault(row["link_id"], []).append(row)
    summary = []
    total_window_ns = args.end_ns - args.start_ns
    for link_id, records in sorted(by_link.items()):
        src_text, dst_text = link_id.split("->", 1)
        src = int(src_text)
        dst = int(dst_text.split("#", 1)[0])
        edge = network.edges.get((src, dst))
        capacity_gbps = (float(edge["capacity_Bps"]) * 8 / 1e9
                         if edge else "")
        covered_ns = sum(int(row["window_duration_ns"]) for row in records)
        mixed_ns = sum(
            int(row["window_duration_ns"])
            for row in records
            if int(row.get("active_kv_flows", 0)) > 0 and
            int(row.get("active_ep_flows", 0)) > 0)
        utilization = [float(row.get("window_utilization", 0.0))
                       for row in records]
        fluid_bytes = [int(row["fluid_outstanding_bytes"]) for row in records]
        kv_gbps = [float(row["window_kv_gbps"]) for row in records]
        ep_gbps = [float(row["window_ep_gbps"]) for row in records]
        summary.append({
            "link_id": link_id,
            "capacity_gbps_aggregate": capacity_gbps,
            "window_ns": total_window_ns,
            "recorded_active_interval_ns": covered_ns,
            "active_time_fraction_of_window": covered_ns / total_window_ns,
            "kv_ep_mixed_interval_ns": mixed_ns,
            "kv_ep_mixed_time_fraction_of_window": mixed_ns / total_window_ns,
            "interval_rows": len(records),
            "max_active_kv_flows": max(
                int(row.get("active_kv_flows", 0)) for row in records),
            "max_active_ep_flows": max(
                int(row.get("active_ep_flows", 0)) for row in records),
            "mean_utilization_while_recorded": sum(utilization) / len(utilization),
            "p95_utilization_while_recorded": percentile(utilization, .95),
            "max_utilization": max(utilization),
            "mean_kv_allocated_gbps_while_recorded": sum(kv_gbps) / len(kv_gbps),
            "max_kv_allocated_gbps": max(kv_gbps),
            "mean_ep_allocated_gbps_while_recorded": sum(ep_gbps) / len(ep_gbps),
            "max_ep_allocated_gbps": max(ep_gbps),
            "fluid_outstanding_p50_bytes": percentile(fluid_bytes, .50),
            "fluid_outstanding_p95_bytes": percentile(fluid_bytes, .95),
            "fluid_outstanding_max_bytes": max(fluid_bytes),
            "released_kv_bytes": sum(int(row.get("released_kv_bytes", 0))
                                      for row in records),
            "released_ep_bytes": sum(int(row.get("released_ep_bytes", 0))
                                      for row in records),
            "queue_semantics": "analytical_fluid_outstanding_not_packet_queue",
        })

    fields = list(summary[0]) if summary else [
        "link_id", "capacity_gbps_aggregate", "window_ns",
        "recorded_active_interval_ns", "active_time_fraction_of_window",
        "kv_ep_mixed_interval_ns", "kv_ep_mixed_time_fraction_of_window",
        "interval_rows", "queue_semantics",
    ]
    outdir = args.output_dir
    write_csv(outdir / "LINK_WINDOW_SUMMARY.csv", fields, summary)
    timeseries_fields = [
        "link_id", "window_start_ns", "window_end_ns", "window_duration_ns",
        "active_kv_flows", "active_ep_flows", "active_flows",
        "window_kv_gbps", "window_ep_gbps", "window_utilization",
        "fluid_outstanding_bytes", "released_kv_bytes", "released_ep_bytes",
    ]
    write_csv(outdir / "LINK_WINDOW_TIMESERIES.csv", timeseries_fields, rows)
    result = {
        "window_start_ns": args.start_ns,
        "window_end_ns": args.end_ns,
        "requested_link_count": len({row["link_id"] for row in rows}),
        "link_interval_rows": len(rows),
        "telemetry_truncated": any(
            bool(item.get("telemetry_truncated")) for item in metadata),
        "truncation_metadata": metadata,
        "queue_semantics": "analytical_fluid_outstanding_not_packet_queue",
        "topology_routing_model": network.topology_audit["routing_model"],
        "summary_csv": str(outdir / "LINK_WINDOW_SUMMARY.csv"),
        "timeseries_csv": str(outdir / "LINK_WINDOW_TIMESERIES.csv"),
    }
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "link_window_summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
