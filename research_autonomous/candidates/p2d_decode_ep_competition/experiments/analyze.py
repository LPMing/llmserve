#!/usr/bin/env python3
"""Audit directed KV/EP overlap and Serving events in the Round-15 cases."""

import bisect
import csv
import gzip
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
EXPECTED_NEW_BYTES = 201_326_592
EXPECTED_OLD_BYTES = 12_582_912


def read_jsonl(path):
    for line in path.open():
        if line.startswith("{"):
            yield json.loads(line)


def cut_edges(path):
    result = set()
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] == "200Gbps":
            a, b = parts[:2]
            result.add(a + "->" + b)
            result.add(b + "->" + a)
    return result


def analyze(case):
    rows = list(csv.DictReader((case / "requests.csv").open(newline="")))
    expected_count = 8 if case.name.startswith("control_") else 24
    if len(rows) != expected_count:
        raise AssertionError("%s: expected %d requests, got %d" %
                             (case, expected_count, len(rows)))
    requests = {int(row["request id"]): row for row in rows}
    if sorted(requests) != list(range(expected_count)):
        raise AssertionError("request IDs are not complete")
    flows = list(read_jsonl(case / "flows.jsonl"))
    kv = [f for f in flows if f.get("traffic_subtype") == "P2D"]
    ep = [f for f in flows if f.get("traffic_class") == "EP"]
    if len(kv) + len(ep) != len(flows):
        raise AssertionError("unexpected network traffic class")
    expected_kv = 8 * EXPECTED_OLD_BYTES + (expected_count - 8) * EXPECTED_NEW_BYTES
    if sum(int(f["bytes"]) for f in kv) != expected_kv:
        raise AssertionError("P2D bytes do not conserve model-derived KV")
    new_by_request = defaultdict(int)
    new_last_flow = defaultdict(int)
    for flow in kv:
        ids = flow.get("request_ids") or []
        if any(int(value) >= 8 for value in ids):
            if len(ids) != 1:
                raise AssertionError("new Prefill flow ambiguously batches requests")
            new_by_request[int(ids[0])] += int(flow["bytes"])
            new_last_flow[int(ids[0])] = max(
                new_last_flow[int(ids[0])], int(flow["end_ns"]))
    if expected_count > 8 and (len(new_by_request) != expected_count - 8 or
                               any(value != EXPECTED_NEW_BYTES
                                   for value in new_by_request.values())):
        raise AssertionError("new-request P2D bytes are not conserved")
    new_flow_to_ready_slacks = [
        (int(requests[rid]["p2d_kv_ready_time_ns"]) - end) / 1e6
        for rid, end in new_last_flow.items()]
    if any(value < 0 for value in new_flow_to_ready_slacks):
        raise AssertionError("a new P2D flow finished after its ready barrier")

    rails = cut_edges(case / "minimal_1p2d_ep16_single_tor_nvlink.txt")
    with gzip.open(case / "flow_ledger.csv.gz", "wt", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("request_id", "source_rank", "dest_rank", "bytes",
                         "start_ns", "end_ns", "source_rail", "dest_rail",
                         "source_endpoint", "dest_endpoint", "physical_path",
                         "traffic_class", "traffic_subtype"))
        for flow in flows:
            cut_path = [edge for edge in flow.get("path", []) if edge in rails]
            writer.writerow((
                "|".join(map(str, flow.get("request_ids") or [])),
                flow.get("logical_src"), flow.get("logical_dst"),
                flow["bytes"], flow["start_ns"], flow["end_ns"],
                cut_path[0] if cut_path else "",
                cut_path[-1] if cut_path else "",
                flow.get("src"), flow.get("dst"),
                "|".join(flow.get("path", [])), flow.get("traffic_class"),
                flow.get("traffic_subtype")))

    events = list(read_jsonl(case / "events.jsonl"))
    event_counts = Counter(event["event"] for event in events)
    with (case / "request_timeline.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("request_id", "arrival_ns", "prefill_end_ns",
                         "kv_ready_ns", "p2d_ready_ns", "decode_admit_ns",
                         "stall_ns", "token2_ns", "completion_ns"))
        for rid in sorted(requests):
            row = requests[rid]
            arrival = int(row["arrival"])
            ready = int(row["p2d_kv_ready_time_ns"])
            writer.writerow((rid, arrival, arrival + int(row["TTFT"]),
                             ready, ready, int(row["decode_admit_time_ns"]),
                             int(row["decode_capacity_queue_wait_ns"]),
                             int(row["second_token_visible_ns"]),
                             int(row["end_time"])))

    ep_by_link = defaultdict(list)
    max_ep_duration = 0
    for flow in ep:
        start = int(flow["start_ns"])
        end = int(flow["end_ns"])
        max_ep_duration = max(max_ep_duration, end - start)
        for link in flow.get("path", []):
            ep_by_link[link].append((start, end))
    for arr in ep_by_link.values():
        arr.sort()
    pair_count = 0
    matched_kv_links = 0
    shared_links = set()
    for flow in kv:
        if not any(int(rid) >= 8 for rid in (flow.get("request_ids") or [])):
            continue
        start = int(flow["start_ns"])
        end = int(flow["end_ns"])
        for link in flow.get("path", []):
            arr = ep_by_link.get(link, [])
            lo = bisect.bisect_left(arr, (start - max_ep_duration, -1))
            hi = bisect.bisect_left(arr, (end + 1, -1))
            matches = sum(1 for ep_start, ep_end in arr[lo:hi]
                          if ep_end > start and ep_start < end)
            if matches:
                pair_count += matches
                matched_kv_links += 1
                shared_links.add(link)

    def metric(subset):
        return {
            "requests": len(subset),
            "mean_token2_ms": statistics.mean(
                (int(r["second_token_visible_ns"]) - int(r["arrival"])) /
                1e6 for r in subset),
            "mean_tpot_ms": statistics.mean(float(r["TPOT"]) / 1e6
                                            for r in subset),
            "mean_completion_ms": statistics.mean(int(r["latency"]) / 1e6
                                                  for r in subset),
            "max_absolute_completion_ms": max(int(r["end_time"]) / 1e6
                                              for r in subset),
        }

    old = [r for r in rows if int(r["request id"]) < 8]
    new = [r for r in rows if int(r["request id"]) >= 8]
    result = {
        "case": case.name,
        "request_count": len(rows),
        "flow_count": len(flows),
        "kv_flow_count": len(kv),
        "ep_flow_count": len(ep),
        "kv_bytes": sum(int(f["bytes"]) for f in kv),
        "ep_bytes": sum(int(f["bytes"]) for f in ep),
        "new_kv_ep_same_directed_link_interval_pairs": pair_count,
        "new_kv_link_rows_overlapping_ep": matched_kv_links,
        "min_new_last_flow_to_ready_slack_ms": (
            min(new_flow_to_ready_slacks) if new_flow_to_ready_slacks else None),
        "shared_directed_links": sorted(shared_links),
        "event_counts": dict(event_counts),
        "old": metric(old),
        "new": metric(new) if new else None,
    }
    (case / "analysis.json").write_text(json.dumps(
        result, indent=2, sort_keys=True) + "\n")
    return result


def main():
    summaries = []
    for name in ("control_fair", "fair", "ep_first", "kv_first"):
        case = HERE / name
        if (case / "requests.csv").exists():
            summaries.append(analyze(case))
    (HERE / "summary.json").write_text(json.dumps(
        summaries, indent=2, sort_keys=True) + "\n")
    for row in summaries:
        print(row["case"], "kv_bytes", row["kv_bytes"],
              "overlap", row["new_kv_ep_same_directed_link_interval_pairs"],
              "old_tpot_ms", round(row["old"]["mean_tpot_ms"], 6),
              "new_completion_ms", (round(row["new"]["mean_completion_ms"], 6)
                                    if row["new"] else None))


if __name__ == "__main__":
    main()
