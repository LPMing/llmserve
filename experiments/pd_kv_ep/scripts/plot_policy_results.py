#!/usr/bin/env python3
"""Plot native data-plane policy tradeoffs from policy_comparison.csv."""

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    with args.input.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    by_case = defaultdict(dict)
    for row in rows:
        by_case[row["case"]][row["policy"]] = row
    cases = list(by_case)
    policies = ["FAIR", "EP_FIRST", "KV_FIRST"]
    positions = list(range(len(cases)))
    width = 0.24
    args.output_dir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    colors = {"FAIR": "#4c72b0", "EP_FIRST": "#55a868", "KV_FIRST": "#c44e52"}
    for index, policy in enumerate(policies):
        offset = (index - 1) * width
        ep = [float(by_case[case][policy]["ep_ratio_vs_ep_only"]) for case in cases]
        kv = [float(by_case[case][policy]["kv_ratio_vs_kv_only"]) for case in cases]
        axes[0].bar([pos + offset for pos in positions], ep, width,
                    label=policy, color=colors[policy])
        axes[1].bar([pos + offset for pos in positions], kv, width,
                    label=policy, color=colors[policy])
    for ax, title, ylabel in (
            (axes[0], "Decode EP protection", "EP CCT P99 / EP_ONLY"),
            (axes[1], "KV-side cost", "KV completion P99 / KV_ONLY")):
        ax.axhline(1.0, color="black", linewidth=1, linestyle="--")
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.set_xticks(positions)
        ax.set_xticklabels(cases, rotation=18, ha="right")
        ax.legend(frameon=False)
    fig.suptitle("Native ns-3 data-plane policy tradeoff; S64, EP16, 1,000-B packets")
    fig.tight_layout()
    fig.savefig(args.output_dir / "policy_comparison.png", dpi=220, bbox_inches="tight")
    fig.savefig(args.output_dir / "policy_comparison.pdf", bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
