#!/usr/bin/env python3
"""Audit P2D and EP barrier provenance in the corrected two-request run."""

import argparse
import gzip
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read_jsonl(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream
                if line.strip() and not line.startswith("#")]


def interval_overlap_by_link(flows):
    intervals = defaultdict(lambda: defaultdict(list))
    for flow in flows:
        traffic_class = flow.get("traffic_class")
        if traffic_class not in ("KV_MOVEMENT", "EP"):
            continue
        start = int(flow["start_ns"])
        end = int(flow["end_ns"])
        if end <= start:
            continue
        for link in flow.get("path", ()):
            intervals[link][traffic_class].append((start, end))

    common_links = sorted(
        link for link, classes in intervals.items()
        if classes.get("KV_MOVEMENT") and classes.get("EP"))
    overlaps = {}
    for link in common_links:
        events = []
        for traffic_class in ("KV_MOVEMENT", "EP"):
            for start, end in intervals[link][traffic_class]:
                events.append((start, 1, traffic_class))
                events.append((end, -1, traffic_class))
        events.sort()
        active = {"KV_MOVEMENT": 0, "EP": 0}
        total_ns = 0
        previous = None
        for timestamp, delta, traffic_class in events:
            if (previous is not None and timestamp > previous and
                    active["KV_MOVEMENT"] and active["EP"]):
                total_ns += timestamp - previous
            active[traffic_class] += delta
            previous = timestamp
        overlaps[link] = total_ns
    return common_links, overlaps


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--flows", default="research_audit/results/"
        "time_unit_fix_flowsim_ep16_i1_o3.jsonl.gz")
    parser.add_argument(
        "--requests", default="research_audit/results/"
        "time_unit_fix_flowsim_ep16_i1_o3.csv")
    parser.add_argument(
        "--collectives", default="research_audit/results/"
        "time_unit_fix_flowsim_ep16_i1_o3_collectives.jsonl.gz")
    args = parser.parse_args()

    flows = read_jsonl(ROOT / args.flows)
    with open(ROOT / args.requests, newline="", encoding="utf-8") as stream:
        import csv
        requests = list(csv.DictReader(stream))
    collectives = read_jsonl(ROOT / args.collectives)

    kv_by_request = defaultdict(list)
    ep_by_request = defaultdict(list)
    ep_by_collective = defaultdict(list)
    for flow in flows:
        ids = tuple(str(value) for value in flow.get("request_ids", ()))
        if flow.get("traffic_class") == "KV_MOVEMENT":
            if len(ids) != 1:
                raise AssertionError("P2D flow must identify one request")
            kv_by_request[ids[0]].append(flow)
        elif flow.get("traffic_class") == "EP":
            if len(ids) != 1:
                raise AssertionError("EP flow must identify one request in this run")
            ep_by_request[ids[0]].append(flow)
            key = (
                ids,
                int(flow["batch_id"]),
                int(flow["collective_id"]),
                int(flow["layer_id"]),
                int(flow["event_type"]),
                flow.get("traffic_subtype"),
            )
            ep_by_collective[key].append(flow)

    checked_requests = 0
    for request in requests:
        request_id = str(request["request id"])
        kv = kv_by_request.get(request_id, [])
        if not kv:
            raise AssertionError("request %s has no recorded P2D shards" % request_id)
        last_kv_ns = max(int(flow["end_ns"]) for flow in kv)
        ready_ns = int(request["p2d_kv_ready_time_ns"])
        admit_ns = int(request["decode_admit_time_ns"])
        if last_kv_ns > ready_ns or ready_ns != admit_ns:
            raise AssertionError(
                "request %s Decode admission precedes required P2D completion" %
                request_id)
        ep = ep_by_request.get(request_id, [])
        if ep and min(int(flow["requested_start_ns"]) for flow in ep) < admit_ns:
            raise AssertionError(
                "request %s has EP issued before Decode admission" % request_id)
        print(
            "request=%s p2d_flows=%d p2d_bytes=%d last_kv_ns=%d "
            "ready_ns=%d handoff_gap_after_last_shard_ns=%d decode_admit_ns=%d "
            "ep_flows=%d" % (
                request_id, len(kv), sum(int(flow["bytes"]) for flow in kv),
                last_kv_ns, ready_ns, ready_ns - last_kv_ns,
                admit_ns, len(ep)))
        checked_requests += 1

    matched_collectives = 0
    for collective in collectives:
        ids = tuple(str(value) for value in collective.get("request_ids", ()))
        key = (
            ids,
            int(collective["collective_batch_id"]),
            int(collective["collective_id"]),
            int(collective["layer_id"]),
            int(collective["event_type"]),
            collective.get("traffic_subtype"),
        )
        peers = ep_by_collective.get(key, [])
        if (len(peers) != int(collective["peer_flow_count"]) or
                not peers or
                max(int(flow["end_ns"]) for flow in peers) !=
                int(collective["end_ns"])):
            raise AssertionError(
                "EP collective %r does not equal its last peer completion" %
                (key,))
        matched_collectives += 1

    common_links, overlap_ns = interval_overlap_by_link(flows)
    has_overlap = any(overlap_ns.values())
    print(
        "requests=%d flow_rows=%d ep_collectives=%d matched_collective_barriers=%d "
        "common_directed_links=%s kv_ep_overlap_ns=%s" % (
            checked_requests, len(flows), len(collectives),
            matched_collectives, common_links, overlap_ns))
    print("RESULT=PASS_BARRIER_ACCOUNTING_%s" % (
        "OVERLAP_PRESENT" if has_overlap else "NO_OVERLAP"))


if __name__ == "__main__":
    main()
