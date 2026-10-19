#!/usr/bin/env python3
"""Audit per-request KV and causal events for the minimal eviction gate."""

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


TARGET_NS = 4_800_000_000
KV_BYTES_PER_TOKEN = 131072


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("case", type=Path)
    args = parser.parse_args()
    case = args.case
    manifest = json.loads((case / "manifest.json").read_text())
    if manifest["status"] != "COMPLETE":
        raise AssertionError("simulation did not complete cleanly")
    workload = [json.loads(line) for line in (case / "workload.jsonl").open()]
    requests = {int(row["request id"]): row for row in
                csv.DictReader((case / "requests.csv").open())}
    events = [json.loads(line) for line in (case / "events.jsonl").open()]
    flows = [json.loads(line) for line in (case / "flows.jsonl").open()
             if line.startswith("{")]
    if len(requests) != len(workload):
        raise AssertionError("not all requests completed")
    target_ids = [i for i, item in enumerate(workload)
                  if item["arrival_time_ns"] == TARGET_NS]
    if len(target_ids) != 2:
        raise AssertionError("expected two distinct target requests")
    if not all(int(requests[i]["end_time"]) < TARGET_NS
               for i in range(len(workload)) if i not in target_ids):
        raise AssertionError("filler work overlaps target arrival")

    by_event = defaultdict(lambda: defaultdict(list))
    for event in events:
        if "request_id" in event:
            by_event[event["event"]][int(event["request_id"])].append(event)
    fillers = manifest.get("fillers", len(workload) - 4)
    refresh = manifest.get("refresh", False)
    expected_hit = 1984 if (fillers == 24 or refresh) else 0
    expected_bytes = ((2048 - expected_hit) * KV_BYTES_PER_TOKEN)
    flow_bytes = Counter()
    last_flow_end = defaultdict(int)
    ledger = []
    for flow in flows:
        ids = flow.get("request_ids", [])
        if len(ids) != 1 or flow.get("traffic_subtype") != "P2D":
            raise AssertionError("unexpected flow type or multiplicity")
        request_id = int(ids[0])
        path = flow["path"]
        if path not in (["0->3", "3->5", "5->4", "4->2"],
                        ["1->3", "3->5", "5->4", "4->2"]):
            raise AssertionError("flow escaped the physical source cut")
        flow_bytes[request_id] += int(flow["bytes"])
        last_flow_end[request_id] = max(
            last_flow_end[request_id], int(flow["end_ns"]))
        ledger.append({
            "request_id": request_id,
            "source_rank": flow["logical_src"],
            "dest_rank": flow["logical_dst"],
            "bytes": flow["bytes"],
            "start_ns": flow["start_ns"],
            "end_ns": flow["end_ns"],
            "source_rail": "3->5", "dest_rail": "5->4",
            "path": "|".join(path),
        })
    for i, item in enumerate(workload):
        declared = item["input_toks"] * KV_BYTES_PER_TOKEN
        if i in target_ids:
            declared = expected_bytes
        if flow_bytes[i] != declared:
            raise AssertionError("KV byte mismatch for request %d" % i)
    with (case / "flow_ledger.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(ledger[0]))
        writer.writeheader()
        writer.writerows(ledger)

    timeline = []
    for request_id in target_ids:
        row = requests[request_id]
        queries = by_event["DEST_PREFIX_QUERY"][request_id]
        if len(queries) != 1:
            raise AssertionError("expected one pre-transfer D query")
        query = queries[0]
        if int(query.get("hit_tokens", 0)) != expected_hit:
            raise AssertionError("D hit did not cross registered threshold")
        if int(row["total_prefix_cache_hit_tokens"]) != 1984:
            raise AssertionError("Prefill prefix was not retained")
        ready = int(row["p2d_kv_ready_time_ns"])
        admit = int(row["decode_admit_time_ns"])
        token2 = int(row["second_token_visible_ns"])
        completion = int(row["end_time"])
        if not (last_flow_end[request_id] <= ready <= admit <= token2 <=
                completion):
            raise AssertionError("causal event order mismatch")
        if by_event["HANDOFF_CAPACITY_WAIT"].get(request_id):
            raise AssertionError("target capacity wait confounds the case")
        timeline.append({
            "request_id": request_id,
            "arrival_ns": TARGET_NS,
            "prefill_start_ns": int(row["prefill_start_ns"]),
            "p_hit_tokens": int(row["total_prefix_cache_hit_tokens"]),
            "d_query_status": query["status"],
            "d_hit_tokens": int(query.get("hit_tokens", 0)),
            "p2d_bytes": flow_bytes[request_id],
            "last_flow_end_ns": last_flow_end[request_id],
            "p2d_ready_ns": ready,
            "decode_admit_ns": admit,
            "token2_ns": token2,
            "completion_ns": completion,
            "decode_capacity_wait_ns": int(row["decode_capacity_queue_wait_ns"]),
        })
    with (case / "target_timeline.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(timeline[0]))
        writer.writeheader()
        writer.writerows(timeline)
    summary = {
        "status": "VALID",
        "target_count": 2,
        "request_count": len(workload),
        "target_d_hit_tokens": expected_hit,
        "target_bytes_each": expected_bytes,
        "source_cut_target_bytes": sum(flow_bytes[i] for i in target_ids),
        "target_ready_elapsed_ns": [
            item["p2d_ready_ns"] - TARGET_NS for item in timeline],
        "target_token2_elapsed_ns": [
            item["token2_ns"] - TARGET_NS for item in timeline],
        "target_completion_elapsed_ns": [
            item["completion_ns"] - TARGET_NS for item in timeline],
        "last_flow_slack_ns": [
            item["p2d_ready_ns"] - item["last_flow_end_ns"]
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
