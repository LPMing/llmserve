#!/usr/bin/env python3
"""Export a compact time-binned view of one physical Prefill NIC uplink."""

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path


def bucket(timestamp, interval_ns):
    return timestamp // interval_ns * interval_ns


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--link-id", type=int, default=152)
    parser.add_argument("--interval-ns", type=int, default=100_000,
                        help="default 100 us, matching the replay link telemetry cadence")
    args = parser.parse_args()
    if args.interval_ns <= 0:
        parser.error("--interval-ns must be positive")

    starts = defaultdict(list)
    finishes = defaultdict(list)
    completed_by_bucket = Counter()
    issued = defaultdict(lambda: {"bytes": 0, "requests": set(),
                                  "src_ranks": set(), "layers": set(), "count": 0,
                                  "by_request_bytes": Counter(),
                                  "by_request_count": Counter()})
    flow_starts = {}
    flow_rows = {}
    with (args.run_dir / "comm_events.csv").open(
            encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            event_id = int(row["event_id"])
            if row["phase"] == "START":
                if int(row["event_type"]) != 1:
                    continue
                flow_starts[event_id] = {
                    "issue_ns": int(row["issue_time_ns"]),
                    "request_id": int(row["request_id"]),
                    "layer": int(row["layer_id"]),
                    "src_rank": int(row["src_rank"]),
                    "bytes": int(row["bytes"]),
                }
            elif row["phase"] == "END" and event_id in flow_starts:
                flow = flow_starts.pop(event_id)
                links = [int(value) for value in
                         row["directed_link_ids"].split(";") if value]
                if args.link_id not in links:
                    continue
                finish_ns = int(row["network_end_ns"])
                start_bucket = bucket(flow["issue_ns"], args.interval_ns)
                finish_bucket = bucket(finish_ns, args.interval_ns)
                starts[flow["issue_ns"]].append((event_id, flow))
                finishes[finish_ns].append(event_id)
                completed_by_bucket[bucket(finish_ns, args.interval_ns)] += 1
                interval = issued[start_bucket]
                interval["bytes"] += flow["bytes"]
                interval["requests"].add(flow["request_id"])
                interval["src_ranks"].add(flow["src_rank"])
                interval["layers"].add(flow["layer"])
                interval["count"] += 1
                interval["by_request_bytes"][flow["request_id"]] += flow["bytes"]
                interval["by_request_count"][flow["request_id"]] += 1
                flow_rows[event_id] = (flow, finish_ns)

    if not flow_rows:
        raise SystemExit(f"no completed P2D KV flow traversed directed link {args.link_id}")

    local_marks = Counter()
    local_by_request = defaultdict(Counter)
    mark_path = args.run_dir / "local_ecn_marks.csv"
    if mark_path.is_file():
        with mark_path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                if int(row["link_id"]) != args.link_id:
                    continue
                time_ns = int(row["timestamp_ns"])
                local_marks[bucket(time_ns, args.interval_ns)] += 1
                for request_id in row["request_ids"].split(";"):
                    if request_id:
                        local_by_request[bucket(time_ns, args.interval_ns)][int(request_id)] += 1

    qp_to_request = {}
    cnp_events = Counter()
    rate_decreases = Counter()
    cc_path = args.run_dir / "cc_events.csv"
    if cc_path.is_file():
        flow_by_qp_start = {}
        # Re-read only the comparatively small request-event ledger to recover
        # the exact packet-QP join tuple for each P2D event.
        with (args.run_dir / "comm_events.csv").open(
                encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                if row["phase"] != "START" or int(row["event_type"]) != 1:
                    continue
                event_id = int(row["event_id"])
                if event_id not in flow_rows:
                    continue
                flow_by_qp_start[(int(row["src_rank"]), int(row["dst_rank"]),
                                  int(row["port"]), int(row["bytes"]),
                                  int(row["issue_time_ns"]))] = (
                    int(row["request_id"]), event_id)
        qp_to_request = {}
        with cc_path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                event = row["event"]
                identity = (int(row["node_id"]), int(row["qp_id"]))
                time_ns = int(row["timestamp"])
                time_bucket = bucket(time_ns, args.interval_ns)
                if event == "QP_START":
                    key = (int(row["src_rank"]), int(row["dst_rank"]),
                           int(row["sport"]), int(row["bytes"]), time_ns)
                    match = flow_by_qp_start.get(key)
                    if match is not None:
                        qp_to_request[identity] = match[0]
                elif event == "CNP" and identity in qp_to_request:
                    cnp_events[(time_bucket, qp_to_request[identity])] += 1
                elif (event == "RATE" and identity in qp_to_request and
                      int(row["new_rate_bps"]) < int(row["old_rate_bps"])):
                    rate_decreases[(time_bucket, qp_to_request[identity])] += 1

    link_samples = defaultdict(lambda: {"queue_max": 0, "tx_bytes": 0,
                                        "tx_packets": 0, "ce_tx": 0})
    previous_counters = None
    link_path = args.run_dir / "link_timeseries.csv"
    with link_path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if int(row["link_id"]) != args.link_id:
                continue
            time_ns = int(row["timestamp"])
            current = (int(row["tx_bytes"]), int(row["tx_packets"]),
                       int(row["ecn_marks"]))
            sample = link_samples[bucket(time_ns, args.interval_ns)]
            sample["queue_max"] = max(sample["queue_max"], int(row["queue_bytes"]))
            if previous_counters is not None:
                sample["tx_bytes"] += max(0, current[0] - previous_counters[0])
                sample["tx_packets"] += max(0, current[1] - previous_counters[1])
                sample["ce_tx"] += max(0, current[2] - previous_counters[2])
            previous_counters = current

    min_time = min(flow["issue_ns"] for flow, _ in flow_rows.values())
    max_time = max(finish for _, finish in flow_rows.values())
    first_bucket = bucket(min_time, args.interval_ns)
    last_bucket = bucket(max_time, args.interval_ns)
    event_times = sorted(set(starts) | set(finishes))
    event_index = 0
    active = {}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["interval_start_ns", "interval_end_ns", "active_kv_qps_end",
              "active_kv_requests_end", "active_source_ranks_end",
              "kv_flows_issued", "kv_offered_bytes", "kv_offered_gbps",
              "kv_flows_completed", "nic_link_tx_bytes", "nic_link_tx_packets",
              "nic_link_drain_gbps", "sampled_queue_max_bytes",
              "ce_carry_tx_observations", "local_new_ce_marks",
              "local_ce_request_counts", "cnp_events_by_request",
              "rate_decreases_by_request", "issued_request_ids",
              "issued_source_ranks", "issued_layers"]
    fields.extend(["active_kv_qps_by_request", "active_kv_bytes_by_request",
                   "issued_flow_count_by_request", "offered_bytes_by_request"])
    with args.output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for interval_start in range(first_bucket, last_bucket + 1, args.interval_ns):
            interval_end = interval_start + args.interval_ns
            max_active = len(active)
            while event_index < len(event_times) and event_times[event_index] < interval_end:
                timestamp = event_times[event_index]
                for event_id in finishes.get(timestamp, []):
                    active.pop(event_id, None)
                for event_id, flow in starts.get(timestamp, []):
                    active[event_id] = flow
                max_active = max(max_active, len(active))
                event_index += 1
            issued_row = issued[interval_start]
            link_row = link_samples[interval_start]
            cnp_by_req = {str(req): n for (t, req), n in cnp_events.items()
                          if t == interval_start}
            rate_by_req = {str(req): n for (t, req), n in rate_decreases.items()
                           if t == interval_start}
            ce_by_req = local_by_request[interval_start]
            active_requests = sorted({f["request_id"] for f in active.values()})
            active_sources = sorted({f["src_rank"] for f in active.values()})
            active_by_request = Counter(f["request_id"] for f in active.values())
            active_bytes_by_request = Counter()
            for flow in active.values():
                active_bytes_by_request[flow["request_id"]] += flow["bytes"]
            offered_gbps = issued_row["bytes"] * 8 / (args.interval_ns / 1e9) / 1e9
            drain_gbps = link_row["tx_bytes"] * 8 / (args.interval_ns / 1e9) / 1e9
            writer.writerow({
                "interval_start_ns": interval_start,
                "interval_end_ns": interval_end,
                "active_kv_qps_end": len(active),
                "active_kv_requests_end": ";".join(map(str, active_requests)),
                "active_source_ranks_end": ";".join(map(str, active_sources)),
                "kv_flows_issued": issued_row["count"],
                "kv_offered_bytes": issued_row["bytes"],
                "kv_offered_gbps": offered_gbps,
                "kv_flows_completed": completed_by_bucket[interval_start],
                "nic_link_tx_bytes": link_row["tx_bytes"],
                "nic_link_tx_packets": link_row["tx_packets"],
                "nic_link_drain_gbps": drain_gbps,
                "sampled_queue_max_bytes": link_row["queue_max"],
                "ce_carry_tx_observations": link_row["ce_tx"],
                "local_new_ce_marks": local_marks[interval_start],
                "local_ce_request_counts": ";".join(
                    f"{req}:{count}" for req, count in sorted(ce_by_req.items())),
                "cnp_events_by_request": ";".join(
                    f"{req}:{count}" for req, count in sorted(cnp_by_req.items())),
                "rate_decreases_by_request": ";".join(
                    f"{req}:{count}" for req, count in sorted(rate_by_req.items())),
                "issued_request_ids": ";".join(
                    map(str, sorted(issued_row["requests"]))),
                "issued_source_ranks": ";".join(
                    map(str, sorted(issued_row["src_ranks"]))),
                "issued_layers": ";".join(map(str, sorted(issued_row["layers"]))),
                "active_kv_qps_by_request": ";".join(
                    f"{req}:{count}" for req, count in sorted(active_by_request.items())),
                "active_kv_bytes_by_request": ";".join(
                    f"{req}:{count}" for req, count in sorted(active_bytes_by_request.items())),
                "issued_flow_count_by_request": ";".join(
                    f"{req}:{count}" for req, count in
                    sorted(issued_row["by_request_count"].items())),
                "offered_bytes_by_request": ";".join(
                    f"{req}:{count}" for req, count in
                    sorted(issued_row["by_request_bytes"].items())),
            })
    print(f"wrote {args.output}: {len(range(first_bucket, last_bucket + 1, args.interval_ns))} bins, "
          f"link={args.link_id}, interval_ns={args.interval_ns}, "
          f"matched_flows={len(flow_rows)}")


if __name__ == "__main__":
    main()
