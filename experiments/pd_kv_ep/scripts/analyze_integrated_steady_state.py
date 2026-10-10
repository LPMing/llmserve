#!/usr/bin/env python3
"""Build compact activity and barrier summaries from an integrated FlowSim run.

KV intervals are per completed FlowSim flow. EP intervals are collective-level;
without FLOWSIM_EP_FLOW_TELEMETRY they do not expose each peer's lifetime.
"""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


def percentile(values, p):
    values = sorted(float(value) for value in values)
    if not values:
        return None
    pos = (len(values) - 1) * p
    lo, hi = math.floor(pos), math.ceil(pos)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def merge(intervals):
    out = []
    for start, end in sorted((int(a), int(b)) for a, b in intervals if b > a):
        if not out or start > out[-1][1]:
            out.append([start, end])
        else:
            out[-1][1] = max(out[-1][1], end)
    return [(a, b) for a, b in out]


def overlap_duration(a, b):
    a, b = merge(a), merge(b)
    i = j = total = 0
    while i < len(a) and j < len(b):
        total += max(0, min(a[i][1], b[j][1]) - max(a[i][0], b[j][0]))
        if a[i][1] <= b[j][1]:
            i += 1
        else:
            j += 1
    return total


def population(intervals, timestamp):
    return sum(start <= timestamp < end for start, end in intervals)


def population_series(intervals, bins, bin_ns, weight=None):
    changes = defaultdict(int)
    for interval in intervals:
        start, end = int(interval[0]), int(interval[1])
        amount = int(weight(interval)) if weight else 1
        if end > start:
            changes[start] += amount
            changes[end] -= amount
    points = sorted(changes)
    point_index = active = 0
    values = []
    for start in bins:
        midpoint = start + bin_ns // 2
        while point_index < len(points) and points[point_index] <= midpoint:
            active += changes[points[point_index]]
            point_index += 1
        values.append(active)
    return values


def load_jsonl(path):
    records = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("{"):
                records.append(json.loads(line))
    return records


def stats(values, scale=1.0):
    values = [float(value) / scale for value in values]
    return {"count": len(values), "mean": (sum(values) / len(values) if values else None),
            "p50": percentile(values, .50), "p95": percentile(values, .95),
            "p99": percentile(values, .99), "max": max(values) if values else None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--flowsim-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bin-us", type=int, default=100)
    args = parser.parse_args()
    if args.bin_us <= 0:
        parser.error("--bin-us must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    with args.requests.open(newline="", encoding="utf-8") as stream:
        requests = list(csv.DictReader(stream))
    kv_events = load_jsonl(args.flowsim_dir / "kv_event_telemetry.jsonl")
    ep_events = load_jsonl(args.flowsim_dir / "collective_telemetry.jsonl")

    arrivals, prefill_proxy, decode, warm_decode = [], [], [], []
    ttft, tbt = [], []
    non_metric_records = 0
    request_rows = {}
    for row in requests:
        rid = int(row["request id"])
        request_rows[rid] = row
        if row.get("trace_record_status") == "EMPTY_ZERO_TOKEN_SOURCE_RECORD":
            non_metric_records += 1
            continue
        arrival = int(float(row["arrival"]))
        finish = int(float(row["end_time"]))
        prefill_end = int(float(row.get("prefill_completion_time_ns") or arrival))
        decode_start = int(float(row.get("decode_scheduler_admit_time_ns") or finish))
        arrivals.append(arrival)
        if prefill_end > arrival:
            prefill_proxy.append((arrival, prefill_end))
        if finish > decode_start:
            decode.append((decode_start, finish))
        try:
            ttft.append(float(row["TTFT"]))
        except (KeyError, TypeError, ValueError):
            pass
        try:
            token_times = json.loads(row.get("TBT", "[]"))
        except (TypeError, json.JSONDecodeError):
            token_times = []
        tbt.extend(float(value) for value in token_times)
        if len(token_times) >= 3 and int(row.get("output") or 0) >= 4:
            first = int(float(row.get("decode_first_token_time_ns") or 0))
            warm = first + sum(int(value) for value in token_times[:3])
            if finish > warm:
                warm_decode.append((warm, finish))

    generated_by_id = {}
    requested_by_id = {}
    completed_by_id = {}
    for event in kv_events:
        flow_id = str(event.get("flow_id"))
        kind = event.get("event")
        if kind == "KV_GENERATED":
            generated_by_id[flow_id] = event
        elif kind == "KV_REQUESTED":
            requested_by_id[flow_id] = event
        elif kind == "KV_COMPLETED":
            completed_by_id[flow_id] = event

    kv_intervals = []
    kv_by_request = defaultdict(list)
    kv_fct, kv_residual, kv_bytes = [], [], 0
    kv_requested_bytes_by_bin = defaultdict(int)
    kv_generated_bytes_by_bin = defaultdict(int)
    kv_completed_bytes_by_bin = defaultdict(int)
    for flow_id, event in completed_by_id.items():
        start, end = int(event["start_ns"]), int(event["end_ns"])
        if end < start:
            continue
        kv_intervals.append((start, end))
        requested = requested_by_id.get(flow_id, {})
        generated = generated_by_id.get(flow_id, {})
        req_time = int(requested.get("timestamp_ns", event.get("requested_start_ns", start)))
        generated_time = int(generated.get("timestamp_ns", req_time))
        size = int(event.get("bytes", 0))
        kv_fct.append(end - start)
        kv_residual.append(end - req_time)
        kv_bytes += size
        for request_id in event.get("request_ids", ()):
            kv_by_request[int(request_id)].append((start, end, req_time, size))
        kv_generated_bytes_by_bin[generated_time] += size
        kv_requested_bytes_by_bin[req_time] += size
        kv_completed_bytes_by_bin[end] += size

    ep_intervals = []
    ep_cct, ep_flow_count = [], []
    ep_dispatch_bytes_by_bin = defaultdict(int)
    ep_combine_bytes_by_bin = defaultdict(int)
    ep_starts_by_type = defaultdict(list)
    ep_records = []
    for event in ep_events:
        if event.get("event") != "COLLECTIVE_COMPLETED":
            continue
        start, end = int(event["start_ns"]), int(event["end_ns"])
        if end < start:
            continue
        ep_intervals.append((start, end))
        ep_cct.append(end - start)
        count = int(event.get("flow_count", event.get("participant_flow_count", 0)))
        ep_flow_count.append(count)
        event_type = int(event.get("event_type") or 0)
        payload = int(event.get("bytes_sum", 0))
        target = ep_dispatch_bytes_by_bin if event_type == 2 else ep_combine_bytes_by_bin
        target[start] += payload
        ep_starts_by_type[event_type].append(start)
        ep_records.append((start, end, count, event_type))

    if not requests:
        raise RuntimeError("request CSV is empty")
    origin = min(arrivals)
    end_time = max([int(float(row["end_time"])) for row in requests] +
                   [end for _, end in kv_intervals + ep_intervals])
    bin_ns = args.bin_us * 1000
    first_bin = origin // bin_ns * bin_ns
    bins = list(range(first_bin, end_time, bin_ns))
    activity_wall_overlap = overlap_duration(kv_intervals, ep_intervals)
    activity_wall_union = sum(b - a for a, b in merge(kv_intervals + ep_intervals))

    kv_request_intervals = {
        rid: merge([(start, end) for start, end, _, _ in intervals])
        for rid, intervals in kv_by_request.items()
    }
    flat_kv_request_intervals = [interval for intervals in kv_request_intervals.values()
                                 for interval in intervals]
    binned_bytes = {}
    for name, source in (
            ("kv_generated", kv_generated_bytes_by_bin),
            ("kv_requested", kv_requested_bytes_by_bin),
            ("kv_completed", kv_completed_bytes_by_bin),
            ("ep_dispatch", ep_dispatch_bytes_by_bin),
            ("ep_combine", ep_combine_bytes_by_bin)):
        values = defaultdict(int)
        for timestamp, amount in source.items():
            values[int(timestamp) // bin_ns] += amount
        binned_bytes[name] = values
    prefill_counts = population_series(prefill_proxy, bins, bin_ns)
    decode_counts = population_series(decode, bins, bin_ns)
    warm_counts = population_series(warm_decode, bins, bin_ns)
    kv_flow_counts = population_series(kv_intervals, bins, bin_ns)
    kv_request_counts = population_series(flat_kv_request_intervals, bins, bin_ns)
    ep_collective_counts = population_series(ep_records, bins, bin_ns)
    ep_flow_envelope = population_series(
        ep_records, bins, bin_ns, weight=lambda row: row[2])

    timeline_path = args.output_dir / "STEADY_STATE_ACTIVITY_TIMELINE.csv"
    fields = ["timestamp_ns", "bin_width_ns", "active_prefill_lifecycle_proxy",
              "active_p2d_requests", "active_decode_requests", "active_warm_decode_requests",
              "active_p2d_flows", "active_ep_collectives",
              "active_ep_peer_flows_collective_envelope",
              "kv_generated_bytes", "kv_requested_bytes", "kv_completed_bytes",
              "ep_dispatch_bytes", "ep_combine_bytes"]
    with timeline_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for index, t in enumerate(bins):
            bin_id = t // bin_ns
            writer.writerow({
                "timestamp_ns": t, "bin_width_ns": bin_ns,
                "active_prefill_lifecycle_proxy": prefill_counts[index],
                "active_p2d_requests": kv_request_counts[index],
                "active_decode_requests": decode_counts[index],
                "active_warm_decode_requests": warm_counts[index],
                "active_p2d_flows": kv_flow_counts[index],
                "active_ep_collectives": ep_collective_counts[index],
                "active_ep_peer_flows_collective_envelope": ep_flow_envelope[index],
                "kv_generated_bytes": binned_bytes["kv_generated"][bin_id],
                "kv_requested_bytes": binned_bytes["kv_requested"][bin_id],
                "kv_completed_bytes": binned_bytes["kv_completed"][bin_id],
                "ep_dispatch_bytes": binned_bytes["ep_dispatch"][bin_id],
                "ep_combine_bytes": binned_bytes["ep_combine"][bin_id],
            })

    def population_summary(values):
        return {"p50": percentile(values, .50), "p95": percentile(values, .95),
                "max": max(values, default=0),
                "mean": sum(values) / len(values) if values else 0}

    summary = {
        "request_count": len(requests),
        "metric_request_count": len(requests) - non_metric_records,
        "non_metric_source_record_count": non_metric_records,
        "arrival_span_ms": (max(arrivals) - min(arrivals)) / 1e6,
        "input_tokens": sum(int(row["input"]) for row in requests),
        "output_tokens": sum(int(row["output"]) for row in requests),
        "observation_span_ms": (end_time - origin) / 1e6,
        "telemetry_semantics": {
            "decode": "scheduler admission through request completion",
            "prefill": "arrival through prefill completion lifecycle proxy; not compute-active",
            "p2d_flows": "completed model-derived KV_MOVEMENT FlowSim records",
            "ep": "collective-level intervals; per-peer lifetimes not emitted in compact mode",
            "ep_flow_envelope": "sum of each active collective's flow_count, an upper envelope, not exact active peer count",
            "queue": "FlowSim residual-fluid telemetry is analytical backlog, not packet-buffer occupancy",
        },
        "active_population_at_100us_bins": {
            "decode": population_summary(decode_counts),
            "p2d_requests": population_summary(kv_request_counts),
            "p2d_flows": population_summary(kv_flow_counts),
            "ep_collectives": population_summary(ep_collective_counts),
            "ep_peer_flows_collective_envelope": population_summary(ep_flow_envelope),
            "warm_decode": population_summary(warm_counts),
        },
        "flow_lifetime_overlap": {
            "kv_ep_overlap_ns": activity_wall_overlap,
            "kv_ep_overlap_duty_cycle_union": (
                activity_wall_overlap / activity_wall_union if activity_wall_union else 0),
        },
        "kv": {
            "completed_flow_count": len(kv_fct), "bytes": kv_bytes,
            "shard_fct_us": stats(kv_fct, 1000),
            "release_to_finish_us": stats(kv_residual, 1000),
            "request_handoff_ms": stats([
                max(x[1] for x in entries) - min(x[2] for x in entries)
                for entries in kv_by_request.values()], 1e6),
        },
        "ep": {
            "collective_count": len(ep_cct), "collective_bytes": sum(
                int(event.get("bytes_sum", 0)) for event in ep_events
                if event.get("event") == "COLLECTIVE_COMPLETED"),
            "cct_us": stats(ep_cct, 1000),
            "peer_flow_count_per_collective": stats(ep_flow_count),
            "period_us": {
                str(kind): stats([b - a for a, b in zip(sorted(starts), sorted(starts)[1:])], 1000)
                for kind, starts in ep_starts_by_type.items()},
        },
        "serving": {"ttft_ms": stats(ttft, 1e6), "token_tbt_ms": stats(tbt, 1e6)},
    }
    (args.output_dir / "steady_state_activity_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
