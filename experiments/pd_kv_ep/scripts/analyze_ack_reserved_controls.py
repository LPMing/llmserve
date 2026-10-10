#!/usr/bin/env python3
"""Compact matched analysis for FULL, KV_ONLY, and EP_ONLY ns-3 replays."""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


EVENT_NAMES = {1: "P2D_KV", 2: "EP_DISPATCH", 3: "EP_COMBINE"}


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    pos = (len(values) - 1) * fraction
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return values[lo]
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


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


def flow_key(row):
    return (
        int(row["event_type"]), int(row["request_id"]),
        int(row["collective_id"]), int(row["layer_id"]),
        int(row["src"]), int(row["dst"]), int(row["port"]),
        int(row["tag"]), int(row["bytes"]), int(row["issue_time_ns"]),
    )


def read_replay(directory):
    manifest = json.loads((directory / "network_run_manifest.json").read_text())
    events_path = directory / "comm_events.csv"
    starts = {}
    events = {}
    with events_path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            event_id = row["event_id"]
            if row["phase"] == "START":
                starts[event_id] = row
            elif row["phase"] == "END" and event_id in starts:
                start = starts.pop(event_id)
                key = flow_key(start)
                events[key] = {
                    "event_type": int(start["event_type"]),
                    "request_id": int(start["request_id"]),
                    "collective_id": int(start["collective_id"]),
                    "layer_id": int(start["layer_id"]),
                    "src": int(start["src"]),
                    "dst": int(start["dst"]),
                    "port": int(start["port"]),
                    "tag": int(start["tag"]),
                    "bytes": int(start["bytes"]),
                    "issue_ns": int(start["issue_time_ns"]),
                    "start_ns": int(start["network_start_ns"]),
                    "end_ns": int(row["network_end_ns"]),
                    "path": start["path"],
                    "links": tuple(sorted(set(
                        value for value in start["directed_link_ids"].split(";")
                        if value))),
                    "event_id": event_id,
                }
    if starts:
        raise RuntimeError(f"{directory}: {len(starts)} flows lack completion rows")
    return manifest, events


def flow_stats(events, event_type):
    selected = [item for item in events.values()
                if item["event_type"] == event_type]
    return stats(item["end_ns"] - item["start_ns"] for item in selected)


def request_barriers(events):
    grouped = defaultdict(list)
    for item in events.values():
        if item["event_type"] == 1:
            grouped[item["request_id"]].append(item)
    result = {}
    for request_id, rows in grouped.items():
        first_issue = min(row["issue_ns"] for row in rows)
        last_finish = max(row["end_ns"] for row in rows)
        result[request_id] = {
            "first_issue_ns": first_issue,
            "last_finish_ns": last_finish,
            "handoff_span_ns": last_finish - first_issue,
            "bytes": sum(row["bytes"] for row in rows),
            "flow_count": len(rows),
        }
    return result


def ep_collectives(events):
    grouped = defaultdict(list)
    for item in events.values():
        if item["event_type"] in (2, 3):
            grouped[(item["collective_id"], item["event_type"])].append(item)
    return grouped


def link_summary(directory):
    path = directory / "link_summary.csv"
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    def summarize(selected):
        return {
            "link_count": len(selected),
            "sum_tx_packets": sum(int(row["tx_packets"]) for row in selected),
            "sum_ecn_marks": sum(int(row["ecn_marks"]) for row in selected),
            "max_link_utilization": max((float(row["peak_utilization"])
                                          for row in selected), default=0.0),
            "max_queue_bytes": max((int(float(row["queue_max_bytes"]))
                                     for row in selected), default=0),
            "sum_pfc_pause": sum(int(row["pfc_pause"]) for row in selected),
            "sum_drops": sum(int(row["drop_count"]) for row in selected),
        }

    physical_scaleout = [row for row in rows
                         if int(float(row["capacity_bps"])) == 200_000_000_000]
    return {
        "all_modeled_links": summarize(rows),
        "physical_200g_scaleout_links": summarize(physical_scaleout),
    }


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def analyze(full_dir, kv_dir, ep_dir, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    manifests = {}
    data = {}
    for name, directory in (("FULL", full_dir), ("KV_ONLY", kv_dir),
                            ("EP_ONLY", ep_dir)):
        manifests[name], data[name] = read_replay(directory)
        if manifests[name]["status"] != "PASS":
            raise RuntimeError(f"{name} replay is not PASS")

    full, kv_only, ep_only = data["FULL"], data["KV_ONLY"], data["EP_ONLY"]
    full_kv = {key: item for key, item in full.items() if item["event_type"] == 1}
    only_kv = {key: item for key, item in kv_only.items() if item["event_type"] == 1}
    full_ep = {key: item for key, item in full.items() if item["event_type"] in (2, 3)}
    only_ep = {key: item for key, item in ep_only.items() if item["event_type"] in (2, 3)}
    if full_kv.keys() != only_kv.keys():
        raise RuntimeError("KV_ONLY does not contain the exact FULL KV flow set")
    if full_ep.keys() != only_ep.keys():
        raise RuntimeError("EP_ONLY does not contain the exact FULL EP flow set")
    kv_path_matches = sum(full_kv[k]["path"] == only_kv[k]["path"] and
                          full_kv[k]["links"] == only_kv[k]["links"]
                          for k in full_kv)
    ep_path_matches = sum(full_ep[k]["path"] == only_ep[k]["path"] and
                          full_ep[k]["links"] == only_ep[k]["links"]
                          for k in full_ep)

    kv_rows = []
    for key, item in full_kv.items():
        isolated = only_kv[key]
        kv_rows.append({
            "request_id": item["request_id"], "layer_id": item["layer_id"],
            "src": item["src"], "dst": item["dst"], "port": item["port"],
            "bytes": item["bytes"], "issue_ns": item["issue_ns"],
            "network_start_ns": item["start_ns"],
            "finish_full_ns": item["end_ns"],
            "fct_full_ns": item["end_ns"] - item["start_ns"],
            "fct_kv_only_ns": isolated["end_ns"] - isolated["start_ns"],
            "fct_slowdown_full_vs_kv_only": (
                (item["end_ns"] - item["start_ns"]) /
                max(1, isolated["end_ns"] - isolated["start_ns"])),
            "full_path": item["path"],
        })
    sizes = sorted(row["bytes"] for row in kv_rows)
    cut1, cut2, cut3 = (percentile(sizes, p) for p in (0.25, 0.50, 0.75))
    for row in kv_rows:
        row["size_quartile"] = ("Q1_smallest" if row["bytes"] <= cut1 else
                                "Q2" if row["bytes"] <= cut2 else
                                "Q3" if row["bytes"] <= cut3 else "Q4_largest")

    def flow_fcts(rows):
        return [row["fct_full_ns"] for row in rows]

    size_summary = []
    for quartile in ("Q1_smallest", "Q2", "Q3", "Q4_largest"):
        rows = [row for row in kv_rows if row["size_quartile"] == quartile]
        ratios = [row["fct_slowdown_full_vs_kv_only"] for row in rows]
        diffs = [row["fct_full_ns"] - row["fct_kv_only_ns"] for row in rows]
        size_summary.append({
            "size_quartile": quartile, "flow_count": len(rows),
            "min_bytes": min((r["bytes"] for r in rows), default=None),
            "max_bytes": max((r["bytes"] for r in rows), default=None),
            "full_fct_mean_ns": stats(flow_fcts(rows))["mean_ns"],
            "full_fct_p99_ns": stats(flow_fcts(rows))["p99_ns"],
            "kv_only_fct_mean_ns": stats([r["fct_kv_only_ns"] for r in rows])["mean_ns"],
            "slowdown_mean": stats(ratios)["mean_ns"],
            "slowdown_p99": stats(ratios)["p99_ns"],
            "delta_fct_mean_ns": stats(diffs)["mean_ns"],
        })
    write_csv(output_dir / "kv_size_interference.csv", size_summary,
              list(size_summary[0]))

    full_barriers = request_barriers(full)
    isolated_barriers = request_barriers(kv_only)
    ordered_layers = sorted({row["layer_id"] for row in full_kv.values()})
    layer_ordinal = {layer: index for index, layer in enumerate(ordered_layers)}
    barrier_slacks = [full_barriers[row["request_id"]]["last_finish_ns"] -
                      row["end_ns"] for row in full_kv.values()]
    slack_p10 = percentile(barrier_slacks, 0.10)
    slack_p25 = percentile(barrier_slacks, 0.25)
    for row in kv_rows:
        barrier = full_barriers[row["request_id"]]
        row["layer_ordinal"] = layer_ordinal[row["layer_id"]]
        row["barrier_slack_ns_fair"] = barrier["last_finish_ns"] - row["finish_full_ns"]
        slack = row["barrier_slack_ns_fair"]
        row["criticality_cohort"] = (
            "exact_last" if slack == 0 else
            "near_p10" if slack <= slack_p10 else
            "near_p25" if slack <= slack_p25 else "slack_rich")
    write_csv(output_dir / "kv_flow_matched_controls.csv", kv_rows,
              ["request_id", "layer_id", "src", "dst", "port", "bytes",
               "size_quartile", "layer_ordinal", "issue_ns",
               "network_start_ns", "finish_full_ns", "barrier_slack_ns_fair",
               "criticality_cohort", "fct_full_ns", "fct_kv_only_ns",
               "fct_slowdown_full_vs_kv_only", "full_path"])
    request_rows = []
    for request_id in sorted(full_barriers):
        f, i = full_barriers[request_id], isolated_barriers[request_id]
        request_rows.append({
            "request_id": request_id, "kv_bytes": f["bytes"],
            "kv_shards": f["flow_count"], "handoff_full_ns": f["handoff_span_ns"],
            "handoff_kv_only_ns": i["handoff_span_ns"],
            "handoff_slowdown_full_vs_kv_only": (
                f["handoff_span_ns"] / max(1, i["handoff_span_ns"])),
            "last_finish_full_ns": f["last_finish_ns"],
            "last_finish_kv_only_ns": i["last_finish_ns"],
        })
    write_csv(output_dir / "kv_request_barriers.csv", request_rows,
              list(request_rows[0]))

    criticality_rows = []
    size_bins = ("Q1_smallest", "Q2", "Q3", "Q4_largest")
    criticality_bins = ("exact_last", "near_p10", "near_p25", "slack_rich")
    total_kv_bytes = sum(row["bytes"] for row in kv_rows)
    for size_bin in size_bins:
        for criticality in criticality_bins:
            selected = [row for row in kv_rows
                        if row["size_quartile"] == size_bin and
                        row["criticality_cohort"] == criticality]
            if not selected:
                continue
            full_fct = [row["fct_full_ns"] for row in selected]
            only_fct = [row["fct_kv_only_ns"] for row in selected]
            criticality_rows.append({
                "size_quartile": size_bin,
                "criticality_cohort": criticality,
                "flow_count": len(selected),
                "bytes": sum(row["bytes"] for row in selected),
                "fraction_of_total_kv_bytes": (
                    sum(row["bytes"] for row in selected) / total_kv_bytes),
                "barrier_slack_p50_ns": percentile(
                    [row["barrier_slack_ns_fair"] for row in selected], 0.50),
                "full_fct_mean_ns": stats(full_fct)["mean_ns"],
                "full_fct_p99_ns": stats(full_fct)["p99_ns"],
                "kv_only_fct_mean_ns": stats(only_fct)["mean_ns"],
                "kv_only_fct_p99_ns": stats(only_fct)["p99_ns"],
                "full_vs_kv_only_slowdown_mean": stats(
                    row["fct_slowdown_full_vs_kv_only"]
                    for row in selected)["mean_ns"],
                "delta_fct_mean_ns": stats(
                    row["fct_full_ns"] - row["fct_kv_only_ns"]
                    for row in selected)["mean_ns"],
            })
    write_csv(output_dir / "kv_size_x_criticality_controls.csv",
              criticality_rows, list(criticality_rows[0]))

    full_groups, isolated_groups = ep_collectives(full), ep_collectives(ep_only)
    if full_groups.keys() != isolated_groups.keys():
        raise RuntimeError("EP_ONLY collective key set differs from FULL")
    full_kv_by_link = defaultdict(list)
    for row in full_kv.values():
        for link in row["links"]:
            full_kv_by_link[link].append((row["start_ns"], row["end_ns"], row["event_id"]))

    ep_rows = []
    for collective_key, flows in full_groups.items():
        isolated = isolated_groups[collective_key]
        full_cct = max(f["end_ns"] for f in flows) - min(f["start_ns"] for f in flows)
        isolated_cct = max(f["end_ns"] for f in isolated) - min(f["start_ns"] for f in isolated)
        last_end = max(f["end_ns"] for f in flows)
        critical = [f for f in flows if f["end_ns"] == last_end]
        second_last = max((f["end_ns"] for f in flows if f["end_ns"] < last_end),
                          default=last_end)
        peer_details = []
        overlapping_kv = set()
        shared_links = set()
        overlap_sum_by_link = 0
        for flow in critical:
            matched = next(isolated_flow for isolated_flow in isolated
                           if flow_key_from_item(flow) == flow_key_from_item(isolated_flow))
            peer_overlap_flows = set()
            peer_shared_links = set()
            peer_overlap_ns = 0
            for link in flow["links"]:
                intervals = []
                for kv_start, kv_end, kv_id in full_kv_by_link.get(link, []):
                    overlap = min(flow["end_ns"], kv_end) - max(flow["start_ns"], kv_start)
                    if overlap > 0:
                        intervals.append((max(flow["start_ns"], kv_start),
                                          min(flow["end_ns"], kv_end)))
                        peer_overlap_flows.add(kv_id)
                        peer_shared_links.add(link)
                intervals.sort()
                merged_end = -1
                for start, end in intervals:
                    if end <= merged_end:
                        continue
                    peer_overlap_ns += end - max(start, merged_end)
                    merged_end = end
            overlapping_kv.update(peer_overlap_flows)
            shared_links.update(peer_shared_links)
            overlap_sum_by_link += peer_overlap_ns
            peer_details.append({
                "src": flow["src"], "dst": flow["dst"],
                "bytes": flow["bytes"], "port": flow["port"],
                "fct_full_ns": flow["end_ns"] - flow["start_ns"],
                "fct_ep_only_ns": matched["end_ns"] - matched["start_ns"],
                "fct_delta_ns": (flow["end_ns"] - flow["start_ns"] -
                                 matched["end_ns"] + matched["start_ns"]),
                "path": flow["path"],
                "kv_shared_links": sorted(peer_shared_links),
                "kv_overlapping_flows": sorted(peer_overlap_flows),
                "kv_overlap_ns_sum_per_link": peer_overlap_ns,
            })
        ep_rows.append({
            "collective_id": collective_key[0],
            "collective_type": EVENT_NAMES[collective_key[1]],
            "collective_flows": len(flows), "full_cct_ns": full_cct,
            "ep_only_cct_ns": isolated_cct,
            "cct_slowdown_full_vs_ep_only": full_cct / max(1, isolated_cct),
            "last_peer_count": len(critical),
            "last_peers": json.dumps(peer_details, separators=(",", ":")),
            "last_minus_second_last_ns": last_end - second_last,
            "last_flow_delta_fct_max_ns": max(
                peer["fct_delta_ns"] for peer in peer_details),
            "critical_peer_paths": " || ".join(peer["path"] for peer in peer_details),
            "kv_overlapping_shared_link_count": len(shared_links),
            "kv_overlapping_flow_count": len(overlapping_kv),
            "critical_peer_kv_overlap_ns_sum_per_link": overlap_sum_by_link,
        })
    write_csv(output_dir / "ep_critical_peer_attribution.csv", ep_rows,
              list(ep_rows[0]))

    summaries = []
    for name, replay in (("FULL", full), ("KV_ONLY", kv_only),
                         ("EP_ONLY", ep_only)):
        kv_stats = stats(row["end_ns"] - row["start_ns"]
                         for row in replay.values() if row["event_type"] == 1)
        ep_stats = stats(
            max(flow["end_ns"] for flow in group) -
            min(flow["start_ns"] for flow in group)
            for group in ep_collectives(replay).values())
        handoffs = stats(row["handoff_span_ns"]
                         for row in request_barriers(replay).values())
        links = link_summary({"FULL": full_dir, "KV_ONLY": kv_dir,
                              "EP_ONLY": ep_dir}[name])
        summaries.append({
            "scenario": name, "completed_flows": len(replay),
            "kv_flow_fct": kv_stats, "kv_request_handoff_span": handoffs,
            "ep_collective_cct": ep_stats, "link_telemetry": links,
        })
    full_ep_ccts = [row["full_cct_ns"] for row in ep_rows]
    only_ep_ccts = [row["ep_only_cct_ns"] for row in ep_rows]
    full_kv_fcts = [row["fct_full_ns"] for row in kv_rows]
    only_kv_fcts = [row["fct_kv_only_ns"] for row in kv_rows]
    metadata = {
        "flow_match": {
            "kv_count": len(full_kv), "kv_only_match_count": len(only_kv),
            "ep_count": len(full_ep), "ep_only_match_count": len(only_ep),
            "kv_path_and_link_exact_matches": kv_path_matches,
            "ep_path_and_link_exact_matches": ep_path_matches,
        },
        "full_vs_isolated": {
            "kv_flow_fct_ratio_distribution": stats(
                a / max(1, b) for a, b in zip(full_kv_fcts, only_kv_fcts)),
            "kv_request_handoff_ratio_distribution": stats(
                row["handoff_slowdown_full_vs_kv_only"] for row in request_rows),
            "ep_collective_cct_ratio_distribution": stats(
                a / max(1, b) for a, b in zip(full_ep_ccts, only_ep_ccts)),
            "ep_p99_ratio_of_absolute_p99_cct": (
                percentile(full_ep_ccts, 0.99) /
                max(1, percentile(only_ep_ccts, 0.99))),
            "ep_mean_ratio_of_absolute_mean_cct": (
                (sum(full_ep_ccts) / len(full_ep_ccts)) /
                max(1, sum(only_ep_ccts) / len(only_ep_ccts))),
        },
        "last_peer": {
            "collective_count": len(ep_rows),
            "critical_peer_row_count": sum(row["last_peer_count"]
                                            for row in ep_rows),
            "critical_peer_rows_with_kv_overlap": sum(
                row["kv_overlapping_shared_link_count"] > 0 for row in ep_rows),
            "critical_peer_overlap_fraction": (
                sum(row["kv_overlapping_shared_link_count"] > 0 for row in ep_rows) /
                sum(row["last_peer_count"] for row in ep_rows)
                if ep_rows else None),
            "barrier_slack_cutoffs_ns": {"p10": slack_p10, "p25": slack_p25},
            "critical_flow_delta_fct": stats(
                row["last_flow_delta_fct_max_ns"] for row in ep_rows),
            "straggler_gap_ns": stats(row["last_minus_second_last_ns"]
                                      for row in ep_rows),
        },
        "scenarios": summaries,
        "limitations": [
            "Fixed issue timestamps are replayed from the integrated FlowSim ledger; ns-3 completion does not feed back to serving scheduling.",
            "This is network counterfactual attribution, not policy-specific TTFT/TBT.",
            "Path identity is checked using exported packet-derived path and directed-link sets.",
        ],
    }
    (output_dir / "matched_control_summary.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def flow_key_from_item(item):
    return (item["event_type"], item["request_id"], item["collective_id"],
            item["layer_id"], item["src"], item["dst"], item["port"],
            item["tag"], item["bytes"], item["issue_ns"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-dir", required=True, type=Path)
    parser.add_argument("--kv-only-dir", required=True, type=Path)
    parser.add_argument("--ep-only-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    result = analyze(args.full_dir.resolve(), args.kv_only_dir.resolve(),
                     args.ep_only_dir.resolve(), args.output_dir.resolve())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
