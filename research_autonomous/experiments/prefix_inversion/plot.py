#!/usr/bin/env python3
"""Plot the measured compute-to-network inversion and P2D-ready plateau."""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def main():
    theory = json.loads((ROOT / "research_autonomous/theory/"
                         "round12_prefix_inversion.json").read_text())
    measured = json.loads((HERE / "summary.json").read_text())
    colors = {1: "#1b9e77", 2: "#d95f02", 4: "#7570b3",
              8: "#e7298a"}
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), layout="constrained")
    for m in (1, 2, 4, 8):
        theoretical = [row for row in theory["rows"]
                       if row["sources"] == m]
        x = [row["prefix_hit_fraction"] * 100 for row in theoretical]
        axes[0].plot(x, [row["source_cut_ratio"] for row in theoretical],
                     "o-", color=colors[m], label="%d P GPUs" % m)
        names = ["p%d_hit%d_miss" % (m, row["prefix_hit_tokens"])
                 for row in theoretical]
        y = []
        for name in names:
            case = measured["cases"][name]
            values = [item["p2d_ready_elapsed_ms"]
                      for item in case["per_request"].values()]
            y.append(sum(values) / len(values))
        axes[1].plot(x, y, "o-", color=colors[m], label="%d P GPUs" % m)
    axes[0].axhline(1, color="black", linewidth=1, linestyle="--")
    axes[0].set(xlabel="Prefill prefix hit (%)",
                ylabel="Source NIC service / profiled layer compute",
                title="Theory: source cut crosses compute")
    axes[0].set_yscale("log")
    axes[0].legend(frameon=False, fontsize=8)
    axes[1].set(xlabel="Prefill prefix hit (%)",
                ylabel="Target P2D-ready after arrival (ms)",
                title="FlowSim: source-NIC latency floor")
    axes[1].legend(frameon=False, fontsize=8)
    for axis in axes:
        axis.grid(alpha=0.2)
    fig.savefig(HERE / "prefix_inversion.pdf")
    fig.savefig(HERE / "prefix_inversion.png", dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    main()
