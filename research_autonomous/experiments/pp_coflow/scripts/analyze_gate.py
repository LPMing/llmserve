#!/usr/bin/env python3
"""Audit KV conservation and PP timing across the two causality repairs."""

import csv
import json
from collections import defaultdict
from pathlib import Path


CASE = Path(__file__).resolve().parents[1]
EXPECTED_PER_REQUEST = 201_326_592


def read_case(name):
    folder = CASE / name
    with (folder / "requests.csv").open(newline="") as stream:
        requests = {int(row["request id"]): row
                    for row in csv.DictReader(stream)}
    with (folder / "flows.jsonl").open() as stream:
        flows = [json.loads(line) for line in stream
                 if line.startswith("{")]
    kv = [flow for flow in flows if flow.get("traffic_subtype") == "P2D"]
    by_request = defaultdict(list)
    for flow in kv:
        ids = flow.get("request_ids")
        if len(ids) != 1:
            raise AssertionError("P2D flow lacks one request identity")
        by_request[int(ids[0])].append(flow)
    if len(requests) != 4 or len(kv) != 384:
        raise AssertionError("expected four requests and 384 KV flows")
    for request_id, group in by_request.items():
        if len(group) != 96 or sum(f["bytes"] for f in group) != EXPECTED_PER_REQUEST:
            raise AssertionError("request %d violates 96-flow KV conservation" %
                                 request_id)
        stages = defaultdict(list)
        for flow in group:
            stage = (int(flow["logical_dst"]) - 32) // 2
            stages[stage].append(flow)
        if set(stages) != {0, 1} or any(
                len(v) != 48 or sum(f["bytes"] for f in v) !=
                EXPECTED_PER_REQUEST // 2 for v in stages.values()):
            raise AssertionError("request %d violates PP stage split" % request_id)
        if max(f["end_ns"] for f in group) > int(
                requests[request_id]["p2d_kv_ready_time_ns"]):
            raise AssertionError("request %d ready before last KV" % request_id)
    stage_groups = defaultdict(list)
    for flow in kv:
        stage_groups[(int(flow["logical_dst"]) - 32) // 2].append(flow)
    first_wave = [flow for flow in stage_groups[0]
                  if int(flow["logical_dst"]) == 32 and
                  int(flow["start_ns"]) == min(
                      int(f["start_ns"]) for f in stage_groups[0]
                      if int(f["logical_dst"]) == 32)]
    if len(first_wave) != 4:
        raise AssertionError("expected four same-rail first-layer flows")
    return {
        "case": name,
        "requests": len(requests),
        "p2d_flows": len(kv),
        "p2d_bytes": sum(f["bytes"] for f in kv),
        "first_stage0_release_ms": min(f["start_ns"] for f in stage_groups[0]) / 1e6,
        "last_stage0_release_ms": max(f["start_ns"] for f in stage_groups[0]) / 1e6,
        "first_stage1_release_ms": min(f["start_ns"] for f in stage_groups[1]) / 1e6,
        "last_stage1_release_ms": max(f["start_ns"] for f in stage_groups[1]) / 1e6,
        "last_kv_finish_ms": max(f["end_ns"] for f in kv) / 1e6,
        "first_wave_fct_ms": (max(f["end_ns"] for f in first_wave) -
                              min(f["start_ns"] for f in first_wave)) / 1e6,
        "p2d_ready_ms": int(requests[0]["p2d_kv_ready_time_ns"]) / 1e6,
        "token2_ms": int(requests[0]["second_token_visible_ns"]) / 1e6,
        "request_completion_ms": int(requests[0]["end_time"]) / 1e6,
    }


def main():
    rows = [read_case(name) for name in (
        "raw_before_fix", "raw_after_pp_fix_before_moe_fix", "raw")]
    if not (rows[0]["first_stage1_release_ms"] <
            rows[0]["last_stage0_release_ms"]):
        raise AssertionError("before-fix PP overlap was not reproduced")
    if not all(row["first_stage1_release_ms"] >
               row["last_stage0_release_ms"] for row in rows[1:]):
        raise AssertionError("after-fix PP dependency still broken")
    if not (rows[2]["first_stage1_release_ms"] >
            rows[1]["first_stage1_release_ms"]):
        raise AssertionError("EP1 TP expert replication did not delay rank 1")
    out = CASE / "processed" / "theory_sim_comparison.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        print(row)


if __name__ == "__main__":
    main()
