#!/usr/bin/env python3
"""Compare matched CC_MODE=1 and legacy CC_MODE=12 packet replays."""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


POLICIES = ("FAIR", "EP_FIRST", "KV_FIRST")
POLICY_DIRS = {
    "CC_MODE_12": {
        "FAIR": "ns3_ack_reserved_fair",
        "EP_FIRST": "ns3_ack_reserved_ep_first",
        "KV_FIRST": "ns3_ack_reserved_kv_first",
    },
    "CC_MODE_1": {
        "FAIR": "ns3_cc1_fair",
        "EP_FIRST": "ns3_cc1_ep_first",
        "KV_FIRST": "ns3_cc1_kv_first",
    },
}


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    pos = (len(values) - 1) * fraction
    low, high = math.floor(pos), math.ceil(pos)
    if low == high:
        return values[low]
    return values[low] + (values[high] - values[low]) * (pos - low)


def stats(values):
    values = list(values)
    return {
        "n": len(values),
        "mean_ns": sum(values) / len(values) if values else None,
        "p50_ns": percentile(values, 0.50),
        "p95_ns": percentile(values, 0.95),
        "p99_ns": percentile(values, 0.99),
        "max_ns": max(values) if values else None,
    }


def read_comm(directory):
    starts = {}
    flows = {}
    with (directory / "comm_events.csv").open(
            newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            event_id = row["event_id"]
            if row["phase"] == "START":
                starts[event_id] = row
            elif row["phase"] == "END" and event_id in starts:
                start = starts.pop(event_id)
                flows[event_id] = {
                    "event_id": event_id,
                    "event_type": int(start["event_type"]),
                    "request_id": int(start["request_id"]),
                    "collective_id": int(start["collective_id"]),
                    "layer_id": int(start["layer_id"]),
                    "src": int(start["src"]),
                    "dst": int(start["dst"]),
                    "port": int(start["port"]),
                    "bytes": int(start["bytes"]),
                    "priority_group": int(start["priority_group"]),
                    "issue_ns": int(start["issue_time_ns"]),
                    "start_ns": int(start["network_start_ns"]),
                    "end_ns": int(row["network_end_ns"]),
                    "path": start["path"],
                    "links": start["directed_link_ids"],
                }
    if starts:
        raise RuntimeError("{} has {} unmatched START events".format(
            directory, len(starts)))
    return flows


def read_cc(directory):
    path = directory / "cc_events.csv"
    if not path.is_file():
        return {
            "available": False,
            "event_counts": {},
            "rate_decrease_delta_bps": stats([]),
            "source_file": None,
        }
    counts = defaultdict(int)
    rate_deltas = []
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            kind = row["event"]
            counts[kind] += 1
            if kind == "RATE":
                old_rate = int(row["old_rate_bps"])
                new_rate = int(row["new_rate_bps"])
                reason = int(row["reason"])
                counts["RATE_REASON_{}".format(reason)] += 1
                rate_deltas.append((old_rate, new_rate, reason))
                if old_rate > new_rate:
                    counts["RATE_DECREASE"] += 1
                elif old_rate < new_rate:
                    counts["RATE_INCREASE"] += 1

    decreasing = [old - new for old, new, _ in rate_deltas if old > new]
    return {
        "available": True,
        "event_counts": dict(sorted(counts.items())),
        "rate_decrease_delta_bps": stats(decreasing),
        "rate_response_latency": "not estimated from aggregate multi-flow event telemetry",
        "source_file": str(path),
    }


def summarize_flows(flows):
    kv = [flow for flow in flows.values() if flow["event_type"] == 1]
    ep = [flow for flow in flows.values() if flow["event_type"] in (2, 3)]
    requests = defaultdict(list)
    collectives = defaultdict(list)
    for flow in kv:
        requests[flow["request_id"]].append(flow)
    for flow in ep:
        collectives[(flow["collective_id"], flow["event_type"])].append(flow)

    handoffs = {}
    post_release = {}
    for request_id, group in requests.items():
        last_issue = max(flow["issue_ns"] for flow in group)
        last_finish = max(flow["end_ns"] for flow in group)
        first_issue = min(flow["issue_ns"] for flow in group)
        handoffs[request_id] = last_finish - first_issue
        post_release[request_id] = last_finish - last_issue

    ccts = {}
    for key, group in collectives.items():
        ccts[key] = max(flow["end_ns"] for flow in group) - min(
            flow["start_ns"] for flow in group)

    return {
        "completed_flows": len(flows),
        "kv_shard_fct": stats(flow["end_ns"] - flow["start_ns"]
                               for flow in kv),
        "kv_request_handoff": stats(handoffs.values()),
        "kv_post_last_release_drain": stats(post_release.values()),
        "ep_flow_fct": stats(flow["end_ns"] - flow["start_ns"]
                              for flow in ep),
        "ep_collective_cct": stats(ccts.values()),
        "ep_dispatch_cct": stats(value for (collective, event_type), value
                                  in ccts.items() if event_type == 2),
        "ep_combine_cct": stats(value for (collective, event_type), value
                                 in ccts.items() if event_type == 3),
        "kv_request_rows": handoffs,
        "kv_post_release_rows": post_release,
        "ep_collective_rows": ccts,
    }


def link_stats(directory):
    rows = list(csv.DictReader(
        (directory / "link_summary.csv").open(newline="", encoding="utf-8")))
    physical = [row for row in rows
                if int(float(row["capacity_bps"])) == 200_000_000_000]
    tx = sum(int(row["tx_packets"]) for row in physical)
    marks = sum(int(row["ecn_marks"]) for row in physical)
    return {
        "physical_200g_link_count": len(physical),
        "physical_link_tx_observations": tx,
        "physical_link_ecn_mark_observations": marks,
        "ecn_mark_fraction_of_link_tx_observations": marks / tx if tx else None,
        "max_queue_bytes_on_physical_links": max(
            (int(float(row["queue_max_bytes"])) for row in physical), default=0),
        "sum_pfc_pause_on_physical_links": sum(
            int(row["pfc_pause"]) for row in physical),
        "sum_drops_on_physical_links": sum(
            int(row["drop_count"]) for row in physical),
    }


def identity(flow):
    return tuple(flow[key] for key in (
        "event_type", "request_id", "collective_id", "layer_id", "src",
        "dst", "port", "bytes", "priority_group", "issue_ns", "path",
        "links"))


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.result_root.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    data = {}
    summary = {
        "purpose": "Matched 4-KiB packet replay comparison: CC_MODE=1 DCQCN vs legacy CC_MODE=12, per policy.",
        "serving_metrics": "Not produced: ns-3 replays fixed issue times and does not feed completion back to the scheduler.",
        "policies": {},
        "matched_identity": {},
    }
    paired_flow_rows = []
    request_rows = []
    collective_rows = []
    for mode, directories in POLICY_DIRS.items():
        for policy, dirname in directories.items():
            directory = root / dirname
            manifest = json.loads((directory / "network_run_manifest.json").read_text())
            if manifest["status"] != "PASS":
                raise RuntimeError("{} is not PASS".format(directory))
            flows = read_comm(directory)
            cc = read_cc(directory)
            metrics = summarize_flows(flows)
            metrics["link_telemetry"] = link_stats(directory)
            metrics["cc_telemetry"] = cc
            summary["policies"].setdefault(policy, {})[mode] = {
                "run_manifest": manifest,
                "metrics": {key: value for key, value in metrics.items()
                            if not key.endswith("_rows")},
            }
            data[(mode, policy)] = (flows, metrics)

    for policy in POLICIES:
        old_flows, old_metrics = data[("CC_MODE_12", policy)]
        new_flows, new_metrics = data[("CC_MODE_1", policy)]
        if old_flows.keys() != new_flows.keys():
            raise RuntimeError("event-id set differs for {}".format(policy))
        identity_matches = sum(identity(old_flows[key]) == identity(new_flows[key])
                               for key in old_flows)
        if identity_matches != len(old_flows):
            raise RuntimeError(
                "request/byte/issue/path identity changed for {}: {}/{}".format(
                    policy, identity_matches, len(old_flows)))
        summary["matched_identity"][policy] = {
            "flow_count": len(old_flows),
            "same_event_identity_issue_path_bytes_priority": identity_matches,
        }
        for event_type, label in ((1, "P2D_KV"), (2, "EP_DISPATCH"),
                                  (3, "EP_COMBINE")):
            old_group = {key: flow for key, flow in old_flows.items()
                         if flow["event_type"] == event_type}
            new_group = {key: flow for key, flow in new_flows.items()
                         if flow["event_type"] == event_type}
            old_fct = {key: flow["end_ns"] - flow["start_ns"]
                       for key, flow in old_group.items()}
            new_fct = {key: flow["end_ns"] - flow["start_ns"]
                       for key, flow in new_group.items()}
            deltas = [new_fct[key] - old_fct[key] for key in old_fct]
            ratios = [new_fct[key] / max(1, old_fct[key]) for key in old_fct]
            paired_flow_rows.append({
                "policy": policy,
                "metric": label + "_flow_FCT",
                "n": len(deltas),
                "cc12_mean_ns": stats(old_fct.values())["mean_ns"],
                "cc1_mean_ns": stats(new_fct.values())["mean_ns"],
                "mean_delta_ns": stats(deltas)["mean_ns"],
                "paired_ratio_mean": stats(ratios)["mean_ns"],
                "paired_ratio_p95": stats(ratios)["p95_ns"],
                "paired_ratio_p99": stats(ratios)["p99_ns"],
                "paired_ratio_max": stats(ratios)["max_ns"],
                "ratio_of_marginal_p99": (
                    stats(new_fct.values())["p99_ns"] /
                    max(1, stats(old_fct.values())["p99_ns"])),
            })

        old_handoff = old_metrics["kv_request_rows"]
        new_handoff = new_metrics["kv_request_rows"]
        for request_id in sorted(old_handoff):
            request_rows.append({
                "policy": policy,
                "request_id": request_id,
                "cc12_handoff_ns": old_handoff[request_id],
                "cc1_handoff_ns": new_handoff[request_id],
                "delta_ns": new_handoff[request_id] - old_handoff[request_id],
                "ratio_cc1_over_cc12": (new_handoff[request_id] /
                                         max(1, old_handoff[request_id])),
                "cc12_post_last_release_drain_ns": old_metrics[
                    "kv_post_release_rows"][request_id],
                "cc1_post_last_release_drain_ns": new_metrics[
                    "kv_post_release_rows"][request_id],
            })

        old_ccts = old_metrics["ep_collective_rows"]
        new_ccts = new_metrics["ep_collective_rows"]
        if old_ccts.keys() != new_ccts.keys():
            raise RuntimeError("EP collective key set differs for {}".format(policy))
        for (collective_id, event_type), old_cct in old_ccts.items():
            new_cct = new_ccts[(collective_id, event_type)]
            collective_rows.append({
                "policy": policy,
                "collective_id": collective_id,
                "event_type": event_type,
                "cc12_cct_ns": old_cct,
                "cc1_cct_ns": new_cct,
                "delta_ns": new_cct - old_cct,
                "ratio_cc1_over_cc12": new_cct / max(1, old_cct),
            })

        for metric_name, old_values, new_values in (
                ("KV_request_handoff", old_handoff, new_handoff),
                ("EP_collective_CCT", old_ccts, new_ccts)):
            keys = old_values.keys() & new_values.keys()
            old_list = [old_values[key] for key in keys]
            new_list = [new_values[key] for key in keys]
            paired_ratios = [new_values[key] / max(1, old_values[key])
                             for key in keys]
            paired_flow_rows.append({
                "policy": policy,
                "metric": metric_name,
                "n": len(keys),
                "cc12_mean_ns": stats(old_list)["mean_ns"],
                "cc1_mean_ns": stats(new_list)["mean_ns"],
                "mean_delta_ns": stats(new_values[key] - old_values[key]
                                        for key in keys)["mean_ns"],
                "paired_ratio_mean": stats(paired_ratios)["mean_ns"],
                "paired_ratio_p95": stats(paired_ratios)["p95_ns"],
                "paired_ratio_p99": stats(paired_ratios)["p99_ns"],
                "paired_ratio_max": stats(paired_ratios)["max_ns"],
                "ratio_of_marginal_p99": (stats(new_list)["p99_ns"] /
                                           max(1, stats(old_list)["p99_ns"])),
            })

    (output / "dcqcn_policy_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_csv(output / "dcqcn_paired_metric_summary.csv", paired_flow_rows,
              ["policy", "metric", "n", "cc12_mean_ns", "cc1_mean_ns",
               "mean_delta_ns", "paired_ratio_mean", "paired_ratio_p95",
               "paired_ratio_p99", "paired_ratio_max",
               "ratio_of_marginal_p99"])
    write_csv(output / "dcqcn_request_handoffs.csv", request_rows,
              ["policy", "request_id", "cc12_handoff_ns", "cc1_handoff_ns",
               "delta_ns", "ratio_cc1_over_cc12",
               "cc12_post_last_release_drain_ns",
               "cc1_post_last_release_drain_ns"])
    write_csv(output / "dcqcn_collective_ccts.csv", collective_rows,
              ["policy", "collective_id", "event_type", "cc12_cct_ns",
               "cc1_cct_ns", "delta_ns", "ratio_cc1_over_cc12"])
    print(json.dumps({
        "output_dir": str(output),
        "matched_identity": summary["matched_identity"],
        "paired_metric_summary": str(output / "dcqcn_paired_metric_summary.csv"),
    }, indent=2))


if __name__ == "__main__":
    main()
