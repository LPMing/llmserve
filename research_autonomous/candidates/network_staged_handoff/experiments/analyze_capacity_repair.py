#!/usr/bin/env python3
"""Check byte, credit and Serving-event conservation in the capacity run."""

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("case", type=Path)
    args = parser.parse_args()
    case = args.case
    events = [json.loads(line) for line in (case / "events.jsonl").open()]
    flows = [json.loads(line) for line in (case / "flows.jsonl").open()
             if line.startswith("{")]
    requests = {int(row["request id"]): row for row in
                csv.DictReader((case / "requests.csv").open())}
    if len(requests) != 30:
        raise AssertionError("the fixture must complete exactly 30 requests")

    by_event = defaultdict(dict)
    waits = defaultdict(list)
    for event in events:
        name = event["event"]
        request_id = event.get("request_id")
        if request_id is None:
            continue
        if name == "HANDOFF_CAPACITY_WAIT":
            waits[int(request_id)].append(int(event["timestamp_ns"]))
        else:
            by_event[name][int(request_id)] = int(event["timestamp_ns"])

    expected_events = ("HANDOFF_CAPACITY_RESERVED", "DEST_PREFIX_COMMIT",
                       "P2D_READY", "SECOND_TOKEN_VISIBLE")
    for name in expected_events:
        if set(by_event[name]) != set(requests):
            raise AssertionError("missing or duplicate event: " + name)

    byte_count = Counter()
    first_start = {}
    last_end = {}
    ledger = []
    for flow in flows:
        ids = flow["request_ids"]
        if len(ids) != 1 or flow["traffic_subtype"] != "P2D":
            raise AssertionError("unexpected flow class or request multiplicity")
        request_id = int(ids[0])
        path = flow["path"]
        if path not in (["0->3", "3->5", "5->4", "4->2"],
                        ["1->3", "3->5", "5->4", "4->2"]):
            raise AssertionError("P2D flow escaped the declared physical cut")
        start_ns, end_ns = int(flow["start_ns"]), int(flow["end_ns"])
        if start_ns < by_event["HANDOFF_CAPACITY_RESERVED"][request_id]:
            raise AssertionError("P2D flow started before receiver credit")
        if end_ns > by_event["P2D_READY"][request_id]:
            raise AssertionError("KV was marked ready before a flow completed")
        byte_count[request_id] += int(flow["bytes"])
        first_start[request_id] = min(start_ns,
                                      first_start.get(request_id, start_ns))
        last_end[request_id] = max(end_ns,
                                   last_end.get(request_id, end_ns))
        ledger.append({
            "request_id": request_id,
            "source_rank": flow["logical_src"],
            "dest_rank": flow["logical_dst"],
            "bytes": flow["bytes"],
            "start_ns": start_ns,
            "end_ns": end_ns,
            "source_rail": "3->5",
            "dest_rail": "5->4",
            "physical_path": "|".join(path),
        })
    if any(byte_count[i] != 268435456 for i in requests):
        raise AssertionError("Llama-3.1-8B 2048-token P2D byte mismatch")
    for request_id, times in waits.items():
        if max(times) > by_event["HANDOFF_CAPACITY_RESERVED"][request_id]:
            raise AssertionError("receiver credit preceded a capacity wait")

    with (case / "flow_ledger.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(ledger[0]))
        writer.writeheader()
        writer.writerows(ledger)

    timeline = []
    for request_id, row in sorted(requests.items()):
        ready = int(row["p2d_kv_ready_time_ns"])
        admit = int(row["decode_admit_time_ns"])
        token2 = int(row["second_token_visible_ns"])
        completion = int(row["end_time"])
        if not (ready <= admit <= token2 <= completion):
            raise AssertionError("Serving timestamps out of order")
        timeline.append({
            "request_id": request_id,
            "arrival_ns": int(row["arrival"]),
            "prefill_start_ns": int(row["prefill_start_ns"]),
            "receiver_credit_ns":
                by_event["HANDOFF_CAPACITY_RESERVED"][request_id],
            "first_flow_start_ns": first_start[request_id],
            "last_flow_end_ns": last_end[request_id],
            "p2d_ready_ns": ready,
            "decode_admit_ns": admit,
            "second_token_ns": token2,
            "completion_ns": completion,
            "capacity_wait_first_ns": min(waits[request_id])
                                      if waits[request_id] else "",
            "capacity_wait_ns":
                by_event["HANDOFF_CAPACITY_RESERVED"][request_id] -
                min(waits[request_id]) if waits[request_id] else 0,
        })
    with (case / "timeline.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(timeline[0]))
        writer.writeheader()
        writer.writerows(timeline)

    summary = {
        "analyzer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "raw_sha256": {name: hashlib.sha256((case / name).read_bytes()).hexdigest()
                       for name in ("events.jsonl", "flows.jsonl",
                                    "requests.csv")},
        "requests_complete": len(requests),
        "p2d_flows": len(flows),
        "p2d_bytes": sum(byte_count.values()),
        "bytes_per_request": 268435456,
        "capacity_wait_event_count": sum(map(len, waits.values())),
        "capacity_wait_request_ids": sorted(i for i, times in waits.items()
                                            if times),
        "capacity_wait_ns_by_request": {
            str(i): by_event["HANDOFF_CAPACITY_RESERVED"][i] - min(times)
            for i, times in sorted(waits.items()) if times},
        "last_completion_ns": max(int(r["end_time"])
                                  for r in requests.values()),
        "note": "Correctness fixture only; synchronous 30-request burst is not a policy benefit measurement.",
    }
    (case / "analysis.json").write_text(json.dumps(summary, indent=2,
                                                  sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
