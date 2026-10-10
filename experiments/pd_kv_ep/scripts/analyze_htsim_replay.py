#!/usr/bin/env python3
"""Summarize an HTSim KV/EP replay and its coarse queue telemetry."""

import argparse
import csv
import json
import re
import statistics
import subprocess
from collections import defaultdict
from pathlib import Path


EVENT_CLASS = {1: "KV_MOVEMENT", 2: "EP_DISPATCH", 3: "EP_COMBINE"}


def percentile(values, fraction):
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = fraction * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def union_duration(intervals):
    if not intervals:
        return 0
    total = 0
    start, end = sorted(intervals)[0]
    for next_start, next_end in sorted(intervals)[1:]:
        if next_start <= end:
            end = max(end, next_end)
        else:
            total += end - start
            start, end = next_start, next_end
    return total + end - start


def overlap_duration(left, right):
    points = []
    for start, end in left:
        points.append((start, 1, 0))
        points.append((end, -1, 0))
    for start, end in right:
        points.append((start, 0, 1))
        points.append((end, 0, -1))
    points.sort()
    active_left = active_right = 0
    previous = None
    overlap = 0
    left_active = 0
    right_active = 0
    for timestamp, delta_left, delta_right in points:
        if previous is not None:
            duration = timestamp - previous
            if active_left:
                left_active += duration
            if active_right:
                right_active += duration
            if active_left and active_right:
                overlap += duration
        active_left += delta_left
        active_right += delta_right
        previous = timestamp
    return overlap, left_active, right_active


def normalize_queue_name(value):
    value = value.strip()
    if ")" in value and value.startswith("queue("):
        value = value.split(")", 1)[1]
    return value


def queue_role(name):
    if "->US" in name:
        return "LEAF_UPLINK"
    if name.startswith("US") and "->LS" in name:
        return "SPINE_DOWNLINK"
    if name.startswith("SRC"):
        return "HOST_UPLINK"
    if "->DST" in name:
        return "LEAF_DOWNLINK"
    return "OTHER"


def load_flow_rows(path):
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        row["flow_id"] = int(row["flow_id"])
        row["start_ns"] = int(row["start_ns"])
        row["end_ns"] = int(row["end_ns"])
        row["bytes"] = int(row["bytes"])
        row["event_type"] = int(row["event_type"])
        row["traffic_class"] = EVENT_CLASS.get(row["event_type"], "OTHER")
    return rows


def load_paths(path):
    paths = {}
    with path.open(encoding="utf-8") as stream:
        next(stream, None)
        for line in stream:
            fields = line.rstrip("\n").split(",", 4)
            if len(fields) != 5:
                continue
            flow_id = int(fields[0])
            queues = [normalize_queue_name(item)
                      for item in fields[4].split(";") if item]
            paths[flow_id] = queues
    return paths


def write_flow_outputs(rows, output_dir):
    by_class = defaultdict(list)
    for row in rows:
        if row["completed"] != "1":
            continue
        cct = row["end_ns"] - row["start_ns"]
        by_class[row["traffic_class"]].append((row["bytes"], cct))

    with (output_dir / "flow_summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["traffic_class", "flow_count", "bytes", "cct_p50_ns",
                         "cct_p95_ns", "cct_p99_ns", "cct_max_ns"])
        for traffic_class in ("KV_MOVEMENT", "EP_DISPATCH", "EP_COMBINE", "OTHER"):
            values = by_class.get(traffic_class, [])
            ccts = [item[1] for item in values]
            writer.writerow([
                traffic_class, len(values), sum(item[0] for item in values),
                int(percentile(ccts, 0.50)), int(percentile(ccts, 0.95)),
                int(percentile(ccts, 0.99)), max(ccts, default=0)])

    groups = defaultdict(list)
    for row in rows:
        if row["completed"] != "1" or row["traffic_class"] not in ("EP_DISPATCH", "EP_COMBINE"):
            continue
        key = (row["event_type"], row["collective_id"], row["start_ns"])
        groups[key].append(row)
    with (output_dir / "collective_summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["traffic_class", "collective_id", "start_ns", "end_ns",
                         "cct_ns", "flow_count", "bytes"])
        for (event_type, collective_id, start_ns), group in sorted(groups.items()):
            end_ns = max(row["end_ns"] for row in group)
            writer.writerow([
                EVENT_CLASS[event_type], collective_id, start_ns, end_ns,
                end_ns - start_ns, len(group), sum(row["bytes"] for row in group)])


def write_queue_outputs(flow_rows, path_rows, queue_log, output_dir, parser):
    queue_intervals = defaultdict(lambda: {"KV_MOVEMENT": [], "EP": []})
    flow_by_id = {row["flow_id"]: row for row in flow_rows}
    for flow_id, queues in path_rows.items():
        row = flow_by_id.get(flow_id)
        if row is None or row["completed"] != "1":
            continue
        traffic_class = row["traffic_class"]
        if traffic_class == "KV_MOVEMENT":
            key = "KV_MOVEMENT"
        elif traffic_class.startswith("EP_"):
            key = "EP"
        else:
            continue
        interval = (row["start_ns"], row["end_ns"])
        for queue in set(queues):
            queue_intervals[queue][key].append((interval[0], interval[1]))

    queue_samples = defaultdict(list)
    range_pattern = re.compile(
        r"^(\S+) Type QUEUE_APPROX ID (\d+) Ev RANGE LastQ (-?\d+) "
        r"MinQ (-?\d+) MaxQ (-?\d+)(?: Name (.*))?$")
    process = subprocess.Popen(
        [str(parser), str(queue_log), "-ascii", "-filter", "Type QUEUE_APPROX"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    # The path_rows argument is replaced by the caller with the HTSim logfile.
    for line in process.stdout:
        match = range_pattern.match(line.rstrip("\n"))
        if not match:
            continue
        timestamp, queue_id, last_q, min_q, max_q, name = match.groups()
        queue_name = normalize_queue_name(name or ("queue_id_" + queue_id))
        queue_samples[queue_name].append(
            (float(timestamp), int(queue_id), int(last_q), int(min_q), int(max_q)))
    process.wait()

    with (output_dir / "queue_timeseries.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time_s", "queue_id", "queue", "role", "last_queue_bytes",
                         "min_queue_bytes", "max_queue_bytes"])
        for queue, samples in sorted(queue_samples.items()):
            for timestamp, queue_id, last_q, min_q, max_q in samples:
                writer.writerow([timestamp, queue_id, queue, queue_role(queue),
                                 last_q, min_q, max_q])

    with (output_dir / "queue_summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["queue", "role", "queue_id", "sample_count", "max_q_p50_bytes",
                         "max_q_p95_bytes", "max_q_p99_bytes", "max_q_bytes"])
        for queue, samples in sorted(queue_samples.items()):
            max_values = [item[4] for item in samples]
            writer.writerow([
                queue, queue_role(queue), samples[0][1], len(samples),
                int(percentile(max_values, 0.50)), int(percentile(max_values, 0.95)),
                int(percentile(max_values, 0.99)), max(max_values, default=0)])

    with (output_dir / "mixed_queue_summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["queue", "role", "kv_flow_count", "ep_flow_count", "kv_bytes",
                         "ep_bytes", "kv_active_ns", "ep_active_ns", "kv_ep_overlap_ns"])
        for queue, classes in sorted(queue_intervals.items()):
            kv = classes["KV_MOVEMENT"]
            ep = classes["EP"]
            if not kv or not ep:
                continue
            kv_ids = {flow_id for flow_id, queues in path_rows.items() if queue in queues
                      and flow_by_id.get(flow_id, {}).get("traffic_class") == "KV_MOVEMENT"}
            ep_ids = {flow_id for flow_id, queues in path_rows.items() if queue in queues
                      and flow_by_id.get(flow_id, {}).get("traffic_class", "").startswith("EP_")}
            overlap, kv_active, ep_active = overlap_duration(kv, ep)
            writer.writerow([
                queue, queue_role(queue), len(kv_ids), len(ep_ids),
                sum(flow_by_id[item]["bytes"] for item in kv_ids),
                sum(flow_by_id[item]["bytes"] for item in ep_ids),
                kv_active, ep_active, overlap])

    return queue_samples, queue_intervals


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--flow-output", required=True, type=Path)
    parser.add_argument("--queue-log", required=True, type=Path)
    parser.add_argument("--path-output", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--parser", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows = load_flow_rows(args.flow_output)
    paths = load_paths(args.path_output)
    write_flow_outputs(rows, args.output_dir)
    queue_samples, queue_intervals = write_queue_outputs(
        rows, paths, args.queue_log, args.output_dir, args.parser)

    all_kv = [(row["start_ns"], row["end_ns"]) for row in rows
              if row["traffic_class"] == "KV_MOVEMENT" and row["completed"] == "1"]
    all_ep = [(row["start_ns"], row["end_ns"]) for row in rows
              if row["traffic_class"].startswith("EP_") and row["completed"] == "1"]
    overlap, kv_active, ep_active = overlap_duration(all_kv, all_ep)
    rows_by_id = {row["flow_id"]: row for row in rows}
    shared_queue_count = 0
    shared_queue_overlap_count = 0
    shared_queue_overlap_ns = 0
    max_shared_queue_bytes = 0
    max_shared_queue_observed_q_bytes = 0
    for queue, classes in queue_intervals.items():
        kv = classes["KV_MOVEMENT"]
        ep = classes["EP"]
        if not kv or not ep:
            continue
        shared_queue_count += 1
        queue_overlap, _, _ = overlap_duration(kv, ep)
        shared_queue_overlap_ns += queue_overlap
        if queue_overlap:
            shared_queue_overlap_count += 1
            kv_ids = {flow_id for flow_id, queues in paths.items()
                      if queue in queues and rows_by_id.get(flow_id, {}).get("traffic_class") == "KV_MOVEMENT"}
            ep_ids = {flow_id for flow_id, queues in paths.items()
                      if queue in queues and rows_by_id.get(flow_id, {}).get("traffic_class", "").startswith("EP_")}
            max_shared_queue_bytes = max(
                max_shared_queue_bytes,
                sum(rows_by_id[item]["bytes"] for item in kv_ids),
                sum(rows_by_id[item]["bytes"] for item in ep_ids))
        for sample in queue_samples.get(queue, []):
            max_shared_queue_observed_q_bytes = max(max_shared_queue_observed_q_bytes, sample[4])
    log_text = args.flow_output.with_suffix(".log").read_text(encoding="utf-8", errors="replace")
    wall_match = re.search(r"WALL_SECONDS=([0-9.]+)", log_text)
    metrics = {
        "flow_count": len(rows),
        "completed_flow_count": sum(row["completed"] == "1" for row in rows),
        "mtu_bytes": 4096,
        "wall_seconds": float(wall_match.group(1)) if wall_match else None,
        "temporal_kv_ep_overlap_ns": overlap,
        "temporal_kv_active_ns": kv_active,
        "temporal_ep_active_ns": ep_active,
        "shared_queue_count": shared_queue_count,
        "shared_queue_overlap_count": shared_queue_overlap_count,
        "shared_queue_overlap_ns": shared_queue_overlap_ns,
        "max_shared_queue_class_bytes": max_shared_queue_bytes,
        "max_shared_queue_observed_q_bytes": max_shared_queue_observed_q_bytes,
        "path_observed_queue_count": len(queue_intervals),
        "queue_sample_count": sum(len(value) for value in queue_samples.values()),
        "serving_metrics": {
            "TTFT": "NOT_AVAILABLE",
            "TPOT": "NOT_AVAILABLE",
            "TBT": "NOT_AVAILABLE",
            "SLO": "NOT_AVAILABLE",
            "reason": "This standalone HTSim replay bypasses the LLMServingSim serving scheduler; it records network completion and queue telemetry only."
        },
    }
    (args.output_dir / "htsim_network_metrics.json").write_text(
        json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "serving_metrics_status.csv").write_text(
        "metric,status,reason\n"
        "TTFT,NOT_AVAILABLE,standalone network replay bypasses serving scheduler\n"
        "TPOT,NOT_AVAILABLE,standalone network replay bypasses serving scheduler\n"
        "TBT,NOT_AVAILABLE,standalone network replay bypasses serving scheduler\n"
        "SLO,NOT_AVAILABLE,standalone network replay bypasses serving scheduler\n",
        encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
