#!/usr/bin/env python3
"""Plot the frozen Round-18 controlled prefix-eviction motivation gate."""

import json
from pathlib import Path

import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parent
BASE = ROOT / "candidates/r18_prefix_retention/experiments"
CASES = (
    ("24 fillers\nD hit", BASE / "filler_24/analysis.json"),
    ("28 fillers\nD miss", BASE / "filler_28/analysis.json"),
    ("28 + refresh\nD hit", BASE / "filler_28_refresh/analysis.json"),
)


def main():
    labels = []
    ready, token2, completion, megabytes = [], [], [], []
    for label, path in CASES:
        data = json.loads(path.read_text())
        if data["status"] != "VALID" or data["target_count"] != 2:
            raise ValueError("invalid frozen experiment: " + str(path))
        labels.append(label)
        ready.append(data["target_ready_elapsed_ns"][0] / 1e6)
        token2.append(data["target_token2_elapsed_ns"][0] / 1e6)
        completion.append(data["target_completion_elapsed_ns"][0] / 1e6)
        megabytes.append(data["target_bytes_each"] / 1e6)
    x = range(len(CASES))
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 6.4), sharex=True,
                             gridspec_kw={"height_ratios": [1, 1.5]})
    axes[0].bar(x, megabytes, color=["#3176b5", "#cd5b45", "#3176b5"])
    axes[0].set_ylabel("P2D KV / target (MB)")
    axes[0].set_ylim(0, 320)
    for i, value in enumerate(megabytes):
        axes[0].text(i, value + 5, "%.2f" % value,
                     ha="center", va="bottom", fontsize=9)
    axes[1].plot(x, ready, "o-", label="P2D ready", color="#cd5b45")
    axes[1].plot(x, token2, "s-", label="Second token", color="#7355a1")
    axes[1].plot(x, completion, "^-", label="Completion", color="#258271")
    axes[1].axhline(42.950, color="gray", linestyle="--", linewidth=1,
                    label="Two full-KV cut floor")
    axes[1].set_ylabel("Elapsed from target arrival (ms)")
    axes[1].set_xticks(list(x), labels)
    axes[1].set_ylim(0, 90)
    axes[1].grid(axis="y", alpha=0.2)
    axes[1].legend(loc="upper right", frameon=False, fontsize=9)
    fig.suptitle("Normal Decode eviction exposes a hot-P source cut")
    fig.tight_layout()
    fig.savefig(ROOT / "MOTIVATION_FIGURE.png", dpi=200)
    fig.savefig(ROOT / "MOTIVATION_FIGURE.pdf")
    plt.close(fig)


if __name__ == "__main__":
    main()
