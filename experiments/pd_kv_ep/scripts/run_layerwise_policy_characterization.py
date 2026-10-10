#!/usr/bin/env python3
"""Run one bounded, model-derived layerwise policy-characterization round.

The workload deliberately separates an already-decoding cohort from later
P2D requests.  This makes the measured overlap cross-request and avoids
mistaking a same-request P/D completion barrier for contention.  All bytes
come from the Qwen3 model configuration and GateRouter; this script never
accepts a byte-size override.

This is a FlowSim network characterization driver.  It reports integrated
serving metrics as unavailable rather than deriving TTFT/TPOT/TBT from a
network-only replay.  A completed integrated serving CSV can be joined later
using the same workload manifest.
"""

import argparse
import csv
import json
import math
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BUILDER = ROOT / "experiments/pd_kv_ep/scripts/build_flowsim_motivation.py"
RUNNER = ROOT / "experiments/pd_kv_ep/scripts/run_flowsim_replay.py"
MODEL = ROOT / "configs/model/Qwen/Qwen3-30B-A3B-Instruct-2507.json"
TOPOLOGY = ROOT / "experiments/pd_kv_ep/configs/ns3/two_prefill_6_rank_shared_spine.txt"


# These are targeted follow-ups to the existing 3-Decode/1-P2D result.  The
# total request count is kept at four so every run remains auditable by hand.
# Increasing KV population and burst width is intentional; changing bytes is
# still done only through model input token counts.
SCENARIOS = {
    "ep3_kv1_large_baseline": {
        "why": "Existing layerwise large-KV point; establishes the reference policy ordering.",
        "ep_inputs": [128, 128, 128], "ep_outputs": [128, 128, 128],
        "kv_inputs": [8192], "kv_outputs": [1],
        "kv_arrivals_ns": [100_000_000],
    },
    "ep2_kv2_medium_burst": {
        "why": "Increase concurrent P2D population from one to two while retaining a Decode cohort.",
        "ep_inputs": [128, 128], "ep_outputs": [128, 128],
        "kv_inputs": [512, 512], "kv_outputs": [1, 1],
        "kv_arrivals_ns": [20_000_000, 20_000_000],
    },
    "ep2_kv2_large_burst": {
        "why": "Test whether two moderate/large layerwise handoffs create an EP_FIRST KV-side penalty.",
        "ep_inputs": [128, 128], "ep_outputs": [128, 128],
        "kv_inputs": [2048, 2048], "kv_outputs": [1, 1],
        "kv_arrivals_ns": [60_000_000, 62_000_000],
    },
    "ep1_kv3_medium_sustained": {
        "why": "Test KV-concurrency amplification with three staggered P2D requests and a lighter EP cohort.",
        "ep_inputs": [128], "ep_outputs": [128],
        "kv_inputs": [1024, 1024, 1024], "kv_outputs": [1, 1, 1],
        "kv_arrivals_ns": [20_000_000, 30_000_000, 40_000_000],
    },
    "ep3_kv1_small_early": {
        "why": "Move a small handoff into the Decode-rich interval to test whether EP_FIRST is still KV-neutral.",
        "ep_inputs": [128, 128, 128], "ep_outputs": [128, 128, 128],
        "kv_inputs": [128], "kv_outputs": [1],
        "kv_arrivals_ns": [10_000_000],
    },
    "ep2_kv2_medium_fanin_aligned": {
        "why": "Place two new medium-KV requests in one Decode pool and align layer-0 injection with a recurrent EP window.",
        "ep_inputs": [128, 128], "ep_outputs": [128, 128],
        "kv_inputs": [512, 512], "kv_outputs": [1, 1],
        "kv_arrivals_ns": [20_891_581, 20_891_581],
        "kv_decode_pool": 1,
    },
    "ep2_kv2_large_fanin_aligned": {
        "why": "Test sustained large-KV fan-in on a shared Decode pool after the first round found no path overlap for default pairing.",
        "ep_inputs": [128, 128], "ep_outputs": [128, 128],
        "kv_inputs": [2048, 2048], "kv_outputs": [1, 1],
        "kv_arrivals_ns": [62_806_756, 62_806_756],
        "kv_decode_pool": 1,
    },
    "ep1_kv3_medium_fanin_aligned": {
        "why": "Test three concurrent medium-KV handoffs into one Decode pool against a smaller but persistent EP cohort.",
        "ep_inputs": [128], "ep_outputs": [128],
        "kv_inputs": [1024, 1024, 1024], "kv_outputs": [1, 1, 1],
        "kv_arrivals_ns": [20_674_000, 20_674_000, 20_674_000],
        "kv_decode_pool": 1,
    },
    "ep3_kv1_small_fanin_aligned": {
        "why": "Use the small-KV request at an exact EP overlap point to test the low-pressure side of the policy boundary.",
        "ep_inputs": [128, 128, 128], "ep_outputs": [128, 128, 128],
        "kv_inputs": [128], "kv_outputs": [1],
        "kv_arrivals_ns": [21_049_000],
        "kv_decode_pool": 1,
    },
    "ep2_kv2_large_decodeheavy": {
        "why": "Increase Decode-side EP duty cycle by colocating two active Decode requests in the opposite pool from two large P2D fan-in requests.",
        "ep_inputs": [128, 128], "ep_outputs": [128, 128],
        "ep_decode_pool": 0,
        "kv_inputs": [8192, 8192], "kv_outputs": [1, 1],
        "kv_arrivals_ns": [60_737_000, 60_737_000],
        "kv_decode_pool": 1,
    },
    "ep1_kv3_large_decodeheavy": {
        "why": "Test whether three large layerwise P2D handoffs create an EP_FIRST KV completion cost against a sustained shared-link EP stream.",
        "ep_inputs": [128], "ep_outputs": [128],
        "ep_decode_pool": 0,
        "kv_inputs": [8192, 8192, 8192], "kv_outputs": [1, 1, 1],
        "kv_arrivals_ns": [60_737_000, 60_737_000, 60_737_000],
        "kv_decode_pool": 1,
    },
}


def _nearest(values, quantile=0.99):
    values = sorted(float(value) for value in values)
    if not values:
        return None
    return values[max(0, math.ceil(quantile * len(values)) - 1)]


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _write_workload(path, spec):
    rows = []
    for index, (input_toks, output_toks) in enumerate(
            zip(spec["ep_inputs"], spec["ep_outputs"])):
        rows.append({
            "request_id": "ep-%d" % index,
            "input_toks": input_toks,
            "output_toks": output_toks,
            "arrival_time_ns": 0,
            "emit_p2d": False,
            "emit_ep": True,
            "workload_role": "active_decode_cohort",
            "decode_pool": spec.get("ep_decode_pool"),
        })
    for index, (input_toks, output_toks, arrival) in enumerate(zip(
            spec["kv_inputs"], spec["kv_outputs"], spec["kv_arrivals_ns"])):
        rows.append({
            "request_id": "kv-%d" % index,
            "input_toks": input_toks,
            "output_toks": output_toks,
            "arrival_time_ns": arrival,
            "emit_p2d": True,
            "emit_ep": False,
            "workload_role": "new_p2d_request",
            "decode_pool": spec.get("kv_decode_pool"),
        })
    rows.sort(key=lambda row: (int(row["arrival_time_ns"]), row["request_id"]))
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, separators=(",", ":")) + "\n")


def _run(command, log_path):
    completed = subprocess.run(
        command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, check=True,
    )
    log_path.write_text(completed.stdout, encoding="utf-8")


def _merge(intervals):
    merged = []
    for start, end in sorted((int(a), int(b)) for a, b in intervals if b > a):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _intersection(left, right):
    total = 0
    i = j = 0
    while i < len(left) and j < len(right):
        start = max(left[i][0], right[j][0])
        end = min(left[i][1], right[j][1])
        if end > start:
            total += end - start
        if left[i][1] <= right[j][1]:
            i += 1
        else:
            j += 1
    return total


def _link_overlap(flow_rows):
    by_link = {"KV_MOVEMENT": defaultdict(list), "EP": defaultdict(list)}
    for row in flow_rows:
        traffic = "KV_MOVEMENT" if row["event_type"] in (
            "P2D_KV", "REMOTE_KV_FETCH") else "EP"
        try:
            start = int(row["start_ns"])
            end = int(row["end_ns"])
        except (KeyError, TypeError, ValueError):
            continue
        for link in str(row.get("path", "")).split(";"):
            if link:
                by_link[traffic][link].append((start, end))
    mixed = 0
    overlap_ns = 0
    union_ns = 0
    for link in set(by_link["KV_MOVEMENT"]) | set(by_link["EP"]):
        kv = _merge(by_link["KV_MOVEMENT"].get(link, []))
        ep = _merge(by_link["EP"].get(link, []))
        if not kv or not ep:
            continue
        overlap = _intersection(kv, ep)
        union = sum(end - start for start, end in _merge(kv + ep))
        if overlap > 0:
            mixed += 1
            overlap_ns += overlap
            union_ns += union
    return mixed, overlap_ns / union_ns if union_ns else 0.0


def _max_concurrency(intervals):
    points = []
    for start, end in intervals:
        if end <= start:
            continue
        points.append((int(start), 1))
        points.append((int(end), -1))
    active = maximum = 0
    for _, delta in sorted(points, key=lambda item: (item[0], item[1])):
        active += delta
        maximum = max(maximum, active)
    return maximum


def _flow_stats(run_dir, requests):
    flows = _read_csv(run_dir / "flows.csv")
    metrics = _read_csv(run_dir / "request_metrics.csv")
    collectives = _read_csv(run_dir / "collectives.csv")
    p2d_ids = {row["request_id"] for row in requests if row.get("emit_p2d") == "True"}
    kv_metrics = [row for row in metrics if row["request_id"] in p2d_ids and
                  int(row.get("kv_flow_count", 0) or 0) > 0]
    kv_fct = [int(row["kv_fct_ns"]) for row in kv_metrics]
    kv_queue = [int(row["kv_queueing_ns"]) for row in kv_metrics]
    ep_cct = [int(row["cct_ns"]) for row in collectives]
    ep_queue = [int(row["queueing_ns"]) for row in collectives]
    kv_intervals = []
    for row in kv_metrics:
        kv_intervals.append((int(row["kv_actual_start_ns"]),
                             int(row["kv_completion_time_ns"])))
    active_kv = _max_concurrency(kv_intervals)
    mixed_links, overlap_fraction = _link_overlap(flows)
    max_queue = 0
    telemetry = run_dir / "link_telemetry.jsonl"
    if telemetry.is_file():
        for line in telemetry.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            max_queue = max(max_queue, int(json.loads(line).get("queue_bytes", 0)))
    return {
        "ep_collective_count": len(ep_cct),
        "ep_cct_p99_ms": (_nearest(ep_cct) / 1e6) if ep_cct else None,
        "ep_queueing_p99_ms": (_nearest(ep_queue) / 1e6) if ep_queue else None,
        "kv_request_count": len(kv_metrics),
        "kv_fct_p99_ms": (_nearest(kv_fct) / 1e6) if kv_fct else None,
        "kv_queueing_p99_ms": (_nearest(kv_queue) / 1e6) if kv_queue else None,
        "kv_bytes": sum(int(row.get("kv_bytes", 0) or 0) for row in kv_metrics),
        "active_kv_request_max": active_kv,
        "mixed_link_count": mixed_links,
        "mixed_link_time_fraction": overlap_fraction,
        "max_residual_fluid_queue_mb": max_queue / 1e6,
        "integrated_serving_metrics": "NOT_AVAILABLE_NETWORK_ONLY",
    }


def _run_scenario(round_root, workload_root, name, spec, python):
    scenario_root = round_root / name
    if scenario_root.exists():
        shutil.rmtree(scenario_root)
    scenario_root.mkdir(parents=True)
    workload_path = workload_root / (name + ".jsonl")
    workload_path.parent.mkdir(parents=True, exist_ok=True)
    _write_workload(workload_path, spec)
    workload_rows = [
        json.loads(line)
        for line in workload_path.read_text(encoding="utf-8").splitlines()
    ]
    manifest = {
        "schema_version": 1,
        "round": round_root.name,
        "scenario": name,
        "why": spec["why"],
        "request_count": len(workload_rows),
        "pd_kv_transfer_mode": "LAYERWISE",
        "model": "Qwen/Qwen3-30B-A3B-Instruct-2507",
        "topology": str(TOPOLOGY),
        "link_gbps": 200,
        "synthetic_byte_override": False,
        "serving_scope": "network characterization; integrated serving metrics are not inferred",
        "requests": workload_rows,
    }
    (scenario_root / "workload_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    _run([
        python, str(BUILDER), "--trace", str(workload_path), "--count",
        str(len(workload_rows)), "--pd-kv-transfer-mode", "LAYERWISE",
        "--output-dir", str(scenario_root / "ledger"), "--link-gbps", "200",
    ], scenario_root / "build.log")
    ledger = scenario_root / "ledger"
    controls = {
        "full_fair": ("FAIR", "FULL"),
        "full_ep_first": ("EP_FIRST", "FULL"),
        "full_kv_first": ("KV_FIRST", "FULL"),
        "kv_only": ("FAIR", "KV_ONLY"),
        "ep_only": ("FAIR", "EP_ONLY"),
    }
    for run_name, (policy, traffic_class) in controls.items():
        output = scenario_root / run_name
        _run([
            python, str(RUNNER), "--events", str(ledger / "events.csv"),
            "--requests", str(ledger / "requests.csv"), "--topology", str(TOPOLOGY),
            "--output-dir", str(output), "--policy", policy,
            "--traffic-class", traffic_class,
        ], output.with_suffix(".log"))
    request_rows = _read_csv(ledger / "requests.csv")
    runs = {}
    for run_name in controls:
        runs[run_name] = _flow_stats(scenario_root / run_name, request_rows)
    ep_only = runs["ep_only"]["ep_cct_p99_ms"]
    kv_only = runs["kv_only"]["kv_fct_p99_ms"]
    for run_name in ("full_fair", "full_ep_first", "full_kv_first"):
        row = runs[run_name]
        row["ep_slowdown_vs_ep_only"] = (
            row["ep_cct_p99_ms"] / ep_only - 1.0
            if row["ep_cct_p99_ms"] is not None and ep_only else None)
        row["kv_slowdown_vs_kv_only"] = (
            row["kv_fct_p99_ms"] / kv_only - 1.0
            if row["kv_fct_p99_ms"] is not None and kv_only else None)
    for run_name in ("kv_only", "ep_only"):
        runs[run_name]["ep_slowdown_vs_ep_only"] = 0.0 if run_name == "ep_only" else None
        runs[run_name]["kv_slowdown_vs_kv_only"] = 0.0 if run_name == "kv_only" else None
    payload = {
        "scenario": name,
        "why": spec["why"],
        "workload_manifest": str((scenario_root / "workload_manifest.json").resolve()),
        "runs": runs,
        "policy_ordering": {
            "ep_protection": sorted(
                ((name, value["ep_slowdown_vs_ep_only"])
                 for name, value in runs.items()
                 if value.get("ep_slowdown_vs_ep_only") is not None),
                key=lambda item: item[1]),
            "kv_protection": sorted(
                ((name, value["kv_slowdown_vs_kv_only"])
                 for name, value in runs.items()
                 if value.get("kv_slowdown_vs_kv_only") is not None),
                key=lambda item: item[1]),
        },
    }
    (scenario_root / "summary.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _append_report(report_path, round_name, payloads):
    if not report_path.exists():
        report_path.write_text(
            "# KV/EP Policy Characterization\n\n"
            "All primary runs use Qwen3 model-derived bytes, 200-Gbps FlowSim, "
            "and `--pd-kv-transfer-mode LAYERWISE`. FlowSim queue values are "
            "residual fluid backlog, not packet-buffer occupancy. Network-only "
            "TTFT/TBT/SLO values are intentionally unavailable.\n\n",
            encoding="utf-8")
    lines = [
        "\n## Round %s\n" % round_name,
        "This round was selected from the prior layerwise result: one large P2D "
        "request produced strong EP slowdown but no meaningful EP_FIRST KV cost, "
        "so this round increases P2D population, burst width, or temporal overlap "
        "without changing the model or injecting synthetic bytes.\n",
    ]
    for payload in payloads:
        name = payload["scenario"]
        lines.extend([
            "### %s\n" % name,
            "Why: %s\n" % payload["why"],
            "| run | EP CCT P99 (ms) | EP slowdown | KV FCT P99 (ms) | KV slowdown | EP queue P99 (ms) | KV queue P99 (ms) | max fluid queue (MB) | mixed links |\n",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|\n",
        ])
        for run_name in ("ep_only", "kv_only", "full_fair", "full_ep_first", "full_kv_first"):
            row = payload["runs"][run_name]
            def fmt(value, suffix="", fraction=False):
                if value is None:
                    return "n/a"
                shown = 100.0 * value if fraction else value
                return "%.3f%s" % (shown, suffix)
            lines.append(
                "| %s | %s | %s | %s | %s | %s | %s | %s | %d |\n" % (
                    run_name, fmt(row.get("ep_cct_p99_ms")),
                    fmt(row.get("ep_slowdown_vs_ep_only"), "%", True),
                    fmt(row.get("kv_fct_p99_ms")),
                    fmt(row.get("kv_slowdown_vs_kv_only"), "%", True),
                    fmt(row.get("ep_queueing_p99_ms")),
                    fmt(row.get("kv_queueing_p99_ms")),
                    fmt(row.get("max_residual_fluid_queue_mb")),
                    int(row.get("mixed_link_count", 0)),
                ))
        fair = payload["runs"]["full_fair"]
        ep_first = payload["runs"]["full_ep_first"]
        kv_first = payload["runs"]["full_kv_first"]
        ep_first_kv = ep_first.get("kv_slowdown_vs_kv_only")
        kv_first_ep = kv_first.get("ep_slowdown_vs_ep_only")
        crossover = (ep_first_kv is not None and kv_first_ep is not None and
                     ep_first_kv > 0.05 and kv_first_ep > 0.05)
        lines.extend([
            "\nObserved crossover candidate: **%s**. " % ("yes" if crossover else "not yet"),
            "EP_FIRST KV penalty = %s; KV_FIRST EP penalty = %s.\n" % (
                "n/a" if ep_first_kv is None else "%.3f%%" % (100 * ep_first_kv),
                "n/a" if kv_first_ep is None else "%.3f%%" % (100 * kv_first_ep)),
            "The corresponding serving-level TTFT/TPOT/TBT/SLO fields are **not available "
            "from this network-only round**.\n",
        ])
    # A machine-readable next-step suggestion keeps the iteration evidence based.
    max_epfirst_kv = max(
        (p["runs"]["full_ep_first"].get("kv_slowdown_vs_kv_only") or 0)
        for p in payloads)
    max_kvfirst_ep = max(
        (p["runs"]["full_kv_first"].get("ep_slowdown_vs_ep_only") or 0)
        for p in payloads)
    if max_epfirst_kv < 0.05:
        next_step = "Increase concurrent/staggered P2D population or move to a sustained KV backlog; EP_FIRST has not paid a measurable KV cost yet."
    elif max_kvfirst_ep < 0.05:
        next_step = "Increase Decode cohort size/output duration or select a Decode-dense window; KV_FIRST has not produced an EP tail yet."
    else:
        next_step = "Refine the nearest crossover boundary with intermediate KV arrivals and input lengths before considering any larger topology."
    lines.extend(["\nNext autonomous step: %s\n" % next_step])
    with report_path.open("a", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", default="round1")
    parser.add_argument("--scenario", action="append", choices=tuple(SCENARIOS))
    parser.add_argument("--output-root", type=Path,
                        default=ROOT / "experiments/pd_kv_ep/results/flowsim_characterization")
    parser.add_argument("--workload-root", type=Path,
                        default=ROOT / "experiments/pd_kv_ep/workloads/characterization")
    parser.add_argument("--report", type=Path,
                        default=ROOT / "experiments/pd_kv_ep/CHARACTERIZATION_REPORT.md")
    args = parser.parse_args()
    selected = args.scenario or list(SCENARIOS)
    round_root = args.output_root / args.round
    round_root.mkdir(parents=True, exist_ok=True)
    payloads = []
    for name in selected:
        payloads.append(_run_scenario(round_root, args.workload_root / args.round,
                                      name, SCENARIOS[name], sys.executable))
    _append_report(args.report, args.round, payloads)
    print(json.dumps({"round": args.round, "scenarios": selected,
                      "report": str(args.report.resolve())}, indent=2))


if __name__ == "__main__":
    main()
