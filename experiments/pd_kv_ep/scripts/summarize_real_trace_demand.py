#!/usr/bin/env python3
"""Summarize bounded real-trace demand analyses.

The input is the output of ``analyze_real_trace_demand.py``.  This script is
an arrival/offered-demand summary only: it never labels offered co-arrival as
packet-level link contention or as a latency result.
"""

import argparse
import csv
import json
import math
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = ROOT / "experiments/pd_kv_ep/results/real_trace/demand"
DEFAULT_OUTPUT = ROOT / "experiments/pd_kv_ep/results/real_trace"


def _percentile(values, fraction):
    values = sorted(values)
    if not values:
        return 0.0
    position = (len(values) - 1) * fraction
    left = math.floor(position)
    right = math.ceil(position)
    if left == right:
        return float(values[left])
    return float(values[left] + (values[right] - values[left]) * (position - left))


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _read_one(path):
    summary_path = path / "summary.json"
    with summary_path.open(encoding="utf-8") as stream:
        summary = json.load(stream)
    bins = _read_csv(path / f"bins_{summary['bin_ms']}ms.csv")
    kv = [float(row["kv_gbps_offered"]) for row in bins]
    ep = [float(row["ep_gbps_offered"]) for row in bins]
    total = [float(row["total_offered_gbps"]) for row in bins]
    mixed = [row.get("mixed_offered_demand", "False").lower() == "true" for row in bins]
    row = {
        "label": summary["label"],
        "trace": summary["trace"],
        "source_trace_provenance": ";".join(summary.get("source_trace_provenance", [])),
        "scale": summary["scale"],
        "request_offset": summary["request_offset"],
        "request_count": summary["request_count"],
        "duration_s": summary["duration_ns"] / 1e9,
        "mean_rps": summary["mean_rps"],
        "input_tokens": summary["input_tokens"],
        "output_tokens": summary["output_tokens"],
        "input_p50": summary["input_p50"],
        "input_p95": summary["input_p95"],
        "output_p50": summary["output_p50"],
        "output_p95": summary["output_p95"],
        "kv_tb_model_derived": summary["kv_bytes_model_derived"] / 1e12,
        "ep_tb_model_derived_balanced": summary["ep_bytes_model_derived_balanced"] / 1e12,
        "ep_to_kv_bytes_ratio": (
            summary["ep_bytes_model_derived_balanced"] /
            max(summary["kv_bytes_model_derived"], 1)),
        "ep_collectives": summary["ep_collectives_model_derived"],
        "bin_count": len(bins),
        "mixed_bin_count": sum(mixed),
        "mixed_bin_fraction": sum(mixed) / max(len(bins), 1),
        "kv_gbps_p50": _percentile(kv, 0.50),
        "kv_gbps_p95": _percentile(kv, 0.95),
        "kv_gbps_max": max(kv, default=0.0),
        "ep_gbps_p50": _percentile(ep, 0.50),
        "ep_gbps_p95": _percentile(ep, 0.95),
        "ep_gbps_max": max(ep, default=0.0),
        "total_gbps_p95": _percentile(total, 0.95),
        "total_gbps_max": max(total, default=0.0),
        "timing_status": summary["timing_status"],
        "network_overlap_claim": summary["network_overlap_claim"],
        "synthetic_override": summary["synthetic_override"],
    }
    return row


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _plot(path_prefix, rows):
    # Keep matplotlib's cache out of the user's home directory on shared hosts.
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/llmservingsim-mplconfig")
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    labels = [row["label"] for row in rows]
    positions = list(range(len(rows)))
    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=True)
    width = 0.36
    axes[0].bar(
        [p - width / 2 for p in positions],
        [row["kv_gbps_p95"] for row in rows],
        width=width,
        label="KV movement offered Gbps p95",
    )
    axes[0].bar(
        [p + width / 2 for p in positions],
        [row["ep_gbps_p95"] for row in rows],
        width=width,
        label="Decode EP offered Gbps p95",
    )
    axes[0].set_ylabel("offered Gbps")
    axes[0].set_title("Bounded real-trace demand; model-derived offered load, not packet overlap")
    axes[0].legend(loc="upper left")
    axes[1].bar(positions, [100 * row["mixed_bin_fraction"] for row in rows])
    axes[1].set_ylabel("mixed offered-demand bins (%)")
    axes[1].set_ylim(0, 100)
    axes[1].set_xticks(positions)
    axes[1].set_xticklabels(labels, rotation=35, ha="right")
    axes[1].set_xlabel("trace sample")
    fig.tight_layout()
    path_prefix.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path_prefix.with_suffix(".png"), dpi=160)
    fig.savefig(path_prefix.with_suffix(".pdf"))
    plt.close(fig)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    paths = sorted(path for path in args.input_dir.iterdir()
                   if path.is_dir() and (path / "summary.json").exists())
    if not paths:
        parser.error(f"no demand summaries found under {args.input_dir}")
    rows = [_read_one(path) for path in paths]
    rows.sort(key=lambda row: row["label"])
    csv_path = args.output_dir / "real_trace_demand_summary.csv"
    json_path = args.output_dir / "real_trace_demand_summary.json"
    _write_csv(csv_path, rows)
    payload = {
        "study_stage": "arrival_offered_demand_discovery",
        "network_overlap_claim": "none; native network telemetry is required",
        "synthetic_override": False,
        "rows": rows,
        "artifacts": {
            "csv": str(csv_path),
            "figure_png": str(args.output_dir / "real_trace_demand_summary.png"),
            "figure_pdf": str(args.output_dir / "real_trace_demand_summary.pdf"),
        },
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    plotted = _plot(args.output_dir / "real_trace_demand_summary", rows)
    print(json.dumps({"rows": len(rows), "csv": str(csv_path), "plotted": plotted}, indent=2))


if __name__ == "__main__":
    main()
