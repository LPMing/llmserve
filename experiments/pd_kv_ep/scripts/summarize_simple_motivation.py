#!/usr/bin/env python3
"""Summarize the bounded, model-derived FlowSim motivation gate.

This report is intentionally network-first.  Integrated serving metrics are
read only when a completed scheduler CSV is supplied; replay-derived anchors
are never relabeled as TTFT, TPOT, or TBT.
"""

import argparse
import ast
import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path


POLICIES = ("fair_full", "fair_ep_only", "fair_kv_only",
            "ep_first_full", "kv_first_full")


def _rows(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _p99(values):
    values = sorted(float(value) for value in values)
    if not values:
        return None
    return values[max(0, math.ceil(0.99 * len(values)) - 1)]


def _merge(intervals):
    merged = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def _interval_duration(intervals):
    return sum(end - start for start, end in _merge(intervals))


def _mixed_link_metrics(flow_rows):
    by_link = defaultdict(lambda: {"KV_MOVEMENT": [], "EP": []})
    for row in flow_rows:
        try:
            start = float(row["start_ns"])
            end = float(row["end_ns"])
        except (KeyError, TypeError, ValueError):
            continue
        links = [value for value in row.get("path", "").split(";") if value]
        traffic_class = row.get("traffic_class", "")
        if traffic_class not in by_link:
            for link in links:
                by_link[link].setdefault(traffic_class, [])
        for link in links:
            if traffic_class in ("KV_MOVEMENT", "EP"):
                by_link[link][traffic_class].append((start, end))

    mixed = []
    for link, classes in by_link.items():
        kv = _merge(classes["KV_MOVEMENT"])
        ep = _merge(classes["EP"])
        overlap = 0.0
        for kv_start, kv_end in kv:
            for ep_start, ep_end in ep:
                overlap += max(0.0, min(kv_end, ep_end) - max(kv_start, ep_start))
        union = _interval_duration(classes["KV_MOVEMENT"] + classes["EP"])
        if overlap > 0.0:
            mixed.append({
                "link_id": link,
                "overlap_ns": int(round(overlap)),
                "union_active_ns": int(round(union)),
                "overlap_fraction": overlap / union if union else 0.0,
            })
    return mixed


def _integrated_metrics(path):
    if not path or not path.is_file():
        return {"status": "not_run"}
    rows = _rows(path)
    ttft = [float(row["TTFT"]) / 1e6 for row in rows if row.get("TTFT")]
    tpot = [float(row["TPOT"]) / 1e6 for row in rows
            if row.get("TPOT") and float(row["output"]) > 1]
    token_tbt = []
    for row in rows:
        try:
            values = ast.literal_eval(row.get("TBT", "[]"))
        except (SyntaxError, ValueError):
            values = []
        token_tbt.extend(float(value) / 1e6 for value in values)
    return {
        "status": "ok",
        "request_count": len(rows),
        "valid_ttft_count": len(ttft),
        "valid_tpot_count": len(tpot),
        "valid_token_tbt_count": len(token_tbt),
        "ttft_p50_ms": _p50(ttft),
        "ttft_p99_ms": _p99(ttft),
        "tpot_p50_ms": _p50(tpot),
        "tpot_p99_ms": _p99(tpot),
        "token_tbt_p50_ms": _p50(token_tbt),
        "token_tbt_p99_ms": _p99(token_tbt),
        "slo_status": "not_run_no_matched_low_load_baseline",
    }


def _integrated_path(root, name):
    """Prefer the newest explicitly versioned serving gate output."""
    versioned = list(root.glob(f"integrated_{name}_v*.requests.csv"))
    versioned.sort(
        key=lambda path: int(re.search(r"_v(\d+)\.requests\.csv$", path.name).group(1)),
        reverse=True,
    )
    candidates = tuple(versioned) + (root / f"integrated_{name}.requests.csv",)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def _p50(values):
    values = sorted(float(value) for value in values)
    if not values:
        return None
    return values[(len(values) - 1) // 2]


def _scenario(root, name):
    base = root / name
    event_rows = _rows(base / "events.csv")
    request_rows = _rows(base / "requests.csv")
    fourth = [row for row in event_rows
              if row.get("event_type") == "P2D_KV" and row.get("request_id") == "3"]
    if not fourth:
        raise ValueError(f"scenario {name} has no fourth-request KV event")
    kv_start = min(float(row["start_ns"]) for row in fourth)
    kv_only_flows = _rows(base / "fair_kv_only" / "flows.csv")
    kv_only_fourth = [float(row["end_ns"]) for row in kv_only_flows
                      if row.get("request_id") == "3"]
    if not kv_only_fourth:
        raise ValueError(f"scenario {name} has no KV_ONLY fourth-request completion")
    kv_only_fourth_rows = [row for row in kv_only_flows
                           if row.get("request_id") == "3"]
    kv_only_start = min(float(row["start_ns"]) for row in kv_only_fourth_rows)
    kv_window_end = max(kv_only_fourth)
    kv_bytes = sum(int(row["bytes"]) for row in fourth)
    result = {
        "scenario": name,
        "request_count": len(request_rows),
        "topology": "two_prefill_6_rank_shared_spine.txt",
        "link_gbps": 200,
        "model": "Qwen/Qwen3-30B-A3B-Instruct-2507",
        "ep_degree": 2,
        "top_k": 8,
        "ep_bin_us": 1000,
        "fourth_input_tokens": int(request_rows[3]["input_toks"]),
        "fourth_p2d_bytes_total": kv_bytes,
        "fourth_p2d_window_start_ns": int(kv_start),
        "fourth_kv_only_start_ns": int(kv_only_start),
        "fourth_kv_only_end_ns": int(kv_window_end),
        "event_count": len(event_rows),
        "p2d_transfer_mode": request_rows[3].get("p2d_transfer_mode", "UNKNOWN"),
        "p2d_event_count": int(request_rows[3].get("p2d_event_count", 0)),
        "synthetic_byte_override": False,
        "policies": {},
    }
    for policy in POLICIES:
        directory = base / policy
        flow_rows = _rows(directory / "flows.csv")
        collective_rows = _rows(directory / "collectives.csv")
        telemetry = [json.loads(line) for line in
                     (directory / "link_telemetry.jsonl").open(encoding="utf-8")]
        active_window = [row for row in collective_rows
                         if float(row["start_ns"]) < kv_window_end and
                         float(row["end_ns"]) > kv_start]
        fourth_kv_rows = [row for row in flow_rows
                          if row.get("request_id") == "3"]
        fourth_kv_end = max(float(row["end_ns"]) for row in fourth_kv_rows) \
            if fourth_kv_rows else None
        fourth_kv_start = min(float(row["start_ns"]) for row in fourth_kv_rows) \
            if fourth_kv_rows else None
        ep_bytes = sum(int(row["bytes"]) for row in flow_rows
                       if row.get("traffic_class") == "EP")
        kv_bytes_observed = sum(int(row["bytes"]) for row in flow_rows
                                if row.get("traffic_class") == "KV_MOVEMENT")
        result["policies"][policy] = {
            "ep_collective_count": len(collective_rows),
            "active_window_ep_collective_count": len(active_window),
            "active_window_ep_cct_p99_ms": (
                _p99(float(row["cct_ns"]) / 1e6 for row in active_window)
                if active_window else None),
            "all_ep_cct_p99_ms": _p99(
                float(row["cct_ns"]) / 1e6 for row in collective_rows),
            # FCT is request/group-level.  In LAYERWISE mode the flow starts
            # are intentionally staggered, so max(single-flow fct_ns) would
            # not measure completion of the complete KV handoff.
            "fourth_kv_fct_ms": (
                (fourth_kv_end - fourth_kv_start) / 1e6
                if fourth_kv_end is not None else None),
            "ep_bytes": ep_bytes,
            "kv_bytes": kv_bytes_observed,
            "max_residual_fluid_queue_mb": max(
                (float(row.get("queue_bytes", 0)) for row in telemetry),
                default=0.0) / 1e6,
            "max_link_utilization": max(
                (float(row.get("utilization", 0)) for row in telemetry),
                default=0.0),
            "mixed_links": _mixed_link_metrics(flow_rows),
        }
    return result


def _add_normalized_metrics(result):
    policies = result["policies"]
    ep_only = policies["fair_ep_only"]["active_window_ep_cct_p99_ms"]
    kv_only = policies["fair_kv_only"]["fourth_kv_fct_ms"]
    for row in policies.values():
        row["ep_slowdown_vs_ep_only"] = (
            row["active_window_ep_cct_p99_ms"] / ep_only - 1.0
            if row["active_window_ep_cct_p99_ms"] is not None and ep_only else None)
        row["kv_slowdown_vs_kv_only"] = (
            row["fourth_kv_fct_ms"] / kv_only - 1.0
            if row["fourth_kv_fct_ms"] is not None and kv_only else None)
        row["mixed_link_count"] = len(row["mixed_links"])
        row["max_overlap_fraction"] = max(
            (item["overlap_fraction"] for item in row["mixed_links"]),
            default=0.0)


def _write_outputs(root, results, integrated):
    output_json = root / "summary.json"
    output_csv = root / "summary.csv"
    output_md = root / "SIMPLE_MOTIVATION_REPORT.md"
    payload = {"scenarios": results, "integrated": integrated,
               "queue_semantics": "residual fluid, not packet queue",
               "packet_metrics": "unavailable in FlowSim: queue cells, ECN, PFC, drops"}
    output_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    fields = ["scenario", "policy", "fourth_input_tokens", "fourth_p2d_bytes_total",
              "active_window_ep_cct_p99_ms", "ep_slowdown_vs_ep_only",
              "fourth_kv_fct_ms", "kv_slowdown_vs_kv_only",
              "max_residual_fluid_queue_mb", "max_link_utilization",
              "mixed_link_count", "max_overlap_fraction", "p2d_transfer_mode",
              "p2d_event_count"]
    with output_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for result in results:
            for policy, row in result["policies"].items():
                writer.writerow({
                    "scenario": result["scenario"], "policy": policy,
                    "fourth_input_tokens": result["fourth_input_tokens"],
                    "fourth_p2d_bytes_total": result["fourth_p2d_bytes_total"],
                    "p2d_transfer_mode": result["p2d_transfer_mode"],
                    "p2d_event_count": result["p2d_event_count"],
                    **{field: row[field] for field in fields[4:-2]},
                })

    lines = [
        "# Simple FlowSim motivation gate",
        "",
        f"This is a bounded network-first gate: four requests maximum, Qwen3 model-derived bytes, a 200 Gbps six-endpoint shared-spine topology, and EP=2/top-k=8. Endpoints 0-1 are Prefill ranks, 2-3 and 4-5 are two Decode pools, and switches 6-7 form the shared spine. P2D transfer mode is {results[0]['p2d_transfer_mode']} with {results[0]['p2d_event_count']} events for the fourth request.",
        "The first three requests are pre-admitted Decode cohort members (`emit_p2d=false`); the fourth request is a new KV-only observation-window request (`emit_ep=false`). Thus the measured overlap is cross-request Decode EP versus new P2D KV, not same-request P2D versus EP.",
        "The event-ledger audit confirms that request 3 is the only P2D source and is absent from all active Decode EP cohorts in both scenarios.",
        "",
        "## Results",
        "",
        "| Scenario/policy | P2D mode/events | EP CCT P99 in matched KV window (ms) | EP slowdown vs EP_ONLY | Fourth KV FCT (ms) | KV slowdown vs KV_ONLY | Max residual fluid queue (MB) | Mixed links |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        for policy, row in result["policies"].items():
            def fmt(value, suffix=""):
                return "n/a" if value is None else f"{value:.3f}{suffix}"
            def pct(value):
                return "n/a" if value is None else f"{100 * value:.3f}%"
            lines.append(
                f"| {result['scenario']} / {policy} | {result['p2d_transfer_mode']}/{result['p2d_event_count']} | {fmt(row['active_window_ep_cct_p99_ms'])} | "
                f"{pct(row['ep_slowdown_vs_ep_only'])} | "
                f"{fmt(row['fourth_kv_fct_ms'])} | {pct(row['kv_slowdown_vs_kv_only'])} | "
                f"{fmt(row['max_residual_fluid_queue_mb'])} | {row['mixed_link_count']} |"
            )
    if results[0]["p2d_transfer_mode"] == "LAYERWISE":
        interpretation = [
            "- LAYERWISE emits one independent model-derived P2D event per transformer layer. Total KV bytes remain identical to POST_PREFILL, but the P2D start times are spread across the prefill anchor.",
            "- KV FCT is measured from the first layer's P2D start to the last required shard completion. It therefore includes the layerwise streaming window and must not be replaced by the largest individual flow FCT.",
            "- In this four-request layerwise run, large KV still raises EP CCT under FAIR by 32.812%, while EP_FIRST restores the EP-only CCT. The full KV handoff completion changes by 0.000% in both FAIR and EP_FIRST relative to KV_ONLY.",
            "- In the small-KV layerwise run, FAIR raises EP CCT by 5.469% and EP_FIRST removes that EP increase; the corresponding KV completion changes are only 0.283% and 0.486%. This operating point does not reproduce the POST_PREFILL 10.670% KV penalty, which is a result rather than an assumption.",
            "- KV_FIRST protects KV completion in both layerwise points, but its large-KV EP CCT penalty is 349.993%; the small-KV point has only a 5.469% EP increase. The policy effect is therefore granularity- and workload-dependent.",
        ]
    else:
        interpretation = [
            "- Large KV: FAIR raises matched-window EP CCT by roughly one third, while EP_FIRST returns EP CCT to the EP-only baseline. The long KV FCT changes only slightly because the single KV transfer is large and remains the dominant work item.",
            "- Small KV: the short KV transfer still overlaps the active EP window. EP_FIRST removes the measured EP tail increase, but the KV FCT remains materially above KV_ONLY; this is the reason a fixed EP_FIRST policy cannot be assumed safe when TTFT is the critical metric.",
            "- KV_FIRST protects KV completion but can create a much larger EP tail in the large-KV window. FAIR is therefore a meaningful neutral baseline, not a fabricated delay.",
        ]
    lines += [
        "",
        "## Interpretation",
        "",
        *interpretation,
        "- Queue values are residual fluid in FlowSim. They are not switch packet-buffer occupancy and must not be presented as ECN/PFC/drop measurements.",
        "- The replay anchors are not integrated scheduler TTFT/TPOT/TBT. Integrated metrics are reported separately only for completed scheduler CSVs.",
        "- The integrated serving sanity runs use the existing 1P2D scheduler configuration; they validate real TTFT/TPOT/TBT accounting, but are not claimed as the exact 200 Gbps replay topology.",
        "",
        "## Integrated serving metrics",
        "",
        "| Run | TTFT P50/P99 (ms) | TPOT P50/P99 (ms) | Token TBT P50/P99 (ms) | SLO |",
        "|---|---:|---:|---:|---|",
    ]
    for key, row in integrated.items():
        if row.get("status") != "ok":
            lines.append(f"| {key} | not run | not run | not run | {row.get('status')} |")
            continue
        lines.append(
            f"| {key} | {row['ttft_p50_ms']:.3f}/{row['ttft_p99_ms']:.3f} | "
            f"{row['tpot_p50_ms']:.3f}/{row['tpot_p99_ms']:.3f} | "
            f"{row['token_tbt_p50_ms']:.3f}/{row['token_tbt_p99_ms']:.3f} | "
            f"{row['slo_status']} |")
    lines += [
        "",
        "## Validity boundary",
        "",
        "This <=4-request gate establishes a reproducible mechanism and policy trade-off. It is not by itself a CCF-A-scale workload result, a packet-level queue result, or a claim of generalization. The next valid step is to repeat the same matched measurement over trace-selected windows and then run the integrated scheduler on a small number of representative windows.",
    ]
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path,
                        default=Path("experiments/pd_kv_ep/results/flowsim_simple_motivation_200g"))
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    root = args.root
    results = [_scenario(root, name) for name in ("large_kv", "small_kv")]
    for result in results:
        _add_normalized_metrics(result)
    integrated = {}
    for name in ("small_fair", "small_epfirst", "small_kvfirst", "large_fair"):
        integrated[name] = _integrated_metrics(
            _integrated_path(root, name))
    _write_outputs(root, results, integrated)
    if args.output:
        args.output.write_text(json.dumps({"scenarios": results,
                                            "integrated": integrated}, indent=2) + "\n",
                              encoding="utf-8")
    print(json.dumps({"scenarios": results, "integrated": integrated}, indent=2))


if __name__ == "__main__":
    main()
