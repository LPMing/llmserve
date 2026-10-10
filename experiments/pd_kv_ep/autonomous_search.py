#!/usr/bin/env python3
"""Bounded autonomous search for native P2D-KV versus Decode-EP contention.

Every point is a pair of runs with identical native requests, model, topology,
and routing.  Only B's arrival schedule differs.  The comparison selects
same-payload Decode collectives through explicit metadata and exact directed
link overlap; broad event envelopes are never used as evidence.
"""

import argparse
import csv
import json
import math
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from matched_search import compare, write_matched_workload
from semantic_events import is_decode_ep, is_p2d_kv


ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "experiments" / "pd_kv_ep"
RESULTS = EXP / "results"
WORKLOADS = EXP / "workloads" / "autonomous"
FIGURES = EXP / "figures"
LOG_PATH = EXP / "autonomous_search_log.md"
NEGATIVE_PATH = EXP / "negative_results.csv"
TABLE_PATH = ROOT / "FINAL_MOTIVATION_TABLE.csv"
TABLE_FIELDS = [
    "workload", "input_distribution", "output_distribution", "arrival_rate",
    "active_decode", "prefill_instances", "EP_degree", "KV_bytes",
    "EP_bytes_per_collective", "shared_link_KV_Gbps", "shared_link_EP_Gbps",
    "peak_utilization", "queue_max", "overlap_fraction", "EP_P50", "EP_P95",
    "EP_P99", "EP_P99_slowdown", "KV_completion", "KV_slowdown", "TTFT",
    "TTFT_slowdown", "TPOT", "TPOT_slowdown", "validity", "seed",
    "mean_concurrent_load_ratio", "shared_link_id", "queue_mean", "ECN", "PFC",
    "drop_count", "baseline_reused", "run_overlap", "run_baseline",
    "telemetry_version", "shared_link_selection", "focus_queue_mean_overlap",
    "focus_queue_max_overlap", "focus_queue_mean_baseline",
    "focus_queue_max_baseline", "focus_queue_span_overlap_ns",
    "focus_queue_span_baseline_ns", "cluster_config",
]


def percentile(values, fraction):
    values = sorted(float(value) for value in values)
    if not values:
        return None
    index = (len(values) - 1) * fraction
    low = math.floor(index)
    high = math.ceil(index)
    if low == high:
        return values[low]
    return values[low] + (values[high] - values[low]) * (index - low)


def read_rows(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def read_timeline(path):
    rows = []
    for row in read_rows(path):
        try:
            row["start_num"] = int(row["start"])
            row["end_num"] = int(row["end"])
            row["bytes_num"] = int(row["bytes"])
        except (KeyError, TypeError, ValueError):
            continue
        if row["end_num"] >= row["start_num"]:
            rows.append(row)
    return rows


def numeric_ids(value):
    return tuple(sorted((item for item in str(value).replace(";", ",").split(",")
                         if item), key=int))


def config_role_counts(config_value):
    """Read role counts from the actual config used for a native run."""
    config_value = (config_value or
                    "experiments/pd_kv_ep/configs/small_pd_moe_ep.json")
    path = Path(config_value)
    if not path.is_absolute():
        path = ROOT / path
    with path.open(encoding="utf-8") as stream:
        config = json.load(stream)
    instances = [instance for node in config.get("nodes", [])
                 for instance in node.get("instances", [])]
    prefill = sum(1 for instance in instances
                  if instance.get("pd_type") == "prefill")
    decode_ep = [int(instance.get("ep_size", instance.get("tp_size", 1)))
                 for instance in instances if instance.get("pd_type") == "decode"]
    return {"prefill_instances": prefill,
            "ep_degree": max(decode_ep, default=0)}


def union_length(intervals):
    merged = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return sum(end - start for start, end in merged)


def choose_shared_link(overlap_path, timeline_rows, kv_ids):
    """Choose the link with most exact B-KV/EP overlap rows, deterministically."""
    by_event = {row.get("event_id", ""): row for row in timeline_rows}
    counts = Counter()
    overlap_rows = []
    for row in read_rows(overlap_path):
        kv = by_event.get(row.get("kv_event_id", ""), {})
        if kv.get("request_id", "") not in set(kv_ids):
            continue
        try:
            duration = int(row["overlap_ns"])
        except (KeyError, TypeError, ValueError):
            continue
        if duration > 0:
            counts[row["link_id"]] += duration
            overlap_rows.append(row)
    if not counts:
        return None, overlap_rows
    # A path can have equal overlap on each hop. Select the lowest numerical
    # directed-link ID in that tie, rather than selecting by observed queue or
    # slowdown, so the representative link cannot be outcome-picked.
    best = sorted(counts, key=lambda link: (-counts[link], int(link)))[0]
    return best, overlap_rows


def link_pressure(timeline_rows, link_id, target_ids, kv_ids, link_summary_path):
    """Measure run-local, shared-link pressure without pairwise double counting."""
    target = tuple(str(value) for value in target_ids)
    selected = []
    for row in timeline_rows:
        if link_id not in set(item for item in row.get("directed_link_ids", "").split(";")
                              if item):
            continue
        if is_p2d_kv(row) and row.get("request_id", "") in set(kv_ids):
            selected.append(("kv", row))
        elif is_decode_ep(row) and numeric_ids(
                row.get("active_request_ids", "")) == target:
            selected.append(("ep", row))
    kv_rows = [row for kind, row in selected if kind == "kv"]
    ep_rows = [row for kind, row in selected if kind == "ep"]
    if not kv_rows or not ep_rows:
        return {"shared_link_id": link_id, "kv_rows": len(kv_rows),
                "ep_rows": len(ep_rows), "overlap_fraction": 0.0,
                "mean_concurrent_load_ratio": 0.0}

    summary = {row["link_id"]: row for row in read_rows(link_summary_path)}
    capacity = float(summary.get(link_id, {}).get("capacity_bps", 0) or 0)
    # Track active communication events by id rather than by a floating-point
    # running sum of rates.  Subtracting non-identical binary floats can leave
    # a tiny positive residual after the final KV event, which previously made
    # idle gaps look like KV/EP overlap and could yield an impossible fraction
    # above one.  This is measurement-only accounting; it does not affect
    # trace generation, the network backend, or CCT collection.
    points = []
    for category, rows in (("kv", kv_rows), ("ep", ep_rows)):
        for ordinal, row in enumerate(rows):
            duration = row["end_num"] - row["start_num"]
            if duration <= 0:
                continue
            rate_bps = row["bytes_num"] * 8.0e9 / duration
            event_key = "%s:%s:%s" % (category, row.get("event_id", ""), ordinal)
            points.append((row["start_num"], 1, category, event_key, rate_bps))
            points.append((row["end_num"], -1, category, event_key, rate_bps))
    points.sort(key=lambda item: item[0])
    active = {"kv": {}, "ep": {}}
    last = points[0][0]
    overlap_time = 0
    load_integral = 0.0
    peak_kv_flow_count = 0
    peak_ep_flow_count = 0
    peak_total_flow_count = 0
    index = 0
    while index < len(points):
        timestamp = points[index][0]
        elapsed = timestamp - last
        if elapsed > 0 and active["kv"] and active["ep"]:
            overlap_time += elapsed
            load_integral += (sum(active["kv"].values()) +
                              sum(active["ep"].values())) * elapsed
        while index < len(points) and points[index][0] == timestamp:
            _, direction, category, event_key, rate = points[index]
            if direction > 0:
                active[category][event_key] = rate
            else:
                active[category].pop(event_key, None)
            index += 1
        # The active maps are keyed by concrete communication events, so these
        # counts are physical-flow concurrency rather than an inferred rate.
        peak_kv_flow_count = max(peak_kv_flow_count, len(active["kv"]))
        peak_ep_flow_count = max(peak_ep_flow_count, len(active["ep"]))
        peak_total_flow_count = max(peak_total_flow_count,
                                    len(active["kv"]) + len(active["ep"]))
        last = timestamp
    kv_active = union_length([(row["start_num"], row["end_num"]) for row in kv_rows])
    ep_active = union_length([(row["start_num"], row["end_num"]) for row in ep_rows])
    first = min(row["start_num"] for _, row in selected)
    last = max(row["end_num"] for _, row in selected)
    span = max(1, last - first)
    kv_bytes = sum(row["bytes_num"] for row in kv_rows)
    ep_bytes = sum(row["bytes_num"] for row in ep_rows)
    return {
        "shared_link_id": link_id,
        "capacity_bps": capacity,
        "kv_rows": len(kv_rows),
        "ep_rows": len(ep_rows),
        "shared_link_kv_gbps": kv_bytes * 8.0e9 / max(1, kv_active) / 1e9,
        "shared_link_ep_gbps": ep_bytes * 8.0e9 / max(1, ep_active) / 1e9,
        "shared_link_total_gbps": (kv_bytes + ep_bytes) * 8.0e9 / span / 1e9,
        "kv_active_fraction": kv_active / span,
        "ep_active_fraction": ep_active / span,
        "overlap_fraction": overlap_time / kv_active if kv_active else 0.0,
        "overlap_time_ns": overlap_time,
        "peak_concurrent_kv_flows": peak_kv_flow_count,
        "peak_concurrent_ep_flows": peak_ep_flow_count,
        "peak_concurrent_total_flows": peak_total_flow_count,
        "mean_concurrent_load_ratio": (
            load_integral / (capacity * overlap_time) if capacity and overlap_time else 0.0),
        "peak_utilization": float(summary.get(link_id, {}).get("peak_utilization", 0) or 0),
        "queue_max_bytes": float(summary.get(link_id, {}).get("queue_max_bytes", 0) or 0),
        "queue_mean_bytes": float(summary.get(link_id, {}).get("queue_mean_bytes", 0) or 0),
        "ecn_marks": int(float(summary.get(link_id, {}).get("ecn_marks", 0) or 0)),
        "pfc_pause": int(float(summary.get(link_id, {}).get("pfc_pause", 0) or 0)),
        "drop_count": int(float(summary.get(link_id, {}).get("drop_count", 0) or 0)),
    }


def merged_intervals(intervals):
    """Return sorted, disjoint half-open intervals."""
    result = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


def collective_link_intervals(timeline_rows, link_id, collective_ids):
    """Select physical-link EP flow intervals for the matched focus set."""
    intervals = []
    for row in timeline_rows:
        if (not is_decode_ep(row) or
                row.get("collective_id", "") not in collective_ids or
                link_id not in row.get("directed_link_ids", "").split(";")):
            continue
        intervals.append((row["start_num"], row["end_num"]))
    return merged_intervals(intervals)


def queue_window_stats(timeseries_path, link_id, intervals):
    """Time-weighted switch queue occupancy over matched EP-link intervals."""
    if not intervals:
        return {"span_ns": 0, "mean_queue_bytes": 0.0,
                "max_queue_bytes": 0.0, "sample_count": 0}
    samples = []
    with timeseries_path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row.get("link_id") != str(link_id):
                continue
            try:
                timestamp = int(row["timestamp"])
                queue_bytes = float(row["queue_bytes"])
            except (KeyError, TypeError, ValueError):
                continue
            # Multiple callbacks can occur at one timestamp. The final row is
            # the state that persists until the next timestamp.
            if samples and samples[-1][0] == timestamp:
                samples[-1] = (timestamp, queue_bytes)
            else:
                samples.append((timestamp, queue_bytes))
    if not samples:
        return {"span_ns": 0, "mean_queue_bytes": 0.0,
                "max_queue_bytes": 0.0, "sample_count": 0}

    timestamps = [item[0] for item in samples]
    total_ns = 0
    integral = 0.0
    maximum = 0.0
    sample_count = 0
    for start, end in intervals:
        index = max(0, _rightmost_leq(timestamps, start))
        current_time = start
        current_queue = (samples[index][1]
                         if samples[index][0] <= start else 0.0)
        while index + 1 < len(samples) and samples[index + 1][0] < end:
            next_time, next_queue = samples[index + 1]
            if next_time > current_time:
                elapsed = next_time - current_time
                integral += current_queue * elapsed
                total_ns += elapsed
                maximum = max(maximum, current_queue)
            current_time = next_time
            current_queue = next_queue
            index += 1
            sample_count += 1
        if end > current_time:
            elapsed = end - current_time
            integral += current_queue * elapsed
            total_ns += elapsed
            maximum = max(maximum, current_queue)
    return {"span_ns": total_ns,
            "mean_queue_bytes": integral / total_ns if total_ns else 0.0,
            "max_queue_bytes": maximum,
            "sample_count": sample_count}


def _rightmost_leq(values, target):
    """Binary-search helper that avoids a dependency for a hot CSV path."""
    low = 0
    high = len(values)
    while low < high:
        middle = (low + high) // 2
        if values[middle] <= target:
            low = middle + 1
        else:
            high = middle
    return low - 1


def matched_queue_stats(matched_path, paths, link_id):
    """Compare queue occupancy on matched EP link windows across the control."""
    matched = [row for row in read_rows(matched_path)
               if row.get("same_payload") == "True"]
    result = {}
    for side, collective_field in (("overlap", "overlap_collective_id"),
                                   ("baseline", "baseline_collective_id")):
        collective_ids = {row.get(collective_field, "") for row in matched
                          if row.get(collective_field, "")}
        intervals = collective_link_intervals(
            read_timeline(paths[side]["timeline"]), link_id, collective_ids)
        result[side] = queue_window_stats(paths[side]["link_timeseries"],
                                          link_id, intervals)
        result[side]["interval_count"] = len(intervals)
    return result


def kv_progress(timeline_rows, kv_ids):
    events = [row for row in timeline_rows if is_p2d_kv(row) and
              row.get("request_id", "") in set(kv_ids)]
    if not events:
        return {}
    start = min(row["start_num"] for row in events)
    ordered = sorted(events, key=lambda row: row["end_num"])
    total = sum(row["bytes_num"] for row in ordered)
    result = {"kv_start_ns": start, "kv_end_ns": max(row["end_num"] for row in ordered),
              "kv_bytes": total, "kv_flow_count": len(ordered)}
    seen = 0
    index = 0
    for percent in (25, 50, 75, 90, 100):
        threshold = total * percent / 100.0
        while index < len(ordered) and seen < threshold:
            seen += ordered[index]["bytes_num"]
            end = ordered[index]["end_num"]
            index += 1
        result[f"KV_{percent}_ns"] = end - start
    result["kv_completion_ns"] = result["kv_end_ns"] - start
    return result


def matched_cct_stats(path):
    rows = [row for row in read_rows(path) if row.get("same_payload") == "True"]
    baseline = [float(row["baseline_cct_ns"]) for row in rows if row.get("baseline_cct_ns")]
    overlap = [float(row["overlap_cct_ns"]) for row in rows if row.get("overlap_cct_ns")]
    bytes_per_collective = [float(row["overlap_bytes"]) for row in rows
                            if row.get("overlap_bytes")]
    return {
        "matched_collectives": len(rows),
        "ep_p50_ns": percentile(overlap, .50),
        "ep_p95_ns": percentile(overlap, .95),
        "ep_p99_ns": percentile(overlap, .99),
        "baseline_ep_p50_ns": percentile(baseline, .50),
        "baseline_ep_p95_ns": percentile(baseline, .95),
        "baseline_ep_p99_ns": percentile(baseline, .99),
        "ep_p50_slowdown": (percentile(overlap, .50) / percentile(baseline, .50)
                            if baseline and percentile(baseline, .50) else None),
        "ep_p95_slowdown": (percentile(overlap, .95) / percentile(baseline, .95)
                            if baseline and percentile(baseline, .95) else None),
        "ep_p99_slowdown": (percentile(overlap, .99) / percentile(baseline, .99)
                            if baseline and percentile(baseline, .99) else None),
        "ep_bytes_per_collective": (sum(bytes_per_collective) / len(bytes_per_collective)
                                    if bytes_per_collective else None),
    }


def serving_stats(path, request_ids):
    requested = {str(value) for value in request_ids}
    rows = [row for row in read_rows(path) if row.get("request id", "") in requested]
    result = {}
    for field, label in (("TTFT", "ttft_ns"), ("TPOT", "tpot_ns"),
                         ("ITL", "itl_raw"), ("latency", "latency_ns")):
        values = []
        for row in rows:
            try:
                values.append(float(row[field]))
            except (KeyError, TypeError, ValueError):
                continue
        if values:
            result[label] = sum(values) / len(values)
    return result


def ratio(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def environment():
    env = os.environ.copy()
    source_chakra = ROOT / "astra-sim" / "extern" / "graph_frontend"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(source_chakra), env.get("PYTHONPATH", "")])
    env.setdefault("MPLCONFIGDIR", "/tmp/llmservingsim-mpl")
    return env


def run_native(run_id, workload, output, cluster_config):
    command = [
        sys.executable, str(EXP / "run_experiments.py"),
        "--scenario", "mixed", "--workload", str(workload),
        "--network-backend", "ns3", "--run-id", run_id,
        "--output", str(output),
    ]
    if cluster_config:
        command.extend(["--cluster-config", str(cluster_config)])
    subprocess.run(command, cwd=ROOT, env=environment(), check=True)


def run_summary(run_id, output):
    run_root = ROOT / "astra-sim" / "inputs" / "runs" / run_id / "ns3" / "output"
    timeline = output.with_suffix(".timeline.csv")
    overlap = output.with_suffix(".directed_link_overlap.csv")
    summary = output.with_suffix(".summary.json")
    command = [
        sys.executable, str(EXP / "analyze_results.py"), str(output),
        "--timeline", str(timeline), "--link-summary", str(run_root / "link_summary.csv"),
        "--directed-link-overlap", str(overlap), "--output", str(summary),
    ]
    subprocess.run(command, cwd=ROOT, env=environment(), check=True)
    return {"timeline": timeline, "overlap": overlap, "summary": summary,
            "link_summary": run_root / "link_summary.csv",
            "link_timeseries": run_root / "link_timeseries.csv"}


def existing_summary(run_id, output):
    """Return previously generated native artifacts after a completeness check.

    Reusing a matched no-overlap baseline is valid only when its request
    contents and topology remain identical.  This helper deliberately does not
    rerun or overwrite an existing baseline; `analyze_pair` still validates
    matched payloads, participants, flow counts, and focus-window isolation.
    """
    run_root = ROOT / "astra-sim" / "inputs" / "runs" / run_id / "ns3" / "output"
    paths = {
        "timeline": output.with_suffix(".timeline.csv"),
        "overlap": output.with_suffix(".directed_link_overlap.csv"),
        "summary": output.with_suffix(".summary.json"),
        "link_summary": run_root / "link_summary.csv",
        "link_timeseries": run_root / "link_timeseries.csv",
    }
    # `summary` is a derived report rather than a native artifact. A recovery
    # path may legitimately reuse a completed run that failed after timeline
    # generation but before its standalone summary command.
    required = [output, paths["timeline"], paths["overlap"],
                paths["link_summary"], paths["link_timeseries"]]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("cannot reuse incomplete baseline artifacts: %s" %
                                ", ".join(missing))
    paths["output"] = output
    return paths


def check_reused_baseline_workload(run_id, spec):
    """Verify native request contents before reusing a prior baseline run."""
    prefix = "auto-"
    suffix = "-baseline"
    if not run_id.startswith(prefix) or not run_id.endswith(suffix):
        raise ValueError("reused baseline run id must use the auto-<label>-baseline form")
    label = run_id[len(prefix):-len(suffix)]
    workload = WORKLOADS / (label + "_baseline.jsonl")
    if not workload.exists():
        raise FileNotFoundError("cannot validate reused baseline workload: %s" % workload)
    rows = [json.loads(line) for line in workload.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    expected = spec["a_count"] + spec["b_count"]
    if len(rows) != expected:
        raise ValueError("reused baseline has %s requests, expected %s" % (len(rows), expected))
    for index in range(spec["a_count"]):
        row = rows[index]
        if (row.get("input_toks"), row.get("output_toks"), row.get("arrival_time_ns")) != (
                spec["a_input"], spec["a_output"], 0):
            raise ValueError("reused baseline Decode request %s differs from current spec" % index)
    for index in range(spec["b_count"]):
        row = rows[spec["a_count"] + index]
        expected_arrival = spec["baseline_arrival_ns"] + index * spec["b_spacing_ns"]
        if (row.get("input_toks"), row.get("output_toks"), row.get("arrival_time_ns")) != (
                spec["b_input"], spec["b_output"], expected_arrival):
            raise ValueError("reused baseline KV request %s differs from current spec" % index)


def check_reused_overlap_workload(run_id, spec):
    """Verify native request contents before reusing a prior overlap run."""
    prefix = "auto-"
    suffix = "-overlap"
    if not run_id.startswith(prefix) or not run_id.endswith(suffix):
        raise ValueError("reused overlap run id must use the auto-<label>-overlap form")
    label = run_id[len(prefix):-len(suffix)]
    workload = WORKLOADS / (label + "_overlap.jsonl")
    if not workload.exists():
        raise FileNotFoundError("cannot validate reused overlap workload: %s" % workload)
    rows = [json.loads(line) for line in workload.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    expected = spec["a_count"] + spec["b_count"]
    if len(rows) != expected:
        raise ValueError("reused overlap has %s requests, expected %s" % (len(rows), expected))
    for index in range(spec["a_count"]):
        row = rows[index]
        if (row.get("input_toks"), row.get("output_toks"), row.get("arrival_time_ns")) != (
                spec["a_input"], spec["a_output"], 0):
            raise ValueError("reused overlap Decode request %s differs from current spec" % index)
    for index in range(spec["b_count"]):
        row = rows[spec["a_count"] + index]
        expected_arrival = spec["overlap_arrival_ns"] + index * spec["b_spacing_ns"]
        if (row.get("input_toks"), row.get("output_toks"), row.get("arrival_time_ns")) != (
                spec["b_input"], spec["b_output"], expected_arrival):
            raise ValueError("reused overlap KV request %s differs from current spec" % index)


def append_log(iteration, hypothesis, changed, runs, validity, result, next_step,
               reason):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_PATH.exists():
        LOG_PATH.write_text("# Autonomous Native Contention Search Log\n", encoding="utf-8")
    with LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write("\n## Iteration %s\n\n" % iteration)
        stream.write("- hypothesis: %s\n" % hypothesis)
        stream.write("- changed parameters: `%s`\n" % json.dumps(changed, sort_keys=True))
        stream.write("- reason: %s\n" % reason)
        stream.write("- runs: `%s`\n" % json.dumps(runs, sort_keys=True))
        stream.write("- validity: `%s`\n" % json.dumps(validity, sort_keys=True))
        stream.write("- result: `%s`\n" % json.dumps(result, sort_keys=True))
        stream.write("- next decision: %s\n" % next_step)


def append_negative(record):
    fields = ["iteration", "label", "reason", "parameters", "timestamp_utc"]
    exists = NEGATIVE_PATH.exists()
    with NEGATIVE_PATH.open("a", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow({"iteration": record["iteration"], "label": record["label"],
                         "reason": record["reason"],
                         "parameters": json.dumps(record["parameters"], sort_keys=True),
                         "timestamp_utc": datetime.now(timezone.utc).isoformat()})


def repair_table():
    """Migrate a prior table header without losing already measured records."""
    if not TABLE_PATH.exists():
        return False
    with TABLE_PATH.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        old_fields = reader.fieldnames or []
        rows = list(reader)
    if old_fields == TABLE_FIELDS and not any(row.get(None) for row in rows):
        return False
    had_reuse_column = "baseline_reused" in old_fields
    normalized = []
    for row in rows:
        extra = row.pop(None, [])
        if not had_reuse_column and extra:
            # The first writer after adding baseline_reused used the new field
            # order against the old header. Recover the shifted values exactly.
            reuse_value = row.get("run_overlap", "")
            overlap_value = row.get("run_baseline", "")
            row["baseline_reused"] = reuse_value
            row["run_overlap"] = overlap_value
            row["run_baseline"] = extra[0]
        row.setdefault("baseline_reused", "False")
        normalized.append({field: row.get(field, "") for field in TABLE_FIELDS})
    _rewrite_table(normalized)
    return True


def _rewrite_table(rows):
    """Atomically write normalized result-table rows."""
    temporary = TABLE_PATH.with_suffix(".repair.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=TABLE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(TABLE_PATH)


def write_table(record):
    repair_table()
    normalized_record = {field: record.get(field, "") for field in TABLE_FIELDS}
    if not TABLE_PATH.exists():
        _rewrite_table([normalized_record])
        return
    with TABLE_PATH.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    replaced = False
    for index, existing in enumerate(rows):
        if existing.get("workload") == normalized_record["workload"]:
            rows[index] = normalized_record
            replaced = True
            break
    if not replaced:
        rows.append(normalized_record)
    _rewrite_table(rows)


def analyze_pair(label, spec, paths, baseline_reused=False,
                 telemetry_version="phy_tx_v2_capped_peak",
                 physical_peak_available=True):
    role_counts = config_role_counts(spec.get("cluster_config"))
    target_ids = [str(index) for index in range(spec["a_count"])]
    kv_ids = [str(spec["a_count"] + index) for index in range(spec["b_count"])]
    matched_path = RESULTS / (label + ".matched_collectives.csv")
    comparison = compare(
        paths["baseline"]["timeline"], paths["overlap"]["timeline"], matched_path,
        no_overlap_name="FOCUS_NO_OVERLAP", overlap_name="FOCUS_OVERLAP",
        overlap_links=paths["overlap"]["overlap"],
        baseline_links=paths["baseline"]["overlap"],
        target_request_ids=target_ids, kv_request_ids=kv_ids)
    timeline = read_timeline(paths["overlap"]["timeline"])
    shared_link, _ = choose_shared_link(paths["overlap"]["overlap"], timeline, kv_ids)
    pressure = (link_pressure(timeline, shared_link, target_ids, kv_ids,
                              paths["overlap"]["link_summary"])
                if shared_link is not None else {})
    focus_queue = (matched_queue_stats(matched_path, paths, shared_link)
                   if shared_link is not None else {})
    progress_overlap = kv_progress(timeline, kv_ids)
    progress_baseline = kv_progress(read_timeline(paths["baseline"]["timeline"]), kv_ids)
    cct = matched_cct_stats(matched_path)
    serving_overlap_a = serving_stats(paths["overlap"]["output"], target_ids)
    serving_baseline_a = serving_stats(paths["baseline"]["output"], target_ids)
    serving_overlap_b = serving_stats(paths["overlap"]["output"], kv_ids)
    serving_baseline_b = serving_stats(paths["baseline"]["output"], kv_ids)
    exact = comparison["exact_overlap_focus"]
    valid = bool(comparison["collectives"]["all_same_payload"] and
                 exact["baseline_focus_isolated"] and
                 exact["overlap_exact_overlap_rows"] > 0 and
                 comparison["kv_request_b"]["bytes_equal"] and
                 comparison["kv_request_b"]["flow_count_equal"])
    record = {
        "workload": label,
        "input_distribution": "A:%sx%s,B:%sx%s" % (
            spec["a_count"], spec["a_input"], spec["b_count"], spec["b_input"]),
        "output_distribution": "A:%s,B:%s" % (spec["a_output"], spec["b_output"]),
        "arrival_rate": "overlap=%sns,baseline=%sns,spacing=%sns" % (
            spec["overlap_arrival_ns"], spec["baseline_arrival_ns"], spec["b_spacing_ns"]),
        "active_decode": spec["a_count"],
        "prefill_instances": role_counts["prefill_instances"],
        "EP_degree": role_counts["ep_degree"],
        "KV_bytes": progress_overlap.get("kv_bytes"),
        "EP_bytes_per_collective": cct.get("ep_bytes_per_collective"),
        "shared_link_KV_Gbps": pressure.get("shared_link_kv_gbps"),
        "shared_link_EP_Gbps": pressure.get("shared_link_ep_gbps"),
        "peak_utilization": (pressure.get("peak_utilization")
                             if physical_peak_available else None),
        "queue_max": focus_queue.get("overlap", {}).get(
            "max_queue_bytes", pressure.get("queue_max_bytes")),
        "overlap_fraction": pressure.get("overlap_fraction"),
        "EP_P50": cct.get("ep_p50_ns"), "EP_P95": cct.get("ep_p95_ns"),
        "EP_P99": cct.get("ep_p99_ns"), "EP_P99_slowdown": cct.get("ep_p99_slowdown"),
        "KV_completion": progress_overlap.get("kv_completion_ns"),
        "KV_slowdown": ratio(progress_overlap.get("kv_completion_ns"),
                              progress_baseline.get("kv_completion_ns")),
        "TTFT": serving_overlap_b.get("ttft_ns"),
        "TTFT_slowdown": ratio(serving_overlap_b.get("ttft_ns"),
                               serving_baseline_b.get("ttft_ns")),
        "TPOT": serving_overlap_a.get("tpot_ns"),
        "TPOT_slowdown": ratio(serving_overlap_a.get("tpot_ns"),
                               serving_baseline_a.get("tpot_ns")),
        "validity": "VALID" if valid else "INVALID_OR_UNMATCHED",
        "seed": 1,
        "mean_concurrent_load_ratio": pressure.get("mean_concurrent_load_ratio"),
        "shared_link_id": shared_link,
        "queue_mean": focus_queue.get("overlap", {}).get(
            "mean_queue_bytes", pressure.get("queue_mean_bytes")),
        "ECN": pressure.get("ecn_marks"), "PFC": pressure.get("pfc_pause"),
        "drop_count": pressure.get("drop_count"),
        "baseline_reused": baseline_reused,
        "run_overlap": str(paths["overlap"]["output"]),
        "run_baseline": str(paths["baseline"]["output"]),
        "telemetry_version": telemetry_version,
        "shared_link_selection": "max_exact_overlap_then_lowest_link_id",
        "focus_queue_mean_overlap": focus_queue.get("overlap", {}).get(
            "mean_queue_bytes"),
        "focus_queue_max_overlap": focus_queue.get("overlap", {}).get(
            "max_queue_bytes"),
        "focus_queue_mean_baseline": focus_queue.get("baseline", {}).get(
            "mean_queue_bytes"),
        "focus_queue_max_baseline": focus_queue.get("baseline", {}).get(
            "max_queue_bytes"),
        "focus_queue_span_overlap_ns": focus_queue.get("overlap", {}).get("span_ns"),
        "focus_queue_span_baseline_ns": focus_queue.get("baseline", {}).get("span_ns"),
        "cluster_config": spec.get("cluster_config"),
        "matched_summary": comparison,
        "kv_progress_overlap": progress_overlap,
        "kv_progress_baseline": progress_baseline,
        "serving_overlap_a": serving_overlap_a,
        "serving_baseline_a": serving_baseline_a,
        "serving_overlap_b": serving_overlap_b,
        "serving_baseline_b": serving_baseline_b,
        "focus_queue": focus_queue,
    }
    write_table(record)
    return record


def run_point(label, spec, iteration, reuse_baseline_run=None,
              reuse_overlap_run=None):
    """Run one bounded, native, arrival-offset matched pair."""
    WORKLOADS.mkdir(parents=True, exist_ok=True)
    overlap_workload = WORKLOADS / (label + "_overlap.jsonl")
    baseline_workload = WORKLOADS / (label + "_baseline.jsonl")
    common = dict(a_input=spec["a_input"], a_output=spec["a_output"],
                  b_input=spec["b_input"], b_output=spec["b_output"],
                  a_count=spec["a_count"], b_count=spec["b_count"],
                  b_spacing_ns=spec["b_spacing_ns"])
    if reuse_overlap_run is None:
        write_matched_workload(overlap_workload, spec["overlap_arrival_ns"], **common)
    if reuse_baseline_run is None:
        write_matched_workload(baseline_workload, spec["baseline_arrival_ns"], **common)
    overlap_id = reuse_overlap_run or "auto-%s-overlap" % label
    baseline_id = reuse_baseline_run or "auto-%s-baseline" % label
    overlap_output = RESULTS / (overlap_id + ".csv")
    baseline_output = RESULTS / (baseline_id + ".csv")
    runs = {"overlap": overlap_id, "baseline": baseline_id,
            "baseline_reused": bool(reuse_baseline_run),
            "overlap_reused": bool(reuse_overlap_run)}
    try:
        if reuse_overlap_run is None:
            run_native(overlap_id, overlap_workload, overlap_output,
                       spec.get("cluster_config"))
            overlap_paths = run_summary(overlap_id, overlap_output)
        else:
            check_reused_overlap_workload(overlap_id, spec)
            overlap_paths = existing_summary(overlap_id, overlap_output)
        if reuse_baseline_run is None:
            run_native(baseline_id, baseline_workload, baseline_output,
                       spec.get("cluster_config"))
            baseline_paths = run_summary(baseline_id, baseline_output)
        else:
            check_reused_baseline_workload(baseline_id, spec)
            baseline_paths = existing_summary(baseline_id, baseline_output)
        paths = {
            "overlap": overlap_paths,
            "baseline": baseline_paths,
        }
        paths["overlap"]["output"] = overlap_output
        paths["baseline"]["output"] = baseline_output
        record = analyze_pair(label, spec, paths,
                              baseline_reused=bool(reuse_baseline_run))
    except subprocess.CalledProcessError as exc:
        reason = "native_command_failed_returncode_%s" % exc.returncode
        append_negative({"iteration": iteration, "label": label,
                         "reason": reason, "parameters": spec})
        append_log(iteration, "native matched pair", spec, runs,
                   {"valid": False, "reason": reason}, {},
                   "diagnose simulator/runtime failure before expanding search",
                   "The native simulator command did not complete.")
        raise
    validity = {"valid": record["validity"] == "VALID",
                "matched": record["matched_summary"]["collectives"]["all_same_payload"],
                "baseline_focus_isolated": record["matched_summary"]["exact_overlap_focus"]["baseline_focus_isolated"],
                "overlap_rows": record["matched_summary"]["exact_overlap_focus"]["overlap_exact_overlap_rows"]}
    if not validity["valid"]:
        append_negative({"iteration": iteration, "label": label,
                         "reason": "invalid_matched_or_exact_overlap_control",
                         "parameters": spec})
    next_step = decide_next(record, spec)
    reason = (
        "A complete native artifact was reused only after exact request-content "
        "validation; the counterpart run was executed without overwriting it."
        if reuse_baseline_run or reuse_overlap_run else
        "This is a new native workload pair, so both matched control runs were required."
    )
    append_log(iteration,
               "Native request-driven KV pressure changes exact-link EP CCT.",
               {**spec, "reuse_baseline_run": reuse_baseline_run,
                "reuse_overlap_run": reuse_overlap_run}, runs, validity,
               {key: record.get(key) for key in (
                   "EP_P99_slowdown", "KV_slowdown", "TPOT_slowdown",
                   "shared_link_id", "mean_concurrent_load_ratio", "queue_max",
                   "overlap_fraction", "focus_queue", "validity")}, next_step, reason)
    return record


def decide_next(record, spec):
    """Fixed, predeclared decision tree; it does not tune a significance threshold."""
    if record["validity"] != "VALID":
        return "Repair matching/overlap validity before interpreting performance."
    if not record.get("shared_link_id"):
        return "Re-audit placement/path: no shared directed link was measured."
    if (record.get("EP_P99_slowdown") or 1.0) < 1.15:
        return "Move to the next predeclared native pressure axis: larger B prompt or B burst."
    return ("Repeat this point with a predeclared arrival-phase variant, then "
            "construct low/medium/high B-pressure points at the same Decode concurrency.")


def frozen_onset_record():
    """Audit, do not overwrite, the pre-existing 512-token onset point."""
    return {
        "label": "frozen_matched32_onset",
        "summary": RESULTS / "matched32-focused_collectives.summary.json",
        "overlap": RESULTS / "matched32-overlap.directed_link_overlap.csv",
        "baseline": RESULTS / "matched32-candidate150.directed_link_overlap.csv",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="kv2048_a1")
    parser.add_argument("--iteration", type=int, default=1)
    parser.add_argument("--a-input", type=int, default=64)
    parser.add_argument("--a-output", type=int, default=64)
    parser.add_argument("--a-count", type=int, default=1)
    parser.add_argument("--b-input", type=int, default=2048)
    parser.add_argument("--b-output", type=int, default=1)
    parser.add_argument("--b-count", type=int, default=1)
    parser.add_argument("--b-spacing-ns", type=int, default=0)
    parser.add_argument("--overlap-arrival-ns", type=int, default=10000000)
    parser.add_argument("--baseline-arrival-ns", type=int, default=200000000)
    parser.add_argument("--cluster-config",
                        default="experiments/pd_kv_ep/configs/small_pd_moe_ep.json",
                        help="native cluster config; request bytes remain model-derived")
    parser.add_argument("--reuse-baseline-run",
                        help="reuse a complete auto-<label>-baseline artifact after "
                             "verifying identical native request contents")
    parser.add_argument("--reuse-overlap-run",
                        help="reuse a complete auto-<label>-overlap artifact after "
                             "verifying identical native request contents")
    parser.add_argument("--repair-table", action="store_true",
                        help="repair a legacy motivation-table header and exit")
    parser.add_argument("--audit-frozen", action="store_true")
    args = parser.parse_args()
    if args.repair_table:
        print(json.dumps({"repaired": repair_table(), "table": str(TABLE_PATH)}))
        return
    if args.audit_frozen:
        onset = frozen_onset_record()
        append_log(0, "Audit the frozen onset point before new search.", {},
                   {key: str(value) for key, value in onset.items()},
                   {"frozen": True}, {},
                   "Run a larger native B prompt with a longer A decode window.",
                   "The frozen onset is retained as an audit reference and is never rerun or overwritten.")
        print(json.dumps({key: str(value) for key, value in onset.items()}, indent=2))
        return
    spec = {
        "a_input": args.a_input, "a_output": args.a_output,
        "a_count": args.a_count, "b_input": args.b_input,
        "b_output": args.b_output, "b_count": args.b_count,
        "b_spacing_ns": args.b_spacing_ns,
        "overlap_arrival_ns": args.overlap_arrival_ns,
        "baseline_arrival_ns": args.baseline_arrival_ns,
        "cluster_config": args.cluster_config,
    }
    record = run_point(args.label, spec, args.iteration,
                       reuse_baseline_run=args.reuse_baseline_run,
                       reuse_overlap_run=args.reuse_overlap_run)
    print(json.dumps(record, indent=2, default=str))


if __name__ == "__main__":
    main()
