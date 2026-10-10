#!/usr/bin/env python3
"""Summarize model-derived FlowSim motivation runs.

The replay request metric is intentionally named ``ttft_data_plane_proxy_ns``
by the runner.  This script never relabels it as integrated scheduler TTFT.
It reports the network-side EP/KV counterfactuals and the policy trade-off.
"""

import argparse
import csv
import json
import math
from pathlib import Path


def _read(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _p99(values):
    values = sorted(float(value) for value in values)
    if not values:
        return None
    return values[max(0, math.ceil(0.99 * len(values)) - 1)]


def _metric(path, column):
    rows = _read(path / "request_metrics.csv")
    return _p99(row[column] for row in rows)


def _scenario_row(root, scenario):
    base = root / scenario
    required = {
        "fair_full": base / "fair_full",
        "fair_ep_only": base / "fair_ep_only",
        "fair_kv_only": base / "fair_kv_only",
        "ep_first_full": base / "ep_first_full",
        "kv_first_full": base / "kv_first_full",
    }
    missing = [str(path) for path in required.values()
               if not (path / "request_metrics.csv").is_file()]
    if missing:
        return {"scenario": scenario, "status": "MISSING: " + ";".join(missing)}

    ep_only = _metric(required["fair_ep_only"], "max_ep_cct_ns")
    kv_only = _metric(required["fair_kv_only"], "kv_completion_time_ns")
    result = {
        "scenario": scenario,
        "status": "ok",
        "fair_ep_p99_ms": _metric(required["fair_full"], "max_ep_cct_ns") / 1e6,
        "ep_only_p99_ms": ep_only / 1e6,
        "ep_first_ep_p99_ms": _metric(required["ep_first_full"], "max_ep_cct_ns") / 1e6,
        "fair_kv_p99_ms": _metric(required["fair_full"], "kv_completion_time_ns") / 1e6,
        "kv_only_p99_ms": kv_only / 1e6,
        "ep_first_kv_p99_ms": _metric(required["ep_first_full"], "kv_completion_time_ns") / 1e6,
        "kv_first_ep_p99_ms": _metric(required["kv_first_full"], "max_ep_cct_ns") / 1e6,
        "kv_first_kv_p99_ms": _metric(required["kv_first_full"], "kv_completion_time_ns") / 1e6,
        "fair_ttft_proxy_p99_ms": _metric(required["fair_full"], "ttft_data_plane_proxy_ns") / 1e6,
        "ep_first_ttft_proxy_p99_ms": _metric(required["ep_first_full"], "ttft_data_plane_proxy_ns") / 1e6,
    }
    result.update({
        "fair_ep_slowdown": result["fair_ep_p99_ms"] / (ep_only / 1e6),
        "ep_first_ep_gain_vs_fair": 1.0 - result["ep_first_ep_p99_ms"] / result["fair_ep_p99_ms"],
        "fair_kv_slowdown": result["fair_kv_p99_ms"] / (kv_only / 1e6),
        "ep_first_kv_penalty_vs_kv_only": result["ep_first_kv_p99_ms"] / (kv_only / 1e6) - 1.0,
        "kv_first_ep_slowdown_vs_ep_only": result["kv_first_ep_p99_ms"] / (ep_only / 1e6),
        "kv_first_kv_penalty_vs_kv_only": result["kv_first_kv_p99_ms"] / (kv_only / 1e6) - 1.0,
        "ep_first_ttft_proxy_penalty_vs_fair": result["ep_first_ttft_proxy_p99_ms"] / result["fair_ttft_proxy_p99_ms"] - 1.0,
    })
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path,
        default=Path("experiments/pd_kv_ep/results/flowsim_motivation"))
    parser.add_argument(
        "--scenarios", nargs="+",
        default=["large_kv_tp2", "small_kv_high_conc_tp2", "small_kv_50g"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = [_scenario_row(args.root, scenario) for scenario in args.scenarios]
    fields = sorted({key for row in rows for key in row})
    preferred = ["scenario", "status"]
    fields = preferred + [field for field in fields if field not in preferred]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
