#!/usr/bin/env python3
"""Summarize request-level serving metrics for a matched policy slice."""

import argparse
import csv
import json
import math
from pathlib import Path


METRICS = (
    "TTFT", "TPOT", "ITL", "latency", "queuing_delay",
    "p2d_kv_ready_time_ns", "decode_first_token_time_ns", "decode_TTFT",
)
POLICIES = ("FAIR", "EP_FIRST", "KV_FIRST")
POLICY_SUFFIX = {"FAIR": "fair", "EP_FIRST": "epfirst", "KV_FIRST": "kvfirst"}


def _values(path, field):
    values = []
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            try:
                value = float(row[field])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(value):
                values.append(value)
    return values


def _request_rows(path, policy, run_id):
    rows = []
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            record = {"policy": policy, "run_id": run_id}
            for field in (
                    "request id", "input", "output", "arrival", "end_time",
                    "latency", "queuing_delay", "TTFT", "TPOT", "ITL",
                    "prefill_completion_time_ns", "p2d_kv_ready_time_ns",
                    "decode_admit_time_ns", "decode_first_token_time_ns",
                    "decode_TTFT"):
                record[field.replace(" ", "_")] = row.get(field, "")
            rows.append(record)
    return rows


def _p99(values):
    if not values:
        return None
    # A nearest-rank p99 is intentionally used for tiny matched slices: with
    # two requests it is the slower request, not an interpolated value.
    return sorted(values)[max(0, math.ceil(0.99 * len(values)) - 1)]


def _stats(values):
    if not values:
        return {"count": 0, "mean": None, "p50": None, "p99": None, "max": None}
    ordered = sorted(values)
    return {
        "count": len(values),
        "mean": sum(values) / len(values),
        "p50": ordered[(len(ordered) - 1) // 2],
        "p99": _p99(values),
        "max": max(values),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path,
                        default=Path("experiments/pd_kv_ep/results/real_trace"))
    parser.add_argument("--run-prefix", default="s64_burstgpt_offset0_2_serving_ns3")
    parser.add_argument("--output-base", type=Path,
                        default=Path("experiments/pd_kv_ep/results/real_trace/"
                                     "serving_policy_comparison_burstgpt_2req"))
    parser.add_argument("--trace-window", default="BurstGPT 30s__window_062460, first two requests")
    parser.add_argument("--run-name-suffix", default="_suppressed",
                        help="suffix appended after the policy name, e.g. _suppressed")
    args = parser.parse_args()

    rows = []
    request_rows = []
    details = {}
    run_manifests = {}
    for policy in POLICIES:
        run_id = f"{args.run_prefix}_{POLICY_SUFFIX[policy]}{args.run_name_suffix}"
        path = args.input_root / f"{run_id}.requests.csv"
        if not path.is_file():
            raise SystemExit(f"missing request CSV for {policy}: {path}")
        manifest_path = args.input_root / f"{run_id}.manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
        run_manifests[policy] = manifest
        policy_stats = {field: _stats(_values(path, field)) for field in METRICS}
        details[policy] = {
            "run_id": run_id,
            "requests_csv": str(path.resolve()),
            "manifest": str(manifest_path.resolve()) if manifest_path.is_file() else None,
            "backend": manifest.get("backend", "unknown"),
            "status": manifest.get("status", "unknown"),
            "request_count": manifest.get("simulated_request_count"),
            "wall_time_s": (
                manifest["finished_at_unix"] - manifest["started_at_unix"]
                if manifest.get("finished_at_unix") is not None and manifest.get("started_at_unix") is not None
                else None
            ),
            "metrics": policy_stats,
        }
        request_rows.extend(_request_rows(path, policy, run_id))
        for field, stats in policy_stats.items():
            rows.append({
                "policy": policy,
                "run_id": run_id,
                "metric": field,
                **stats,
            })

    fair = details["FAIR"]["metrics"]
    for row in rows:
        baseline = fair[row["metric"]]["p99"]
        row["p99_ratio_vs_fair"] = (
            row["p99"] / baseline if row["p99"] is not None and baseline else None
        )

    args.output_base.parent.mkdir(parents=True, exist_ok=True)
    csv_path = args.output_base.with_suffix(".csv")
    json_path = args.output_base.with_suffix(".json")
    md_path = args.output_base.with_suffix(".md")
    request_csv_path = args.output_base.with_name(args.output_base.name + "_requests.csv")
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with request_csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(request_rows[0]))
        writer.writeheader()
        writer.writerows(request_rows)
    payload = {
        "study": "matched serving policy slice",
        "run_prefix": args.run_prefix,
        "request_count": len(request_rows) // len(POLICIES),
        "backend": "native_ns3",
        "trace_window": args.trace_window,
        "cluster": "S64, Qwen3-30B-A3B, TP2 P/D, Decode EP16, 200 Gbps",
        "ep_semantics": "A2A_P2P",
        "pd_kv_mode": "POST_PREFILL",
        "pd_receiver_mode": "ACTUAL",
        "packet_payload_size": run_manifests.get("FAIR", {}).get("packet_payload_size"),
        "telemetry": "none; compact serving logs",
        "note": "Two-request native ns-3 serving evidence; not a large-scale SLO claim.",
        "policies": details,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with md_path.open("w", encoding="utf-8") as stream:
        stream.write("# Matched serving policy comparison\n\n")
        stream.write(f"{args.trace_window}, S64, Qwen3-30B-A3B, TP2 P/D, Decode EP16, "
                     "native ns-3 backend, A2A_P2P, actual Decode receiver. "
                     "P99 is nearest-rank; with two requests it equals the slower request.\n\n")
        stream.write("This is bounded request-level serving evidence and is not extrapolated "
                     "to large-scale SLO attainment.\n\n")
        stream.write("| metric | FAIR P99 | EP_FIRST P99 | EP_FIRST/FAIR | KV_FIRST P99 | KV_FIRST/FAIR |\n")
        stream.write("|---|---:|---:|---:|---:|---:|\n")
        for field in METRICS:
            values = {}
            for policy in POLICIES:
                values[policy] = details[policy]["metrics"][field]["p99"]
            base = values["FAIR"]
            def fmt(value):
                if value is None:
                    return "n/a"
                if field.endswith("_ns") or field in {"TTFT", "TPOT", "ITL", "latency", "queuing_delay", "decode_TTFT"}:
                    return f"{value / 1e6:.3f}"
                return f"{value:.3f}"
            def ratio(value):
                return "n/a" if value is None or not base else f"{value / base:.3f}x"
            stream.write(f"| {field} | {fmt(base)} | {fmt(values['EP_FIRST'])} | "
                         f"{ratio(values['EP_FIRST'])} | {fmt(values['KV_FIRST'])} | "
                         f"{ratio(values['KV_FIRST'])} |\n")
        stream.write("\nSource manifests keep the compact-log and policy provenance:\n\n")
        for policy in POLICIES:
            stream.write(f"- `{details[policy]['run_id']}.manifest.json`\n")
        stream.write(f"\nPer-request metrics: `{request_csv_path.name}`.\n")
    print(json.dumps({
        "csv": str(csv_path),
        "json": str(json_path),
        "markdown": str(md_path),
        "requests_csv": str(request_csv_path),
    }, indent=2))


if __name__ == "__main__":
    main()
