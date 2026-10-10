#!/usr/bin/env python3
"""Analyze native ns-3 model-derived KV/EP replay artifacts.

The analyzer uses completed backend communication intervals.  EP latency is
reported at collective level: last completion minus collective start.  It also
checks exact overlap of completed KV and EP flow intervals on directed links,
so an unchanged CCT is not confused with an absent shared path.
"""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


EVENT_NAMES = {1: "P2D_KV", 2: "EP_DISPATCH", 3: "EP_COMBINE"}


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _manifest(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _config_value(scenario_dir, key):
    path = scenario_dir / "replay.conf"
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] == key:
            return fields[1]
    return None


def read_completed(scenario_dir):
    path = scenario_dir / "comm_events.csv"
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    starts = {row["event_id"]: row for row in rows
              if row.get("phase") == "START" and row.get("event_id") not in ("", "-1")}
    ends = {row["event_id"]: row for row in rows
            if row.get("phase") == "END" and row.get("event_id") not in ("", "-1")}
    completed = []
    for event_id, start in starts.items():
        end = ends.get(event_id)
        if end is None or not end.get("network_end_ns"):
            continue
        try:
            event_type = int(start["event_type"])
            serving_role = start.get("serving_role", "")
            event_name = EVENT_NAMES.get(event_type, f"UNKNOWN_{event_type}")
            if event_name == "P2D_KV" and serving_role == "remote_kv":
                event_name = "REMOTE_KV_FETCH"
            completed.append({
                "event_id": event_id,
                "request_id": start.get("request_id", ""),
                "collective_id": start.get("collective_id", ""),
                "event_type": event_name,
                "layer_id": start.get("layer_id", ""),
                "active_request_ids": start.get("active_request_ids", ""),
                "serving_role": start.get("serving_role", ""),
                "src": start.get("src", ""),
                "dst": start.get("dst", ""),
                "bytes": int(start["bytes"]),
                "start": int(start["network_start_ns"]),
                "end": int(end["network_end_ns"]),
                "path": start.get("path", ""),
                "directed_link_ids": start.get("directed_link_ids", ""),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return rows, completed


def _stats(values):
    values = [float(value) for value in values]
    return {
        "count": len(values),
        "mean": sum(values) / len(values) if values else None,
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": max(values) if values else None,
    }


def _group_intervals(rows, kind):
    groups = {}
    for row in rows:
        if kind == "kv" and row["event_type"] not in {"P2D_KV", "REMOTE_KV_FETCH"}:
            continue
        if kind == "ep" and row["event_type"] not in {"EP_DISPATCH", "EP_COMBINE"}:
            continue
        key = row["request_id"] if kind == "kv" else row["collective_id"]
        value = groups.setdefault(key, {"start": row["start"], "end": row["end"], "bytes": 0})
        value["start"] = min(value["start"], row["start"])
        value["end"] = max(value["end"], row["end"])
        value["bytes"] += row["bytes"]
    return groups


def _link_overlap(rows, output_dir):
    by_link = defaultdict(lambda: {"kv": [], "ep": []})
    for row in rows:
        kind = ("kv" if row["event_type"] in {"P2D_KV", "REMOTE_KV_FETCH"}
                else "ep" if row["event_type"].startswith("EP_") else "")
        if not kind:
            continue
        for link_id in set(item for item in row["directed_link_ids"].split(";") if item):
            by_link[link_id][kind].append(row)
    fields = ["link_id", "kv_event_id", "ep_event_id", "kv_collective_id",
              "ep_collective_id", "kv_start", "kv_end", "ep_start", "ep_end",
              "overlap_ns", "kv_bytes", "ep_bytes", "pressure_ratio"]
    summary = defaultdict(lambda: {"pairs": 0, "overlap_ns": 0, "kv_bytes": 0,
                                   "ep_bytes": 0, "max_pressure_ratio": 0.0})
    overlap_path = output_dir / "directed_link_overlap.csv"
    with overlap_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for link_id, groups in sorted(by_link.items()):
            for kv in groups["kv"]:
                for ep in groups["ep"]:
                    overlap = min(kv["end"], ep["end"]) - max(kv["start"], ep["start"])
                    if overlap <= 0:
                        continue
                    pressure = (kv["bytes"] + ep["bytes"]) * 8.0e9 / (200e9 * overlap)
                    writer.writerow({
                        "link_id": link_id,
                        "kv_event_id": kv["event_id"], "ep_event_id": ep["event_id"],
                        "kv_collective_id": kv["collective_id"],
                        "ep_collective_id": ep["collective_id"],
                        "kv_start": kv["start"], "kv_end": kv["end"],
                        "ep_start": ep["start"], "ep_end": ep["end"],
                        "overlap_ns": overlap, "kv_bytes": kv["bytes"],
                        "ep_bytes": ep["bytes"], "pressure_ratio": pressure,
                    })
                    item = summary[link_id]
                    item["pairs"] += 1
                    item["overlap_ns"] += overlap
                    item["kv_bytes"] += kv["bytes"]
                    item["ep_bytes"] += ep["bytes"]
                    item["max_pressure_ratio"] = max(item["max_pressure_ratio"], pressure)
    summary_path = output_dir / "directed_link_overlap_summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["link_id"] + list(next(iter(summary.values()), {"pairs": 0}).keys()), lineterminator="\n")
        writer.writeheader()
        for link_id, item in sorted(summary.items(), key=lambda pair: (-pair[1]["pairs"], pair[0])):
            writer.writerow({"link_id": link_id, **item})
    return {
        "pair_count": sum(item["pairs"] for item in summary.values()),
        "link_count": len(summary),
        "max_overlap_ns": max((item["overlap_ns"] for item in summary.values()), default=0),
        "output": str(overlap_path),
        "summary_output": str(summary_path),
    }


def analyze(scenario_dir, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = _manifest(scenario_dir / "replay_manifest.json")
    run_manifest = _manifest(scenario_dir / "network_run_manifest.json")
    raw_rows, rows = read_completed(scenario_dir)
    timeline_fields = ["event_id", "request_id", "collective_id", "event_type", "layer_id",
                       "active_request_ids", "serving_role", "src", "dst", "bytes",
                       "start", "end", "path", "directed_link_ids"]
    with (output_dir / "timeline.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=timeline_fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    kv_groups = _group_intervals(rows, "kv")
    ep_groups = _group_intervals(rows, "ep")
    kv_cct = [value["end"] - value["start"] for value in kv_groups.values()]
    ep_cct = [value["end"] - value["start"] for value in ep_groups.values()]
    overlap = _link_overlap(rows, output_dir)
    packet_payload_size = run_manifest.get("packet_payload_size")
    if packet_payload_size is None:
        packet_payload_size = _config_value(scenario_dir, "PACKET_PAYLOAD_SIZE")
    telemetry_interval_ms = run_manifest.get("telemetry_interval_ms")
    if telemetry_interval_ms is None:
        interval_ns = _config_value(scenario_dir, "LINK_TELEMETRY_INTERVAL_NS")
        telemetry_interval_ms = float(interval_ns) / 1_000_000 if interval_ns else 1000.0
    policy = run_manifest.get("kv_ep_network_policy")
    if policy is None:
        policy = _config_value(scenario_dir, "KV_EP_NETWORK_POLICY") or "FAIR"
    summary = {
        "scenario_dir": str(scenario_dir),
        "traffic_class": manifest["traffic_class"],
        "kv_subtype": manifest.get("kv_subtype", "P2D"),
        "p2d_bytes": manifest.get("p2d_bytes", 0),
        "remote_kv_bytes": manifest.get("remote_kv_bytes", 0),
        "remote_kv_blocks": manifest.get("remote_kv_blocks", 0),
        "scale": manifest["scale"],
        "request_count": manifest["request_count"],
        "expected_event_count": manifest["event_count"],
        "ep_bytes": manifest.get("ep_bytes", 0),
        "backend_start_rows": sum(row.get("phase") == "START" for row in raw_rows),
        "backend_end_rows": sum(row.get("phase") == "END" for row in raw_rows),
        "completed_event_count": len(rows),
        "completion_coverage": len(rows) / manifest["event_count"] if manifest["event_count"] else 0,
        "network_run_status": run_manifest["status"],
        "kv_ep_network_policy": policy,
        "packet_payload_size": int(packet_payload_size) if packet_payload_size is not None else 1000,
        "telemetry_interval_ms": telemetry_interval_ms,
        "kv_request_completion_ns": _stats(kv_cct),
        "ep_collective_cct_ns": _stats(ep_cct),
        "ep_collective_count": len(ep_groups),
        "kv_request_count_with_p2d": len(kv_groups),
        "kv_request_count_with_movement": len(kv_groups),
        "directed_link_overlap": overlap,
        "timing_model": manifest["timing_model"],
        "synthetic_byte_override": manifest["synthetic_byte_override"],
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario-dir", action="append", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    summaries = []
    for scenario in args.scenario_dir:
        scenario = scenario.resolve()
        name = scenario.name
        summaries.append(analyze(scenario, args.output_dir.resolve() / name))
    by_class = {row["traffic_class"]: row for row in summaries}
    comparison = []
    ep_base = by_class.get("EP_ONLY", {}).get("ep_collective_cct_ns", {})
    kv_base = by_class.get("KV_ONLY", {}).get("kv_request_completion_ns", {})
    for row in summaries:
        ep = row["ep_collective_cct_ns"]
        kv = row["kv_request_completion_ns"]
        comparison.append({
            "traffic_class": row["traffic_class"],
            "ep_p99_ns": ep.get("p99"),
            "ep_p99_ratio_vs_ep_only": (ep.get("p99") / ep_base["p99"]
                                         if ep.get("p99") and ep_base.get("p99") else None),
            "kv_p99_ns": kv.get("p99"),
            "kv_p99_ratio_vs_kv_only": (kv.get("p99") / kv_base["p99"]
                                         if kv.get("p99") and kv_base.get("p99") else None),
            "shared_link_overlap_pairs": row["directed_link_overlap"]["pair_count"],
            "completed_event_count": row["completed_event_count"],
        })
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "comparison.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(comparison[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(comparison)
    print(json.dumps({"scenarios": summaries, "comparison": comparison}, indent=2))


if __name__ == "__main__":
    main()
