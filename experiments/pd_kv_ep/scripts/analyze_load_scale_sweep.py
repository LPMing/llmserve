#!/usr/bin/env python3
"""Aggregate matched FULL/KV_ONLY/EP_ONLY load-scale replays.

Each group is an identical trace slice and topology at one offered-load
factor.  The script deliberately consumes the native completed-flow
artifacts through ``analyze_model_derived_replay`` so EP latency remains a
collective-level metric and no request/control-plane claim is inferred from
the standalone network replay.
"""

import argparse
import csv
import json
import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from analyze_model_derived_replay import analyze


def _parse_group(spec):
    try:
        label, paths = spec.split("=", 1)
        full, kv, ep = paths.split(",")
        load_scale = float(label)
    except ValueError as exc:
        raise ValueError(
            "group must be LOAD_SCALE=FULL_DIR,KV_ONLY_DIR,EP_ONLY_DIR") from exc
    if not math.isfinite(load_scale) or load_scale <= 0:
        raise ValueError(f"invalid load scale: {label}")
    return load_scale, {
        "FULL": Path(full),
        "KV_ONLY": Path(kv),
        "EP_ONLY": Path(ep),
    }


def _ratio(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _p99(summary, field):
    return summary[field].get("p99")


def _summarize_group(load_scale, dirs, output_root):
    summaries = {}
    for traffic_class, directory in dirs.items():
        directory = directory.resolve()
        if not (directory / "replay_manifest.json").is_file():
            raise FileNotFoundError(f"missing replay_manifest.json: {directory}")
        if not (directory / "network_run_manifest.json").is_file():
            raise FileNotFoundError(f"missing network_run_manifest.json: {directory}")
        summaries[traffic_class] = analyze(
            directory, output_root / f"load_{load_scale:g}" / traffic_class)

    full = summaries["FULL"]
    kv = summaries["KV_ONLY"]
    ep = summaries["EP_ONLY"]
    full_ep_p99 = _p99(full, "ep_collective_cct_ns")
    ep_only_p99 = _p99(ep, "ep_collective_cct_ns")
    full_kv_p99 = _p99(full, "kv_request_completion_ns")
    kv_only_p99 = _p99(kv, "kv_request_completion_ns")
    return {
        "load_scale": load_scale,
        "trace": full.get("scenario_dir"),
        "request_count": full["request_count"],
        "packet_payload_size": full["packet_payload_size"],
        "telemetry_interval_ms": full["telemetry_interval_ms"],
        "full_event_coverage": full["completion_coverage"],
        "kv_only_event_coverage": kv["completion_coverage"],
        "ep_only_event_coverage": ep["completion_coverage"],
        "full_ep_collective_count": full["ep_collective_count"],
        "ep_only_collective_count": ep["ep_collective_count"],
        "full_kv_request_count": full["kv_request_count_with_movement"],
        "kv_only_request_count": kv["kv_request_count_with_movement"],
        "full_ep_p50_ns": full["ep_collective_cct_ns"].get("p50"),
        "full_ep_p99_ns": full_ep_p99,
        "ep_only_ep_p99_ns": ep_only_p99,
        "ep_slowdown": _ratio(full_ep_p99, ep_only_p99),
        "full_kv_p50_ns": full["kv_request_completion_ns"].get("p50"),
        "full_kv_p99_ns": full_kv_p99,
        "kv_only_kv_p99_ns": kv_only_p99,
        "kv_slowdown": _ratio(full_kv_p99, kv_only_p99),
        "full_overlap_pairs": full["directed_link_overlap"]["pair_count"],
        "full_overlap_links": full["directed_link_overlap"]["link_count"],
        "full_max_overlap_ns": full["directed_link_overlap"]["max_overlap_ns"],
        "full_p2d_bytes": full["p2d_bytes"],
        "full_ep_bytes": full.get("ep_bytes", 0),
        "full_summary": full,
        "kv_only_summary": kv,
        "ep_only_summary": ep,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--group", action="append", required=True,
        help="LOAD_SCALE=FULL_DIR,KV_ONLY_DIR,EP_ONLY_DIR; repeat per load")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    groups = [_parse_group(spec) for spec in args.group]
    rows = []
    details = []
    for load_scale, directories in sorted(groups, key=lambda item: item[0]):
        item = _summarize_group(load_scale, directories, output_dir / "per_group")
        details.append(item)
        row = {key: value for key, value in item.items()
               if not key.endswith("_summary")}
        rows.append(row)

    csv_path = output_dir / "load_scale_sweep.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    json_path = output_dir / "load_scale_sweep.json"
    json_path.write_text(json.dumps(details, indent=2) + "\n", encoding="utf-8")
    md_path = output_dir / "load_scale_sweep.md"
    with md_path.open("w", encoding="utf-8") as stream:
        stream.write("# Native load-scale sweep\n\n")
        stream.write("These are S64 native network replays on matched trace slices. "
                     "EP P99 is collective-level; TTFT/TPOT are not inferred.\n\n")
        stream.write("| load | EP P99 FULL (us) | EP P99 EP_ONLY (us) | EP slowdown | "
                     "KV P99 FULL (us) | KV P99 KV_ONLY (us) | KV slowdown | "
                     "overlap pairs | overlap links | coverage |\n")
        stream.write("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n")
        for row in rows:
            def us(value):
                return "" if value is None else f"{value / 1000.0:.3f}"
            def ratio(value):
                return "" if value is None else f"{value:.4f}x"
            stream.write(
                f"| {row['load_scale']:g} | {us(row['full_ep_p99_ns'])} | "
                f"{us(row['ep_only_ep_p99_ns'])} | {ratio(row['ep_slowdown'])} | "
                f"{us(row['full_kv_p99_ns'])} | {us(row['kv_only_kv_p99_ns'])} | "
                f"{ratio(row['kv_slowdown'])} | {row['full_overlap_pairs']} | "
                f"{row['full_overlap_links']} | {row['full_event_coverage']:.3f} |\n")
        stream.write("\nThe replay manifest records packet payload, telemetry cadence, "
                     "load scale, and interval scale for provenance.\n")
    print(json.dumps({
        "groups": len(rows),
        "csv": str(csv_path),
        "json": str(json_path),
        "markdown": str(md_path),
    }, indent=2))


if __name__ == "__main__":
    main()
