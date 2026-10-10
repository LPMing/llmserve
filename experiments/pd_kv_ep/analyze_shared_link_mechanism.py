#!/usr/bin/env python3
"""Report every exact P2D-KV/EP shared directed link for matched native runs.

This is deliberately a measurement-only postprocessor.  It reads the native
timeline and ns-3 telemetry already emitted by a completed paired run.  A link
appears only when a B-request P2D flow and a same-payload A-request EP flow
have an explicit positive interval intersection on that directed physical link.
"""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import autonomous_search as search
from semantic_events import is_decode_ep, is_p2d_kv


DEFAULT_POINTS = (
    "two_prefill_b1_512_a2:2:1",
    "two_prefill_b1_2048_a2:2:1",
    "two_prefill_b2_2048_a2:2:2",
)

FIELDS = (
    "workload", "link_id", "src_node", "dst_node", "selection_rule",
    "selected_by_table", "exact_overlap_rows", "exact_overlap_ns",
    "exact_ep_collectives", "overlap_ep_intervals", "baseline_ep_intervals",
    "queue_overlap_mean_bytes", "queue_overlap_max_bytes",
    "queue_baseline_mean_bytes", "queue_baseline_max_bytes",
    "queue_mean_delta_bytes", "queue_max_delta_bytes", "kv_flow_count",
    "kv_bytes", "ep_flow_count", "ep_bytes", "overlap_time_ns",
    "peak_concurrent_kv_flows", "peak_concurrent_ep_flows",
    "peak_concurrent_total_flows", "shared_link_kv_gbps",
    "shared_link_ep_gbps", "capacity_bps", "peak_utilization", "ecn_marks",
    "pfc_pause", "drop_count",
)


def parse_point(value):
    """Parse label:A-request-count:B-request-count."""
    pieces = value.rsplit(":", 2)
    if len(pieces) != 3:
        raise argparse.ArgumentTypeError("point must be label:a_count:b_count")
    label, a_count, b_count = pieces
    try:
        return label, int(a_count), int(b_count)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("request counts must be integers") from exc


def run_paths(label, side):
    run_id = "auto-%s-%s" % (label, side)
    output = search.RESULTS / (run_id + ".csv")
    paths = search.existing_summary(run_id, output)
    paths["output"] = output
    return paths


def matched_collectives(path):
    """Return same-payload overlap-to-baseline collective ID mappings."""
    mapping = {}
    for row in search.read_rows(path):
        if row.get("same_payload") != "True":
            continue
        overlap_id = row.get("overlap_collective_id", "")
        baseline_id = row.get("baseline_collective_id", "")
        if overlap_id and baseline_id:
            mapping[overlap_id] = baseline_id
    return mapping


def exact_links(overlap_path, timeline, kv_ids, collective_mapping):
    """Group valid exact-overlap evidence by directed physical link."""
    by_event = {row.get("event_id", ""): row for row in timeline}
    result = defaultdict(lambda: {
        "row_count": 0,
        "overlap_ns": 0,
        "overlap_collectives": set(),
        "baseline_collectives": set(),
    })
    kv_ids = {str(value) for value in kv_ids}
    for row in search.read_rows(overlap_path):
        kv_event = by_event.get(row.get("kv_event_id", ""), {})
        overlap_collective = row.get("ep_collective_id", "")
        if (kv_event.get("request_id") not in kv_ids or
                overlap_collective not in collective_mapping):
            continue
        try:
            duration = int(row.get("overlap_ns", 0))
        except (TypeError, ValueError):
            continue
        if duration <= 0:
            continue
        evidence = result[row["link_id"]]
        evidence["row_count"] += 1
        evidence["overlap_ns"] += duration
        evidence["overlap_collectives"].add(overlap_collective)
        evidence["baseline_collectives"].add(collective_mapping[overlap_collective])
    return result


def link_summary(path):
    return {row["link_id"]: row for row in search.read_rows(path)}


def record_for_link(label, link_id, evidence, overlap_paths, baseline_paths,
                    overlap_timeline, target_ids, kv_ids, selected_link):
    overlap_intervals = search.collective_link_intervals(
        overlap_timeline, link_id, evidence["overlap_collectives"])
    baseline_intervals = search.collective_link_intervals(
        search.read_timeline(baseline_paths["timeline"]), link_id,
        evidence["baseline_collectives"])
    overlap_queue = search.queue_window_stats(
        overlap_paths["link_timeseries"], link_id, overlap_intervals)
    baseline_queue = search.queue_window_stats(
        baseline_paths["link_timeseries"], link_id, baseline_intervals)
    pressure = search.link_pressure(
        overlap_timeline, link_id, target_ids, kv_ids,
        overlap_paths["link_summary"])
    summary = link_summary(overlap_paths["link_summary"]).get(link_id, {})
    return {
        "workload": label,
        "link_id": link_id,
        "src_node": summary.get("src_node", ""),
        "dst_node": summary.get("dst_node", ""),
        "selection_rule": "all_positive_exact_shared_directed_links",
        "selected_by_table": str(link_id == selected_link),
        "exact_overlap_rows": evidence["row_count"],
        "exact_overlap_ns": evidence["overlap_ns"],
        "exact_ep_collectives": len(evidence["overlap_collectives"]),
        "overlap_ep_intervals": len(overlap_intervals),
        "baseline_ep_intervals": len(baseline_intervals),
        "queue_overlap_mean_bytes": overlap_queue["mean_queue_bytes"],
        "queue_overlap_max_bytes": overlap_queue["max_queue_bytes"],
        "queue_baseline_mean_bytes": baseline_queue["mean_queue_bytes"],
        "queue_baseline_max_bytes": baseline_queue["max_queue_bytes"],
        "queue_mean_delta_bytes": (overlap_queue["mean_queue_bytes"] -
                                   baseline_queue["mean_queue_bytes"]),
        "queue_max_delta_bytes": (overlap_queue["max_queue_bytes"] -
                                  baseline_queue["max_queue_bytes"]),
        "kv_flow_count": pressure.get("kv_rows", 0),
        "kv_bytes": sum(row["bytes_num"] for row in overlap_timeline
                        if is_p2d_kv(row) and
                        row.get("request_id") in set(kv_ids) and
                        link_id in row.get("directed_link_ids", "").split(";")),
        "ep_flow_count": pressure.get("ep_rows", 0),
        "ep_bytes": sum(row["bytes_num"] for row in overlap_timeline
                        if is_decode_ep(row) and
                        search.numeric_ids(row.get("active_request_ids", "")) ==
                        tuple(target_ids) and
                        link_id in row.get("directed_link_ids", "").split(";")),
        "overlap_time_ns": pressure.get("overlap_time_ns", 0),
        "peak_concurrent_kv_flows": pressure.get("peak_concurrent_kv_flows", 0),
        "peak_concurrent_ep_flows": pressure.get("peak_concurrent_ep_flows", 0),
        "peak_concurrent_total_flows": pressure.get("peak_concurrent_total_flows", 0),
        "shared_link_kv_gbps": pressure.get("shared_link_kv_gbps", 0.0),
        "shared_link_ep_gbps": pressure.get("shared_link_ep_gbps", 0.0),
        "capacity_bps": pressure.get("capacity_bps", 0.0),
        "peak_utilization": pressure.get("peak_utilization", 0.0),
        "ecn_marks": pressure.get("ecn_marks", 0),
        "pfc_pause": pressure.get("pfc_pause", 0),
        "drop_count": pressure.get("drop_count", 0),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--point", action="append", type=parse_point,
                        help="label:a_count:b_count; may be repeated")
    parser.add_argument("--output", type=Path,
                        default=search.RESULTS / "shared_link_mechanism.csv")
    args = parser.parse_args()
    points = args.point or [parse_point(value) for value in DEFAULT_POINTS]
    records = []
    for label, a_count, b_count in points:
        overlap_paths = run_paths(label, "overlap")
        baseline_paths = run_paths(label, "baseline")
        overlap_timeline = search.read_timeline(overlap_paths["timeline"])
        target_ids = [str(index) for index in range(a_count)]
        kv_ids = [str(a_count + index) for index in range(b_count)]
        mapping = matched_collectives(search.RESULTS / (label + ".matched_collectives.csv"))
        evidence = exact_links(overlap_paths["overlap"], overlap_timeline,
                               kv_ids, mapping)
        selected_link, _ = search.choose_shared_link(overlap_paths["overlap"],
                                                     overlap_timeline, kv_ids)
        for link_id in sorted(evidence, key=int):
            records.append(record_for_link(
                label, link_id, evidence[link_id], overlap_paths, baseline_paths,
                overlap_timeline, target_ids, kv_ids, selected_link))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)
    print(json.dumps({"output": str(args.output), "records": len(records)}, indent=2))


if __name__ == "__main__":
    main()
