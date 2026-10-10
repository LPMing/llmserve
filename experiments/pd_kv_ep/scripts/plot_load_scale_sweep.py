#!/usr/bin/env python3
"""Plot a native load-scale sweep without implying serving-level SLOs."""

import argparse
import csv
import shutil
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = ROOT / (
    "experiments/pd_kv_ep/results/real_trace/"
    "load_scale_sweep_burstgpt_16/load_scale_sweep.csv")
DEFAULT_OUTPUT = ROOT / "experiments/pd_kv_ep/figures/real_trace"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--stem", default="load_scale_burstgpt_16")
    args = parser.parse_args()
    rows = list(csv.DictReader(args.input.open(newline="", encoding="utf-8")))
    if not rows:
        raise SystemExit("load-scale CSV is empty")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    csv_output = output / f"{args.stem}.csv"
    shutil.copyfile(args.input, csv_output)

    load = [float(row["load_scale"]) for row in rows]
    ep = [float(row["ep_slowdown"]) for row in rows]
    kv = [float(row["kv_slowdown"]) for row in rows]
    pairs = [float(row["full_overlap_pairs"]) for row in rows]
    links = [float(row["full_overlap_links"]) for row in rows]
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.8))
    axes[0].plot(load, ep, marker="o", label="EP P99 slowdown")
    axes[0].plot(load, kv, marker="s", label="KV P99 slowdown")
    axes[0].axhline(1.0, color="black", linewidth=0.8)
    axes[0].set_xlabel("Offered load scale")
    axes[0].set_ylabel("FULL / isolated")
    axes[0].set_title("Network slowdown")
    axes[0].set_xticks(load)
    axes[0].legend(frameon=False)
    axes[1].plot(load, pairs, marker="o", label="overlap pairs")
    axes[1].plot(load, links, marker="s", label="directed links")
    axes[1].set_xlabel("Offered load scale")
    axes[1].set_ylabel("Count")
    axes[1].set_title("Exact completed-flow overlap")
    axes[1].set_xticks(load)
    axes[1].legend(frameon=False)
    fig.suptitle("BurstGPT 062460, S64 native replay; network metrics only")
    fig.tight_layout()
    fig.savefig(output / f"{args.stem}.png", dpi=220, bbox_inches="tight")
    fig.savefig(output / f"{args.stem}.pdf", bbox_inches="tight")
    plt.close(fig)
    print({"csv": str(csv_output), "png": str(output / f"{args.stem}.png"),
           "pdf": str(output / f"{args.stem}.pdf")})


if __name__ == "__main__":
    main()
