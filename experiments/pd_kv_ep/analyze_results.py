#!/usr/bin/env python3
"""Summarize LLMServingSim serving metrics from an output CSV."""

import argparse
import csv
import json
import math
from pathlib import Path

from semantic_events import is_decode_ep, is_p2d_kv


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    index = (len(values) - 1) * fraction
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (index - lower)


def read_metrics(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _percentile(values, fraction):
    return percentile([float(value) for value in values], fraction)


def _json_numbers(value):
    """Parse serialized per-token intervals without rejecting old CSVs."""
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [float(item) for item in parsed
            if isinstance(item, (int, float)) and math.isfinite(float(item))]


def read_timeline(path):
    with path.open(newline="", encoding="utf-8") as stream:
        rows = []
        for row in csv.DictReader(stream):
            try:
                row["start_num"] = int(row["start"])
                row["end_num"] = int(row["end"])
                row["bytes_num"] = int(row["bytes"])
            except (KeyError, TypeError, ValueError):
                continue
            if row["end_num"] >= row["start_num"]:
                rows.append(row)
        return rows


def read_link_summary(path):
    if path is None or not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as stream:
        return {row["link_id"]: row for row in csv.DictReader(stream)}


def write_directed_link_overlap(timeline_path, output_path, link_summary_path=None):
    """Compute exact interval overlap on shared directed physical links.

    This deliberately does not use the P2D/EP envelope. Every row is a pair
    of completed communication events whose explicit directed path contains
    the same link id.
    """
    rows = read_timeline(timeline_path)
    link_summary = read_link_summary(link_summary_path)
    by_link = {}
    for row in rows:
        links = [item for item in row.get("directed_link_ids", "").split(";")
                 if item and item != "-1"]
        for link_id in set(links):
            by_link.setdefault(link_id, {"kv": [], "ep": []})
            if is_p2d_kv(row):
                by_link[link_id]["kv"].append(row)
            elif is_decode_ep(row):
                by_link[link_id]["ep"].append(row)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["link_id", "kv_event_id", "ep_event_id", "kv_collective_id",
              "ep_collective_id", "kv_start", "kv_end", "ep_start", "ep_end",
              "overlap_ns", "kv_interval_ns", "ep_interval_ns",
              "kv_overlap_fraction", "ep_overlap_fraction", "kv_bytes",
              "ep_bytes", "capacity_bps", "pressure_ratio", "overlap_class"]
    count = 0
    shared_overlap = 0
    with output_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for link_id, groups in sorted(by_link.items()):
            capacity = float(link_summary.get(link_id, {}).get("capacity_bps", 0) or 0)
            for kv in groups["kv"]:
                for ep in groups["ep"]:
                    overlap = min(kv["end_num"], ep["end_num"]) - max(
                        kv["start_num"], ep["start_num"])
                    if overlap <= 0:
                        continue
                    kv_interval = kv["end_num"] - kv["start_num"]
                    ep_interval = ep["end_num"] - ep["start_num"]
                    pressure = ((kv["bytes_num"] + ep["bytes_num"]) * 8.0e9 /
                                (capacity * overlap) if capacity > 0 else None)
                    writer.writerow({
                        "link_id": link_id,
                        "kv_event_id": kv.get("event_id", ""),
                        "ep_event_id": ep.get("event_id", ""),
                        "kv_collective_id": kv.get("collective_id", ""),
                        "ep_collective_id": ep.get("collective_id", ""),
                        "kv_start": kv["start_num"], "kv_end": kv["end_num"],
                        "ep_start": ep["start_num"], "ep_end": ep["end_num"],
                        "overlap_ns": overlap,
                        "kv_interval_ns": kv_interval,
                        "ep_interval_ns": ep_interval,
                        "kv_overlap_fraction": overlap / kv_interval if kv_interval else 0,
                        "ep_overlap_fraction": overlap / ep_interval if ep_interval else 0,
                        "kv_bytes": kv["bytes_num"], "ep_bytes": ep["bytes_num"],
                        "capacity_bps": int(capacity) if capacity else "",
                        "pressure_ratio": pressure if pressure is not None else "",
                        "overlap_class": "SHARED_DIRECTED_LINK_OVERLAP",
                    })
                    count += 1
                    shared_overlap = max(shared_overlap, overlap)
    return {"pair_count": count, "max_overlap_ns": shared_overlap,
            "output": str(output_path)}


def communication_summary(path):
    rows = read_timeline(path)
    p2d = [row for row in rows if is_p2d_kv(row)]
    ep = [row for row in rows if is_decode_ep(row)]
    collectives = {}
    for row in ep:
        key = row.get("collective_id") or (
            row["event_type"], row["start_num"])
        value = collectives.setdefault(key, {"start": row["start_num"],
                                             "end": row["end_num"],
                                             "event_type": row["event_type"]})
        value["start"] = min(value["start"], row["start_num"])
        value["end"] = max(value["end"], row["end_num"])
    ccts = [value["end"] - value["start"] for value in collectives.values()]
    total_start = min((row["start_num"] for row in rows), default=0)
    total_end = max((row["end_num"] for row in rows), default=0)
    total_bytes = sum(row["bytes_num"] for row in rows)
    duration = total_end - total_start
    overlaps = []
    for kv in p2d:
        for collective in collectives.values():
            overlap = min(kv["end_num"], collective["end"]) - max(
                kv["start_num"], collective["start"])
            if overlap > 0:
                overlaps.append(overlap)
    p2d_window = (
        (min((row["start_num"] for row in p2d), default=0),
         max((row["end_num"] for row in p2d), default=0))
        if p2d else None
    )
    ep_window = (
        (min((row["start_num"] for row in ep), default=0),
         max((row["end_num"] for row in ep), default=0))
        if ep else None
    )
    envelope_overlap = 0
    if p2d_window and ep_window:
        envelope_overlap = max(0, min(p2d_window[1], ep_window[1]) -
                               max(p2d_window[0], ep_window[0]))
    summary = {
        "source": str(path),
        "timed_event_count": len(rows),
        "p2d_flow_count": len(p2d),
        "p2d_bytes": sum(row["bytes_num"] for row in p2d),
        "p2d_transfer_time_ns": {
            "mean": (sum(row["end_num"] - row["start_num"] for row in p2d) /
                     len(p2d) if p2d else None),
            "p50": _percentile([row["end_num"] - row["start_num"] for row in p2d], .5),
            "p95": _percentile([row["end_num"] - row["start_num"] for row in p2d], .95),
            "p99": _percentile([row["end_num"] - row["start_num"] for row in p2d], .99),
        },
        "ep_collective_count": len(collectives),
        "ep_cct_ns": {
            "mean": sum(ccts) / len(ccts) if ccts else None,
            "p50": _percentile(ccts, .5),
            "p95": _percentile(ccts, .95),
            "p99": _percentile(ccts, .99),
        },
        "aggregate_observed_gbps": (total_bytes * 8 * 1e9 / duration / 1e9
                                     if duration > 0 else None),
        "p2d_ep_overlap_count": len(overlaps),
        "max_p2d_ep_overlap_ns": max(overlaps, default=0),
        "p2d_ep_envelope_overlap_ns": envelope_overlap,
        "p2d_window_ns": p2d_window,
        "ep_window_ns": ep_window,
        "request_id_status": (
            "direct request_id on P2D events; collective active_request_ids "
            "joined by exact (system, collective_id) issue metadata when available"
        ),
    }
    link_rows = [row for row in rows if row.get("directed_link_ids")]
    summary["shared_directed_link_flow_count"] = len(link_rows)
    summary["serving_overlap_definition"] = "P2D/EP event-envelope overlap is diagnostic only"
    summary["shared_link_overlap_definition"] = "exact completed-flow interval overlap on explicit directed_link_ids"
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--timeline", type=Path, default=None)
    parser.add_argument("--link-summary", type=Path, default=None)
    parser.add_argument("--directed-link-overlap", type=Path, default=None)
    args = parser.parse_args()
    rows = read_metrics(args.csv)
    summary = {
        "source": str(args.csv),
        "request_count": len(rows),
        "synthetic_byte_override": False,
        "metrics": {},
    }
    for field in ("TTFT", "TPOT", "TBT", "ITL", "latency", "queuing_delay"):
        values = []
        for row in rows:
            if field == "TBT":
                values.extend(value for value in _json_numbers(row.get(field, ""))
                              if value >= 0)
                continue
            metric_field = field
            # In a real P/D run, user-visible TTFT is the Decode first-token
            # timestamp.  ``TTFT`` remains the legacy Prefill-side field for
            # backward compatibility, while ``decode_TTFT`` is canonical.
            if field == "TTFT":
                try:
                    decode_ttft = float(row.get("decode_TTFT", ""))
                except (TypeError, ValueError):
                    decode_ttft = -1
                if decode_ttft >= 0:
                    values.append(decode_ttft)
                    continue
            try:
                value = float(row.get(metric_field, ""))
            except (TypeError, ValueError):
                continue
            if value >= 0:
                values.append(value)
        if values:
            summary["metrics"][field] = {
                "mean": sum(values) / len(values),
                "p50": percentile(values, 0.50),
                "p95": percentile(values, 0.95),
                "p99": percentile(values, 0.99),
            }
    if args.timeline is not None:
        summary["communication"] = communication_summary(args.timeline)
        overlap_path = args.directed_link_overlap or args.timeline.with_name(
            "directed_link_overlap.csv")
        summary["communication"]["directed_link_overlap"] = \
            write_directed_link_overlap(args.timeline, overlap_path,
                                        args.link_summary)
    output = args.output or args.csv.with_suffix(".summary.json")
    output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
