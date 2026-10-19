#!/usr/bin/env python3
"""Print compact summaries for the native-ns-3 incast replay runs."""

import csv
import argparse
import json
import sys
import statistics
from collections import defaultdict
from pathlib import Path


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def percentile(values, pct):
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * pct / 100
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (index - lower)


def summarize(run_dir):
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "network_run_manifest.json").read_text())
    events = read_csv(run_dir / "comm_events.csv")
    links = {int(row["link_id"]): row for row in read_csv(run_dir / "link_summary.csv")}
    starts = [row for row in events if row["phase"] == "START"]
    ends = [row for row in events if row["phase"] == "END"]

    per_request = defaultdict(list)
    request_issues = defaultdict(list)
    request_finishes = defaultdict(list)
    per_request_rows = defaultdict(list)
    for row in ends:
        request_id = row["request_id"]
        per_request[request_id].append(int(row["duration_ns"]))
        request_issues[request_id].append(int(row["issue_time_ns"]))
        request_finishes[request_id].append(int(row["network_end_ns"]))
        per_request_rows[request_id].append(row)

    request_barriers = {}
    for request_id, finish_times in request_finishes.items():
        first_issue = min(request_issues[request_id])
        last_finish = max(finish_times)
        critical_row = max(per_request_rows[request_id],
                           key=lambda row: int(row["network_end_ns"]))
        last_release = max(request_issues[request_id])
        request_barriers[request_id] = {
            "first_release_ms": round(first_issue / 1e6, 6),
            "last_release_ms": round(last_release / 1e6, 6),
            "p2d_ready_absolute_ms": round(last_finish / 1e6, 6),
            "p2d_ready_elapsed_ms": round((last_finish - first_issue) / 1e6, 6),
            "last_release_to_ready_ms": round((last_finish - last_release) / 1e6, 6),
            "last_completing_event_id": int(critical_row["event_id"]),
            "last_completing_layer_id": int(critical_row["layer_id"]),
            "last_completing_shard_release_ms": round(
                int(critical_row["issue_time_ns"]) / 1e6, 6),
            "last_completing_shard_finish_ms": round(
                int(critical_row["network_end_ns"]) / 1e6, 6),
        }

    path_link_ids = []
    for row in starts:
        for link_id in row["directed_link_ids"].split(";"):
            value = int(link_id)
            if value not in path_link_ids:
                path_link_ids.append(value)

    mark_path = run_dir / "local_ecn_marks.csv"
    mark_groups = defaultdict(lambda: {
        "count": 0, "first_ns": None, "last_ns": None, "max_queue_after_dequeue": 0,
        "kmin_bytes": None, "kmax_bytes": None,
    })
    if mark_path.exists():
        with mark_path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                key = (int(row["switch_id"]), int(row["link_id"]), int(row["egress_port"]),
                       int(row["queue_index"]))
                entry = mark_groups[key]
                now = int(row["timestamp_ns"])
                entry["count"] += 1
                entry["first_ns"] = now if entry["first_ns"] is None else min(entry["first_ns"], now)
                entry["last_ns"] = now if entry["last_ns"] is None else max(entry["last_ns"], now)
                entry["max_queue_after_dequeue"] = max(
                    entry["max_queue_after_dequeue"], int(row["mmu_egress_bytes_after_dequeue"]))
                entry["kmin_bytes"] = int(row["kmin_bytes"])
                entry["kmax_bytes"] = int(row["kmax_bytes"])

    cc_path = run_dir / "cc_events.csv"
    cc_by_qp = defaultdict(lambda: {
        "qp_start_rate_gbps": None, "min_rate_gbps": None,
        "last_rate_gbps": None, "cnp_count": 0, "rate_change_count": 0,
        "first_cnp_ns": None, "first_rate_change_ns": None,
        "last_rate_change_ns": None,
    })
    if cc_path.exists():
        with cc_path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                qp = row["qp_id"]
                entry = cc_by_qp[qp]
                event = row["event"]
                now = int(row["timestamp"])
                if event == "QP_START":
                    rate = int(row["new_rate_bps"]) / 1e9
                    entry["qp_start_rate_gbps"] = round(rate, 6)
                    entry["min_rate_gbps"] = rate
                    entry["last_rate_gbps"] = rate
                elif event == "CNP":
                    entry["cnp_count"] += 1
                    entry["first_cnp_ns"] = now if entry["first_cnp_ns"] is None else min(
                        entry["first_cnp_ns"], now)
                elif event == "RATE":
                    rate = int(row["new_rate_bps"]) / 1e9
                    entry["rate_change_count"] += 1
                    entry["first_rate_change_ns"] = (
                        now if entry["first_rate_change_ns"] is None
                        else min(entry["first_rate_change_ns"], now))
                    entry["min_rate_gbps"] = rate if entry["min_rate_gbps"] is None else min(
                        entry["min_rate_gbps"], rate)
                    entry["last_rate_gbps"] = round(rate, 6)
                    entry["last_rate_change_ns"] = now
    for entry in cc_by_qp.values():
        if entry["min_rate_gbps"] is not None:
            entry["min_rate_gbps"] = round(entry["min_rate_gbps"], 6)

    fct_ms = [int(row["duration_ns"]) / 1e6 for row in ends]
    cc_entries = list(cc_by_qp.values())
    changed_qps = [entry for entry in cc_entries if entry["rate_change_count"]]
    cnp_qps = [entry for entry in cc_entries if entry["cnp_count"]]
    start_rates = [entry["qp_start_rate_gbps"] for entry in cc_entries
                   if entry["qp_start_rate_gbps"] is not None]
    min_rates = [entry["min_rate_gbps"] for entry in cc_entries
                 if entry["min_rate_gbps"] is not None]

    return {
        "run": run_dir.name,
        "status": manifest.get("status"),
        "cc_mode": manifest.get("cc_mode_override"),
        "events": len(starts),
        "requests": len(per_request),
        "total_payload_bytes": sum(int(row["bytes"]) for row in starts),
        "event_fct_ms": {row["event_id"]: round(int(row["duration_ns"]) / 1e6, 6)
                         for row in ends},
        "event_fct_summary_ms": {
            "mean": round(statistics.fmean(fct_ms), 6) if fct_ms else None,
            "p50": round(percentile(fct_ms, 50), 6) if fct_ms else None,
            "p95": round(percentile(fct_ms, 95), 6) if fct_ms else None,
            "p99": round(percentile(fct_ms, 99), 6) if fct_ms else None,
            "max": round(max(fct_ms), 6) if fct_ms else None,
        },
        "request_barrier_ms": {
            request: round(max(durations) / 1e6, 6)
            for request, durations in sorted(per_request.items(), key=lambda pair: int(pair[0]))
        },
        "request_barrier_elapsed_ms": {
            request: request_barriers[request]["p2d_ready_elapsed_ms"]
            for request in sorted(request_barriers, key=int)
        },
        "request_p2d_ready": {
            request: request_barriers[request]
            for request in sorted(request_barriers, key=int)
        },
        "p2d_ready_mean_from_t0_ms": round(
            sum(item["p2d_ready_absolute_ms"] for item in request_barriers.values()) /
            max(1, len(request_barriers)), 6),
        "network_replay_makespan_ms": round(
            max((item["p2d_ready_absolute_ms"] for item in request_barriers.values()),
                default=0), 6),
        "path_links": [
            {
                "link_id": link_id,
                "src": int(links[link_id]["src_node"]),
                "dst": int(links[link_id]["dst_node"]),
                "capacity_gbps": round(int(links[link_id]["capacity_bps"]) / 1e9, 3),
                "tx_bytes": int(links[link_id]["tx_bytes"]),
                "peak_util": float(links[link_id]["peak_utilization"]),
                "max_queue_bytes": int(links[link_id]["queue_max_bytes"]),
                "ecn_packet_observations": int(links[link_id]["ecn_marks"]),
                "pfc_pause": int(links[link_id]["pfc_pause"]),
                "drops": int(links[link_id]["drop_count"]),
            }
            for link_id in path_link_ids
        ],
        "local_ecn_first_marks": [
            {"switch_id": key[0], "link_id": key[1], "egress_port": key[2],
             "queue_index": key[3], **value}
            for key, value in sorted(mark_groups.items())
        ],
        "cc_per_qp": dict(sorted(cc_by_qp.items(), key=lambda pair: int(pair[0]))),
        "cc_summary": {
            "qp_count": len(cc_entries),
            "qps_with_cnp": len(cnp_qps),
            "qps_with_rate_change": len(changed_qps),
            "cnp_events": sum(entry["cnp_count"] for entry in cc_entries),
            "rate_change_events": sum(entry["rate_change_count"] for entry in cc_entries),
            "initial_rate_gbps_min": min(start_rates) if start_rates else None,
            "initial_rate_gbps_max": max(start_rates) if start_rates else None,
            "minimum_rate_gbps_min": min(min_rates) if min_rates else None,
            "minimum_rate_gbps_median": percentile(min_rates, 50),
            "minimum_rate_gbps_max": max(min_rates) if min_rates else None,
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("runs", nargs="+")
    args = parser.parse_args()
    reports = [summarize(path) for path in args.runs]
    if args.compact:
        reports = [{
            "run": report["run"],
            "cc_mode": report["cc_mode"],
            "events": report["events"],
            "total_payload_bytes": report["total_payload_bytes"],
            "event_fct_summary_ms": report["event_fct_summary_ms"],
            "request_p2d_ready_barrier_ms": report["request_barrier_ms"],
            "request_barrier_elapsed_ms": report["request_barrier_elapsed_ms"],
            "request_p2d_ready": report["request_p2d_ready"],
            "p2d_ready_mean_from_t0_ms": report["p2d_ready_mean_from_t0_ms"],
            "network_replay_makespan_ms": report["network_replay_makespan_ms"],
            "bottleneck_links": [link for link in report["path_links"]
                                 if link["max_queue_bytes"] > 65536 or
                                 link["pfc_pause"] or link["drops"]],
            "local_ecn_first_marks": report["local_ecn_first_marks"],
            "cc_summary": report["cc_summary"],
        } for report in reports]
    print(json.dumps(reports, indent=2))
