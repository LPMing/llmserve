#!/usr/bin/env python3
"""Analyze matched K-request self-contention and DCQCN counterfactuals."""

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


KV_EVENT_TYPE = 1


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
                "p95_ns": None, "p99_ns": None, "max_ns": None}
    return {
        "count": len(values),
        "mean_ns": sum(values) / len(values),
        "p50_ns": percentile(values, .50),
        "p95_ns": percentile(values, .95),
        "p99_ns": percentile(values, .99),
        "max_ns": max(values),
    }


def read_flows(run_dir, request_ids):
    request_ids = set(request_ids)
    phases = {}
    with (run_dir / "comm_events.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            event_id = int(row["event_id"])
            if row["phase"] == "START":
                if (int(row["event_type"]) != KV_EVENT_TYPE or
                        int(row["request_id"]) not in request_ids):
                    continue
                row["event_id_int"] = event_id
                row["request_id_int"] = int(row["request_id"])
                row["event_type_int"] = int(row["event_type"])
                row["collective_id_int"] = int(row["collective_id"])
                row["layer_id_int"] = int(row["layer_id"])
                row["src_int"] = int(row["src_rank"])
                row["dst_int"] = int(row["dst_rank"])
                row["bytes_int"] = int(row["bytes"])
                row["port_int"] = int(row["port"])
                row["issue_ns"] = int(row["issue_time_ns"])
                row["links"] = []
                phases[event_id] = row
            elif row["phase"] == "END" and event_id in phases:
                flow = phases[event_id]
                flow["finish_ns"] = int(row["network_end_ns"])
                flow["network_start_ns"] = int(row["network_start_ns"])
                flow["duration_ns"] = int(row["duration_ns"])
                flow["issue_to_finish_ns"] = flow["finish_ns"] - flow["issue_ns"]
                flow["links"] = [int(value) for value in
                                  row["directed_link_ids"].split(";") if value]
    return [flow for flow in phases.values() if "finish_ns" in flow]


def match_key(flow):
    return (flow["request_id_int"], flow["collective_id_int"],
            flow["event_type_int"], flow["layer_id_int"], flow["src_int"],
            flow["dst_int"], flow["bytes_int"], flow["issue_ns"])


def request_kv_metrics(flows, request_id):
    selected = [flow for flow in flows if flow["event_type_int"] == KV_EVENT_TYPE
                and flow["request_id_int"] == request_id]
    if not selected:
        return None
    last = max(selected, key=lambda flow: (flow["finish_ns"], flow["issue_ns"],
                                          flow["layer_id_int"], flow["src_int"],
                                          flow["dst_int"]))
    first_issue = min(flow["issue_ns"] for flow in selected)
    last_release = max(flow["issue_ns"] for flow in selected)
    last_finish = max(flow["finish_ns"] for flow in selected)
    for flow in selected:
        flow["barrier_slack_ns"] = last_finish - flow["finish_ns"]
    cnp_flows = [flow for flow in selected if flow.get("cnp_events", 0) > 0]
    reduced_flows = [flow for flow in selected
                     if flow.get("rate_decrease_events", 0) > 0]
    return {
        "flow_count": len(selected),
        "bytes": sum(flow["bytes_int"] for flow in selected),
        "first_issue_ns": first_issue,
        "last_layer_release_ns": last_release,
        "last_completion_ns": last_finish,
        "request_handoff_ns": last_finish - first_issue,
        "residual_drain_ns": last_finish - last_release,
        "last_shard": {
            "layer": last["layer_id_int"],
            "src_rank": last["src_int"],
            "dst_rank": last["dst_int"],
            "bytes": last["bytes_int"],
            "issue_ns": last["issue_ns"],
            "finish_ns": last["finish_ns"],
            "duration_ns": last["duration_ns"],
            "issue_to_finish_ns": last["issue_to_finish_ns"],
            "cnp_events": last.get("cnp_events", 0),
            "rate_decrease_events": last.get("rate_decrease_events", 0),
            "barrier_slack_ns": 0,
            "directed_links": last["links"],
            "flow_match_key": list(match_key(last)),
        },
        "network_fct_ns": summarize([flow["duration_ns"] for flow in selected]),
        "issue_to_finish_ns": summarize(
            [flow["issue_to_finish_ns"] for flow in selected]),
        "barrier_slack_ns": summarize(
            [flow["barrier_slack_ns"] for flow in selected]),
        "completed_by_last_layer_release_count": sum(
            flow["finish_ns"] <= last_release for flow in selected),
        "cnp_hit_shard_count": len(cnp_flows),
        "rate_reduced_shard_count": len(reduced_flows),
        "cnp_hit_shard_slack_ns": summarize(
            [flow["barrier_slack_ns"] for flow in cnp_flows]),
        "rate_reduced_shard_slack_ns": summarize(
            [flow["barrier_slack_ns"] for flow in reduced_flows]),
        "critical_last_shard_received_cnp": last.get("cnp_events", 0) > 0,
        "critical_last_shard_rate_reduced": last.get("rate_decrease_events", 0) > 0,
    }


def cc_request_metrics(run_dir, flows, request_ids):
    path = run_dir / "cc_events.csv"
    output = {str(request_id): {
        "qp_starts": 0,
        "cnp_events": 0,
        "rate_events": 0,
        "rate_decreases": 0,
        "unique_qps_with_cnp": set(),
        "unique_qps_with_rate_decrease": set(),
    } for request_id in request_ids}
    if not path.is_file():
        return {"available": False, "by_request": {}}
    flow_by_start = {}
    for flow in flows:
        key = (flow["src_int"], flow["dst_int"], flow["port_int"],
               flow["bytes_int"], flow["issue_ns"])
        flow_by_start[key] = flow
    qp_to_request = {}
    qp_to_flow = {}
    per_flow_feedback = defaultdict(Counter)
    target_qp_start_matches = 0
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            event = row["event"]
            identity = (int(row["node_id"]), int(row["qp_id"]))
            if event == "QP_START":
                key = (int(row["src_rank"]), int(row["dst_rank"]),
                       int(row["sport"]), int(row["bytes"]),
                       int(row["timestamp"]))
                flow = flow_by_start.get(key)
                if flow is None:
                    continue
                else:
                    target_qp_start_matches += 1
                    qp_to_request[identity] = flow["request_id_int"]
                    qp_to_flow[identity] = match_key(flow)
                    request_key = str(flow["request_id_int"])
                    if request_key in output:
                        output[request_key]["qp_starts"] += 1
            elif event in ("CNP", "RATE"):
                request_id = qp_to_request.get(identity)
                if request_id is None:
                    continue
                request_key = str(request_id)
                if request_key not in output:
                    continue
                output[request_key][event.lower() + "_events"] += 1
                flow_key = qp_to_flow.get(identity)
                if flow_key is not None:
                    per_flow_feedback[flow_key][event.lower() + "_events"] += 1
                if (event == "RATE" and
                        int(row["new_rate_bps"]) < int(row["old_rate_bps"])):
                    output[request_key]["rate_decreases"] += 1
                    output[request_key]["unique_qps_with_rate_decrease"].add(identity)
                    if flow_key is not None:
                        per_flow_feedback[flow_key]["rate_decrease_events"] += 1
                if event == "CNP":
                    output[request_key]["unique_qps_with_cnp"].add(identity)
    by_request = {}
    for request_key, counts in output.items():
        by_request[request_key] = {
            key: (len(value) if isinstance(value, set) else value)
            for key, value in counts.items()
        }
    for flow in flows:
        feedback = per_flow_feedback[match_key(flow)]
        flow["cnp_events"] = feedback["cnp_events"]
        flow["rate_decrease_events"] = feedback["rate_decrease_events"]
    return {"available": True,
            "target_qp_start_matches": target_qp_start_matches,
            "by_request": by_request}


def cc_mode_from_config(path):
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] == "CC_MODE":
            return int(fields[1])
    return None


def load_run(name, run_dir, request_ids):
    manifest = json.loads((run_dir / "network_run_manifest.json").read_text(
        encoding="utf-8"))
    flows = read_flows(run_dir, request_ids)
    config_path = run_dir / "replay.conf"
    mode = cc_mode_from_config(config_path)
    manifest_mode = manifest.get("cc_mode_override")
    if manifest_mode is not None and int(manifest_mode) != mode:
        raise ValueError(f"{name}: CC_MODE manifest/config mismatch")
    cc_metrics = cc_request_metrics(run_dir, flows, request_ids)
    requests = {str(request_id): request_kv_metrics(flows, request_id)
                for request_id in request_ids}
    summary = {
        "name": name,
        "directory": str(run_dir.resolve()),
        "status": manifest["status"],
        "cc_mode": mode,
        "traffic_class": manifest["traffic_class"],
        "excluded_kv_request_ids": manifest.get("excluded_kv_request_ids", []),
        "input_event_count": manifest["event_count"],
        "excluded_kv_events": manifest.get("excluded_kv_events", 0),
        "input_event_sha256": sha256(Path(manifest["input_replay_dir"]) / "events.csv"),
        "config_sha256": sha256(config_path),
        "wall_seconds": manifest["wall_seconds"],
        "request_metrics": requests,
        "cc_metrics": cc_metrics,
        "target_kv_flow_count": len(flows),
    }
    return summary, flows


def compare_request(full, isolated, request_id):
    full_flows = [flow for flow in full if flow["event_type_int"] == KV_EVENT_TYPE
                  and flow["request_id_int"] == request_id]
    iso_flows = [flow for flow in isolated if flow["event_type_int"] == KV_EVENT_TYPE
                 and flow["request_id_int"] == request_id]
    full_by_key = {match_key(flow): flow for flow in full_flows}
    iso_by_key = {match_key(flow): flow for flow in iso_flows}
    common = set(full_by_key) & set(iso_by_key)
    paired_completion_delta = [full_by_key[key]["finish_ns"] -
                               iso_by_key[key]["finish_ns"] for key in common]
    route_mismatch = sum(full_by_key[key]["links"] != iso_by_key[key]["links"]
                         for key in common)
    full_metrics = request_kv_metrics(full, request_id)
    iso_metrics = request_kv_metrics(isolated, request_id)
    if full_metrics is None or iso_metrics is None:
        return {"request_id": request_id, "matched_shards": len(common),
                "error": "request absent from one run"}
    full_handoff = full_metrics["request_handoff_ns"]
    iso_handoff = iso_metrics["request_handoff_ns"]
    full_drain = full_metrics["residual_drain_ns"]
    iso_drain = iso_metrics["residual_drain_ns"]
    return {
        "request_id": request_id,
        "matched_shards": len(common),
        "unmatched_full_shards": len(set(full_by_key) - common),
        "unmatched_isolated_shards": len(set(iso_by_key) - common),
        "matched_route_mismatches": route_mismatch,
        "full_request_handoff_ns": full_handoff,
        "isolated_request_handoff_ns": iso_handoff,
        "handoff_delta_ns": full_handoff - iso_handoff,
        "handoff_slowdown_fraction": full_handoff / iso_handoff - 1,
        "full_residual_drain_ns": full_drain,
        "isolated_residual_drain_ns": iso_drain,
        "residual_drain_delta_ns": full_drain - iso_drain,
        "residual_drain_slowdown_fraction": full_drain / iso_drain - 1
        if iso_drain else None,
        "full_network_fct_ns": full_metrics["network_fct_ns"],
        "isolated_network_fct_ns": iso_metrics["network_fct_ns"],
        "network_fct_p99_slowdown_fraction": (
            full_metrics["network_fct_ns"]["p99_ns"] /
            iso_metrics["network_fct_ns"]["p99_ns"] - 1),
        "paired_shard_completion_delta_ns": summarize(paired_completion_delta),
        "full_last_shard": full_metrics["last_shard"],
        "isolated_last_shard": iso_metrics["last_shard"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--request-id", action="append", required=True, type=int)
    parser.add_argument("--run", action="append", required=True,
                        help="NAME=DIR; repeat for each CC/class/isolation run")
    args = parser.parse_args()
    run_dirs = {}
    for value in args.run:
        name, path = value.split("=", 1)
        run_dirs[name] = Path(path)
    ids = sorted(set(args.request_id))
    loaded = {name: load_run(name, path, ids) for name, path in run_dirs.items()}
    runs = {name: item[0] for name, item in loaded.items()}
    raw_flows = {name: item[1] for name, item in loaded.items()}
    source_hashes = {run["input_event_sha256"] for run in runs.values()}
    if len(source_hashes) != 1:
        raise SystemExit("counterfactuals do not use the same immutable event ledger")
    event_counts = {run["input_event_count"] for run in runs.values()}
    if len(event_counts) != 1:
        raise SystemExit("counterfactuals have different source event counts")

    comparisons = {}
    for request_id in ids:
        comparisons[str(request_id)] = {}
        for name, isolated_id in (("FULL_CC1", f"K{request_id}_ISO_CC1"),
                                  ("FULL_CC0", f"K{request_id}_ISO_CC0")):
            if name in raw_flows and isolated_id in raw_flows:
                comparisons[str(request_id)][f"{name}_vs_{isolated_id}"] = compare_request(
                    raw_flows[name], raw_flows[isolated_id], request_id)

    class_removal = {}
    for full_name, kv_name in (("FULL_CC1", "KV_ONLY_CC1"),
                               ("FULL_CC0", "KV_ONLY_CC0")):
        if full_name in raw_flows and kv_name in raw_flows:
            class_removal[f"{full_name}_vs_{kv_name}"] = {
                str(request_id): compare_request(raw_flows[full_name],
                                                   raw_flows[kv_name], request_id)
                for request_id in ids
            }

    # Within-run CC comparison isolates transport feedback while preserving
    # the same issue schedule, paths, bytes, and traffic population.
    cc_pairs = [("FULL_CC1", "FULL_CC0"), ("KV_ONLY_CC1", "KV_ONLY_CC0"),
                ("K8_ISO_CC1", "K8_ISO_CC0"),
                ("K9_ISO_CC1", "K9_ISO_CC0")]
    cc_mode_comparisons = {}
    for cc1_name, cc0_name in cc_pairs:
        if cc1_name not in raw_flows or cc0_name not in raw_flows:
            continue
        cc_mode_comparisons[f"{cc1_name}_vs_{cc0_name}"] = {
            str(request_id): compare_request(raw_flows[cc1_name],
                                               raw_flows[cc0_name], request_id)
            for request_id in ids
        }

    result = {
        "experiment": "immutable S8 D8+K2 matched K-request isolation and CC ablation",
        "source_event_sha256": next(iter(source_hashes)),
        "source_event_count": next(iter(event_counts)),
        "request_ids": ids,
        "runs": runs,
        "K2_vs_per_request_isolation": comparisons,
        "FULL_vs_KV_ONLY": class_removal,
        "CC_MODE1_vs_CC_MODE0": cc_mode_comparisons,
        "interpretation_boundary": (
            "Packet replay holds event issue timestamps fixed and has no packet-to-serving "
            "scheduler feedback. Handoff/residual drain are network request-barrier proxies; "
            "they are not integrated TTFT, TPOT, or TBT."),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "source_event_sha256": result["source_event_sha256"],
        "runs": {name: {"cc_mode": run["cc_mode"],
                        "excluded_kv_events": run["excluded_kv_events"],
                        "handoffs": run["request_metrics"]}
                 for name, run in runs.items()},
        "comparisons": comparisons,
        "CC_MODE1_vs_CC_MODE0": cc_mode_comparisons,
    }, indent=2))


if __name__ == "__main__":
    main()
