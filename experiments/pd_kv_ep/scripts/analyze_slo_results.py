#!/usr/bin/env python3
"""Compute explicitly-baselined serving SLO summaries.

The script deliberately refuses to present a same-slice policy run as a
low-load baseline.  Such a baseline can still be used for a diagnostic gate,
but the output is marked invalid_for_paper=True.
"""

import argparse
import csv
import json
import math
from pathlib import Path


METRICS = ("TTFT", "TPOT", "latency")


def _read(path):
    rows = []
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            parsed = {}
            for field in METRICS + ("arrival", "end_time"):
                try:
                    parsed[field] = float(row[field])
                except (KeyError, TypeError, ValueError):
                    parsed[field] = None
            # For P/D rows, the serving-visible TTFT is the first Decode
            # token, which includes Prefill, P2D KV readiness, and Decode
            # admission.  Fall back to the legacy TTFT for non-P/D rows.
            try:
                decode_ttft = float(row.get("decode_TTFT", ""))
            except (TypeError, ValueError):
                decode_ttft = None
            if decode_ttft is not None and math.isfinite(decode_ttft) and decode_ttft >= 0:
                parsed["TTFT"] = decode_ttft
            if all(parsed[field] is not None and math.isfinite(parsed[field])
                   for field in METRICS):
                rows.append(parsed)
    return rows


def _nearest(values, quantile):
    ordered = sorted(values)
    if not ordered:
        return None
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def _stats(rows, field):
    values = [row[field] for row in rows]
    if not values:
        return {"count": 0, "mean": None, "p50": None, "p90": None,
                "p99": None, "max": None}
    return {
        "count": len(values),
        "mean": sum(values) / len(values),
        "p50": _nearest(values, 0.50),
        "p90": _nearest(values, 0.90),
        "p99": _nearest(values, 0.99),
        "max": max(values),
    }


def _attainment(rows, field, threshold):
    if threshold is None or not rows:
        return None
    return sum(row[field] <= threshold for row in rows) / len(rows)


def _throughput(rows):
    if not rows:
        return None
    arrivals = [row["arrival"] for row in rows if row["arrival"] is not None]
    ends = [row["end_time"] for row in rows if row["end_time"] is not None]
    if not arrivals or not ends:
        return None
    span_ns = max(ends) - min(arrivals)
    return len(rows) / (span_ns / 1e9) if span_ns > 0 else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True, type=Path,
                        help="same trace/model/topology low-load request CSV")
    parser.add_argument("--baseline-kind", choices=("low_load", "same_slice_gate"),
                        default="low_load")
    parser.add_argument("--run", action="append", required=True,
                        metavar="LABEL=REQUESTS_CSV",
                        help="comparison run; may be supplied multiple times")
    parser.add_argument("--output-base", required=True, type=Path)
    parser.add_argument("--mfs-tpot-factor", type=float, default=None,
                        help="explicit TPOT multiplier; omitted means MFS TPOT is not evaluated")
    parser.add_argument("--dist-ttft-factor", type=float, default=3.0)
    parser.add_argument("--dist-tpot-factor", type=float, default=1.5)
    args = parser.parse_args()

    baseline = _read(args.baseline)
    if not baseline:
        raise SystemExit(f"baseline has no valid TTFT/TPOT rows: {args.baseline}")
    baseline_stats = {field: _stats(baseline, field) for field in METRICS}

    runs = {}
    for spec in args.run:
        if "=" not in spec:
            raise SystemExit(f"--run must be LABEL=REQUESTS_CSV, got {spec!r}")
        label, raw_path = spec.split("=", 1)
        rows = _read(Path(raw_path))
        if not rows:
            raise SystemExit(f"run has no valid TTFT/TPOT rows: {raw_path}")
        stats = {field: _stats(rows, field) for field in METRICS}
        thresholds = {
            "mfs_ttft": 3.0 * baseline_stats["TTFT"]["p50"],
            "mfs_tpot": (
                args.mfs_tpot_factor * baseline_stats["TPOT"]["p50"]
                if args.mfs_tpot_factor is not None else None
            ),
            "dist_ttft": args.dist_ttft_factor * baseline_stats["TTFT"]["p50"],
            "dist_tpot": args.dist_tpot_factor * baseline_stats["TPOT"]["p50"],
        }
        splitwise = {}
        for quantile in ("p50", "p90", "p99"):
            splitwise[quantile] = {
                "ttft_threshold": baseline_stats["TTFT"][quantile] *
                                  {"p50": 2.0, "p90": 3.0, "p99": 6.0}[quantile],
                "tpot_threshold": baseline_stats["TPOT"][quantile] *
                                  {"p50": 1.25, "p90": 1.5, "p99": 5.0}[quantile],
            }
        runs[label] = {
            "requests_csv": str(Path(raw_path).resolve()),
            "request_count": len(rows),
            "throughput_rps": _throughput(rows),
            "metrics": stats,
            "slo_profile_mfs": {
                "ttft_threshold_ns": thresholds["mfs_ttft"],
                "ttft_attainment": _attainment(rows, "TTFT", thresholds["mfs_ttft"]),
                "tpot_threshold_ns": thresholds["mfs_tpot"],
                "tpot_attainment": _attainment(rows, "TPOT", thresholds["mfs_tpot"]),
            },
            "slo_profile_splitwise": {
                q: {
                    **limits,
                    "ttft_attainment": _attainment(rows, "TTFT", limits["ttft_threshold"]),
                    "tpot_attainment": _attainment(rows, "TPOT", limits["tpot_threshold"]),
                }
                for q, limits in splitwise.items()
            },
            "slo_profile_dist_serve": {
                "ttft_threshold_ns": thresholds["dist_ttft"],
                "tpot_threshold_ns": thresholds["dist_tpot"],
                "joint_attainment": sum(
                    row["TTFT"] <= thresholds["dist_ttft"] and
                    row["TPOT"] <= thresholds["dist_tpot"]
                    for row in rows
                ) / len(rows),
                "goodput_rps": _throughput([
                    row for row in rows
                    if row["TTFT"] <= thresholds["dist_ttft"] and
                    row["TPOT"] <= thresholds["dist_tpot"]
                ]),
            },
        }

    args.output_base.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "study": "normalized serving SLO analysis",
        "baseline": str(args.baseline.resolve()),
        "baseline_kind": args.baseline_kind,
        "baseline_sample_warning": (
            "baseline has fewer than 10 completed requests; use as a feasibility gate only"
            if len(baseline) < 10 else None
        ),
        "invalid_for_paper": args.baseline_kind != "low_load" or len(baseline) < 10,
        "baseline_request_count": len(baseline),
        "baseline_metrics": baseline_stats,
        "profiles": {
            "SLO_PROFILE_MFS": {"ttft_factor": 3.0,
                                "tpot_factor": args.mfs_tpot_factor},
            "SLO_PROFILE_SPLITWISE": {
                "ttft_factors": {"p50": 2.0, "p90": 3.0, "p99": 6.0},
                "tpot_factors": {"p50": 1.25, "p90": 1.5, "p99": 5.0},
            },
            "SLO_PROFILE_DIST_SERVE": {
                "ttft_factor": args.dist_ttft_factor,
                "tpot_factor": args.dist_tpot_factor,
                "joint_target": 0.90,
            },
        },
        "runs": runs,
    }
    json_path = args.output_base.with_suffix(".json")
    csv_path = args.output_base.with_suffix(".csv")
    md_path = args.output_base.with_suffix(".md")
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        fields = ["run", "metric", "mean_ns", "p50_ns", "p90_ns", "p99_ns",
                  "mfs_ttft_attainment", "mfs_tpot_attainment",
                  "dist_joint_attainment", "dist_goodput_rps"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for label, result in runs.items():
            for metric in METRICS:
                writer.writerow({
                    "run": label,
                    "metric": metric,
                    "mean_ns": result["metrics"][metric]["mean"],
                    "p50_ns": result["metrics"][metric]["p50"],
                    "p90_ns": result["metrics"][metric]["p90"],
                    "p99_ns": result["metrics"][metric]["p99"],
                    "mfs_ttft_attainment": result["slo_profile_mfs"]["ttft_attainment"],
                    "mfs_tpot_attainment": result["slo_profile_mfs"]["tpot_attainment"],
                    "dist_joint_attainment": result["slo_profile_dist_serve"]["joint_attainment"],
                    "dist_goodput_rps": result["slo_profile_dist_serve"]["goodput_rps"],
                })
    with md_path.open("w", encoding="utf-8") as stream:
        stream.write("# Normalized serving SLO analysis\n\n")
        stream.write(f"Baseline kind: `{args.baseline_kind}`. "
                     f"`invalid_for_paper={payload['invalid_for_paper']}`.\n\n")
        if payload["invalid_for_paper"]:
            stream.write("This is a diagnostic gate only: the baseline kind or "
                         "sample size is insufficient for paper SLO claims.\n\n")
        stream.write("| run | requests | TTFT P99 (ms) | TPOT P99 (ms) | joint attainment | goodput (req/s) |\n")
        stream.write("|---|---:|---:|---:|---:|---:|\n")
        for label, result in runs.items():
            stream.write(
                f"| {label} | {result['request_count']} | "
                f"{result['metrics']['TTFT']['p99'] / 1e6:.3f} | "
                f"{result['metrics']['TPOT']['p99'] / 1e6:.3f} | "
                f"{result['slo_profile_dist_serve']['joint_attainment']:.3f} | "
                f"{result['slo_profile_dist_serve']['goodput_rps'] or 0:.3f} |\n")
    print(json.dumps({"json": str(json_path), "csv": str(csv_path),
                      "markdown": str(md_path)}, indent=2))


if __name__ == "__main__":
    main()
