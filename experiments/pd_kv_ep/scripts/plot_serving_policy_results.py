#!/usr/bin/env python3
"""Plot request-level metrics from analyze_serving_policy_results.py."""

import argparse
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


POLICIES = ("FAIR", "EP_FIRST", "KV_FIRST")
METRICS = ("TTFT", "TPOT", "latency", "p2d_kv_ready_time_ns")
COLORS = {"FAIR": "#4c72b0", "EP_FIRST": "#55a868", "KV_FIRST": "#c44e52"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    with args.input.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    selected = {
        (row["policy"], row["metric"]): row
        for row in rows
        if row["metric"] in METRICS
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    figure_csv = args.output_dir / "serving_policy_figure.csv"
    with figure_csv.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["policy", "metric", "p50_ms", "p99_ms", "p99_ratio_vs_fair"],
        )
        writer.writeheader()
        for metric in METRICS:
            for policy in POLICIES:
                row = selected[(policy, metric)]
                scale = 1e6 if metric != "p2d_kv_ready_time_ns" else 1e6
                writer.writerow({
                    "policy": policy,
                    "metric": metric,
                    "p50_ms": float(row["p50"]) / scale,
                    "p99_ms": float(row["p99"]) / scale,
                    "p99_ratio_vs_fair": row["p99_ratio_vs_fair"],
                })

    positions = list(range(len(METRICS)))
    width = 0.24
    fig, ax = plt.subplots(figsize=(10.5, 4.8))
    for index, policy in enumerate(POLICIES):
        offset = (index - 1) * width
        values = [float(selected[(policy, metric)]["p99"]) / 1e6 for metric in METRICS]
        ax.bar(
            [pos + offset for pos in positions],
            values,
            width,
            label=policy,
            color=COLORS[policy],
        )
    ax.set_xticks(positions)
    ax.set_xticklabels(["TTFT", "TPOT", "E2E latency", "P2D KV ready"], rotation=12)
    ax.set_ylabel("P99 (ms)")
    ax.set_title("Native ns-3 serving policy gate: S64, BurstGPT, 2 requests")
    ax.legend(frameon=False, ncol=3)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(args.output_dir / "serving_policy_comparison.png", dpi=220, bbox_inches="tight")
    fig.savefig(args.output_dir / "serving_policy_comparison.pdf", bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
