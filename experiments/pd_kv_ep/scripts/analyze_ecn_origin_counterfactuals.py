#!/usr/bin/env python3
"""Analyze local CE origins and matched native ns-3 class-removal replays."""

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


CLASS_BY_EVENT_TYPE = {1: "KV_MOVEMENT", 2: "EP", 3: "EP"}
CLASS_ORDER = ("KV_MOVEMENT", "EP", "OTHER")


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def summarize(values):
    if not values:
        return {"count": 0, "mean_ns": None, "p50_ns": None,
                "p95_ns": None, "p99_ns": None}
    return {
        "count": len(values),
        "mean_ns": sum(values) / len(values),
        "p50_ns": percentile(values, 0.50),
        "p95_ns": percentile(values, 0.95),
        "p99_ns": percentile(values, 0.99),
    }


def sweep(points):
    active = Counter()
    overlap_ns = 0
    peak = Counter()
    deltas = defaultdict(Counter)
    for timestamp, delta in points:
        deltas[timestamp].update(delta)
    previous = None
    for timestamp in sorted(deltas):
        if previous is not None and active["KV_MOVEMENT"] and active["EP"]:
            overlap_ns += timestamp - previous
        for traffic_class, change in deltas[timestamp].items():
            active[traffic_class] += change
            if active[traffic_class] < 0:
                raise ValueError("negative active-flow counter")
            peak[traffic_class] = max(peak[traffic_class], active[traffic_class])
        previous = timestamp
    return overlap_ns, peak


def load_flows(run_dir):
    phases = {}
    with (run_dir / "comm_events.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            event_id = int(row["event_id"])
            if row["phase"] == "START":
                event_type = int(row["event_type"])
                row["traffic_class"] = CLASS_BY_EVENT_TYPE.get(event_type, "OTHER")
                row["issue_ns"] = int(row["issue_time_ns"])
                row["bytes_int"] = int(row["bytes"])
                row["links"] = []
                phases[event_id] = row
            elif row["phase"] == "END" and event_id in phases:
                flow = phases[event_id]
                flow["finish_ns"] = int(row["network_end_ns"])
                flow["network_start_ns"] = int(row["network_start_ns"])
                flow["duration_ns"] = int(row["duration_ns"])
                flow["links"] = [int(value) for value in
                                  row["directed_link_ids"].split(";") if value]
    return [flow for flow in phases.values() if "finish_ns" in flow]


def flow_match_key(flow):
    return (int(flow["request_id"]), int(flow["collective_id"]),
            int(flow["event_type"]), int(flow["layer_id"]), int(flow["src"]),
            int(flow["dst"]), int(flow["bytes_int"]), int(flow["issue_ns"]))


def flow_class_metrics(flows):
    by_class = defaultdict(list)
    for flow in flows:
        by_class[flow["traffic_class"]].append(flow["duration_ns"])
    return {name: summarize(by_class[name]) for name in CLASS_ORDER}


def kv_flow_metrics_by_request(flows):
    by_request = defaultdict(list)
    for flow in flows:
        if flow["traffic_class"] == "KV_MOVEMENT":
            by_request[int(flow["request_id"])].append(flow["duration_ns"])
    return {str(request_id): summarize(values)
            for request_id, values in sorted(by_request.items())}


def request_handoffs(flows):
    by_request = defaultdict(list)
    for flow in flows:
        if flow["traffic_class"] == "KV_MOVEMENT":
            by_request[int(flow["request_id"])].append(flow)
    result = {}
    for request_id, group in by_request.items():
        first_issue = min(item["issue_ns"] for item in group)
        last_release = max(item["issue_ns"] for item in group)
        last_finish = max(item["finish_ns"] for item in group)
        straggler = max(group, key=lambda item: item["finish_ns"])
        result[request_id] = {
            "flow_count": len(group),
            "first_issue_ns": first_issue,
            "last_layer_issue_ns": last_release,
            "last_finish_ns": last_finish,
            "request_handoff_ns": last_finish - first_issue,
            "residual_drain_ns": last_finish - last_release,
            "last_shard_layer": int(straggler["layer_id"]),
            "last_shard_src": int(straggler["src"]),
            "last_shard_dst": int(straggler["dst"]),
            "last_shard_bytes": int(straggler["bytes_int"]),
        }
    return result


def collective_metrics(flows):
    groups = defaultdict(list)
    for flow in flows:
        if flow["traffic_class"] == "EP":
            key = (int(flow["collective_id"]), int(flow["layer_id"]),
                   int(flow["event_type"]))
            groups[key].append(flow)
    ccts = []
    details = {}
    for key, group in groups.items():
        start = min(item["issue_ns"] for item in group)
        finish = max(item["finish_ns"] for item in group)
        cct = finish - start
        ccts.append(cct)
        details["%d:%d:%d" % key] = {
            "flow_count": len(group),
            "start_ns": start,
            "finish_ns": finish,
            "cct_ns": cct,
            "last_flow_event_id": int(max(group, key=lambda item: item["finish_ns"])["event_id"]),
        }
    return summarize(ccts), details


def class_feedback(run_dir, flows):
    exact = {}
    for flow in flows:
        key = (int(flow["src_rank"]), int(flow["dst_rank"]),
               int(flow["port"]), int(flow["bytes_int"]), int(flow["issue_ns"]))
        exact[key] = flow["traffic_class"]
    qp_class = {}
    metrics = defaultdict(Counter)
    unmatched_starts = 0
    unmatched_feedback = Counter()
    path = run_dir / "cc_events.csv"
    if not path.is_file():
        return {"available": False}
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            event = row["event"]
            identity = (int(row["node_id"]), int(row["qp_id"]))
            if event == "QP_START":
                key = (int(row["src_rank"]), int(row["dst_rank"]),
                       int(row["sport"]), int(row["bytes"]),
                       int(row["timestamp"]))
                traffic_class = exact.get(key)
                if traffic_class is None:
                    unmatched_starts += 1
                    continue
                qp_class[identity] = traffic_class
                metrics[traffic_class]["qp_starts"] += 1
            elif event in ("CNP", "RATE"):
                traffic_class = qp_class.get(identity)
                if traffic_class is None:
                    unmatched_feedback[event] += 1
                    continue
                metrics[traffic_class][event.lower() + "_events"] += 1
                if event == "RATE" and int(row["new_rate_bps"]) < int(row["old_rate_bps"]):
                    metrics[traffic_class]["rate_decreases"] += 1
    return {
        "available": True,
        "unmatched_qp_starts": unmatched_starts,
        "unmatched_feedback": dict(unmatched_feedback),
        "by_class": {traffic_class: dict(metrics[traffic_class])
                     for traffic_class in CLASS_ORDER},
    }


def local_mark_counts(run_dir):
    path = run_dir / "local_ecn_marks.csv"
    counts = Counter()
    if not path.is_file():
        return counts
    for row in read_csv(path):
        counts[int(row["link_id"])] += 1
    return counts


def analyze_links(full_dir, flows):
    summary_rows = read_csv(full_dir / "link_summary.csv")
    local_counts = local_mark_counts(full_dir)
    per_link = defaultdict(lambda: {
        "bytes": Counter(), "classes": set(), "points": []})
    for flow in flows:
        traffic_class = flow["traffic_class"]
        for link in flow["links"]:
            item = per_link[link]
            item["bytes"][traffic_class] += flow["bytes_int"]
            item["classes"].add(traffic_class)
            item["points"].append((flow["issue_ns"], {traffic_class: 1}))
            item["points"].append((flow["finish_ns"], {traffic_class: -1}))

    rows = []
    for row in summary_rows:
        link_id = int(row["link_id"])
        cap = int(row["capacity_bps"])
        kmin = (600000 if cap == 200_000_000_000 else
                800000 if cap in (400_000_000_000, 2_400_000_000_000,
                                  7_200_000_000_000) else None)
        queue = int(row["queue_max_bytes"])
        observed_ce = int(row["ecn_marks"])
        new_marks = local_counts[link_id]
        overlap_ns, peak = sweep(per_link[link_id]["points"])
        classes = per_link[link_id]["classes"]
        rows.append({
            "link_id": link_id,
            "src": int(row["src_node"]),
            "dst": int(row["dst_node"]),
            "capacity_bps": cap,
            "local_new_marks": new_marks,
            "CE_carry_through_observations": observed_ce - new_marks,
            "CE_transmit_observations": observed_ce,
            "KV_bytes": per_link[link_id]["bytes"]["KV_MOVEMENT"],
            "EP_bytes": per_link[link_id]["bytes"]["EP"],
            "KV_active": int(peak["KV_MOVEMENT"] > 0),
            "EP_active": int(peak["EP"] > 0),
            "KV_EP_overlap_ns": overlap_ns,
            "peak_active_KV_flows": peak["KV_MOVEMENT"],
            "peak_active_EP_flows": peak["EP"],
            "max_queue_bytes": queue,
            "Kmin_bytes": kmin if kmin is not None else "unknown",
            "mean_utilization": float(row["mean_utilization"]),
            "peak_utilization": float(row["peak_utilization"]),
            "traffic_classes_present": ";".join(
                name for name in CLASS_ORDER if name in classes),
        })
    return rows


def compare_runs(run_dirs):
    loaded = {name: load_flows(path) for name, path in run_dirs.items()}
    by_run = {}
    for name, flows in loaded.items():
        kv = [flow for flow in flows if flow["traffic_class"] == "KV_MOVEMENT"]
        ep = [flow for flow in flows if flow["traffic_class"] == "EP"]
        cct, groups = collective_metrics(flows)
        by_run[name] = {
            "flow_count": len(flows),
            "flow_fct_ns_by_class": flow_class_metrics(flows),
            "kv_flow_fct_ns_by_request": kv_flow_metrics_by_request(flows),
            "kv_request_handoff_ns": summarize(
                [r["request_handoff_ns"] for r in request_handoffs(flows).values()]),
            "kv_request_residual_drain_ns": summarize(
                [r["residual_drain_ns"] for r in request_handoffs(flows).values()]),
            "kv_request_handoffs": request_handoffs(flows),
            "ep_collective_cct_ns": cct,
            "ep_collective_count": len(groups),
            "cc_feedback": class_feedback(run_dirs[name], flows),
        }

    matched = {}
    pairs = (("FULL", "KV_ONLY", "KV_MOVEMENT"),
             ("FULL", "EP_ONLY", "EP"))
    for full_name, isolated_name, traffic_class in pairs:
        if full_name not in loaded or isolated_name not in loaded:
            continue
        full_by_key = defaultdict(list)
        isolated_by_key = defaultdict(list)
        for flow in loaded[full_name]:
            if flow["traffic_class"] == traffic_class:
                full_by_key[flow_match_key(flow)].append(flow)
        for flow in loaded[isolated_name]:
            if flow["traffic_class"] == traffic_class:
                isolated_by_key[flow_match_key(flow)].append(flow)
        keys = set(full_by_key) | set(isolated_by_key)
        missing = sum(abs(len(full_by_key[key]) - len(isolated_by_key[key]))
                      for key in keys)
        full_fct = [flow["duration_ns"] for items in full_by_key.values()
                    for flow in items]
        isolated_fct = [flow["duration_ns"] for items in isolated_by_key.values()
                        for flow in items]
        slowdown = None
        a = summarize(full_fct)["p99_ns"]
        b = summarize(isolated_fct)["p99_ns"]
        if a is not None and b:
            slowdown = a / b - 1.0
        matched["%s_FULL_vs_%s" % (traffic_class, isolated_name)] = {
            "matched_key_count": len(keys) - sum(
                1 for key in keys if not full_by_key[key] or not isolated_by_key[key]),
            "unmatched_flow_rows": missing,
            "full_flow_fct_ns": summarize(full_fct),
            "isolated_flow_fct_ns": summarize(isolated_fct),
            "p99_slowdown_fraction": slowdown,
            "matched_route_mismatch_count": sum(
                1 for key in keys if full_by_key[key] and isolated_by_key[key]
                and full_by_key[key][0]["links"] != isolated_by_key[key][0]["links"]),
            "full_handoffs": by_run[full_name]["kv_request_handoffs"]
            if traffic_class == "KV_MOVEMENT" else None,
            "isolated_handoffs": by_run[isolated_name]["kv_request_handoffs"]
            if traffic_class == "KV_MOVEMENT" else None,
        }

    if "FULL" in loaded and "KV_ONLY" in loaded:
        handoff_full = by_run["FULL"]["kv_request_handoffs"]
        handoff_only = by_run["KV_ONLY"]["kv_request_handoffs"]
        full_by_request = defaultdict(list)
        only_by_request = defaultdict(list)
        for flow in loaded["FULL"]:
            if flow["traffic_class"] == "KV_MOVEMENT":
                full_by_request[int(flow["request_id"])].append(flow)
        for flow in loaded["KV_ONLY"]:
            if flow["traffic_class"] == "KV_MOVEMENT":
                only_by_request[int(flow["request_id"])].append(flow)
        request_comparison = {}
        for request_id in sorted(set(full_by_request) | set(only_by_request)):
            a = full_by_request[request_id]
            b = only_by_request[request_id]
            a_fct = [flow["duration_ns"] for flow in a]
            b_fct = [flow["duration_ns"] for flow in b]
            a_hand = handoff_full.get(request_id)
            b_hand = handoff_only.get(request_id)
            request_comparison[str(request_id)] = {
                "full_flow_count": len(a),
                "isolated_flow_count": len(b),
                "full_flow_fct_ns": summarize(a_fct),
                "isolated_flow_fct_ns": summarize(b_fct),
                "flow_fct_mean_slowdown_fraction": (
                    sum(a_fct) / sum(b_fct) - 1.0 if b_fct and sum(b_fct) else None),
                "flow_fct_p99_slowdown_fraction": (
                    percentile(a_fct, 0.99) / percentile(b_fct, 0.99) - 1.0
                    if a_fct and b_fct and percentile(b_fct, 0.99) else None),
                "full_handoff": a_hand,
                "isolated_handoff": b_hand,
                "handoff_slowdown_fraction": (
                    a_hand["request_handoff_ns"] /
                    b_hand["request_handoff_ns"] - 1.0
                    if a_hand and b_hand and b_hand["request_handoff_ns"] else None),
                "residual_drain_slowdown_fraction": (
                    a_hand["residual_drain_ns"] /
                    b_hand["residual_drain_ns"] - 1.0
                    if a_hand and b_hand and b_hand["residual_drain_ns"] else None),
                "matched_route_mismatch_count": sum(
                    1 for flow_key in set(map(flow_match_key, a)) &
                    set(map(flow_match_key, b))
                    if next(item for item in a if flow_match_key(item) == flow_key)["links"] !=
                    next(item for item in b if flow_match_key(item) == flow_key)["links"]),
            }
        matched["KV_REQUEST_FULL_vs_KV_ONLY"] = request_comparison

    if "FULL" in loaded and "EP_ONLY" in loaded:
        def cct_map(flows):
            groups = defaultdict(list)
            for flow in flows:
                if flow["traffic_class"] == "EP":
                    key = (int(flow["collective_id"]), int(flow["layer_id"]),
                           int(flow["event_type"]))
                    groups[key].append(flow)
            return {key: (max(item["finish_ns"] for item in group) -
                          min(item["issue_ns"] for item in group))
                    for key, group in groups.items()}
        full_ccts = cct_map(loaded["FULL"])
        only_ccts = cct_map(loaded["EP_ONLY"])
        common = set(full_ccts) & set(only_ccts)
        full_values = [full_ccts[key] for key in common]
        only_values = [only_ccts[key] for key in common]
        full_p99 = percentile(full_values, 0.99)
        only_p99 = percentile(only_values, 0.99)
        matched["EP_COLLECTIVE_FULL_vs_EP_ONLY"] = {
            "matched_collective_count": len(common),
            "unmatched_full_collectives": len(set(full_ccts) - common),
            "unmatched_isolated_collectives": len(set(only_ccts) - common),
            "full_cct_ns": summarize(full_values),
            "isolated_cct_ns": summarize(only_values),
            "p99_slowdown_fraction": (
                full_p99 / only_p99 - 1.0 if full_p99 is not None and only_p99 else None),
        }
    return loaded, by_run, matched


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run", action="append", default=[],
                        help="NAME=DIR; repeat for FULL, KV_ONLY, EP_ONLY")
    args = parser.parse_args()
    run_dirs = {}
    for value in args.run:
        name, path = value.split("=", 1)
        run_dirs[name] = Path(path)
    if "FULL" not in run_dirs:
        parser.error("a FULL run is required")

    loaded, by_run, matched = compare_runs(run_dirs)
    link_rows = analyze_links(run_dirs["FULL"], loaded["FULL"])
    output_root = args.output_root
    output_root.mkdir(parents=True, exist_ok=True)
    with (output_root / "LOCAL_ECN_ORIGIN_BY_LINK.csv").open(
            "w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(link_rows[0]),
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(link_rows)

    local_rows = read_csv(run_dirs["FULL"] / "local_ecn_marks.csv")
    local_summary = {
        "local_mark_count": len(local_rows),
        "local_marks_by_link": dict(Counter(int(row["link_id"])
                                             for row in local_rows)),
        "local_marks_by_class": dict(Counter(row["traffic_class"]
                                              for row in local_rows)),
        "local_marks_by_link_class": {
            "%s:%s" % key: count for key, count in Counter(
                (int(row["link_id"]), row["traffic_class"])
                for row in local_rows).items()},
        "local_mark_queue_bytes": summarize(
            [int(row["mmu_egress_bytes_after_dequeue"]) for row in local_rows]),
        "local_mark_rows_below_kmin": sum(
            int(row["mmu_egress_bytes_after_dequeue"]) < int(row["kmin_bytes"])
            for row in local_rows),
        "non_ect_to_ce_count": sum(int(row["ecn_before"]) == 0
                                    for row in local_rows),
        "ect0_to_ce_count": sum(int(row["ecn_before"]) == 2
                                 for row in local_rows),
        "ect1_to_ce_count": sum(int(row["ecn_before"]) == 1
                                 for row in local_rows),
    }
    for name, path in run_dirs.items():
        manifest_path = path / "network_run_manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(manifest_path)
        run_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        by_run[name]["run_manifest"] = run_manifest
        by_run[name]["output_sha256"] = {
            file_name: sha256(path / file_name)
            for file_name in ("replay.conf", "comm_events.csv", "cc_events.csv",
                              "link_summary.csv", "local_ecn_marks.csv")
            if (path / file_name).is_file()}

    result = {
        "experiment": "immutable S8 D8+K2 CC_MODE=1 matched traffic-class ablation",
        "source_event_sha256": sha256(
            Path(json.loads((run_dirs["FULL"] / "network_run_manifest.json")
                            .read_text(encoding="utf-8"))["input_replay_dir"])
            / "events.csv"),
        "runs": by_run,
        "matched_counterfactuals": matched,
        "local_ecn_origin": local_summary,
        "cross_class_ecnp_hypothesis": (
            "FAIL_CLASS_TRIGGERED_CE_ON_PREFILL_KV_ONLY_LINKS"
            if local_summary["local_marks_by_class"].get("KV_MOVEMENT", 0) ==
               local_summary["local_mark_count"] and
               len(local_summary["local_marks_by_link"]) == 1
            else "REQUIRES_LINK_AND_COUNTERFACTUAL_REVIEW"),
        "serving_boundary": (
            "Native ns-3 replays fixed FlowSim issue timestamps; it does not return "
            "packet completion to the serving scheduler. No ns-3 TTFT/TPOT/TBT is inferred."),
    }
    (output_root / "ECN_ORIGIN_COUNTERFACTUAL_ANALYSIS.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "local_ecn_origin": local_summary,
        "cross_class_ecnp_hypothesis": result["cross_class_ecnp_hypothesis"],
        "matched_counterfactuals": {
            key: {name: value for name, value in row.items()
                  if name not in ("full_handoffs", "isolated_handoffs")}
            for key, row in matched.items()},
    }, indent=2))


if __name__ == "__main__":
    main()
