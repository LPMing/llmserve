#!/usr/bin/env python3
"""Validate and summarize integrated FlowSim serving runs.

The request CSV is the source of truth for serving metrics.  Network
telemetry is used only for an independent traffic/overlap audit.  In
particular, this script never substitutes a flow completion time for TTFT,
TPOT, or TBT.

The FlowSim backend is fluid rather than packet-level.  Consequently this
report deliberately marks packet queue, ECN, PFC, and drop metrics as
unavailable instead of deriving them from residual fluid.
"""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


SERVING_FIELDS = (
    "TTFT", "TPOT", "latency", "queuing_delay", "decode_TTFT",
)
PERCENTILES = (0.50, 0.90, 0.95, 0.99)


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _nearest(values, quantile):
    ordered = sorted(values)
    if not ordered:
        return None
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def _stats(values):
    values = [value for value in values if value is not None and
              math.isfinite(value)]
    if not values:
        return {"count": 0, "mean": None, "p50": None, "p90": None,
                "p95": None, "p99": None, "max": None}
    return {
        "count": len(values),
        "mean": sum(values) / len(values),
        "p50": _nearest(values, 0.50),
        "p90": _nearest(values, 0.90),
        "p95": _nearest(values, 0.95),
        "p99": _nearest(values, 0.99),
        "max": max(values),
    }


def _parse_tbt(raw):
    try:
        values = json.loads(raw or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(values, list):
        return None
    parsed = []
    for value in values:
        number = _finite(value)
        if number is None or number < 0:
            return None
        parsed.append(number)
    return parsed


def _read_requests(path):
    rows = []
    errors = []
    with path.open(encoding="utf-8", newline="") as stream:
        for line_number, row in enumerate(csv.DictReader(stream), start=2):
            parsed = dict(row)
            parsed["request_id"] = row.get("request id", "")
            try:
                parsed["request_id"] = int(parsed["request_id"])
            except (TypeError, ValueError):
                errors.append(f"line {line_number}: invalid request id")
            for field in (
                    "input", "output", "arrival", "end_time", "latency",
                    "queuing_delay", *SERVING_FIELDS,
                    "prefill_completion_time_ns", "p2d_kv_ready_time_ns",
                    "decode_admit_time_ns", "decode_first_token_time_ns"):
                parsed[field] = _finite(row.get(field))
            parsed["tbt"] = _parse_tbt(row.get("TBT"))
            if parsed["tbt"] is None:
                errors.append(f"line {line_number}: invalid TBT JSON")
            rows.append(parsed)
    return rows, errors


def _validate_requests(rows):
    errors = []
    request_ids = [row["request_id"] for row in rows
                   if isinstance(row.get("request_id"), int)]
    if len(request_ids) != len(set(request_ids)):
        errors.append("duplicate request ids")
    for row in rows:
        rid = row.get("request_id", "?")
        for field in ("TTFT", "TPOT", "latency", "arrival", "end_time",
                      "decode_TTFT"):
            if row.get(field) is None or row[field] < 0:
                errors.append(f"request {rid}: invalid {field}")
        if row.get("end_time") is not None and row.get("arrival") is not None:
            if row["end_time"] < row["arrival"]:
                errors.append(f"request {rid}: end before arrival")
        tbt = row.get("tbt") or []
        output = row.get("output")
        if output is not None and int(output) >= 1:
            # The serving CSV preserves one decode interval for a one-token
            # request (the admission/first-token interval), while requests
            # with multiple output tokens expose inter-token intervals after
            # the first token.  Accept both native representations; never
            # synthesize or drop the recorded interval.
            expected_lengths = {int(output) - 1, int(output)}
            if len(tbt) not in expected_lengths:
                errors.append(
                    f"request {rid}: TBT length {len(tbt)} not in "
                    f"native lengths {sorted(expected_lengths)}")
        lifecycle = [row.get(field) for field in (
            "prefill_completion_time_ns", "p2d_kv_ready_time_ns",
            "decode_admit_time_ns", "decode_first_token_time_ns")]
        if all(value is not None for value in lifecycle):
            if lifecycle != sorted(lifecycle):
                errors.append(f"request {rid}: P/D lifecycle timestamps not monotonic")
            if row.get("end_time") is not None and lifecycle[-1] > row["end_time"]:
                errors.append(f"request {rid}: first token after request end")
        if (row.get("TTFT") is not None and row.get("decode_TTFT") is not None
                and abs(row["TTFT"] - row["decode_TTFT"]) > 1.0):
            errors.append(f"request {rid}: TTFT != decode_TTFT")
    return errors


def _request_metric_rows(rows):
    result = []
    all_tbt = []
    for row in rows:
        tbt = row.get("tbt") or []
        all_tbt.extend(tbt)
        row_result = {
            "request_id": row.get("request_id"),
            "input": row.get("input"),
            "output": row.get("output"),
            "arrival": row.get("arrival"),
            "end_time": row.get("end_time"),
            "TTFT": row.get("TTFT"),
            "TPOT": row.get("TPOT"),
            "latency": row.get("latency"),
            "queuing_delay": row.get("queuing_delay"),
            "TBT_count": len(tbt),
            "TBT_mean": sum(tbt) / len(tbt) if tbt else None,
            "TBT_max": max(tbt) if tbt else None,
        }
        result.append(row_result)
    return result, all_tbt


def _merge_intervals(intervals):
    merged = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _intersection_duration(left, right):
    total = 0
    index = 0
    other = 0
    while index < len(left) and other < len(right):
        start = max(left[index][0], right[other][0])
        end = min(left[index][1], right[other][1])
        if end > start:
            total += end - start
        if left[index][1] < right[other][1]:
            index += 1
        else:
            other += 1
    return total


def _read_telemetry(path):
    records = []
    malformed = 0
    truncated = False
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("#") or not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            start = _finite(record.get("start_ns"))
            end = _finite(record.get("end_ns"))
            if start is None or end is None or end < start:
                malformed += 1
                continue
            record["start_ns"] = int(start)
            record["end_ns"] = int(end)
            records.append(record)
    # ``FLOWSIM_MAX_TELEMETRY_ROWS`` bounds the in-memory residual-fluid
    # timeseries, not the streamed per-flow JSONL.  Do not infer truncation
    # from the number of completed flow records.
    truncated = False
    return records, {"malformed_records": malformed, "possibly_truncated": truncated}


def _network_summary(path):
    records, parse_meta = _read_telemetry(path)
    by_class = defaultdict(list)
    bytes_by_class = defaultdict(int)
    link_intervals = defaultdict(lambda: defaultdict(list))
    for record in records:
        traffic_class = str(record.get("traffic_class", "OTHER"))
        by_class[traffic_class].append((record["start_ns"], record["end_ns"]))
        bytes_by_class[traffic_class] += int(record.get("bytes", 0) or 0)
        for link in record.get("path", []) or []:
            link_intervals[link][traffic_class].append(
                (record["start_ns"], record["end_ns"]))
    merged = {key: _merge_intervals(value)
              for key, value in by_class.items()}
    all_intervals = [interval for values in by_class.values() for interval in values]
    all_merged = _merge_intervals(all_intervals)
    kv = merged.get("KV_MOVEMENT", [])
    ep = merged.get("EP", [])
    overlap_ns = _intersection_duration(kv, ep)
    span_ns = (all_merged[-1][1] - all_merged[0][0]) if all_merged else 0
    mixed_links = []
    for link, classes in link_intervals.items():
        link_kv = _merge_intervals(classes.get("KV_MOVEMENT", []))
        link_ep = _merge_intervals(classes.get("EP", []))
        link_overlap = _intersection_duration(link_kv, link_ep)
        if link_overlap:
            mixed_links.append({
                "link": link,
                "overlap_ns": link_overlap,
                "kv_active_ns": sum(end - start for start, end in link_kv),
                "ep_active_ns": sum(end - start for start, end in link_ep),
            })
    mixed_links.sort(key=lambda item: item["overlap_ns"], reverse=True)
    return {
        "telemetry": str(path.resolve()),
        "flow_count": len(records),
        "bytes_by_class": dict(bytes_by_class),
        "flow_count_by_class": {key: len(value) for key, value in by_class.items()},
        "global_kv_ep_overlap_ns": overlap_ns,
        "global_activity_span_ns": span_ns,
        "global_kv_ep_overlap_fraction": overlap_ns / span_ns if span_ns else 0.0,
        "mixed_link_count": len(mixed_links),
        "top_mixed_links": mixed_links[:10],
        "packet_queue_metrics_available": False,
        "ecn_pfc_drop_metrics_available": False,
        "queue_semantics": "FlowSim queue_bytes is residual fluid, not packet queue",
        **parse_meta,
    }


def _throughput(rows, predicate=None):
    selected = [row for row in rows if predicate is None or predicate(row)]
    if not selected:
        return 0.0
    arrivals = [row["arrival"] for row in selected if row.get("arrival") is not None]
    ends = [row["end_time"] for row in selected if row.get("end_time") is not None]
    if not arrivals or not ends:
        return 0.0
    span = max(ends) - min(arrivals)
    return len(selected) / (span / 1e9) if span > 0 else 0.0


def _parse_labeled_paths(values, label):
    result = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"{label} must be LABEL=PATH: {value}")
        name, raw_path = value.split("=", 1)
        result[name] = Path(raw_path)
    return result


def _slo(baseline_rows, rows, baseline_kind, mfs_tpot_factor,
         dist_ttft_factor, dist_tpot_factor):
    baseline_metrics, _ = _request_metric_rows(baseline_rows)
    run_metrics, _ = _request_metric_rows(rows)
    baseline_by_id = {row["request_id"]: row for row in baseline_metrics}
    run_by_id = {row["request_id"]: row for row in run_metrics}
    common = sorted(set(baseline_by_id) & set(run_by_id))
    baseline_stats = {
        metric: _stats([row[metric] for row in baseline_metrics
                        if row.get(metric) is not None])
        for metric in ("TTFT", "TPOT", "TBT_mean", "TBT_max")
    }
    ttft_p50 = baseline_stats["TTFT"]["p50"]
    tpot_p50 = baseline_stats["TPOT"]["p50"]
    result = {
        "baseline_kind": baseline_kind,
        "baseline_request_count": len(baseline_rows),
        "run_request_count": len(rows),
        "common_request_count": len(common),
        "baseline_metrics": baseline_stats,
        "invalid_for_paper": baseline_kind != "low_load" or len(baseline_rows) < 10,
        "profiles": {},
    }
    if ttft_p50 is None or tpot_p50 is None:
        return result
    mfs = {
        "ttft_threshold_ns": 3.0 * ttft_p50,
        "ttft_attainment": sum(row["TTFT"] <= 3.0 * ttft_p50 for row in run_metrics) / len(run_metrics),
        "tpot_threshold_ns": None,
        "tpot_attainment": None,
    }
    if mfs_tpot_factor is not None:
        threshold = mfs_tpot_factor * tpot_p50
        mfs["tpot_threshold_ns"] = threshold
        mfs["tpot_attainment"] = sum(row["TPOT"] <= threshold for row in run_metrics) / len(run_metrics)
    splitwise = {}
    for quantile, ttft_factor, tpot_factor in (
            ("p50", 2.0, 1.25), ("p90", 3.0, 1.5), ("p99", 6.0, 5.0)):
        ttft_threshold = ttft_factor * baseline_stats["TTFT"][quantile]
        tpot_threshold = tpot_factor * baseline_stats["TPOT"][quantile]
        splitwise[quantile] = {
            "ttft_threshold_ns": ttft_threshold,
            "tpot_threshold_ns": tpot_threshold,
            "ttft_attainment": sum(row["TTFT"] <= ttft_threshold for row in run_metrics) / len(run_metrics),
            "tpot_attainment": sum(row["TPOT"] <= tpot_threshold for row in run_metrics) / len(run_metrics),
        }
    dist_ttft = dist_ttft_factor * ttft_p50
    dist_tpot = dist_tpot_factor * tpot_p50
    joint = [row for row in run_metrics
             if row["TTFT"] <= dist_ttft and row["TPOT"] <= dist_tpot]
    joint_ids = {row["request_id"] for row in joint}
    result["profiles"] = {
        "SLO_PROFILE_MFS": mfs,
        "SLO_PROFILE_SPLITWISE": splitwise,
        "SLO_PROFILE_DIST_SERVE": {
            "ttft_threshold_ns": dist_ttft,
            "tpot_threshold_ns": dist_tpot,
            "joint_attainment": len(joint) / len(run_metrics),
            "joint_target": 0.90,
            "goodput_rps": _throughput(
                rows, lambda row: row.get("request_id") in joint_ids),
        },
        "paired_ratios": {
            "TTFT": [run_by_id[rid]["TTFT"] / baseline_by_id[rid]["TTFT"]
                     for rid in common if baseline_by_id[rid]["TTFT"] > 0],
            "TPOT": [run_by_id[rid]["TPOT"] / baseline_by_id[rid]["TPOT"]
                     for rid in common if baseline_by_id[rid]["TPOT"] > 0],
        },
    }
    return result


def _format_ms(value):
    return "n/a" if value is None else f"{value / 1e6:.3f}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="append", required=True,
                        metavar="LABEL=REQUESTS_CSV")
    parser.add_argument("--telemetry", action="append", default=[],
                        metavar="LABEL=TELEMETRY_JSONL")
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--baseline-kind", choices=("low_load", "diagnostic"),
                        default="low_load")
    parser.add_argument("--output-base", required=True, type=Path)
    parser.add_argument("--expected-requests", type=int)
    parser.add_argument("--mfs-tpot-factor", type=float)
    parser.add_argument("--dist-ttft-factor", type=float, default=3.0)
    parser.add_argument("--dist-tpot-factor", type=float, default=1.5)
    args = parser.parse_args()

    run_paths = _parse_labeled_paths(args.run, "--run")
    telemetry_paths = _parse_labeled_paths(args.telemetry, "--telemetry")
    baseline_rows, baseline_parse_errors = _read_requests(args.baseline)
    baseline_validation = _validate_requests(baseline_rows)
    runs = {}
    rows_for_csv = []
    for label, path in run_paths.items():
        request_rows, parse_errors = _read_requests(path)
        validation_errors = parse_errors + _validate_requests(request_rows)
        if args.expected_requests is not None and len(request_rows) != args.expected_requests:
            validation_errors.append(
                f"request count {len(request_rows)} != expected {args.expected_requests}")
        metric_rows, token_tbt = _request_metric_rows(request_rows)
        metrics = {}
        for field in ("TTFT", "TPOT", "latency", "queuing_delay",
                      "TBT_mean", "TBT_max"):
            metrics[field] = _stats([row[field] for row in metric_rows
                                     if row.get(field) is not None])
        metrics["TBT_token"] = _stats(token_tbt)
        runs[label] = {
            "requests_csv": str(path.resolve()),
            "request_count": len(request_rows),
            "request_metrics": metric_rows,
            "metrics": metrics,
            "throughput_rps": _throughput(request_rows),
            "validation": {"valid": not validation_errors,
                            "errors": validation_errors[:100]},
            "network": (_network_summary(telemetry_paths[label])
                         if label in telemetry_paths else None),
            "slo": _slo(baseline_rows, request_rows, args.baseline_kind,
                         args.mfs_tpot_factor, args.dist_ttft_factor,
                         args.dist_tpot_factor),
        }
        for metric, stats in metrics.items():
            rows_for_csv.append({
                "run": label,
                "metric": metric,
                **{key: value for key, value in stats.items()},
            })

    payload = {
        "study": "integrated FlowSim serving validation",
        "baseline_csv": str(args.baseline.resolve()),
        "baseline_kind": args.baseline_kind,
        "baseline_request_count": len(baseline_rows),
        "baseline_validation": {
            "valid": not (baseline_parse_errors + baseline_validation),
            "errors": (baseline_parse_errors + baseline_validation)[:100],
        },
        "serving_metric_definitions": {
            "TTFT": "decode first-token completion minus request arrival",
            "TPOT": "mean TBT after the first generated token, from scheduler CSV",
            "TBT": "raw per-token decode intervals from scheduler CSV; native one-token requests may contain the first-token interval, while multi-token requests normally contain output-1 inter-token intervals",
            "SLO": "normalized against the same trace/model/topology low-load baseline",
        },
        "network_backend_limitations": {
            "packet_queue": "unavailable in fluid FlowSim",
            "ECN": "unavailable in fluid FlowSim",
            "PFC": "unavailable in fluid FlowSim",
            "drops": "unavailable in fluid FlowSim",
            "queue_bytes": "must not be interpreted as a packet queue",
        },
        "runs": runs,
    }
    args.output_base.parent.mkdir(parents=True, exist_ok=True)
    json_path = args.output_base.with_suffix(".json")
    csv_path = args.output_base.with_suffix(".csv")
    md_path = args.output_base.with_suffix(".md")
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        fields = ["run", "metric", "count", "mean", "p50", "p90", "p95",
                  "p99", "max"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows_for_csv)
    with md_path.open("w", encoding="utf-8") as stream:
        stream.write("# Integrated FlowSim serving validation\n\n")
        stream.write(f"Baseline: `{args.baseline.resolve()}`; kind=`{args.baseline_kind}`; "
                     f"baseline requests={len(baseline_rows)}.\n\n")
        if len(baseline_rows) < 10 or args.baseline_kind != "low_load":
            stream.write(
                "> This is a diagnostic/feasibility result, not a final paper SLO claim: "
                "the matched low-load baseline has fewer than 10 requests or is not marked low_load.\n\n")
        stream.write("Serving metrics are from the integrated scheduler request CSV, not network telemetry.\n\n")
        stream.write("| run | valid | requests | TTFT P99 ms | TPOT P99 ms | TBT mean P99 ms | TBT token P99 ms | joint SLO |\n")
        stream.write("|---|---:|---:|---:|---:|---:|---:|---:|\n")
        for label, result in runs.items():
            metrics = result["metrics"]
            joint = result["slo"].get("profiles", {}).get("SLO_PROFILE_DIST_SERVE", {}).get("joint_attainment")
            stream.write(
                f"| {label} | {result['validation']['valid']} | {result['request_count']} | "
                f"{_format_ms(metrics['TTFT']['p99'])} | "
                f"{_format_ms(metrics['TPOT']['p99'])} | "
                f"{_format_ms(metrics['TBT_mean']['p99'])} | "
                f"{_format_ms(metrics['TBT_token']['p99'])} | "
                f"{joint if joint is not None else 'n/a'} |\n")
            network = result.get("network")
            if network:
                stream.write(
                    f"\n`{label}` network: {network['flow_count']} completed flows, "
                    f"KV/EP global overlap={network['global_kv_ep_overlap_fraction']:.4f}, "
                    f"mixed links={network['mixed_link_count']}; packet queues/ECN/PFC/drops unavailable.\n\n")
        stream.write("\nValidation errors are retained in the JSON output; no incomplete row is silently filled.\n")
    print(json.dumps({"json": str(json_path), "csv": str(csv_path),
                      "markdown": str(md_path)}, indent=2))


if __name__ == "__main__":
    main()
