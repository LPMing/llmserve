#!/usr/bin/env python3
"""Audit phase overlap and sampled packet queues in the Azure16 replay.

This deliberately keeps serving intervals (FlowSim) separate from packet
completion intervals (native ns-3). It does not claim packet feedback into the
serving scheduler.
"""

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


def percentile(values, p):
    values = sorted(values)
    if not values:
        return None
    pos = (len(values) - 1) * p
    lo, hi = math.floor(pos), math.ceil(pos)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def merge_intervals(intervals):
    out = []
    for start, end in sorted((a, b) for a, b in intervals if b > a):
        if not out or start > out[-1][1]:
            out.append([start, end])
        else:
            out[-1][1] = max(out[-1][1], end)
    return [(a, b) for a, b in out]


def overlap_intervals(left, right):
    left, right = merge_intervals(left), merge_intervals(right)
    out = []
    i = j = 0
    while i < len(left) and j < len(right):
        a, b = max(left[i][0], right[j][0]), min(left[i][1], right[j][1])
        if b > a:
            out.append((a, b))
        if left[i][1] <= right[j][1]:
            i += 1
        else:
            j += 1
    return out


def interval_length(intervals):
    return sum(b - a for a, b in merge_intervals(intervals))


def population_at(intervals, times):
    edges = []
    for start, end in intervals:
        if end > start:
            edges.append((start, 1))
            edges.append((end, -1))
    edges.sort()
    values = []
    index = count = 0
    for t in times:
        while index < len(edges) and edges[index][0] <= t:
            count += edges[index][1]
            index += 1
        values.append(count)
    return values


def weighted_population_stats(intervals, origin, end):
    changes = defaultdict(int)
    for start, finish in intervals:
        start, finish = max(start, origin), min(finish, end)
        if finish > start:
            changes[start] += 1
            changes[finish] -= 1
    changes[origin] += 0
    changes[end] += 0
    points = sorted(changes)
    durations = defaultdict(int)
    current = 0
    for i, t in enumerate(points[:-1]):
        current += changes[t]
        durations[current] += points[i + 1] - t
    total = sum(durations.values())

    def quantile(p):
        target = p * total
        seen = 0
        for value in sorted(durations):
            seen += durations[value]
            if seen >= target:
                return value
        return max(durations, default=0)

    return {
        "p50": quantile(.50), "p95": quantile(.95),
        "max": max(durations, default=0),
        "mean": (sum(k * v for k, v in durations.items()) / total
                 if total else 0),
        "duration_ns": total,
    }


def cross_request_overlap_ns(left, right):
    """Time with activity on both sides from at least two distinct requests."""
    events = defaultdict(lambda: [defaultdict(int), defaultdict(int)])
    for request_id, start, end in left:
        if end > start:
            events[start][0][request_id] += 1
            events[end][0][request_id] -= 1
    for request_id, start, end in right:
        if end > start:
            events[start][1][request_id] += 1
            events[end][1][request_id] -= 1
    active = [defaultdict(int), defaultdict(int)]
    total = 0
    points = sorted(events)
    for i, timestamp in enumerate(points[:-1]):
        for side in (0, 1):
            for request_id, delta in events[timestamp][side].items():
                active[side][request_id] += delta
                if active[side][request_id] <= 0:
                    active[side].pop(request_id, None)
        if not active[0] or not active[1]:
            continue
        if any(a != b for a in active[0] for b in active[1]):
            total += points[i + 1] - timestamp
    return total


def read_comm_events(path):
    starts, flows = {}, []
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            event_id = row["event_id"]
            if row["phase"] == "START":
                starts[event_id] = row
            elif row["phase"] == "END":
                start = starts.pop(event_id, None)
                if start is None:
                    continue
                actual_links = [x for x in row.get("directed_link_ids", "").split(";")
                                if x and x != "-1"]
                if not actual_links:
                    actual_links = [x for x in start.get("directed_link_ids", "").split(";")
                                    if x and x != "-1"]
                flows.append({
                    "event_id": int(event_id),
                    "type": int(start["event_type"]),
                    "request_id": int(start["request_id"]),
                    "collective_id": int(start["collective_id"]),
                    "layer_id": int(start["layer_id"]),
                    "src": int(start["src"]), "dst": int(start["dst"]),
                    "bytes": int(start["bytes"]),
                    "issue": int(start["issue_time_ns"]),
                    "start": int(start["network_start_ns"]),
                    "end": int(row["network_end_ns"]),
                    "links": set(actual_links),
                    "active_request_ids": start.get("active_request_ids", ""),
                })
    if starts:
        raise RuntimeError("{} unmatched START rows in {}".format(len(starts), path))
    return flows


def read_topology(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    node_count, switch_count, edge_count = map(int, lines[0].split())
    switch_ids = set(map(int, lines[1].split()))
    edges = []
    port_map = {}
    device_counts = defaultdict(lambda: 1)  # ns-3 device zero is loopback
    for edge_index, line in enumerate(lines[2:2 + edge_count]):
        fields = line.split()
        src, dst = int(fields[0]), int(fields[1])
        edges.append({"link_id": edge_index * 2, "src": src, "dst": dst,
                      "capacity": fields[2]})
        port_map[(src, device_counts[src])] = (dst, edge_index * 2)
        device_counts[src] += 1
        port_map[(dst, device_counts[dst])] = (src, edge_index * 2 + 1)
        device_counts[dst] += 1
    return node_count, switch_ids, edges, port_map


def read_queue_samples(path, port_map):
    samples = defaultdict(list)
    if not path.is_file():
        return samples
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            fields = line.split()
            if len(fields) < 3 or fields[0] != "time":
                continue
            timestamp, node = int(fields[1]), int(fields[2])
            index = 3
            while index + 2 < len(fields):
                if fields[index] == "j":
                    port, size = int(fields[index + 1]), int(fields[index + 2])
                    mapped = port_map.get((node, port))
                    if mapped:
                        samples[mapped[1]].append((timestamp, size))
                    index += 3
                else:
                    index += 1
    return samples


def queue_episodes(samples, links, interval_ns, threshold=1000):
    by_id = {int(row["link_id"]): row for row in links}
    episodes = []
    for link_id, rows in samples.items():
        rows = sorted((t, q) for t, q in rows if q >= threshold)
        current = []
        for sample in rows:
            if current and sample[0] - current[-1][0] > interval_ns:
                episodes.append((link_id, current))
                current = []
            current.append(sample)
        if current:
            episodes.append((link_id, current))
    result = []
    for link_id, group in episodes:
        link = by_id[link_id]
        src, dst = int(link["src_node"]), int(link["dst_node"])
        kind = ("decode_ingress" if dst in range(72, 80) and src in (82, 83)
                else "leaf_spine_cut" if src in range(80, 84) and dst in (84, 85)
                or src in (84, 85) and dst in range(80, 84)
                else "other")
        start, last = group[0][0], group[-1][0]
        result.append({
            "link_id": link_id, "src_node": src, "dst_node": dst,
            "link_kind": kind, "start_ns": start,
            "end_estimate_ns": last + interval_ns,
            "duration_estimate_ns": last - start + interval_ns,
            "max_sampled_queue_bytes": max(q for _, q in group),
            "mean_sampled_queue_bytes": sum(q for _, q in group) / len(group),
            "positive_samples": len(group),
            "sampling_interval_ns": interval_ns,
            "minimum_reported_queue_bytes": threshold,
        })
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--request-csv", type=Path, required=True)
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ns3-run", default="ns3_ack_reserved_fair")
    parser.add_argument("--bin-us", type=int, default=100)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    requests = list(csv.DictReader(args.request_csv.open(newline="", encoding="utf-8")))
    ns3_dir = args.base / args.ns3_run
    flows = read_comm_events(ns3_dir / "comm_events.csv")
    node_count, switch_ids, edges, port_map = read_topology(args.topology)
    link_rows = list(csv.DictReader((ns3_dir / "link_summary.csv").open(
        newline="", encoding="utf-8")))
    q_samples = read_queue_samples(ns3_dir / "qlen.txt", port_map)
    queue_interval = 100_000
    conf = ns3_dir / "replay.conf"
    for line in conf.read_text(encoding="utf-8").splitlines():
        if line.startswith("QLEN_MON_INTERVAL_NS "):
            queue_interval = int(line.split()[1])
    episodes = queue_episodes(q_samples, link_rows, queue_interval)

    # Serving-stage intervals are taken only from the integrated FlowSim ledger.
    decode_intervals, decode_labeled = [], []
    prefill_lifecycle = []
    arrivals = []
    request_by_id = {}
    for row in requests:
        rid = int(row["request id"])
        request_by_id[rid] = row
        arrival = int(row["arrival"])
        prefill_end = int(row["prefill_completion_time_ns"])
        decode_start = int(row["decode_scheduler_admit_time_ns"])
        finish = int(row["end_time"])
        arrivals.append(arrival)
        if prefill_end > arrival:
            prefill_lifecycle.append((arrival, prefill_end))
        if finish > decode_start:
            decode_intervals.append((decode_start, finish))
            decode_labeled.append((rid, decode_start, finish))

    kv_flows = [f for f in flows if f["type"] == 1]
    ep_flows = [f for f in flows if f["type"] in (2, 3)]
    kv_flow_intervals = [(f["start"], f["end"]) for f in kv_flows]
    ep_flow_intervals = [(f["start"], f["end"]) for f in ep_flows]
    kv_by_request = defaultdict(list)
    for f in kv_flows:
        kv_by_request[f["request_id"]].append((f["start"], f["end"]))
    kv_request_intervals = [iv for group in kv_by_request.values()
                            for iv in merge_intervals(group)]

    ep_groups = defaultdict(list)
    for flow in ep_flows:
        ep_groups[(flow["collective_id"], flow["type"])].append(flow)
    collectives = []
    for (cid, kind), group in ep_groups.items():
        start = min(f["start"] for f in group)
        end = max(f["end"] for f in group)
        active_ids = set()
        for flow in group:
            if flow["request_id"] >= 0:
                active_ids.add(flow["request_id"])
            active_ids.update(int(x) for x in flow["active_request_ids"].split(",")
                              if x.strip().isdigit())
        collectives.append({"id": cid, "type": kind, "start": start,
                            "end": end, "request_ids": active_ids,
                            "flow_count": len(group),
                            "bytes": sum(f["bytes"] for f in group),
                            "cct_ns": end - start})
    ep_collective_intervals = [(c["start"], c["end"]) for c in collectives]

    # Request-specific fourth-token warm points. TBT entries are intervals after
    # the first token; reaching the fourth emitted token consumes three intervals.
    warm_decode, warm_decode_labeled = [], []
    for row in requests:
        output_len = int(row["output"])
        if output_len < 4:
            continue
        first_token = int(row["decode_first_token_time_ns"])
        raw = row.get("TBT", "[]")
        try:
            tbt = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            tbt = []
        if len(tbt) >= 3:
            warm = first_token + sum(int(x) for x in tbt[:3])
            finish = int(row["end_time"])
            if finish > warm:
                warm_decode.append((warm, finish))
                warm_decode_labeled.append((int(row["request id"]), warm, finish))
    p2d_labeled = [
        (rid, start, finish)
        for rid, intervals in kv_by_request.items()
        for start, finish in merge_intervals(intervals)
    ]
    warm_ep_labeled = []
    warm_by_request = defaultdict(list)
    for rid, start, finish in warm_decode_labeled:
        warm_by_request[rid].append((start, finish))
    for collective in collectives:
        for rid in collective["request_ids"]:
            if rid not in warm_by_request:
                continue
            for start, finish in overlap_intervals(
                    warm_by_request[rid], [(collective["start"], collective["end"])]):
                warm_ep_labeled.append((rid, start, finish))

    origin = min([f["start"] for f in flows] + arrivals)
    end_time = max([f["end"] for f in flows] +
                   [int(r["end_time"]) for r in requests])
    bin_ns = args.bin_us * 1000
    bin_starts = list(range((origin // bin_ns) * bin_ns, end_time, bin_ns))
    bin_times = [t + bin_ns // 2 for t in bin_starts]

    activity_series = {
        "prefill_lifecycle_proxy": population_at(prefill_lifecycle, bin_times),
        "active_p2d_requests": population_at(kv_request_intervals, bin_times),
        "active_p2d_flows": population_at(kv_flow_intervals, bin_times),
        "active_decode_requests": population_at(decode_intervals, bin_times),
        "active_ep_flows": population_at(ep_flow_intervals, bin_times),
        "active_ep_collectives": population_at(ep_collective_intervals, bin_times),
        "decode_warm_after_4_tokens": population_at(warm_decode, bin_times),
    }
    issued = defaultdict(lambda: [0, 0])
    for flow in flows:
        index = (flow["issue"] - bin_starts[0]) // bin_ns
        if 0 <= index < len(bin_starts):
            issued[index][0 if flow["type"] == 1 else 1] += flow["bytes"]
    timeline_path = args.output_dir / "STEADY_STATE_ACTIVITY_TIMELINE.csv"
    fields = ["timestamp_ns", "bin_width_ns", *activity_series,
              "issued_kv_bytes_per_interval", "issued_ep_bytes_per_interval",
              "issued_kv_gbps", "issued_ep_gbps"]
    with timeline_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for i, t in enumerate(bin_starts):
            kv_bytes, ep_bytes = issued[i]
            writer.writerow({
                "timestamp_ns": t, "bin_width_ns": bin_ns,
                **{name: values[i] for name, values in activity_series.items()},
                "issued_kv_bytes_per_interval": kv_bytes,
                "issued_ep_bytes_per_interval": ep_bytes,
                "issued_kv_gbps": kv_bytes * 8 / bin_ns,
                "issued_ep_gbps": ep_bytes * 8 / bin_ns,
            })

    # Overall flow-lifetime overlap and directed-link path-overlap proxy.
    kv_union, ep_union = merge_intervals(kv_flow_intervals), merge_intervals(ep_flow_intervals)
    any_overlap = overlap_intervals(kv_union, ep_union)
    any_overlap_ns = interval_length(any_overlap)
    any_union_ns = interval_length(kv_union + ep_union)
    by_link = {"kv": defaultdict(list), "ep": defaultdict(list)}
    for f in kv_flows:
        for link in f["links"]:
            by_link["kv"][link].append((f["start"], f["end"]))
    for f in ep_flows:
        for link in f["links"]:
            by_link["ep"][link].append((f["start"], f["end"]))
    link_overlap_intervals, link_overlap_sum, link_active_sum = [], 0, 0
    per_link_overlap = {}
    for link in set(by_link["kv"]) & set(by_link["ep"]):
        k, e = merge_intervals(by_link["kv"][link]), merge_intervals(by_link["ep"][link])
        overlaps = overlap_intervals(k, e)
        duration = interval_length(overlaps)
        if duration:
            per_link_overlap[link] = duration
            link_overlap_intervals.extend(overlaps)
            link_overlap_sum += duration
            link_active_sum += interval_length(k + e)
    shared_wall_ns = interval_length(link_overlap_intervals)

    # Identify decode NIC ingress and leaf-spine cut links from node roles.
    decode_ingress_ids = set()
    leaf_spine_ids = set()
    for row in link_rows:
        lid, src, dst = int(row["link_id"]), int(row["src_node"]), int(row["dst_node"])
        if dst in range(72, 80) and src in (82, 83):
            decode_ingress_ids.add(lid)
        if (src in range(80, 84) and dst in (84, 85)) or (
                src in (84, 85) and dst in range(80, 84)):
            leaf_spine_ids.add(lid)
    episode_path = args.output_dir / "AZURE16_QUEUE_EPISODES.csv"
    episode_fields = ["link_id", "src_node", "dst_node", "link_kind", "start_ns",
                      "end_estimate_ns", "duration_estimate_ns",
                      "max_sampled_queue_bytes", "mean_sampled_queue_bytes",
                      "positive_samples", "sampling_interval_ns",
                      "minimum_reported_queue_bytes"]
    with episode_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=episode_fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(episodes)

    relevant_episodes = [e for e in episodes if e["link_kind"] in
                         ("decode_ingress", "leaf_spine_cut")]
    ep_collectives_starting_in = {"decode_ingress": 0, "leaf_spine_cut": 0}
    for ep in collectives:
        for episode in relevant_episodes:
            if episode["start_ns"] <= ep["start"] < episode["end_estimate_ns"]:
                ep_collectives_starting_in[episode["link_kind"]] += 1
                break

    def duration_stats(values):
        return {"p50_us": percentile(values, .50) / 1000 if values else 0,
                "p95_us": percentile(values, .95) / 1000 if values else 0,
                "max_us": max(values) / 1000 if values else 0,
                "count": len(values)}

    starts_by_type = defaultdict(list)
    for collective in collectives:
        starts_by_type[collective["type"]].append(collective["start"])
    period_stats = {}
    for kind, starts in starts_by_type.items():
        periods = [b - a for a, b in zip(sorted(starts), sorted(starts)[1:])]
        period_stats[str(kind)] = duration_stats(periods)

    pop_stats = {
        "decode_scheduler_active": weighted_population_stats(decode_intervals, origin, end_time),
        "p2d_request_network_active": weighted_population_stats(kv_request_intervals, origin, end_time),
        "p2d_flow_network_active": weighted_population_stats(kv_flow_intervals, origin, end_time),
        "ep_flow_network_active": weighted_population_stats(ep_flow_intervals, origin, end_time),
        "ep_collective_network_active": weighted_population_stats(ep_collective_intervals, origin, end_time),
        "prefill_lifecycle_proxy_not_compute_active": weighted_population_stats(
            prefill_lifecycle, origin, end_time),
        "decode_warm_after_four_emitted_tokens": weighted_population_stats(
            warm_decode, origin, end_time),
    }
    queue_by_kind = defaultdict(list)
    for episode in episodes:
        queue_by_kind[episode["link_kind"]].append(episode["duration_estimate_ns"])
    relevant_queue = {}
    for kind in ("decode_ingress", "leaf_spine_cut", "other"):
        relevant_queue[kind] = duration_stats(queue_by_kind[kind])

    arrivals.sort()
    arrival_gaps = [b - a for a, b in zip(arrivals, arrivals[1:])]
    all_requests_ids = set(request_by_id)
    stats = {
        "request_count": len(requests),
        "request_ids": sorted(all_requests_ids),
        "arrival_span_ms": (max(arrivals) - min(arrivals)) / 1e6 if arrivals else 0,
        "arrival_gap_us": duration_stats(arrival_gaps),
        "arrival_count_within_1ms_max": max(
            (sum(1 for a in arrivals if t <= a < t + 1_000_000)
             for t in arrivals), default=0),
        "input_tokens_total": sum(int(r["input"]) for r in requests),
        "output_tokens_total": sum(int(r["output"]) for r in requests),
        "requests_with_output_ge_4": sum(int(r["output"]) >= 4 for r in requests),
        "decode_intervals_definition": "decode_scheduler_admit_time_ns to request end_time from integrated FlowSim requests.csv",
        "prefill_interval_definition": "arrival to prefill_completion_time_ns; lifecycle proxy only, not active compute",
        "warm_decode_definition": "after first token plus first 3 recorded TBT intervals (fourth emitted token), until request end; request-level proxy for several decode iterations",
        "network_replay": str(ns3_dir),
        "network_flow_count": len(flows),
        "p2d_flow_count": len(kv_flows),
        "ep_dispatch_flow_count": sum(f["type"] == 2 for f in flows),
        "ep_combine_flow_count": sum(f["type"] == 3 for f in flows),
        "ep_collective_count_dispatch_combine": len(collectives),
        "observation_start_ns": origin,
        "observation_end_ns": end_time,
        "observation_duration_ms": (end_time - origin) / 1e6,
        "population_time_weighted": pop_stats,
        "kv_ep_flow_lifetime_overlap_ns": any_overlap_ns,
        "kv_ep_overlap_duty_cycle_union": any_overlap_ns / any_union_ns if any_union_ns else 0,
        "kv_ep_overlap_fraction_observation": any_overlap_ns / (end_time - origin),
        "decode_and_p2d_any_overlap_ns_including_possible_same_request": interval_length(
            overlap_intervals(decode_intervals, kv_request_intervals)),
        "decode_and_p2d_cross_request_overlap_ns": cross_request_overlap_ns(
            decode_labeled, p2d_labeled),
        "warm_decode_and_p2d_cross_request_overlap_ns": cross_request_overlap_ns(
            warm_decode_labeled, p2d_labeled),
        "warm_decode_ep_and_other_request_p2d_overlap_ns": cross_request_overlap_ns(
            warm_ep_labeled, p2d_labeled),
        "same_directed_link_flow_lifetime_overlap_wall_ns": shared_wall_ns,
        "same_directed_link_flow_lifetime_overlap_fraction_observation": shared_wall_ns / (end_time - origin),
        "same_directed_link_overlap_link_ns": link_overlap_sum,
        "same_directed_link_union_activity_link_ns": link_active_sum,
        "same_directed_link_overlap_link_fraction": link_overlap_sum / link_active_sum if link_active_sum else 0,
        "directed_links_with_kv_and_ep_overlap": len(per_link_overlap),
        "top_shared_directed_links_by_overlap_ns": sorted(
            ({"link_id": int(k), "overlap_ns": v} for k, v in per_link_overlap.items()),
            key=lambda x: x["overlap_ns"], reverse=True)[:20],
        "ep_collective_inter_start_period": period_stats,
        "qlen_monitor_interval_ns": queue_interval,
        "qlen_reporting_threshold_bytes": 1000,
        "queue_episode_method": "switch egress MMU qlen snapshots; sampled every configured interval; only queues >=1000 B are printed; episode duration is a sampled estimate, not exact queue occupancy duration",
        "queue_episode_duration_estimates": relevant_queue,
        "ep_collectives_starting_during_sampled_queue_episode": ep_collectives_starting_in,
        "queue_episode_count_decode_ingress": sum(e["link_kind"] == "decode_ingress" for e in episodes),
        "queue_episode_count_leaf_spine": sum(e["link_kind"] == "leaf_spine_cut" for e in episodes),
        "decode_ingress_directed_links": sorted(decode_ingress_ids),
        "leaf_spine_directed_links": sorted(leaf_spine_ids),
        "topology_nodes": node_count,
        "switch_node_ids": sorted(switch_ids),
        "timeline_bin_ns": bin_ns,
        "caveat": "ns-3 packet completions are not fed back into the integrated FlowSim serving schedule; serving intervals and packet network intervals are aligned by the original fixed issue timestamps, not a closed-loop ns-3 serving run. Flow-lifetime path overlap is not per-packet simultaneous link occupancy.",
    }
    (args.output_dir / "azure16_phase_overlap_metrics.json").write_text(
        json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
