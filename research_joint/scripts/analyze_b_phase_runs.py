#!/usr/bin/env python3
"""Compact analysis of the two EP4-group phase-staggering characterization."""

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path


GROUP_A = {0, 1, 4, 5}
GROUP_B = {2, 3, 6, 7}


def request_group(request_ids, fallback=None):
    ids = set(int(value) for value in (request_ids or []))
    if ids and ids <= GROUP_A:
        return "A"
    if ids and ids <= GROUP_B:
        return "B"
    return fallback or "MIXED_OR_UNKNOWN"


def read_requests(path, single_group=None):
    rows = []
    with Path(path).open(newline="") as stream:
        for row in csv.DictReader(stream):
            row["request_id"] = int(row["request id"])
            row["group"] = (single_group if single_group else
                            ("A" if row["request_id"] in GROUP_A else "B"))
            for key in ("arrival", "end_time", "latency", "TTFT", "TPOT",
                        "p2d_kv_ready_time_ns", "decode_admit_time_ns",
                        "decode_first_batch_start_ns", "decode_first_batch_finish_ns",
                        "second_token_visible_ns", "ttst_ns", "decode_phase_wait_ns"):
                row[key] = int(row[key]) if row.get(key) not in (None, "") else -1
            row["itl_values"] = [int(value.strip()) for value in row["ITL"].strip("[]").split(",") if value.strip()]
            rows.append(row)
    return rows


def read_telemetry(path, single_group=None):
    totals = Counter()
    group_totals = Counter()
    group_event_counts = Counter()
    group_round_ccts = defaultdict(list)
    rounds = {}
    flow_paths = Counter()
    event_types = Counter()
    first_ns = None
    last_ns = 0
    with Path(path).open() as stream:
        for line in stream:
            if not line.startswith("{"):
                continue
            row = json.loads(line)
            event_type = int(row.get("event_type", -1))
            event_types[event_type] += 1
            byte_count = int(row.get("bytes", 0))
            totals[(event_type, str(row.get("traffic_class", "unknown")))] += byte_count
            group = request_group(row.get("request_ids"), fallback=single_group)
            if group in ("A", "B"):
                group_totals[(group, event_type)] += byte_count
                group_event_counts[(group, event_type)] += 1
            start = int(row.get("start_ns", row.get("requested_start_ns", 0)))
            finish = int(row.get("end_ns", start))
            first_ns = start if first_ns is None else min(first_ns, start)
            last_ns = max(last_ns, finish)
            path_edges = tuple(str(edge) for edge in (row.get("path") or []))
            flow_paths[(event_type, path_edges)] += 1
            if event_type not in (2, 3):
                continue
            if group not in ("A", "B"):
                continue
            key = (group, event_type, int(row.get("batch_id", -1)),
                   int(row.get("collective_id", -1)), int(row.get("layer_id", -1)))
            acc = rounds.setdefault(key, {
                "start": start, "finish": finish, "requested": int(row.get("requested_start_ns", start)),
                "bytes": 0, "flows": 0, "edges": set(), "flow_finishes": []})
            acc["start"] = min(acc["start"], start)
            acc["requested"] = min(acc["requested"], int(row.get("requested_start_ns", start)))
            acc["finish"] = max(acc["finish"], finish)
            acc["bytes"] += byte_count
            acc["flows"] += 1
            acc["edges"].update(path_edges)
            acc["flow_finishes"].append(finish)

    # Match logically corresponding rounds across groups and check actual path/time exposure.
    matched = {}
    for key, value in rounds.items():
        group_round_ccts[(key[0], key[1])].append(value["finish"] - value["requested"])
        _, event_type, batch_id, collective_id, layer_id = key
        matched.setdefault((event_type, batch_id, collective_id, layer_id), {})[key[0]] = value
    overlap_rounds = 0
    shared_path_overlap_rounds = 0
    overlap_ns_total = 0
    critical_pairs = []
    for logical_key, by_group in matched.items():
        if "A" not in by_group or "B" not in by_group:
            continue
        a, b = by_group["A"], by_group["B"]
        overlap = max(0, min(a["finish"], b["finish"]) - max(a["start"], b["start"]))
        if overlap:
            overlap_rounds += 1
            overlap_ns_total += overlap
            common = a["edges"] & b["edges"]
            if common:
                shared_path_overlap_rounds += 1
                critical_pairs.append((logical_key, overlap, sorted(common)))

    return {
        "event_types": event_types,
        "totals": totals,
        "group_totals": group_totals,
        "group_event_counts": group_event_counts,
        "group_round_ccts": group_round_ccts,
        "rounds": rounds,
        "matched_rounds": sum(1 for value in matched.values() if "A" in value and "B" in value),
        "overlap_rounds": overlap_rounds,
        "shared_path_overlap_rounds": shared_path_overlap_rounds,
        "overlap_ns_total": overlap_ns_total,
        "critical_pairs": critical_pairs,
        "first_ns": first_ns if first_ns is not None else 0,
        "last_ns": last_ns,
    }


def percentile_nearest(values, p):
    values = sorted(values)
    if not values:
        return 0
    return values[max(0, min(len(values) - 1, int((len(values) - 1) * p + 0.999999)))]


def summarize(label, request_path, telemetry_path, single_group=None):
    reqs = read_requests(request_path, single_group=single_group)
    telemetry = read_telemetry(telemetry_path, single_group=single_group)
    groups = {}
    for group in ((single_group,) if single_group else ("A", "B")):
        selected = [row for row in reqs if row["group"] == group]
        all_itl = [value for row in selected for value in row["itl_values"]]
        groups[group] = {
            "n_requests": len(selected),
            "ttft_mean_ns": statistics.mean(row["TTFT"] for row in selected),
            "first_itl_mean_ns": statistics.mean(row["itl_values"][0] for row in selected),
            "itl_mean_ns": statistics.mean(all_itl),
            "itl_max_ns": max(all_itl),
            "completion_max_ns": max(row["end_time"] for row in selected),
            "decode_admit_mean_ns": statistics.mean(row["decode_admit_time_ns"] for row in selected),
            "phase_wait_mean_ns": statistics.mean(row["decode_phase_wait_ns"] for row in selected),
        }
    groups["ALL"] = {
        "n_requests": len(reqs),
        "ttft_mean_ns": statistics.mean(row["TTFT"] for row in reqs),
        "first_itl_mean_ns": statistics.mean(row["itl_values"][0] for row in reqs),
        "itl_mean_ns": statistics.mean(value for row in reqs for value in row["itl_values"]),
        "itl_max_ns": max(value for row in reqs for value in row["itl_values"]),
        "completion_max_ns": max(row["end_time"] for row in reqs),
        "decode_admit_mean_ns": statistics.mean(row["decode_admit_time_ns"] for row in reqs),
        "phase_wait_mean_ns": statistics.mean(row["decode_phase_wait_ns"] for row in reqs),
    }
    return {"label": label, "groups": groups, "telemetry": telemetry}


def write_rows(path, summaries):
    columns = ["run", "group", "request_count", "TTFT_mean_ns", "first_ITL_mean_ns",
               "ITL_mean_ns", "ITL_max_ns", "decode_admit_mean_ns", "phase_wait_mean_ns",
               "completion_max_ns", "EP_dispatch_bytes", "EP_dispatch_CCT_mean_ns",
               "EP_combine_bytes", "EP_combine_CCT_mean_ns", "KV_bytes",
               "KV_flow_count", "EP_dispatch_flow_count", "EP_combine_flow_count",
               "matched_EP_rounds", "overlap_EP_rounds", "shared_path_overlap_EP_rounds",
               "aggregate_round_overlap_ns", "telemetry_event_count"]
    with Path(path).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for summary in summaries:
            telem = summary["telemetry"]
            for group, values in summary["groups"].items():
                dispatch_bytes = telem["group_totals"].get((group, 2), 0)
                combine_bytes = telem["group_totals"].get((group, 3), 0)
                kv_bytes = telem["group_totals"].get((group, 1), 0)
                dispatch_ccts = telem["group_round_ccts"].get((group, 2), [])
                combine_ccts = telem["group_round_ccts"].get((group, 3), [])
                writer.writerow({
                    "run": summary["label"], "group": group,
                    "request_count": values["n_requests"],
                    "TTFT_mean_ns": round(values["ttft_mean_ns"]),
                    "first_ITL_mean_ns": round(values["first_itl_mean_ns"]),
                    "ITL_mean_ns": round(values["itl_mean_ns"]),
                    "ITL_max_ns": values["itl_max_ns"],
                    "decode_admit_mean_ns": round(values["decode_admit_mean_ns"]),
                    "phase_wait_mean_ns": round(values["phase_wait_mean_ns"]),
                    "completion_max_ns": values["completion_max_ns"],
                    "EP_dispatch_bytes": dispatch_bytes,
                    "EP_dispatch_CCT_mean_ns": round(statistics.mean(dispatch_ccts)) if dispatch_ccts else "",
                    "EP_combine_bytes": combine_bytes,
                    "EP_combine_CCT_mean_ns": round(statistics.mean(combine_ccts)) if combine_ccts else "",
                    "KV_bytes": kv_bytes,
                    "KV_flow_count": telem["group_event_counts"].get((group, 1), 0),
                    "EP_dispatch_flow_count": telem["group_event_counts"].get((group, 2), 0),
                    "EP_combine_flow_count": telem["group_event_counts"].get((group, 3), 0),
                    "matched_EP_rounds": telem["matched_rounds"],
                    "overlap_EP_rounds": telem["overlap_rounds"],
                    "shared_path_overlap_EP_rounds": telem["shared_path_overlap_rounds"],
                    "aggregate_round_overlap_ns": telem["overlap_ns_total"],
                    "telemetry_event_count": sum(telem["event_types"].values()),
                })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="research_joint/06_B_PHASE_EXPERIMENTS.csv")
    parser.add_argument("--sync-requests", default="research_joint/outputs/b_ep4_sync_requests.csv")
    parser.add_argument("--sync-telemetry", default="/tmp/research_joint_ep4_sync_telemetry.jsonl")
    parser.add_argument("--phase-requests", default="research_joint/outputs/b_ep4_phase20us_requests.csv")
    parser.add_argument("--phase-telemetry", default="/tmp/research_joint_ep4_phase20us_fixed_telemetry.jsonl")
    parser.add_argument("--b-only-requests", default="research_joint/outputs/b_ep4_b_only_requests.csv")
    parser.add_argument("--b-only-telemetry", default="/tmp/research_joint_ep4_b_only_telemetry.jsonl")
    parser.add_argument("--a-only-requests", default="research_joint/outputs/b_ep4_a_only_requests.csv")
    parser.add_argument("--a-only-telemetry", default="/tmp/research_joint_ep4_a_only_telemetry.jsonl")
    args = parser.parse_args()
    summaries = [
        summarize("B0_GROUP_A_ONLY_FAIR", args.a_only_requests, args.a_only_telemetry,
                  single_group="A"),
        summarize("B1_GROUP_B_ONLY_FAIR", args.b_only_requests, args.b_only_telemetry,
                  single_group="B"),
        summarize("B2_SYNC_FAIR", args.sync_requests, args.sync_telemetry),
        summarize("B3_PHASE20US_GROUP_B_FAIR", args.phase_requests, args.phase_telemetry),
    ]
    write_rows(args.output, summaries)
    for summary in summaries:
        print(summary["label"], "groups=", summary["groups"],
              "event_types=", dict(summary["telemetry"]["event_types"]),
              "bytes=", dict(summary["telemetry"]["totals"]),
              "matched/overlap/shared=", summary["telemetry"]["matched_rounds"],
              summary["telemetry"]["overlap_rounds"],
              summary["telemetry"]["shared_path_overlap_rounds"],
              "aggregate_overlap_ns=", summary["telemetry"]["overlap_ns_total"])
        print("critical_overlap_examples=", summary["telemetry"]["critical_pairs"][:3])


if __name__ == "__main__":
    main()
