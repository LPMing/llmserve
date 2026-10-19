#!/usr/bin/env python3
"""Verify natural D eviction with P-prefix survival and no live D alternative."""

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TARGET_ARRIVAL_NS = 2_700_000_000
KV_BYTES_PER_TARGET = 268_435_456
DELTA_BYTES_PER_TARGET = 8_388_608


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def analyze(label):
    case = HERE / label
    rows = list(csv.DictReader((case / "requests.csv").open(newline="")))
    targets = {int(row["request id"]): row for row in rows
               if int(row["arrival"]) == TARGET_ARRIVAL_NS}
    prior = [row for row in rows
             if int(row["arrival"]) < TARGET_ARRIVAL_NS]
    assert len(targets) == 8
    assert all(int(row["end_time"]) < TARGET_ARRIVAL_NS for row in prior)
    assert all(int(row["total_prefix_cache_hit_tokens"]) == 1984
               for row in targets.values())
    assert all(int(row["decode_capacity_queue_wait_ns"]) == 0
               for row in targets.values())

    workload = [json.loads(line) for line in (case / "workload.jsonl").open()]
    target_tokens = [tuple(row["input_tok_ids"][:1984])
                     for row in workload if row["arrival_time_ns"] ==
                     TARGET_ARRIVAL_NS]
    assert len(set(target_tokens)) == 8

    events = [json.loads(line) for line in (case / "events.jsonl").open()]
    queries = {event["request_id"]: event for event in events
               if event["event"] == "DEST_PREFIX_QUERY" and
               event.get("request_id") in targets}
    assert len(queries) == 8
    expected_status = "HIT" if label.startswith("churn0") else "MISS"
    assert all(event["status"] == expected_status
               for event in queries.values())
    assert Counter(event["destination_instance_id"]
                   for event in queries.values()) == {8: 4, 9: 4}

    flows = [json.loads(line) for line in (case / "flows.jsonl").open()
             if line.startswith("{")]
    flows = [flow for flow in flows
             if flow.get("traffic_subtype") == "P2D" and
             set(flow["request_ids"]) & set(targets)]
    by_request = defaultdict(list)
    for flow in flows:
        assert len(flow["request_ids"]) == 1
        assert "10->13" in flow["path"]
        by_request[flow["request_ids"][0]].append(flow)
    expected_bytes = (DELTA_BYTES_PER_TARGET if expected_status == "HIT"
                      else KV_BYTES_PER_TARGET)
    assert all(len(by_request[i]) == 32 for i in targets)
    assert all(sum(flow["bytes"] for flow in by_request[i]) ==
               expected_bytes for i in targets)
    assert len(flows) == 256
    metrics = {}
    for request_id, row in sorted(targets.items()):
        last_flow = max(flow["end_ns"] for flow in by_request[request_id])
        ready = int(row["p2d_kv_ready_time_ns"])
        admit = int(row["decode_admit_time_ns"])
        token2 = int(row["second_token_visible_ns"])
        assert last_flow <= ready <= admit <= token2
        metrics[str(request_id)] = {
            "source_instance_id": int(request_id) % 8,
            "decode_instance_id": int(row["instance id"]),
            "prefix_hit_tokens": int(
                row["total_prefix_cache_hit_tokens"]),
            "destination_query": queries[request_id]["status"],
            "kv_bytes": sum(flow["bytes"] for flow in
                            by_request[request_id]),
            "last_flow_elapsed_ms": (
                last_flow - TARGET_ARRIVAL_NS) / 1e6,
            "ready_elapsed_ms": (
                ready - TARGET_ARRIVAL_NS) / 1e6,
            "admit_elapsed_ms": (
                admit - TARGET_ARRIVAL_NS) / 1e6,
            "token2_elapsed_ms": (
                token2 - TARGET_ARRIVAL_NS) / 1e6,
            "complete_elapsed_ms": (
                int(row["end_time"]) - TARGET_ARRIVAL_NS) / 1e6,
        }
    return {
        "case": label,
        "completed_prior_requests": len(prior),
        "last_prior_completion_ms": max(
            int(row["end_time"]) for row in prior) / 1e6,
        "normal_decode_kv_blocks": sorted({
            event["total_kv_blocks"] for event in events
            if event["event"] == "P2D_READY" and
            event.get("request_id") in targets}),
        "source_nic_gbps": 100,
        "source_edge": "10->13",
        "distinct_target_prefixes": len(set(target_tokens)),
        "aggregate_target_kv_bytes": sum(flow["bytes"] for flow in flows),
        "target_flows": len(flows),
        "targets": metrics,
        "sha256": {name: digest(case / name) for name in (
            "cluster.json", "topology.txt", "rank_map.json",
            "workload.jsonl", "requests.csv", "events.jsonl",
            "flows.jsonl")},
    }


def main():
    controls = {label: analyze(label) for label in (
        "churn0_distinct", "churn8_distinct")}
    hot = controls["churn0_distinct"]
    evicted = controls["churn8_distinct"]
    ready_hot = next(iter(hot["targets"].values()))["ready_elapsed_ms"]
    ready_evicted = next(iter(evicted["targets"].values()))[
        "ready_elapsed_ms"]
    summary = {
        "controls": controls,
        "eviction_minus_resident_ready_ms": ready_evicted - ready_hot,
        "conditional_reduction_if_residency_restored_fraction": (
            (ready_evicted - ready_hot) / ready_evicted),
        "status": "NATURAL_ASYMMETRY_VALIDATED; no incremental online-policy gain",
        "limit": (
            "Identical-Prefix single-flight is ruled out by eight distinct "
            "target prefixes. A cache-admission/placement baseline might "
            "retain them; the control is not an achieved new policy."),
        "source_sha256": {str(path.relative_to(ROOT)): digest(path)
                          for path in (HERE / "churn.py",
                                       HERE / "analyze_churn.py",
                                       ROOT / "serving/core/router.py",
                                       ROOT / "serving/core/scheduler.py")},
    }
    target = HERE / "churn_summary.json"
    target.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print("wrote", target)
    print("resident_ms", ready_hot, "evicted_ms", ready_evicted,
          "difference_ms", ready_evicted - ready_hot)


if __name__ == "__main__":
    main()
