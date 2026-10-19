#!/usr/bin/env python3
"""Check D-credit occupancy, flow conservation and P/D event ordering."""

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


KV_BYTES_PER_TOKEN = 131072
POOL_BLOCKS = 3400


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("case", type=Path)
    args = parser.parse_args()
    case = args.case
    manifest = json.loads((case / "manifest.json").read_text())
    if manifest["status"] != "COMPLETE":
        raise AssertionError("simulation did not complete cleanly")
    workload = [json.loads(line) for line in (case / "workload.jsonl").open()]
    length = workload[0]["input_toks"]
    if len(workload) != 4 or any(item["input_toks"] != length
                                  for item in workload):
        raise AssertionError("four-request fixture changed")
    rows = {int(row["request id"]): row for row in
            csv.DictReader((case / "requests.csv").open())}
    if set(rows) != set(range(4)):
        raise AssertionError("a request failed to complete")
    events = [json.loads(line) for line in (case / "events.jsonl").open()]
    flows = [json.loads(line) for line in (case / "flows.jsonl").open()
             if line.startswith("{")]
    by_event = defaultdict(lambda: defaultdict(list))
    for event in events:
        if "request_id" in event:
            by_event[event["event"]][int(event["request_id"])].append(event)
        if event.get("free_kv_blocks") is not None and event.get("pd_type") == "decode":
            free = int(event["free_kv_blocks"])
            if not 0 <= free <= POOL_BLOCKS:
                raise AssertionError("Decode KV occupancy escaped the pool")

    flow_bytes = Counter()
    first_flow = {}
    last_flow = defaultdict(int)
    ledger = []
    for flow in flows:
        ids = flow.get("request_ids", [])
        if len(ids) != 1 or flow.get("traffic_subtype") != "P2D":
            raise AssertionError("unexpected flow or request multiplicity")
        request_id = int(ids[0])
        path = flow["path"]
        if path not in (["0->5", "5->7", "7->6", "6->4"],
                        ["1->5", "5->7", "7->6", "6->4"],
                        ["2->5", "5->7", "7->6", "6->4"],
                        ["3->5", "5->7", "7->6", "6->4"]):
            raise AssertionError("flow escaped the declared100-Gb/s cut")
        start_ns, end_ns = int(flow["start_ns"]), int(flow["end_ns"])
        flow_bytes[request_id] += int(flow["bytes"])
        first_flow[request_id] = min(start_ns,
                                     first_flow.get(request_id, start_ns))
        last_flow[request_id] = max(last_flow[request_id], end_ns)
        ledger.append({
            "request_id": request_id,
            "source_rank": flow["logical_src"],
            "dest_rank": flow["logical_dst"],
            "bytes": flow["bytes"],
            "start_ns": start_ns,
            "end_ns": end_ns,
            "source_rail": "5->7", "dest_rail": "7->6",
            "path": "|".join(path),
        })
    expected_bytes = length * KV_BYTES_PER_TOKEN
    if any(flow_bytes[i] != expected_bytes for i in range(4)):
        raise AssertionError("model-derived KV bytes do not match flows")
    with (case / "flow_ledger.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(ledger[0]))
        writer.writeheader()
        writer.writerows(ledger)

    timeline = []
    first_d_ready = min(int(rows[i]["p2d_kv_ready_time_ns"])
                        for i in range(4))
    for i in range(4):
        row = rows[i]
        credits = by_event["HANDOFF_CAPACITY_RESERVED"][i]
        if len(credits) != 1:
            raise AssertionError("request %d lacks one receiver credit" % i)
        credit = int(credits[0]["timestamp_ns"])
        start = int(row["prefill_start_ns"])
        ready = int(row["p2d_kv_ready_time_ns"])
        admit = int(row["decode_admit_time_ns"])
        token2 = int(row["second_token_visible_ns"])
        completion = int(row["end_time"])
        if not (credit <= start <= first_flow[i] <= last_flow[i] <=
                ready <= admit <= token2 <= completion):
            raise AssertionError("credit/flow/Serving causal order mismatch")
        timeline.append({
            "request_id": i,
            "arrival_ns": 0,
            "credit_ns": credit,
            "prefill_start_ns": start,
            "prefill_idle_wait_ns": start,
            "first_flow_start_ns": first_flow[i],
            "last_flow_end_ns": last_flow[i],
            "p2d_ready_ns": ready,
            "decode_admit_ns": admit,
            "decode_capacity_queue_wait_ns":
                int(row["decode_capacity_queue_wait_ns"]),
            "token2_ns": token2,
            "completion_ns": completion,
            "d_credit_hold_ns": completion - credit,
            "capacity_wait_events": len(by_event["HANDOFF_CAPACITY_WAIT"][i]),
        })
    with (case / "timeline.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(timeline[0]))
        writer.writeheader()
        writer.writerows(timeline)
    waits = by_event["HANDOFF_CAPACITY_WAIT"]
    if length == 12000 and any(waits.values()):
        raise AssertionError("negative control unexpectedly waited for D credit")
    if length == 14000:
        if not waits[3] or int(waits[3][0]["timestamp_ns"]) >= first_d_ready:
            raise AssertionError("credit did not block the fourth P before D work")
        if int(waits[3][0]["free_kv_blocks"]) != 772:
            raise AssertionError("registered three-credit pool residual changed")
    summary = {
        "status": "VALID",
        "prompt_tokens": length,
        "requests_complete": 4,
        "bytes_per_request": expected_bytes,
        "p2d_bytes": sum(flow_bytes.values()),
        "p2d_flows": len(flows),
        "capacity_wait_request_ids": sorted(i for i, rows_ in waits.items()
                                            if rows_),
        "first_d_ready_ns": first_d_ready,
        "prefill_start_ns_by_request": {
            str(item["request_id"]): item["prefill_start_ns"]
            for item in timeline},
        "last_completion_ns": max(item["completion_ns"]
                                  for item in timeline),
        "last_flow_slack_ns": [item["p2d_ready_ns"] -
                               item["last_flow_end_ns"]
                               for item in timeline],
        "analyzer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "raw_sha256": {name: hashlib.sha256((case / name).read_bytes()).hexdigest()
                       for name in ("events.jsonl", "flows.jsonl",
                                    "requests.csv")},
    }
    (case / "analysis.json").write_text(json.dumps(
        summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
