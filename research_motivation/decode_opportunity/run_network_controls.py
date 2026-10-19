#!/usr/bin/env python3
"""Run small model-derived P2D network-only controls for decode opportunities."""

import csv
import json
from pathlib import Path

from serving.core.flowsim_backend import FlowSpec, PersistentFluidFlowNetwork


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TOPOLOGY = HERE / "two_prefill_two_decode_shared_cut_200g.txt"
RANK_MAP = HERE / "rank_map_2p2d_tp2_cross_cut.json"
OUTPUT = HERE / "05_NETWORK_ONLY_RESULTS.csv"

# Qwen3-30B-A3B, BF16 KV: 48 layers * 2(K,V) * 4 KV heads * 128 head_dim *
# 2 bytes = 98,304 bytes/token across TP.  Each of two TP shards carries half.
KV_BYTES_PER_REQUEST = 201_326_592
KV_BYTES_PER_SHARD = KV_BYTES_PER_REQUEST // 2
REQUESTS = {
    # request ID, source logical TP ranks, paired Decode logical TP ranks
    2: ((0, 1), (10, 11)),  # P0 -> D1 (late Decode lane)
    3: ((4, 5), (8, 9)),    # P1 -> D0 (early Decode lane)
}


def _flows(request_ids):
    result = []
    for request_id in request_ids:
        sources, destinations = REQUESTS[request_id]
        for shard, (src, dst) in enumerate(zip(sources, destinations)):
            result.append(FlowSpec(
                "p2d-r%d-tp%d" % (request_id, shard), src, dst,
                KV_BYTES_PER_SHARD, 0, "KV_MOVEMENT", "P2D",
                request_ids=(request_id,), event_type=1))
    return result


def _run(case, policy="FAIR", request_first_id=None, included=(2, 3)):
    network = PersistentFluidFlowNetwork(
        str(TOPOLOGY), policy=policy, rank_map=json.loads(
            RANK_MAP.read_text(encoding="utf-8"))["logical_to_physical"],
        request_first_id=request_first_id)
    network.simulate(_flows(included))
    by_request = {}
    for request_id in included:
        request_flows = [
            row for row in network.last_flows
            if request_id in row.get("request_ids", ())]
        ready = max(row["end_ns"] for row in request_flows)
        last = max(request_flows, key=lambda row: row["end_ns"])
        by_request[request_id] = {
            "request_id": request_id,
            "flow_count": len(request_flows),
            "kv_bytes": sum(row["bytes"] for row in request_flows),
            "release_ns": min(row["requested_start_ns"]
                               for row in request_flows),
            "first_flow_start_ns": min(row["start_ns"]
                                        for row in request_flows),
            "ready_ns": ready,
            "handoff_fct_ns": ready - min(
                row["requested_start_ns"] for row in request_flows),
            "last_shard_flow_id": last["flow_id"],
            "last_shard_path": "|".join(last["path"]),
        }
    rows = []
    for request_id, metrics in by_request.items():
        rows.append({
            "case": case,
            "network_policy": policy,
            "request_first_id": ("" if request_first_id is None
                                 else request_first_id),
            **metrics,
            "total_kv_bytes_all_requests": sum(
                row["bytes"] for row in network.last_flows),
            "flow_ids": "|".join(sorted(
                row["flow_id"] for row in network.last_flows
                if request_id in row.get("request_ids", ()))),
        })
    return rows


def main():
    cases = []
    cases.extend(_run("N0_ISOLATED_REQ2", included=(2,)))
    cases.extend(_run("N0_ISOLATED_REQ3", included=(3,)))
    cases.extend(_run("N1_FAIR", policy="FAIR"))
    cases.extend(_run("N2_REQ2_GROUP_FIRST", policy="KV_REQUEST_FIRST",
                      request_first_id=2))
    cases.extend(_run("N3_REQ3_GROUP_FIRST", policy="KV_REQUEST_FIRST",
                      request_first_id=3))
    # Both requests have identical bytes and release time. FIFO-by-request-ID
    # and SRPT/coflow-FIFO therefore induce the same request-2-first order in
    # this exact tie. These are explicit tie-equivalent controls, not claims
    # that independent FIFO/SRPT implementations were run.
    cases.extend(_run("N4_FIFO_ID_TIE_EQUIVALENT", policy="KV_REQUEST_FIRST",
                      request_first_id=2))
    cases.extend(_run("N5_SRPT_COFLOW_FIFO_TIE_EQUIVALENT",
                      policy="KV_REQUEST_FIRST", request_first_id=2))

    fieldnames = [
        "case", "network_policy", "request_first_id", "request_id",
        "flow_count", "kv_bytes", "release_ns", "first_flow_start_ns",
        "ready_ns", "handoff_fct_ns", "last_shard_flow_id",
        "last_shard_path", "total_kv_bytes_all_requests", "flow_ids",
    ]
    with OUTPUT.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(cases)
    print("wrote %s (%d rows)" % (OUTPUT, len(cases)))


if __name__ == "__main__":
    main()
