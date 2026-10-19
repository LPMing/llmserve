#!/usr/bin/env python3
"""Audit matched early-credit and two-stage P/D handoff experiments."""

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path


KV_BYTES_PER_TOKEN = 131072
POOL_BLOCKS = 3400


def one(events, name, request_id):
    found = [item for item in events if item["event"] == name and
             int(item.get("request_id", -1)) == request_id]
    if len(found) != 1:
        raise AssertionError("expected one %s for request %d, found %d" %
                             (name, request_id, len(found)))
    return found[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("case", type=Path)
    args = parser.parse_args()
    case = args.case
    manifest = json.loads((case / "manifest.json").read_text())
    if manifest["status"] != "COMPLETE":
        raise AssertionError("simulator failed")
    admission = manifest["admission"]
    if admission not in ("EARLY_LAYERWISE", "EARLY_POST", "TWO_STAGE_FIFO"):
        raise AssertionError("not a matched full-KV admission arm")
    workload = [json.loads(line) for line in (case / "workload.jsonl").open()]
    requests = {int(row["request id"]): row for row in
                csv.DictReader((case / "requests.csv").open())}
    if len(workload) != 4 or set(requests) != set(range(4)):
        raise AssertionError("not all four requests completed")
    events = [json.loads(line) for line in (case / "events.jsonl").open()]
    flows = [json.loads(line) for line in (case / "flows.jsonl").open()
             if line.startswith("{")]
    for event in events:
        if event.get("pd_type") == "decode" and event.get("free_kv_blocks") is not None:
            if not 0 <= int(event["free_kv_blocks"]) <= POOL_BLOCKS:
                raise AssertionError("D pool occupancy escaped capacity")
    by_flow = defaultdict(list)
    ledger = []
    valid_paths = {tuple(["%d->5" % i, "5->7", "7->6", "6->4"])
                   for i in range(4)}
    for flow in flows:
        ids = flow.get("request_ids", [])
        if len(ids) != 1 or flow.get("traffic_subtype") != "P2D":
            raise AssertionError("non-P2D or unattributed flow")
        if tuple(flow["path"]) not in valid_paths:
            raise AssertionError("P2D flow escaped declared rails")
        request_id = int(ids[0])
        by_flow[request_id].append(flow)
        ledger.append({
            "request_id": request_id,
            "source_rank": int(flow["logical_src"]),
            "dest_rank": int(flow["logical_dst"]),
            "bytes": int(flow["bytes"]),
            "start_ns": int(flow["start_ns"]),
            "end_ns": int(flow["end_ns"]),
            "source_rail": "5->7", "dest_rail": "7->6",
            "path": "|".join(flow["path"]),
        })
    if set(by_flow) != set(range(4)):
        raise AssertionError("a request has no P2D flow")
    times = []
    for i, item in enumerate(workload):
        row = requests[i]
        credit_event = one(events, "HANDOFF_CAPACITY_RESERVED", i)
        credit = int(credit_event["timestamp_ns"])
        required_blocks = (int(item["input_toks"]) + 1 + 15) // 16
        if int(credit_event["required_blocks"]) != required_blocks:
            raise AssertionError("credit block requirement mismatch")
        request_flows = by_flow[i]
        transferred = sum(int(flow["bytes"]) for flow in request_flows)
        expected = int(item["input_toks"]) * KV_BYTES_PER_TOKEN
        if transferred != expected:
            raise AssertionError("request %d sent %d instead of %d bytes" %
                                 (i, transferred, expected))
        first = min(int(flow["start_ns"]) for flow in request_flows)
        last = max(int(flow["end_ns"]) for flow in request_flows)
        arrival = int(item["arrival_time_ns"])
        prefill = int(row["prefill_start_ns"])
        ready = int(row["p2d_kv_ready_time_ns"])
        admit = int(row["decode_admit_time_ns"])
        token2 = int(row["second_token_visible_ns"])
        completion = int(row["end_time"])
        if not (arrival <= prefill <= first and credit <= first <= last <=
                ready <= admit <= token2 <= completion):
            raise AssertionError("P/D causal event chain broken for %d" % i)
        compute_end = -1
        release = -1
        if admission == "TWO_STAGE_FIFO":
            held = one(events, "PREFILL_COMPUTE_DONE_SOURCE_HELD", i)
            transfer = one(events, "SOURCE_KV_TRANSFER_STARTED", i)
            released = one(events, "SOURCE_KV_RELEASED", i)
            compute_end = int(held["timestamp_ns"])
            release = int(released["timestamp_ns"])
            if int(held["held_blocks"]) < (int(item["input_toks"]) + 15)//16:
                raise AssertionError("source KV hold is too small")
            if not (prefill <= compute_end <= credit ==
                    int(transfer["timestamp_ns"]) <= first <= last <= release == ready):
                raise AssertionError("source KV/credit/flow lifetime mismatch")
            if released["cancelled"]:
                raise AssertionError("unexpected cancellation in completed run")
        else:
            if credit > prefill:
                raise AssertionError("early credit was acquired after Prefill start")
        times.append({
            "request_id": i, "arrival_ns": arrival,
            "input_tokens": int(item["input_toks"]),
            "output_tokens": int(item["output_toks"]),
            "required_d_blocks": required_blocks,
            "prefill_start_ns": prefill,
            "prefill_compute_end_ns": compute_end,
            "credit_ns": credit,
            "first_flow_ns": first, "last_flow_ns": last,
            "source_release_ns": release,
            "p2d_ready_ns": ready, "decode_admit_ns": admit,
            "token2_ns": token2, "completion_ns": completion,
            "p2d_bytes": transferred,
        })
    boundaries = sorted({time for item in times
                         for time in (item["credit_ns"], item["completion_ns"])})
    max_reserved = max(sum(item["required_d_blocks"] for item in times
                           if item["credit_ns"] <= time < item["completion_ns"])
                       for time in boundaries)
    if max_reserved > POOL_BLOCKS:
        raise AssertionError("D reservations exceed pool")
    with (case / "matched_flow_ledger.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(ledger[0]))
        writer.writeheader()
        writer.writerows(ledger)
    with (case / "matched_timeline.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(times[0]))
        writer.writeheader()
        writer.writerows(times)
    summary = {
        "status": "VALID", "admission": admission,
        "shape": manifest["shape"],
        "requests_complete": len(requests),
        "p2d_flow_count": len(flows),
        "p2d_bytes": sum(item["p2d_bytes"] for item in times),
        "max_reserved_d_blocks": max_reserved,
        "last_completion_ns": max(item["completion_ns"] for item in times),
        "mean_completion_latency_ns": sum(item["completion_ns"]-
                                           item["arrival_ns"] for item in times)/4,
        "analyzer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "raw_sha256": {name: hashlib.sha256((case / name).read_bytes()).hexdigest()
                       for name in ("requests.csv", "events.jsonl", "flows.jsonl")},
    }
    (case / "matched_analysis.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
