#!/usr/bin/env python3
"""Audit the online-history, varied-KV-size LRU/LFU comparison."""

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
    if (manifest["status"] != "COMPLETE" or not manifest["history_repeat"] or
            not manifest["varied_fillers"]):
        raise AssertionError("not a completed Round-19 history/cost case")
    workload = [json.loads(line) for line in (case / "workload.jsonl").open()]
    rows = {int(row["request id"]): row for row in
            csv.DictReader((case / "requests.csv").open())}
    events = [json.loads(line) for line in (case / "events.jsonl").open()]
    flows = [json.loads(line) for line in (case / "flows.jsonl").open()
             if line.startswith("{")]
    if len(workload) != 34 or set(rows) != set(range(34)):
        raise AssertionError("not all requests completed")
    target_ns = int(manifest["target_arrival_ns"])
    if target_ns != 5_500_000_000:
        raise AssertionError("target timestamp changed")
    target_ids = [i for i, req in enumerate(workload)
                  if int(req["arrival_time_ns"]) == target_ns]
    if target_ids != [32, 33]:
        raise AssertionError("target identity changed")
    if any(int(rows[i]["end_time"]) >= target_ns for i in range(32)):
        raise AssertionError("earlier work overlaps the target cohort")
    if any(len(req["input_tok_ids"]) != int(req["input_toks"])
           for req in workload):
        raise AssertionError("incomplete prompt token ID sidecar")
    if [workload[i]["input_toks"] for i in range(4, 32)] != [
            2048 if i % 2 == 0 else 3072 for i in range(28)]:
        raise AssertionError("heterogeneous filler lengths changed")
    query = {int(item["request_id"]): item for item in events
             if item["event"] == "DEST_PREFIX_QUERY"}
    if set(query) != set(range(34)):
        raise AssertionError("each request needs one D prefix query")
    bytes_by_request = Counter()
    last_flow = defaultdict(int)
    ledger = []
    paths = {tuple(["%d->3" % source, "3->5", "5->4", "4->2"])
             for source in (0, 1)}
    for flow in flows:
        ids = flow.get("request_ids", [])
        if len(ids) != 1 or flow.get("traffic_subtype") != "P2D":
            raise AssertionError("unattributed or non-P2D flow")
        if tuple(flow["path"]) not in paths:
            raise AssertionError("flow escaped the physical source cut")
        request_id = int(ids[0])
        size = int(flow["bytes"])
        bytes_by_request[request_id] += size
        last_flow[request_id] = max(last_flow[request_id], int(flow["end_ns"]))
        ledger.append({
            "request_id": request_id,
            "source_rank": int(flow["logical_src"]),
            "dest_rank": int(flow["logical_dst"]),
            "bytes": size,
            "start_ns": int(flow["start_ns"]),
            "end_ns": int(flow["end_ns"]),
            "source_rail": "3->5", "dest_rail": "5->4",
            "path": "|".join(flow["path"]),
        })
    for i, req in enumerate(workload):
        d_hit = int(query[i].get("hit_tokens", 0))
        expected = (int(req["input_toks"]) - d_hit) * KV_BYTES_PER_TOKEN
        if bytes_by_request[i] != expected:
            raise AssertionError("request %d transferred %d, expected %d" %
                                 (i, bytes_by_request[i], expected))
    for event in events:
        if event.get("pd_type") == "decode" and event.get("free_kv_blocks") is not None:
            if not 0 <= int(event["free_kv_blocks"]) <= POOL_BLOCKS:
                raise AssertionError("D KV capacity violated")
    timeline = []
    for i in target_ids:
        row = rows[i]
        if int(row["total_prefix_cache_hit_tokens"]) != 1984:
            raise AssertionError("P warm prefix did not survive")
        ready = int(row["p2d_kv_ready_time_ns"])
        admit = int(row["decode_admit_time_ns"])
        token2 = int(row["second_token_visible_ns"])
        completion = int(row["end_time"])
        if not last_flow[i] <= ready <= admit <= token2 <= completion:
            raise AssertionError("Serving causal chain broken")
        if any(event.get("request_id") == i and
               event["event"] == "HANDOFF_CAPACITY_WAIT" for event in events):
            raise AssertionError("target credit wait confounds cache test")
        timeline.append({
            "request_id": i, "arrival_ns": target_ns,
            "p_hit_tokens": int(row["total_prefix_cache_hit_tokens"]),
            "d_hit_tokens": int(query[i].get("hit_tokens", 0)),
            "p2d_bytes": bytes_by_request[i],
            "last_flow_ns": last_flow[i],
            "p2d_ready_ns": ready,
            "decode_admit_ns": admit,
            "token2_ns": token2,
            "completion_ns": completion,
        })
    with (case / "history_flow_ledger.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(ledger[0]))
        writer.writeheader()
        writer.writerows(ledger)
    with (case / "history_target_timeline.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(timeline[0]))
        writer.writeheader()
        writer.writerows(timeline)
    summary = {
        "status": "VALID", "policy": manifest["eviction_policy"],
        "requests_complete": len(rows),
        "p2d_flows": len(flows),
        "p2d_bytes_total": sum(bytes_by_request.values()),
        "target_d_hit_tokens": [item["d_hit_tokens"] for item in timeline],
        "target_p2d_bytes": [item["p2d_bytes"] for item in timeline],
        "target_completion_elapsed_ns": [
            item["completion_ns"]-target_ns for item in timeline],
        "target_token2_elapsed_ns": [
            item["token2_ns"]-target_ns for item in timeline],
        "raw_sha256": {name: hashlib.sha256((case / name).read_bytes()).hexdigest()
                       for name in ("events.jsonl", "flows.jsonl", "requests.csv")},
        "analyzer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    (case / "history_analysis.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
