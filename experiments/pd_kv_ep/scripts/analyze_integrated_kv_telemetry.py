#!/usr/bin/env python3
"""Analyze integrated FlowSim KV events without fabricating batch attribution.

The worker writes one event for every model-derived P2D flow.  A flow may be
an aggregate for several requests when the serving scheduler batches them;
this script keeps the aggregate bytes at global scope and marks request rows
as ``batch_aggregate`` instead of dividing bytes by request count.
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
            if not line.strip() or line.startswith("#"):
                continue
            rows.append(json.loads(line))
    return rows


def _read_flows(path):
    rows = []
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip() or line.startswith("#"):
                continue
            row = json.loads(line)
            if row.get("traffic_class") == "KV_MOVEMENT":
                rows.append(row)
    return rows


def _read_collectives(path):
    return [row for row in _read_jsonl(path)
            if row.get("event") == "COLLECTIVE_COMPLETED"]


def _read_csv(path):
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _percentile(values, fraction):
    values = sorted(float(value) for value in values)
    if not values:
        return None
    index = min(len(values) - 1, int(math.ceil(fraction * len(values))) - 1)
    return values[max(0, index)]


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


def _serving_summary(requests, include_groups=True):
    """Summarize real integrated serving fields without filling missing data."""
    metrics = {}
    for name in ("TTFT", "TPOT", "latency"):
        values = [_int(row.get(name)) for row in requests]
        metrics[name.lower() + "_ns"] = _summary(
            value for value in values if value is not None)
    tbt_values = []
    itl_values = []
    for row in requests:
        raw = row.get("TBT", "")
        try:
            sequence = json.loads(raw) if raw else []
        except (TypeError, json.JSONDecodeError):
            sequence = []
        tbt_values.extend(float(value) for value in sequence)
        raw_itl = row.get("ITL", "")
        try:
            itl_sequence = json.loads(raw_itl) if raw_itl else []
        except (TypeError, json.JSONDecodeError):
            itl_sequence = []
        itl_values.extend(float(value) for value in itl_sequence)
    metrics["tbt_token_ns"] = _summary(tbt_values)
    metrics["itl_token_ns"] = _summary(itl_values)
    # ITL is stored by the serving frontend as a JSON token sequence, not as
    # one scalar request field.  Keep the legacy key, but make it point to the
    # real token-level summary instead of silently reporting count=0.
    metrics["itl_ns"] = metrics["itl_token_ns"]
    if include_groups:
        by_input = defaultdict(list)
        for row in requests:
            input_tokens = _int(row.get("input"))
            if input_tokens is not None:
                by_input[str(input_tokens)].append(row)
        metrics["by_input_tokens"] = {
            input_tokens: _serving_summary(rows, include_groups=False)
            for input_tokens, rows in sorted(by_input.items(),
                                             key=lambda item: int(item[0]))
        }
    return metrics


def _flow_ids(row):
    ids = row.get("request_ids", ())
    if isinstance(ids, str):
        try:
            ids = json.loads(ids)
        except json.JSONDecodeError:
            ids = [item for item in ids.split(";") if item]
    return tuple(str(item) for item in (ids or ()))


def _event_rows(run_dir):
    events = _read_jsonl(run_dir / "kv_event_telemetry.jsonl")
    if events:
        return events
    # Backward-compatible fallback for runs produced before the event stream.
    rows = _read_flows(run_dir / "flow_telemetry.jsonl")
    fallback = []
    for row in rows:
        base = {
            "flow_id": row.get("flow_id"),
            "src": row.get("src"),
            "dst": row.get("dst"),
            "bytes": row.get("bytes"),
            "request_ids": row.get("request_ids", []),
            "batch_id": row.get("batch_id"),
            "layer_id": row.get("layer_id"),
            "event_type": row.get("event_type"),
            "collective_id": row.get("collective_id"),
            "traffic_subtype": row.get("traffic_subtype"),
            "requested_start_ns": row.get("requested_start_ns"),
            "start_ns": row.get("start_ns"),
            "end_ns": row.get("end_ns"),
            "path": row.get("path", []),
        }
        for name, timestamp in (("KV_REQUESTED", row.get("requested_start_ns")),
                                ("KV_STARTED", row.get("start_ns")),
                                ("KV_COMPLETED", row.get("end_ns"))):
            item = dict(base)
            item["event"] = name
            item["timestamp_ns"] = timestamp
            fallback.append(item)
    return fallback


def _write_csv(path, fieldnames, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _interval_overlap(left, right):
    left_links = set(left.get("path", []) or [])
    right_links = left_links.intersection(set(right.get("path", []) or []))
    if not right_links:
        return 0
    start = max(_int(left.get("start_ns"), 0), _int(right.get("start_ns"), 0))
    end = min(_int(left.get("end_ns"), 0), _int(right.get("end_ns"), 0))
    return max(0, end - start)


def _build_timeseries(events, output, thresholds):
    # KV_GENERATED is the model-derived producer release into a sender-side
    # staging buffer. KV_REQUESTED is admission to the network. KV_COMPLETED
    # is the actual network drain. Older runs only have KV_REQUESTED, in which
    # case it is also the generation point. STARTED changes no byte counter.
    ordered = sorted(
        (row for row in events if _int(row.get("timestamp_ns")) is not None),
        key=lambda row: (_int(row.get("timestamp_ns")), row.get("event", "")),
    )
    has_generated_events = any(row.get("event") == "KV_GENERATED"
                               for row in ordered)
    generated = released = completed = 0
    network_outstanding = active = 0
    last_ts = None
    max_outstanding = max_network_outstanding = max_staged = 0
    weighted_outstanding = weighted_network_outstanding = 0.0
    total_span = 0
    above = {threshold: 0 for threshold in thresholds}
    rows = []
    for row in ordered:
        timestamp = _int(row.get("timestamp_ns"))
        if last_ts is not None and timestamp >= last_ts:
            delta = timestamp - last_ts
            total_outstanding = generated - completed
            weighted_outstanding += total_outstanding * delta
            weighted_network_outstanding += network_outstanding * delta
            total_span += delta
            for threshold in thresholds:
                if total_outstanding >= threshold:
                    above[threshold] += delta
        event = row.get("event")
        bytes_value = _int(row.get("bytes"), 0) or 0
        generated_delta = bytes_value if (
            event == "KV_GENERATED" or
            (not has_generated_events and event == "KV_REQUESTED")) else 0
        released_delta = bytes_value if event == "KV_REQUESTED" else 0
        completed_delta = bytes_value if event == "KV_COMPLETED" else 0
        if generated_delta:
            generated += bytes_value
        if released_delta:
            released += bytes_value
            network_outstanding += bytes_value
            active += 1
        elif event == "KV_COMPLETED":
            completed += bytes_value
            network_outstanding = max(0, network_outstanding - bytes_value)
            active = max(0, active - 1)
        outstanding = max(0, generated - completed)
        staged = max(0, generated - released)
        max_outstanding = max(max_outstanding, outstanding)
        max_network_outstanding = max(max_network_outstanding,
                                       network_outstanding)
        max_staged = max(max_staged, staged)
        interval_ns = max(0, timestamp - (last_ts if last_ts is not None else timestamp))
        rows.append({
            "timestamp_ns": timestamp,
            "event": event,
            "flow_id": row.get("flow_id"),
            "request_ids": json.dumps(row.get("request_ids", []), separators=(",", ":")),
            "layer_id": row.get("layer_id"),
            "bytes_delta_generated": generated_delta,
            "bytes_delta_released": released_delta,
            "bytes_delta_completed": completed_delta,
            "generated_bytes_cumulative": generated,
            "released_bytes_cumulative": released,
            "completed_bytes_cumulative": completed,
            "outstanding_kv_bytes": outstanding,
            "network_outstanding_kv_bytes": network_outstanding,
            "staged_kv_bytes": staged,
            "active_p2d_flow_count": active,
            "generated_rate_gbps": (generated_delta * 8e9 / interval_ns / 1e9
                                     if interval_ns else 0.0),
            "drain_rate_gbps": (completed_delta * 8e9 / interval_ns / 1e9
                                 if interval_ns else 0.0),
        })
        last_ts = timestamp
    summary = {
        "event_count": len(ordered),
        "kv_flow_count": len({row.get("flow_id") for row in ordered
                               if row.get("flow_id") is not None}),
        "generated_bytes": generated,
        "released_bytes": released,
        "completed_bytes": completed,
        "residual_outstanding_bytes": outstanding,
        "max_outstanding_kv_bytes": max_outstanding,
        "max_network_outstanding_kv_bytes": max_network_outstanding,
        "max_staged_kv_bytes": max_staged,
        "avg_outstanding_kv_bytes_time_weighted": (
            weighted_outstanding / total_span if total_span else 0.0),
        "avg_network_outstanding_kv_bytes_time_weighted": (
            weighted_network_outstanding / total_span if total_span else 0.0),
        "time_span_ns": total_span,
        "time_above_bytes": {str(key): value for key, value in above.items()},
        "thresholds_bytes": thresholds,
    }
    requested_rows = [row for row in ordered
                      if row.get("event") == "KV_REQUESTED"]
    generated_rows = [row for row in ordered
                      if row.get("event") == "KV_GENERATED"]
    completed_rows = [row for row in ordered
                      if row.get("event") == "KV_COMPLETED"]
    def _rate(rows, total_bytes):
        if len(rows) < 2:
            return None
        span = _int(rows[-1].get("timestamp_ns"), 0) - _int(
            rows[0].get("timestamp_ns"), 0)
        return (total_bytes * 8e9 / span / 1e9) if span > 0 else None
    summary["generation_drain"] = {
        "generation_start_ns": (_int((generated_rows or requested_rows)[0].get("timestamp_ns"))
                                 if (generated_rows or requested_rows) else None),
        "generation_end_ns": (_int((generated_rows or requested_rows)[-1].get("timestamp_ns"))
                               if (generated_rows or requested_rows) else None),
        "drain_start_ns": (_int(completed_rows[0].get("timestamp_ns"))
                            if completed_rows else None),
        "drain_end_ns": (_int(completed_rows[-1].get("timestamp_ns"))
                          if completed_rows else None),
        "generation_rate_gbps": _rate(
            generated_rows or requested_rows, generated),
        "release_rate_gbps": _rate(requested_rows, released),
        "drain_rate_gbps": _rate(completed_rows, completed),
    }
    fields = list(rows[0].keys()) if rows else [
        "timestamp_ns", "event", "flow_id", "request_ids",
        "layer_id", "bytes_delta_generated", "bytes_delta_completed",
        "bytes_delta_released", "generated_bytes_cumulative",
        "released_bytes_cumulative", "completed_bytes_cumulative",
        "outstanding_kv_bytes", "network_outstanding_kv_bytes",
        "staged_kv_bytes", "active_p2d_flow_count",
        "generated_rate_gbps", "drain_rate_gbps"]
    _write_csv(output / "kv_timeseries.csv", fields, rows)
    return summary


def _build_request_metrics(run_dir, events, flows, output, request_csv=None):
    request_csv = request_csv or (run_dir / "requests.csv")
    if not request_csv.is_file():
        request_csv = run_dir.parent / "requests.csv"
    requests = _read_csv(request_csv)
    by_request = defaultdict(list)
    for row in events:
        ids = _flow_ids(row)
        for request_id in ids:
            by_request[request_id].append(row)
    flow_by_id = {str(row.get("flow_id")): row for row in flows}
    ep_flows = [row for row in _read_jsonl(run_dir / "flow_telemetry.jsonl")
                if row.get("traffic_class") == "EP"]
    output_rows = []
    for request in requests:
        request_id = str(request.get("request id", request.get("request_id", "")))
        owned = by_request.get(request_id, [])
        completed = [row for row in owned if row.get("event") == "KV_COMPLETED"]
        requested = [row for row in owned if row.get("event") == "KV_REQUESTED"]
        first_requested = min((_int(row.get("timestamp_ns")) for row in requested
                               if _int(row.get("timestamp_ns")) is not None), default=None)
        last_requested = max((_int(row.get("timestamp_ns")) for row in requested
                              if _int(row.get("timestamp_ns")) is not None), default=None)
        last_completed = max((_int(row.get("timestamp_ns")) for row in completed
                              if _int(row.get("timestamp_ns")) is not None), default=None)
        aggregate = any(len(_flow_ids(row)) != 1 for row in owned)
        critical = max(
            (row for row in flows if request_id in _flow_ids(row)),
            key=lambda row: _int(row.get("end_ns"), -1),
            default=None)
        overlap_ns = 0
        overlap_links = set()
        if critical is not None:
            for ep in ep_flows:
                overlap = _interval_overlap(critical, ep)
                if overlap:
                    overlap_ns = max(overlap_ns, overlap)
                    overlap_links.update(set(critical.get("path", [])) &
                                         set(ep.get("path", [])))
        row = {
            "request_id": request_id,
            "kv_flow_count": len({row.get("flow_id") for row in owned}),
            "kv_byte_attribution": "batch_aggregate" if aggregate else "exact_single_request",
            "kv_generated_bytes_exact": (
                sum(_int(row.get("bytes"), 0) or 0 for row in requested)
                if not aggregate else ""),
            "kv_completed_bytes_exact": (
                sum(_int(row.get("bytes"), 0) or 0 for row in completed)
                if not aggregate else ""),
            "first_kv_requested_ns": first_requested,
            "last_kv_requested_ns": last_requested,
            "last_kv_completed_ns": last_completed,
            "arrival_ns": _int(request.get("arrival")),
            "kv_fct_ns": (
                _int(request.get("p2d_kv_ready_time_ns"), 0) -
                _int(request.get("arrival"), 0)
                if _int(request.get("p2d_kv_ready_time_ns")) is not None and
                _int(request.get("arrival")) is not None else ""),
            "kv_handoff_span_ns": (
                last_completed - first_requested
                if first_requested is not None and last_completed is not None else ""),
            "kv_post_prefill_drain_ns": (
                last_completed - last_requested
                if last_requested is not None and last_completed is not None else ""),
            "p2d_kv_ready_time_ns": _int(request.get("p2d_kv_ready_time_ns")),
            "ttft_ns": _int(request.get("TTFT")),
            "critical_kv_flow_id": critical.get("flow_id") if critical else "",
            "critical_kv_layer_id": critical.get("layer_id") if critical else "",
            "critical_kv_requested_ns": critical.get("requested_start_ns") if critical else "",
            "critical_kv_start_ns": critical.get("start_ns") if critical else "",
            "critical_kv_finish_ns": critical.get("end_ns") if critical else "",
            "critical_kv_queueing_ns": (
                _int(critical.get("start_ns"), 0) -
                _int(critical.get("requested_start_ns"), 0)
                if critical else ""),
            "critical_kv_service_ns": (
                _int(critical.get("end_ns"), 0) -
                _int(critical.get("start_ns"), 0)
                if critical else ""),
            "critical_kv_ep_overlap_ns": overlap_ns,
            "critical_kv_ep_overlap_links": ";".join(sorted(overlap_links)),
        }
        output_rows.append(row)
    fields = list(output_rows[0].keys()) if output_rows else ["request_id"]
    _write_csv(output / "kv_request_metrics.csv", fields, output_rows)
    return output_rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--requests", type=Path, default=None,
                        help="integrated serving request CSV; defaults to run-dir/requests.csv or its parent")
    parser.add_argument("--threshold-bytes", default="1048576,16777216,67108864,268435456,1073741824")
    args = parser.parse_args()
    args.run_dir = args.run_dir.resolve()
    args.run_dir.mkdir(parents=True, exist_ok=True)
    thresholds = sorted({int(item) for item in args.threshold_bytes.split(",") if item})
    events = _event_rows(args.run_dir)
    flows = _read_flows(args.run_dir / "flow_telemetry.jsonl")
    summary = _build_timeseries(events, args.run_dir, thresholds)
    request_rows = _build_request_metrics(
        args.run_dir, events, flows, args.run_dir,
        request_csv=(args.requests.resolve() if args.requests else None))
    summary["request_count"] = len(request_rows)
    request_csv = args.requests.resolve() if args.requests else (args.run_dir / "requests.csv")
    if not request_csv.is_file():
        request_csv = args.run_dir.parent / "requests.csv"
    serving_requests = _read_csv(request_csv)
    if serving_requests:
        summary["serving_metrics"] = _serving_summary(serving_requests)
    collectives = _read_collectives(args.run_dir / "collective_telemetry.jsonl")
    if collectives:
        ep = [row for row in collectives if row.get("traffic_class") == "EP"]
        summary["collective_metrics"] = {
            "all_count": len(collectives),
            "ep_count": len(ep),
            "ep_cct_ns": _summary(
                _int(row.get("cct_ns"), 0) or 0 for row in ep),
            "ep_bytes_per_participant": _summary(
                (_int(row.get("bytes_per_participant"), None)
                 if _int(row.get("bytes_per_participant")) is not None else
                 _int(row.get("bytes_sum"), 0) or 0)
                for row in ep),
            "ep_peer_flow_count": _summary(
                (_int(row.get("peer_flow_count"), None)
                 if _int(row.get("peer_flow_count")) is not None else
                 _int(row.get("participant_flow_count"), 0) or 0)
                for row in ep),
        }
    summary["telemetry_semantics"] = {
        "queue": "FlowSim residual-fluid backlog, not packet-buffer occupancy",
        "generated": "P2D bytes released by the model-side graph producer",
        "requested": "P2D flow admitted/released to the FlowSim network",
        "completed": "actual FlowSim flow completion",
        "outstanding": "generated minus completed; includes staged and network-resident bytes",
        "network_outstanding": "requested minus completed; excludes staged sender bytes",
        "aggregate_attribution": "aggregate bytes are never split across request_ids",
    }
    (args.run_dir / "kv_telemetry_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "run_dir": str(args.run_dir),
        "event_count": summary["event_count"],
        "max_outstanding_kv_bytes": summary["max_outstanding_kv_bytes"],
        "avg_outstanding_kv_bytes_time_weighted": summary[
            "avg_outstanding_kv_bytes_time_weighted"],
        "request_count": len(request_rows),
        "outputs": ["kv_timeseries.csv", "kv_request_metrics.csv",
                     "kv_telemetry_summary.json"],
    }, indent=2))


if __name__ == "__main__":
    main()
