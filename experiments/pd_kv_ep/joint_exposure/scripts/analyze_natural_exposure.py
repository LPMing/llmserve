#!/usr/bin/env python3
"""Join integrated FlowSim KV, EP collective, serving-iteration and request ledgers.

The script reports topology-route coactivity as a screening signal. FlowSim
routes are deterministic shortest paths over aggregate directed link pairs;
this is not packet ECMP or packet-queue evidence. It does not infer a
counterfactual barrier delay from temporal overlap.
"""

import argparse
import csv
import json
import math
import pathlib
import sys
from bisect import bisect_right
from collections import Counter, defaultdict


def read_jsonl(path):
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("{"):
                yield json.loads(line)


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def percentile(values, q):
    ordered = sorted(float(v) for v in values)
    if not ordered:
        return None
    return ordered[min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))]


def summarize(values):
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return {"n": 0}
    return {"n": len(vals), "mean": sum(vals) / len(vals),
            "p50": percentile(vals, .50), "p95": percentile(vals, .95),
            "p99": percentile(vals, .99), "max": max(vals)}


def merge_intervals(intervals):
    merged = []
    for start, end in sorted(intervals):
        if end < start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def overlap_duration(intervals, start, end):
    return sum(max(0, min(b, end) - max(a, start))
               for a, b in intervals if a < end and b > start)


def overlaps_window(intervals, starts, start, end):
    """Return only merged intervals intersecting [start,end), via binary search."""
    index = max(0, bisect_right(starts, start) - 1)
    result = []
    while index < len(intervals):
        a, b = intervals[index]
        if a >= end:
            break
        if b > start:
            result.append((max(start, a), min(end, b)))
        index += 1
    return result


def interval_index(weighted_intervals):
    """Index half-open intervals as active counts and active byte sums."""
    starts = sorted((int(start), int(weight))
                    for start, end, weight in weighted_intervals if end > start)
    ends = sorted((int(end), int(weight))
                  for start, end, weight in weighted_intervals if end > start)

    def prefix(rows):
        result = [0]
        for _, weight in rows:
            result.append(result[-1] + weight)
        return result

    return {
        "start_times": [row[0] for row in starts],
        "end_times": [row[0] for row in ends],
        "start_prefix": prefix(starts),
        "end_prefix": prefix(ends),
    }


def interval_state(index, timestamp):
    """Return active interval count and summed weights at timestamp."""
    if index is None:
        return 0, 0
    timestamp = int(timestamp)
    started = bisect_right(index["start_times"], timestamp)
    ended = bisect_right(index["end_times"], timestamp)
    return (started - ended,
            index["start_prefix"][started] - index["end_prefix"][ended])


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields,
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--requests", type=pathlib.Path, required=True)
    parser.add_argument("--iterations", type=pathlib.Path, required=True)
    parser.add_argument("--telemetry-dir", type=pathlib.Path, required=True)
    parser.add_argument("--topology", type=pathlib.Path, required=True)
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    args = parser.parse_args()

    repo = pathlib.Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(repo / "serving" / "core"))
    from flowsim_backend import FluidFlowNetwork

    network = FluidFlowNetwork(str(args.topology), policy="FAIR")
    requests = read_csv(args.requests)
    iterations = read_csv(args.iterations)
    groups = {}
    request_batches = defaultdict(list)
    for row in iterations:
        if row.get("pd_type") != "decode":
            continue
        batch = int(row["batch_id"])
        group = groups.setdefault(batch, {
            "start": 2**63 - 1, "finish": 0, "request_ids": set(),
            "instances": set(), "rows": 0,
        })
        group["start"] = min(group["start"], int(row["start_ns"]))
        group["finish"] = max(group["finish"], int(row["finish_ns"]))
        group["instances"].add(int(row["instance_id"]))
        group["rows"] += 1
        try:
            group["request_ids"].update(
                int(value) for value in json.loads(row.get("request_ids") or "[]"))
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
    for batch, group in groups.items():
        for request_id in group["request_ids"]:
            request_batches[request_id].append(batch)

    kv_flows = {}
    for event in read_jsonl(args.telemetry_dir / "kv_event_telemetry.jsonl"):
        flow_id = event.get("flow_id")
        if not flow_id:
            continue
        if event.get("event") == "KV_STARTED":
            kv_flows[flow_id] = {
                "start": int(event["start_ns"]), "end": None,
                "path": tuple(event.get("path") or ()),
                "request_ids": tuple(int(x) for x in event.get("request_ids") or ()),
                "bytes": int(event.get("bytes") or 0),
                "src": event.get("src"), "dst": event.get("dst"),
                "requested": int(event.get("requested_start_ns") or event["start_ns"]),
                "layer": event.get("layer_id"),
            }
        elif event.get("event") == "KV_COMPLETED" and flow_id in kv_flows:
            kv_flows[flow_id]["end"] = int(event.get("end_ns", event["timestamp_ns"]))

    kv_by_link = defaultdict(list)
    kv_link_flow_intervals = defaultdict(list)
    kv_link_byte_intervals = defaultdict(list)
    kv_by_request = defaultdict(list)
    for flow_id, flow in kv_flows.items():
        if flow["end"] is None:
            continue
        flow["flow_id"] = flow_id
        for link in flow["path"]:
            kv_by_link[link].append((flow["start"], flow["end"]))
            kv_link_flow_intervals[link].append(
                (flow["start"], flow["end"], 1))
            kv_link_byte_intervals[link].append(
                (flow["start"], flow["end"], flow["bytes"]))
        for request_id in flow["request_ids"]:
            kv_by_request[request_id].append(flow)
    kv_link_union = {link: merge_intervals(intervals)
                     for link, intervals in kv_by_link.items()}
    kv_link_starts = {link: [interval[0] for interval in intervals]
                      for link, intervals in kv_link_union.items()}
    kv_link_flow_indexes = {
        link: interval_index(intervals)
        for link, intervals in kv_link_flow_intervals.items()
    }
    kv_link_byte_indexes = {
        link: interval_index(intervals)
        for link, intervals in kv_link_byte_intervals.items()
    }

    request_by_id = {int(row["request id"]): row for row in requests}
    decode_activity = []
    for request in requests:
        try:
            decode_start = int(request.get("decode_scheduler_admit_time_ns") or -1)
            decode_end = int(request.get("end_time") or -1)
        except (TypeError, ValueError):
            continue
        if decode_start >= 0 and decode_end > decode_start:
            decode_activity.append((decode_start, decode_end, 1))
    decode_activity_index = interval_index(decode_activity)
    kv_activity_index = interval_index([
        (flow["start"], flow["end"], flow["bytes"])
        for flow in kv_flows.values() if flow["end"] is not None
    ])
    kv_flow_count_index = interval_index([
        (flow["start"], flow["end"], 1)
        for flow in kv_flows.values() if flow["end"] is not None
    ])

    # Pre-resolve critical peer routes once. This supports both directions of
    # barrier exposure without treating all EP bytes as if they used one path.
    collective_events = [event for event in read_jsonl(
        args.telemetry_dir / "collective_telemetry.jsonl")
        if event.get("event") == "COLLECTIVE_COMPLETED"]
    collective_critical_paths = []
    ep_link_intervals = defaultdict(list)
    for event in collective_events:
        start, finish = int(event["start_ns"]), int(event["end_ns"])
        paths = []
        for flow_id in event.get("critical_flow_ids") or ():
            parts = str(flow_id).split(":")
            if len(parts) >= 4 and parts[1] == "p2p":
                try:
                    src, dst = int(parts[2]), int(parts[3])
                    paths.append(tuple(network._link_name(link)
                                       for link in network.path(src, dst)))
                except (ValueError, IndexError):
                    continue
        collective_critical_paths.append(paths)
        for link in {link for path in paths for link in path}:
            ep_link_intervals[link].append((start, finish, 1))
    ep_link_indexes = {
        link: interval_index(intervals)
        for link, intervals in ep_link_intervals.items()
    }
    ep_activity_index = interval_index([
        (int(event["start_ns"]), int(event["end_ns"]), 1)
        for event in collective_events
    ])
    ep_link_union = {
        link: merge_intervals([(start, end) for start, end, _ in intervals])
        for link, intervals in ep_link_intervals.items()
    }
    ep_link_union_starts = {
        link: [start for start, _ in intervals]
        for link, intervals in ep_link_union.items()
    }

    kv_barriers = []
    for request_id, flows in sorted(kv_by_request.items()):
        request = request_by_id.get(request_id)
        if request is None:
            continue
        last_finish = max(flow["end"] for flow in flows)
        # A barrier can have several shards tied at the final timestamp. Keep
        # every co-critical shard rather than selecting an arbitrary dict row.
        critical_flows = [flow for flow in flows if flow["end"] == last_finish]
        critical_release = min(int(flow["requested"]) for flow in critical_flows)
        prefill_finish = int(request["prefill_completion_time_ns"])
        decode_batches = sorted(request_batches.get(request_id, ()),
                                key=lambda b: groups[b]["start"])
        first_decode = groups[decode_batches[0]]["start"] if decode_batches else None
        active_decode_count, _ = interval_state(
            decode_activity_index, critical_release)
        active_kv_count, _ = interval_state(
            kv_flow_count_index, critical_release)
        _, active_kv_bytes = interval_state(kv_activity_index, critical_release)
        shared_ep_links = set()
        shared_ep_intervals = []
        active_ep_route_link_incidence = 0
        active_ep_link_incidence = 0
        active_ep_link_bytes = 0
        critical_links = {link for flow in critical_flows for link in flow["path"]}
        for link in critical_links:
            ep_count, _ = interval_state(
                ep_link_indexes.get(link), critical_release)
            active_ep_route_link_incidence += ep_count
            kv_count, _ = interval_state(
                kv_link_flow_indexes.get(link), critical_release)
            _, kv_link_bytes = interval_state(
                kv_link_byte_indexes.get(link), critical_release)
            active_ep_link_incidence += kv_count
            active_ep_link_bytes += kv_link_bytes
            spans = ep_link_union.get(link, ())
            starts = ep_link_union_starts.get(link, ())
            for left, right in overlaps_window(
                    spans, starts,
                    min(flow["start"] for flow in critical_flows), last_finish):
                shared_ep_links.add(link)
                shared_ep_intervals.append((left, right))
        shared_ep_overlap_ns = sum(
            end - start for start, end in merge_intervals(shared_ep_intervals))
        kv_barriers.append({
            "communication_id": "KV_REQUEST_%d" % request_id,
            "type": "P2D_KV_REQUEST_BARRIER",
            "request_id": request_id,
            "batch_id": "",
            "layer_id": ";".join(sorted({str(flow["layer"])
                                          for flow in critical_flows})),
            "release_time_ns": min(flow["requested"] for flow in flows),
            "critical_release_time_ns": critical_release,
            "finish_time_ns": last_finish,
            "next_serving_barrier_ns": prefill_finish,
            "remaining_slack_ns": prefill_finish - last_finish,
            "baseline_network_span_ns": last_finish -
                                        min(flow["requested"] for flow in flows),
            # No isolated-network counterfactual has been run, so exposed
            # network delay remains unknown (blank), not the observed FCT.
            "critical_flow_fct_or_cct_ns": max(
                max(0, last_finish - int(flow["requested"]))
                for flow in critical_flows),
            "network_remaining_time_ns": "",
            "active_decode_requests": active_decode_count,
            "active_p2d_flows_at_release": active_kv_count,
            # Sum of declared sizes for active flows, not remaining bytes or
            # a measured instantaneous bandwidth.
            "active_p2d_flow_size_sum_at_release": active_kv_bytes,
            "cohort_size": "",
            "critical_route_kv_same_link_overlap": int(bool(shared_ep_links)),
            "critical_route_overlap_ns": shared_ep_overlap_ns,
            "shared_directed_links": ";".join(sorted(shared_ep_links)),
            "same_link_active_ep_collective_link_incidence_at_release": active_ep_route_link_incidence,
            "same_link_active_kv_flow_link_incidence_at_release": active_ep_link_incidence,
            "same_link_active_kv_link_byte_incidence_at_release": active_ep_link_bytes,
            "active_ep_collectives_at_critical_release": interval_state(
                ep_activity_index, critical_release)[0],
            "path": ";".join(sorted(critical_links)),
            "critical_flow_ids": ";".join(sorted(
                flow["flow_id"] for flow in critical_flows)),
            "critical_flow_count": len(critical_flows),
            "critical_flow_bytes": sum(flow["bytes"] for flow in critical_flows),
            "flow_count": len(flows),
            "bytes": sum(flow["bytes"] for flow in flows),
            "status": "EXACT_REQUEST_ATTRIBUTION",
            "first_decode_iteration_start_ns": first_decode,
            "kv_finish_before_first_decode": (
                "" if first_decode is None else str(last_finish <= first_decode)),
            "ttft_ns": int(request["TTFT"]),
        })

    # Test whether actual last-completing peer paths share active directed KV
    # links. The per-link byte field below is a flow-link incidence sum, not
    # unique bytes and not an instantaneous utilization measurement.
    ep_rows = []
    overlap_link_counts = Counter()
    collective_ccts = []
    batch_cct = defaultdict(int)
    batch_event_count = Counter()
    batch_contained = 0
    overlap_cct = []
    window_stats = defaultdict(lambda: {
        "collectives": 0, "critical_route_overlap": 0,
        "cct_ns": [], "overlap_ns": [], "cohort_sizes": [],
    })
    for event_index, event in enumerate(collective_events):
        start, finish = int(event["start_ns"]), int(event["end_ns"])
        cct = int(event["cct_ns"])
        # Collective ID encoding: logical decode batch * 10,000,000 + layer*10 + event type.
        batch = int(event["collective_id"]) // 10_000_000
        group = groups.get(batch)
        contained = bool(group and group["start"] <= start <= finish <= group["finish"])
        batch_contained += int(contained)
        batch_cct[batch] += cct
        batch_event_count[batch] += 1
        collective_ccts.append(cct)

        critical_paths = collective_critical_paths[event_index]
        critical_route_links = {link for path in critical_paths for link in path}
        shared = set()
        overlap_intervals = []
        for path in critical_paths:
            for link in path:
                spans = kv_link_union.get(link, ())
                starts = kv_link_starts.get(link, ())
                for left, right in overlaps_window(spans, starts, start, finish):
                    shared.add(link)
                    overlap_intervals.append((left, right))
                    overlap_link_counts[link] += 1
        overlap_ns = sum(b - a for a, b in merge_intervals(overlap_intervals))
        same_route = bool(shared)
        if same_route:
            overlap_cct.append(cct)
        active_decode_count, _ = interval_state(decode_activity_index, start)
        active_p2d_count, _ = interval_state(kv_flow_count_index, start)
        _, active_p2d_bytes = interval_state(kv_activity_index, start)
        same_link_kv_flow_incidence = 0
        same_link_kv_byte_incidence = 0
        for link in critical_route_links:
            link_flow_count, _ = interval_state(
                kv_link_flow_indexes.get(link), start)
            _, link_bytes = interval_state(
                kv_link_byte_indexes.get(link), start)
            same_link_kv_flow_incidence += link_flow_count
            same_link_kv_byte_incidence += link_bytes
        active_ep_link_incidence = 0
        for link in critical_route_links:
            active_ep_link_incidence += interval_state(
                ep_link_indexes.get(link), start)[0]
        window = (start // 1_000_000) * 1_000_000
        stat = window_stats[window]
        stat["collectives"] += 1
        stat["critical_route_overlap"] += int(same_route)
        stat["cct_ns"].append(cct)
        stat["overlap_ns"].append(overlap_ns)
        if group:
            stat["cohort_sizes"].append(len(group["request_ids"]))
        ep_rows.append({
            "communication_id": event.get("round_id", event.get("collective_id")),
            "type": "EP_COLLECTIVE_" + str(event.get("event_type", "")),
            "request_id": "",
            "batch_id": batch,
            "layer_id": event.get("layer_id"),
            "release_time_ns": start,
            "critical_release_time_ns": start,
            "finish_time_ns": finish,
            "next_serving_barrier_ns": group["finish"] if group else "",
            "remaining_slack_ns": (group["finish"] - finish) if group and contained else "",
            "baseline_network_span_ns": cct,
            "critical_flow_fct_or_cct_ns": cct,
            # No isolated-network counterfactual has been run, so exposed
            # network delay remains unknown (blank), not the observed CCT.
            "network_remaining_time_ns": "",
            "active_decode_requests": active_decode_count,
            "active_p2d_flows_at_release": active_p2d_count,
            # Sum of declared sizes for active flows, not remaining bytes or
            # a measured instantaneous bandwidth.
            "active_p2d_flow_size_sum_at_release": active_p2d_bytes,
            "cohort_size": (len(group["request_ids"]) if group else ""),
            "critical_route_kv_same_link_overlap": int(same_route),
            "critical_route_overlap_ns": overlap_ns,
            "shared_directed_links": ";".join(sorted(shared)),
            "same_link_active_ep_collective_link_incidence_at_release": active_ep_link_incidence,
            "same_link_active_kv_flow_link_incidence_at_release": same_link_kv_flow_incidence,
            "same_link_active_kv_link_byte_incidence_at_release": same_link_kv_byte_incidence,
            "active_ep_collectives_at_critical_release": interval_state(
                ep_activity_index, start)[0],
            "path": ";".join(sorted({link for path in critical_paths for link in path})),
            "critical_flow_ids": ";".join(event.get("critical_flow_ids") or ()),
            "critical_flow_count": event.get("critical_flow_count"),
            "critical_flow_bytes": event.get("critical_flow_bytes"),
            "flow_count": event.get("flow_count"),
            "bytes": event.get("bytes_sum"),
            "status": "ITERATION_MATCH" if contained else "NO_MATCH_OR_INTERVAL_MISMATCH",
            "first_decode_iteration_start_ns": group["start"] if group else "",
            "kv_finish_before_first_decode": "",
            "ttft_ns": "",
        })

    # Per-request TBT -> decode-batch join. Sum of collective CCTs is reported
    # only as an accounting bound/share proxy, not as additive exposed time.
    request_step_rows = []
    step_ep_ratios = []
    for request_id, request in request_by_id.items():
        batches = sorted(request_batches.get(request_id, ()),
                         key=lambda b: groups[b]["start"])
        try:
            tbt = [float(value) for value in json.loads(request.get("TBT") or "[]")]
        except (ValueError, TypeError, json.JSONDecodeError):
            tbt = []
        # Some first-token conventions omit a scheduler batch, so preserve
        # only index-aligned rows if cardinalities match; otherwise mark unmatched.
        if len(batches) != len(tbt):
            continue
        for index, (batch, tbt_ns) in enumerate(zip(batches, tbt), 1):
            group = groups[batch]
            ep_sum = batch_cct.get(batch, 0)
            iter_ns = group["finish"] - group["start"]
            ratio = ep_sum / tbt_ns if tbt_ns > 0 else None
            step_ep_ratios.append(ratio)
            request_step_rows.append({
                "request_id": request_id, "token_step_index": index,
                "decode_batch_id": batch, "batch_start_ns": group["start"],
                "batch_finish_ns": group["finish"], "iteration_duration_ns": iter_ns,
                "tbt_ns": int(tbt_ns), "ep_collective_count": batch_event_count[batch],
                "sum_ep_cct_ns_nonadditive_upper_bound": ep_sum,
                "sum_ep_cct_over_tbt": ratio,
                "ep_events_all_matched_iteration": int(batch_event_count[batch] == 96),
            })

    outdir = args.output_dir
    outdir.mkdir(parents=True, exist_ok=True)
    comm_fields = ["communication_id", "type", "request_id", "batch_id", "layer_id",
                   "release_time_ns", "finish_time_ns", "next_serving_barrier_ns",
                   "remaining_slack_ns", "baseline_network_span_ns",
                   "critical_release_time_ns", "critical_flow_fct_or_cct_ns",
                   "network_remaining_time_ns", "active_decode_requests",
                   "active_p2d_flows_at_release", "active_p2d_flow_size_sum_at_release",
                   "cohort_size",
                   "critical_route_kv_same_link_overlap", "critical_route_overlap_ns",
                   "same_link_active_ep_collective_link_incidence_at_release",
                   "same_link_active_kv_flow_link_incidence_at_release",
                   "same_link_active_kv_link_byte_incidence_at_release",
                   "active_ep_collectives_at_critical_release",
                   "shared_directed_links", "path", "critical_flow_ids",
                   "critical_flow_count", "critical_flow_bytes", "flow_count", "bytes", "status",
                   "first_decode_iteration_start_ns", "kv_finish_before_first_decode", "ttft_ns"]
    write_csv(outdir / "COMMUNICATION_EXPOSURE_TRACE.csv", comm_fields, kv_barriers + ep_rows)
    write_csv(outdir / "REQUEST_DECODE_STEP_ATTRIBUTION.csv",
              ["request_id", "token_step_index", "decode_batch_id", "batch_start_ns",
               "batch_finish_ns", "iteration_duration_ns", "tbt_ns", "ep_collective_count",
               "sum_ep_cct_ns_nonadditive_upper_bound", "sum_ep_cct_over_tbt",
               "ep_events_all_matched_iteration"], request_step_rows)

    ranking = []
    for window, stat in sorted(window_stats.items()):
        n = stat["collectives"]
        ranking.append({
            "window_start_ns": window, "window_end_ns": window + 1_000_000,
            "ep_collectives": n,
            "critical_route_kv_overlap_count": stat["critical_route_overlap"],
            "critical_route_overlap_fraction": stat["critical_route_overlap"] / n if n else 0,
            "ep_cct_mean_us": sum(stat["cct_ns"]) / max(1, n) / 1000,
            "ep_cct_p99_us": percentile(stat["cct_ns"], .99) / 1000 if n else "",
            "critical_route_overlap_mean_ns": sum(stat["overlap_ns"]) / max(1, n),
            "decode_cohort_mean": (sum(stat["cohort_sizes"]) / len(stat["cohort_sizes"])
                                    if stat["cohort_sizes"] else ""),
            "validity": "route_coactivity_screen_only_no_complete_link_queue_telemetry",
        })
    write_csv(outdir / "EXPOSURE_WINDOW_RANKING.csv",
              ["window_start_ns", "window_end_ns", "ep_collectives",
               "critical_route_kv_overlap_count", "critical_route_overlap_fraction",
               "ep_cct_mean_us", "ep_cct_p99_us", "critical_route_overlap_mean_ns",
               "decode_cohort_mean", "validity"], ranking)

    kv_handoff = [int(row["remaining_slack_ns"]) for row in kv_barriers]
    serving = {}
    for metric, col in (("ttft_ns", "TTFT"), ("tpot_ns", "TPOT"), ("latency_ns", "latency")):
        vals = [float(row[col]) for row in requests if row.get(col) not in ("", "-1")]
        serving[metric] = summarize(vals)
    tbt_values = [float(value) for row in requests
                  for value in json.loads(row.get("TBT") or "[]")]
    cct_us = [v / 1000 for v in collective_ccts]
    summary = {
        "run_id": args.run_id,
        "topology_routing_model": network.topology_audit["routing_model"],
        "topology_directed_aggregate_pairs": len(network.edges),
        "kv_flow_count": len(kv_flows),
        "kv_total_bytes": sum(flow["bytes"] for flow in kv_flows.values()),
        "request_count": len(requests),
        "request_kv_barriers": len(kv_barriers),
        "all_kv_request_attribution_exact_single_request": all(
            row.get("request_ids") and len(row["request_ids"]) == 1
            for row in kv_flows.values()),
        "kv_handoff_slack_ns": summarize(kv_handoff),
        "requests_kv_finish_before_first_decode_batch": sum(
            row["kv_finish_before_first_decode"] == "True" for row in kv_barriers),
        "requests_with_decode_batch_join": len(request_batches),
        "decode_batch_count": len(groups),
        "decode_batch_active_request_count": summarize(
            [len(group["request_ids"]) for group in groups.values()]),
        "decode_batch_rows_per_batch": summarize([group["rows"] for group in groups.values()]),
        "collective_count": len(collective_events),
        "collective_events_matched_to_decode_iteration_interval": batch_contained,
        "collective_events_outside_or_unmatched": len(collective_events) - batch_contained,
        "collectives_per_decode_batch_distribution": summarize(list(batch_event_count.values())),
        "ep_cct_us": summarize(cct_us),
        "critical_peer_route_same_link_kv_overlap_count": len(overlap_cct),
        "critical_peer_route_same_link_kv_overlap_fraction": len(overlap_cct) / max(1, len(collective_events)),
        "overlap_collective_cct_us": summarize([v / 1000 for v in overlap_cct]),
        "top_critical_route_shared_links": overlap_link_counts.most_common(20),
        "request_step_tbt_join_count": len(request_step_rows),
        "request_step_tbt_unmatched_requests": len(requests) - len({r["request_id"] for r in request_step_rows}),
        "ep_cct_sum_over_tbt_nonadditive_proxy": summarize(step_ep_ratios),
        "serving": serving,
        "tbt_token_ns": summarize(tbt_values),
        "link_sidecar_note": "Must be audited separately for truncation/window coverage before any link queue/utilization claim.",
    }
    with (outdir / "analysis_summary.json").open("w", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
