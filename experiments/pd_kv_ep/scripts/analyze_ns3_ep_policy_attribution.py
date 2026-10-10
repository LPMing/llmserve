#!/usr/bin/env python3
"""Compare EP collective barriers and last peers across native ns-3 policies."""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


EP_TYPES = {2: "EP_DISPATCH", 3: "EP_COMBINE"}


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * fraction
    lo, hi = math.floor(position), math.ceil(position)
    if lo == hi:
        return values[lo]
    return values[lo] + (values[hi] - values[lo]) * (position - lo)


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


def start_key(row):
    return (
        int(row["event_type"]), int(row["collective_id"]),
        int(row["layer_id"]), int(row["src"]), int(row["dst"]),
        int(row["port"]), int(row["tag"]), int(row["bytes"]),
        int(row["issue_time_ns"]),
    )


def read_run(directory, keep_ep_flow_fct=False):
    starts = {}
    groups = defaultdict(lambda: {
        "start_ns": None, "last_end_ns": -1, "second_last_end_ns": -1,
        "last_peers": [], "flow_count": 0,
    })
    kv_by_link = defaultdict(list)
    ep_flow_fct = {} if keep_ep_flow_fct else None
    event_count = 0
    with (directory / "comm_events.csv").open(
            newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            event_id = row["event_id"]
            if row["phase"] == "START":
                event_type = int(row["event_type"])
                if event_type not in (1, 2, 3):
                    continue
                links = tuple(value for value in
                              row["directed_link_ids"].split(";") if value)
                starts[event_id] = (
                    event_type, start_key(row), int(row["network_start_ns"]),
                    int(row["bytes"]), int(row["collective_id"]),
                    int(row["layer_id"]), int(row["src"]), int(row["dst"]),
                    int(row["port"]), int(row["issue_time_ns"]),
                    row["path"], links)
                continue
            if row["phase"] != "END" or event_id not in starts:
                continue
            start = starts.pop(event_id)
            event_type, key, start_ns, byte_count, collective_id, layer_id, src, dst, port, issue_ns, path, links = start
            end_ns = int(row["network_end_ns"])
            duration_ns = end_ns - start_ns
            event_count += 1
            if event_type == 1:
                for link in links:
                    kv_by_link[link].append((start_ns, end_ns, event_id))
                continue
            group_key = (collective_id, event_type)
            group = groups[group_key]
            group["flow_count"] += 1
            group["start_ns"] = (start_ns if group["start_ns"] is None else
                                 min(group["start_ns"], start_ns))
            if end_ns > group["last_end_ns"]:
                group["second_last_end_ns"] = group["last_end_ns"]
                group["last_end_ns"] = end_ns
                group["last_peers"] = []
            elif end_ns < group["last_end_ns"]:
                group["second_last_end_ns"] = max(
                    group["second_last_end_ns"], end_ns)
            if end_ns == group["last_end_ns"]:
                group["last_peers"].append({
                    "key": key, "start_ns": start_ns, "end_ns": end_ns,
                    "fct_ns": duration_ns, "bytes": byte_count,
                    "layer_id": layer_id, "src": src, "dst": dst,
                    "port": port, "issue_ns": issue_ns, "path": path,
                    "links": links,
                })
            if ep_flow_fct is not None:
                ep_flow_fct[key] = duration_ns
    if starts:
        raise RuntimeError(f"{directory}: {len(starts)} events are incomplete")
    return groups, kv_by_link, ep_flow_fct, event_count


def kv_exposure(peer, kv_by_link):
    overlap_ids = set()
    overlap_links = set()
    overlap_ns_by_link = 0
    for link in peer["links"]:
        intervals = []
        for start_ns, end_ns, flow_id in kv_by_link.get(link, []):
            left = max(peer["start_ns"], start_ns)
            right = min(peer["end_ns"], end_ns)
            if right > left:
                intervals.append((left, right))
                overlap_ids.add(flow_id)
                overlap_links.add(link)
        intervals.sort()
        merged_end = -1
        for left, right in intervals:
            if right <= merged_end:
                continue
            overlap_ns_by_link += right - max(left, merged_end)
            merged_end = right
    return overlap_ids, overlap_links, overlap_ns_by_link


def analyze(policy_dirs, ep_only_dir, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    ep_only_groups, _, ep_only_flow_fct, ep_only_count = read_run(
        ep_only_dir, keep_ep_flow_fct=True)
    policy_rows = []
    collective_rows = []
    policy_data = {}
    for policy, directory in policy_dirs.items():
        groups, kv_by_link, _, event_count = read_run(directory)
        policy_data[policy] = (groups, kv_by_link)
        if groups.keys() != ep_only_groups.keys():
            raise RuntimeError(f"{policy}: EP collective keys differ from EP_ONLY")
        ccts = []
        cct_ratios = []
        last_delta = []
        last_overlaps = 0
        for collective_key, group in groups.items():
            base_group = ep_only_groups[collective_key]
            full_cct = group["last_end_ns"] - group["start_ns"]
            base_cct = base_group["last_end_ns"] - base_group["start_ns"]
            ccts.append(full_cct)
            cct_ratios.append(full_cct / max(1, base_cct))
            peer_records = []
            for peer in group["last_peers"]:
                base_fct = ep_only_flow_fct.get(peer["key"])
                if base_fct is None:
                    raise RuntimeError(
                        f"{policy}: cannot match EP_ONLY critical peer {peer['key']}")
                delta = peer["fct_ns"] - base_fct
                last_delta.append(delta)
                overlaps, shared_links, overlap_ns = kv_exposure(peer, kv_by_link)
                last_overlaps += bool(shared_links)
                peer_records.append({
                    "src": peer["src"], "dst": peer["dst"],
                    "layer_id": peer["layer_id"], "bytes": peer["bytes"],
                    "port": peer["port"], "fct_ns": peer["fct_ns"],
                    "ep_only_fct_ns": base_fct, "fct_delta_ns": delta,
                    "path": peer["path"],
                    "kv_shared_links": sorted(shared_links),
                    "kv_overlapping_flow_count": len(overlaps),
                    "kv_overlap_ns_sum_per_link": overlap_ns,
                })
            collective_rows.append({
                "policy": policy, "collective_id": collective_key[0],
                "collective_type": EP_TYPES[collective_key[1]],
                "flow_count": group["flow_count"], "cct_ns": full_cct,
                "ep_only_cct_ns": base_cct,
                "cct_ratio_vs_ep_only": full_cct / max(1, base_cct),
                "cct_delta_ns": full_cct - base_cct,
                "last_peer_count": len(peer_records),
                "last_minus_second_last_ns": (
                    group["last_end_ns"] - group["second_last_end_ns"]),
                "last_peers": json.dumps(peer_records, separators=(",", ":")),
            })
        policy_rows.append({
            "policy": policy,
            "completed_ep_flows": sum(group["flow_count"]
                                       for group in groups.values()),
            "collectives": len(groups), "ep_cct": stats(ccts),
            "per_collective_ratio_vs_ep_only": stats(cct_ratios),
            "ratio_of_absolute_p99_cct": (
                percentile(ccts, 0.99) /
                max(1, percentile([g["last_end_ns"] - g["start_ns"]
                                   for g in ep_only_groups.values()], 0.99))),
            "last_peer_fct_delta_vs_ep_only": stats(last_delta),
            "last_peers_with_overlapping_kv_on_same_directed_link": last_overlaps,
            "last_peer_overlap_fraction": (
                last_overlaps / len(last_delta) if last_delta else None),
        })

    with (output_dir / "ep_collective_policy_attribution.csv").open(
            "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(collective_rows[0]),
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(collective_rows)
    (output_dir / "ep_collective_policy_summary.json").write_text(
        json.dumps({"ep_only_flow_count": ep_only_count,
                    "policies": policy_rows}, indent=2) + "\n",
        encoding="utf-8")
    return policy_rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fair-dir", required=True, type=Path)
    parser.add_argument("--ep-first-dir", required=True, type=Path)
    parser.add_argument("--kv-first-dir", required=True, type=Path)
    parser.add_argument("--ep-only-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    rows = analyze({
        "FAIR": args.fair_dir.resolve(),
        "EP_FIRST": args.ep_first_dir.resolve(),
        "KV_FIRST": args.kv_first_dir.resolve(),
    }, args.ep_only_dir.resolve(), args.output_dir.resolve())
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
