#!/usr/bin/env python3
"""Produce compact paper-facing figures from completed native artifacts.

No experiment result is regenerated here.  The script reads the final matched
result table, the all-exact-shared-link mechanism table, and the declared
topology design.  In particular, it does not interpolate artificial traffic
points or select a link by its observed slowdown.
"""

import argparse
import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POINTS = (
    ("two_prefill_b1_512_a2", "low\n1×512 prompt"),
    ("two_prefill_b1_2048_a2", "medium\n1×2048 prompt"),
    ("two_prefill_b2_2048_a2", "high\n2×2048 prompts"),
)


def rows_by_key(path, key):
    with path.open(newline="", encoding="utf-8") as stream:
        return {row[key]: row for row in csv.DictReader(stream)}


def values(rows, field):
    return [float(rows[label][field]) for label, _ in POINTS]


def labels():
    return [name for _, name in POINTS]


def style():
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "font.size": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.dpi": 160,
    })
    return plt


def figure_validation(plt, rows, output):
    overlap = values(rows, "EP_P99")
    slowdown = values(rows, "EP_P99_slowdown")
    baseline = [value / factor for value, factor in zip(overlap, slowdown)]
    x = list(range(len(POINTS)))
    width = 0.34
    figure, axis = plt.subplots(figsize=(7.3, 4.1))
    axis.bar([i - width / 2 for i in x], [v / 1e3 for v in baseline], width,
             label="isolated control", color="#8fa8c7")
    mixed = axis.bar([i + width / 2 for i in x], [v / 1e3 for v in overlap], width,
                     label="native P2D + Decode EP", color="#d95f5f")
    for bar, factor in zip(mixed, slowdown):
        axis.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.08,
                  "%.3f×" % factor, ha="center", va="bottom", fontsize=9)
    axis.set_xticks(x, labels())
    axis.set_ylabel("matched EP collective P99 CCT (µs)")
    axis.set_title("M1. Native matched validation: KV pressure raises Decode EP tail")
    axis.set_ylim(0, max(v / 1e3 for v in overlap) * 1.20)
    axis.legend(frameon=False, ncol=2, loc="upper left")
    figure.tight_layout()
    figure.savefig(output, bbox_inches="tight")
    plt.close(figure)


def figure_pressure_curve(plt, rows, output):
    ep = values(rows, "EP_P99_slowdown")
    tpot = values(rows, "TPOT_slowdown")
    kv = values(rows, "KV_slowdown")
    kv_mb = [float(rows[label]["KV_bytes"]) / 1024 ** 2 for label, _ in POINTS]
    x = list(range(len(POINTS)))
    figure, (left, right) = plt.subplots(1, 2, figsize=(10.0, 3.9),
                                         gridspec_kw={"width_ratios": [1.15, 1]})
    line = left.plot(x, ep, marker="o", linewidth=2.5, color="#c23b3b",
                     label="EP P99 CCT")
    left.axhline(1.0, color="#777777", linewidth=1, linestyle="--")
    for i, (value, mb) in enumerate(zip(ep, kv_mb)):
        left.annotate("%.0f MiB" % mb, (i, value), xytext=(0, 8),
                      textcoords="offset points", ha="center", fontsize=8)
    left.set_xticks(x, labels())
    left.set_ylabel("normalized to isolated control")
    left.set_title("EP tail response")
    left.set_ylim(0.95, max(ep) * 1.12)
    right.plot(x, tpot, marker="o", linewidth=2, color="#4c78a8",
               label="A Decode TPOT")
    right.plot(x, kv, marker="s", linewidth=2, color="#59a14f",
               label="B P2D completion")
    right.axhline(1.0, color="#777777", linewidth=1, linestyle="--")
    right.set_xticks(x, ["low", "medium", "high"])
    right.set_ylabel("normalized to isolated control")
    right.set_title("Serving / bulk response")
    right.legend(frameon=False, loc="upper left", fontsize=8)
    figure.suptitle("M2. Request-driven pressure points, not synthetic byte sweep", y=1.02)
    figure.tight_layout()
    figure.savefig(output, bbox_inches="tight")
    plt.close(figure)


def figure_link_mechanism(plt, mechanism, rows, output):
    exact = {(row["workload"], row["link_id"]): row for row in mechanism}
    point_labels = ["low", "medium", "high"]
    x = list(range(len(POINTS)))
    figure, (left, right) = plt.subplots(1, 2, figsize=(10.2, 4.1))
    for link_id, color, marker in (("9", "#8fa8c7", "o"), ("12", "#c23b3b", "s")):
        overlap = [float(exact[(label, link_id)]["queue_overlap_mean_bytes"])
                   for label, _ in POINTS]
        baseline = [float(exact[(label, link_id)]["queue_baseline_mean_bytes"])
                    for label, _ in POINTS]
        left.plot(x, baseline, color=color, marker=marker, linestyle="--",
                  alpha=0.65, label="link %s control" % link_id)
        left.plot(x, overlap, color=color, marker=marker, linewidth=2.3,
                  label="link %s mixed" % link_id)
    left.set_yscale("log")
    left.set_xticks(x, point_labels)
    left.set_ylabel("mean queue over exact EP windows (bytes, log scale)")
    left.set_title("All exact shared directed links")
    left.legend(frameon=False, fontsize=7, ncol=2, loc="upper left")
    conc = [float(exact[(label, "12")]["peak_concurrent_kv_flows"])
            for label, _ in POINTS]
    p99 = values(rows, "EP_P99_slowdown")
    bars = right.bar(x, p99, color="#d95f5f", alpha=0.88)
    for bar, count in zip(bars, conc):
        right.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.04,
                   "%d concurrent\nKV flows" % count, ha="center", va="bottom",
                   fontsize=8)
    right.axhline(1.0, color="#777777", linewidth=1, linestyle="--")
    right.set_xticks(x, point_labels)
    right.set_ylim(0.95, max(p99) * 1.16)
    right.set_ylabel("matched EP P99 CCT slowdown")
    right.set_title("Core link 12: 6→7")
    figure.suptitle("M3. Queue mechanism: dual native P2D fan-in creates the tail jump", y=1.02)
    figure.tight_layout()
    figure.savefig(output, bbox_inches="tight")
    plt.close(figure)


def box(axis, xy, width, height, label, color):
    from matplotlib.patches import FancyBboxPatch
    patch = FancyBboxPatch(xy, width, height, boxstyle="round,pad=0.015",
                           linewidth=1.2, edgecolor=color, facecolor="#ffffff")
    axis.add_patch(patch)
    axis.text(xy[0] + width / 2, xy[1] + height / 2, label, ha="center", va="center",
              fontsize=9, color=color)
    return patch


def figure_scale_design(plt, output):
    figure, axis = plt.subplots(figsize=(9.5, 4.7))
    axis.set_xlim(0, 10)
    axis.set_ylim(0, 7)
    axis.axis("off")
    box(axis, (3.0, 5.7), 1.4, 0.65, "Spine 0\n200 Gbps", "#555555")
    box(axis, (5.6, 5.7), 1.4, 0.65, "Spine 1\n200 Gbps", "#555555")
    leaves = [
        (0.5, "Leaf 0\nP0", "#4c78a8"),
        (2.8, "Leaf 1\nP1", "#4c78a8"),
        (5.2, "Leaf 2\nD0", "#f58518"),
        (7.5, "Leaf 3\nD0", "#f58518"),
    ]
    for x, label, color in leaves:
        box(axis, (x, 4.0), 1.45, 0.62, label, color)
        for spine_x in (3.7, 6.3):
            axis.plot([x + 0.725, spine_x], [4.62, 5.7], color="#9a9a9a", linewidth=1)
    boxes = [
        (0.25, "P0\n32 GPUs = 4×8\nservers", "#4c78a8"),
        (2.55, "P1\n32 GPUs = 4×8\nservers", "#4c78a8"),
        (5.1, "D0 half\n32 GPUs = 4×8\nservers", "#f58518"),
        (7.4, "D0 half\n32 GPUs = 4×8\nservers", "#f58518"),
    ]
    for x, label, color in boxes:
        box(axis, (x, 1.9), 1.95, 1.15, label, color)
        axis.plot([x + 0.975, x + 0.975], [3.05, 4.0], color="#9a9a9a", linewidth=1)
    axis.text(5, 1.0,
              "Planned 128 physical-GPU topology; not a measured result.\n"
              "P→D KV naturally crosses leaf/spine; EP=64 naturally crosses Decode leaves.\n"
              "Intra-server NVLink/NVSwitch must remain outside the scale-out fabric.",
              ha="center", va="center", fontsize=9)
    axis.set_title("M4. Planned 2P×32 + 1D×64 leaf-spine topology", fontsize=12)
    figure.tight_layout()
    figure.savefig(output, bbox_inches="tight")
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, default=ROOT / "FINAL_MOTIVATION_TABLE.csv")
    parser.add_argument("--mechanism", type=Path,
                        default=ROOT / "experiments/pd_kv_ep/results/shared_link_mechanism.csv")
    parser.add_argument("--figures", type=Path,
                        default=ROOT / "experiments/pd_kv_ep/figures")
    args = parser.parse_args()
    rows = rows_by_key(args.table, "workload")
    missing = [label for label, _ in POINTS if label not in rows]
    if missing:
        raise SystemExit("missing completed motivation rows: %s" % ", ".join(missing))
    with args.mechanism.open(newline="", encoding="utf-8") as stream:
        mechanism = list(csv.DictReader(stream))
    required_mechanism = {(label, link) for label, _ in POINTS for link in ("9", "12")}
    present = {(row["workload"], row["link_id"]) for row in mechanism}
    if required_mechanism - present:
        raise SystemExit("missing all-link mechanism rows: %s" %
                         sorted(required_mechanism - present))
    args.figures.mkdir(parents=True, exist_ok=True)
    plt = style()
    figure_validation(plt, rows, args.figures / "figure_m1_native_validation.png")
    figure_pressure_curve(plt, rows, args.figures / "figure_m2_pressure_curve.png")
    figure_link_mechanism(plt, mechanism, rows,
                           args.figures / "figure_m3_link_mechanism.png")
    figure_scale_design(plt, args.figures / "figure_m4_scale_design.png")
    print("wrote four figures to", args.figures)


if __name__ == "__main__":
    main()
