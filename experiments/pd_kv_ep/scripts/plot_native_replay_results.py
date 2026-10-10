#!/usr/bin/env python3
"""Create compact paper-facing figures from completed native replay analyses.

The input summaries are network-only counterfactuals.  The figures preserve
the packet payload and timing-model metadata in the accompanying CSV so that
they cannot be mistaken for closed-loop TTFT/TPOT measurements.
"""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = ROOT / "experiments/pd_kv_ep/figures/real_trace"


def _load(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _slug(value):
    return "".join(char if char.isalnum() else "_" for char in value).strip("_").lower()


def _write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _summary_rows(summary_paths):
    rows = []
    for label, path in summary_paths:
        summary = _load(path)
        rows.append((label, path, summary))
    return rows


def _comparison_rows(summaries):
    rows = []
    for label, path, summary in summaries:
        scenario_dir = Path(summary["scenario_dir"])
        run_manifest = scenario_dir / "network_run_manifest.json"
        payload = ""
        telemetry = ""
        if run_manifest.exists():
            run = _load(run_manifest)
            payload = run.get("packet_payload_size", 1000)
            telemetry = run.get("telemetry_interval_ms", 1000.0)
        replay_manifest = scenario_dir / "replay_manifest.json"
        ep_bin_us = ""
        if replay_manifest.exists():
            ep_bin_us = _load(replay_manifest).get("ep_bin_us", "")
        ep = summary.get("ep_collective_cct_ns", {})
        kv = summary.get("kv_request_completion_ns", {})
        rows.append({
            "workload": label,
            "traffic_class": summary["traffic_class"],
            "kv_subtype": summary.get("kv_subtype", "P2D"),
            "p2d_bytes": summary.get("p2d_bytes", 0),
            "remote_kv_bytes": summary.get("remote_kv_bytes", 0),
            "remote_kv_blocks": summary.get("remote_kv_blocks", 0),
            "scale": summary["scale"],
            "request_count": summary["request_count"],
            "packet_payload_size": payload,
            "telemetry_interval_ms": telemetry,
            "ep_bin_us": ep_bin_us,
            "ep_p99_ms": "" if ep.get("p99") is None else ep["p99"] / 1e6,
            "kv_p99_ms": "" if kv.get("p99") is None else kv["p99"] / 1e6,
            "ep_collective_count": summary["ep_collective_count"],
            "kv_request_count": summary["kv_request_count_with_p2d"],
            "overlap_pairs": summary["directed_link_overlap"]["pair_count"],
            "overlap_links": summary["directed_link_overlap"]["link_count"],
            "completion_coverage": summary["completion_coverage"],
            "timing_model": summary["timing_model"]["kind"],
        })
    return rows


def _matched(rows):
    by_workload = defaultdict(dict)
    for row in rows:
        by_workload[row["workload"]][row["traffic_class"]] = row
    output = []
    for workload, values in by_workload.items():
        full = values.get("FULL", {})
        ep = values.get("EP_ONLY", {})
        kv = values.get("KV_ONLY", {})
        full_ep = float(full["ep_p99_ms"]) if full.get("ep_p99_ms") != "" else math.nan
        ep_only = float(ep["ep_p99_ms"]) if ep.get("ep_p99_ms") != "" else math.nan
        full_kv = float(full["kv_p99_ms"]) if full.get("kv_p99_ms") != "" else math.nan
        kv_only = float(kv["kv_p99_ms"]) if kv.get("kv_p99_ms") != "" else math.nan
        output.append({
            "workload": workload,
            "kv_subtype": full.get("kv_subtype", "P2D"),
            "p2d_bytes": full.get("p2d_bytes", 0),
            "remote_kv_bytes": full.get("remote_kv_bytes", 0),
            "remote_kv_blocks": full.get("remote_kv_blocks", 0),
            "packet_payload_size": full.get("packet_payload_size", ""),
            "ep_bin_us": full.get("ep_bin_us", ""),
            "ep_only_p99_ms": ep_only,
            "full_ep_p99_ms": full_ep,
            "ep_slowdown_pct": (full_ep / ep_only - 1.0) * 100.0,
            "kv_only_p99_ms": kv_only,
            "full_kv_p99_ms": full_kv,
            "kv_slowdown_pct": (full_kv / kv_only - 1.0) * 100.0,
            "overlap_pairs": int(full.get("overlap_pairs", 0)),
            "overlap_links": int(full.get("overlap_links", 0)),
        })
    return output


def _save(fig, output, stem):
    fig.tight_layout()
    fig.savefig(output / (stem + ".png"), dpi=220, bbox_inches="tight")
    fig.savefig(output / (stem + ".pdf"), bbox_inches="tight")
    plt.close(fig)


def _plot_performance(output, matched):
    labels = [row["workload"] for row in matched]
    positions = list(range(len(labels)))
    width = 0.36
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.2))
    ep_only = [row["ep_only_p99_ms"] for row in matched]
    full_ep = [row["full_ep_p99_ms"] for row in matched]
    axes[0].bar([p - width / 2 for p in positions], ep_only, width, label="EP_ONLY")
    axes[0].bar([p + width / 2 for p in positions], full_ep, width, label="FULL")
    axes[0].set_ylabel("EP CCT P99 (ms)")
    axes[0].set_title("Decode EP impact")
    axes[0].legend(frameon=False)
    axes[0].set_xticks(positions)
    axes[0].set_xticklabels(labels, rotation=18, ha="right")
    axes[1].bar(positions, [row["ep_slowdown_pct"] for row in matched], color="#c44e52")
    axes[1].axhline(20.0, color="black", linestyle="--", linewidth=1, label="20% reference")
    axes[1].set_ylabel("FULL EP P99 slowdown (%)")
    axes[1].set_title("KV movement attribution")
    axes[1].set_xticks(positions)
    axes[1].set_xticklabels(labels, rotation=18, ha="right")
    axes[1].legend(frameon=False)
    payloads = sorted({row.get("packet_payload_size") for row in matched
                       if row.get("packet_payload_size") not in (None, "")})
    bins = sorted({row.get("ep_bin_us") for row in matched
                   if row.get("ep_bin_us") not in (None, "")})
    payload_text = ", ".join(f"{value} B" for value in payloads) or "unknown packet size"
    bin_text = ", ".join(f"{float(value) / 1000:g} ms" for value in bins) or "unknown EP bin"
    fig.suptitle("Native ns-3 model-derived replay; network metric only\n"
                 f"EP bin = {bin_text}, packet payload = {payload_text}")
    _save(fig, output, "native_replay_performance")


def _plot_overlap(output, matched):
    labels = [row["workload"] for row in matched]
    positions = list(range(len(labels)))
    width = 0.36
    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    ax2 = ax.twinx()
    pairs = ax.bar([p - width / 2 for p in positions],
                   [row["overlap_pairs"] for row in matched], width,
                   label="overlap pairs", color="#4c72b0")
    links = ax2.bar([p + width / 2 for p in positions],
                    [row["overlap_links"] for row in matched], width,
                    label="directed links", color="#dd8452")
    ax.set_ylabel("Overlapping KV/EP flow pairs", color="#4c72b0")
    ax2.set_ylabel("Shared directed links", color="#dd8452")
    ax.set_title("Exact KV/EP directed-link overlap")
    ax.set_xticks(positions)
    ax.set_xticklabels(labels, rotation=18, ha="right")
    ax.legend([pairs, links], ["overlap pairs", "directed links"], frameon=False)
    fig.suptitle("Completed flow intervals only; overlap is not offered-demand co-arrival")
    _save(fig, output, "native_replay_overlap")


def _write_hotspots(output, summary_paths):
    rows = []
    for label, summary_path in summary_paths:
        path = summary_path.parent / "directed_link_overlap_summary.csv"
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                rows.append({"workload": label, **row})
    if rows:
        _write_csv(output / "native_replay_hotspots.csv", rows, list(rows[0]))


def _timeline_rows(summary_path, bin_ns):
    timeline_path = summary_path.parent / "timeline.csv"
    with timeline_path.open(newline="", encoding="utf-8") as stream:
        events = list(csv.DictReader(stream))
    end_ns = max((int(row["end"]) for row in events), default=0)
    rows = []
    for begin in range(0, end_ns + bin_ns, bin_ns):
        finish = begin + bin_ns
        kv_bits = 0.0
        ep_bits = 0.0
        for event in events:
            start = int(event["start"])
            end = int(event["end"])
            overlap = max(0, min(end, finish) - max(start, begin))
            if overlap <= 0:
                continue
            contribution = int(event["bytes"]) * 8.0 * overlap / float(bin_ns)
            if event["event_type"] in {"P2D_KV", "REMOTE_KV_FETCH"}:
                kv_bits += contribution
            elif event["event_type"].startswith("EP_"):
                ep_bits += contribution
        rows.append({
            "bin_start_ms": begin / 1e6,
            "bin_end_ms": finish / 1e6,
            "kv_gbps": kv_bits / 1e9,
            "ep_gbps": ep_bits / 1e9,
        })
    return rows


def _plot_timeline(output, label, summary_path, bin_ns):
    rows = _timeline_rows(summary_path, bin_ns)
    slug = _slug(label)
    fields = ["bin_start_ms", "bin_end_ms", "kv_gbps", "ep_gbps"]
    _write_csv(output / ("native_replay_timeline_" + slug + ".csv"), rows, fields)
    fig, ax = plt.subplots(figsize=(10.5, 4.2))
    x = [row["bin_start_ms"] for row in rows]
    kv_line = ax.step(x, [row["kv_gbps"] for row in rows], where="post",
                      label="P2D KV", color="#4c72b0")[0]
    ep_axis = ax.twinx()
    ep_line = ep_axis.step(x, [row["ep_gbps"] for row in rows], where="post",
                           label="Decode EP", color="#dd8452")[0]
    ax.set_xlabel("Replay time (ms)")
    ax.set_ylabel("P2D KV average traffic (Gbps)", color="#4c72b0")
    ep_axis.set_ylabel("Decode EP average traffic (Gbps)", color="#dd8452")
    ax.set_title(label + " traffic timeline")
    ax.legend([kv_line, ep_line], ["P2D KV", "Decode EP"], frameon=False,
              loc="upper right")
    scenario = _load(summary_path)
    run_manifest = Path(scenario["scenario_dir"]) / "network_run_manifest.json"
    payload = _load(run_manifest).get("packet_payload_size", "unknown") if run_manifest.exists() else "unknown"
    fig.suptitle(f"Native completed-flow intervals; {bin_ns / 1e6:g}-ms bins; "
                 f"model-derived bytes; packet payload = {payload} B")
    _save(fig, output, "native_replay_timeline_" + slug)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--analysis", action="append", nargs=2, metavar=("LABEL", "SUMMARY"),
                        required=True, help="label and FULL summary.json; repeat per workload")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--bin-ms", type=float, default=100.0)
    args = parser.parse_args()
    if args.bin_ms <= 0:
        parser.error("--bin-ms must be positive")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    summary_paths = [(label, Path(path).resolve()) for label, path in args.analysis]
    summaries = []
    for label, full_path in summary_paths:
        summaries.append((label, full_path, _load(full_path)))
        full_dir = full_path.parent
        for sibling in ("EP_ONLY", "KV_ONLY"):
            candidates = list(full_dir.parent.glob("*/summary.json"))
            for candidate in candidates:
                data = _load(candidate)
                if data.get("traffic_class") == sibling:
                    summaries.append((label, candidate, data))
                    break
    rows = _comparison_rows(summaries)
    _write_csv(output / "native_replay_comparison.csv", rows,
               list(rows[0]) if rows else ["workload"])
    matched = _matched(rows)
    _write_csv(output / "native_replay_matched_summary.csv", matched, list(matched[0]))
    _write_csv(output / "native_replay_performance.csv", matched, list(matched[0]))
    _plot_performance(output, matched)
    _plot_overlap(output, matched)
    _write_hotspots(output, summary_paths)
    for label, path in summary_paths:
        _plot_timeline(output, label, path, int(args.bin_ms * 1e6))
    print(json.dumps({"output_dir": str(output), "workloads": [row["workload"] for row in matched],
                      "figures": ["native_replay_performance", "native_replay_overlap"]}, indent=2))


if __name__ == "__main__":
    main()
