#!/usr/bin/env python3
"""Check P2D bytes and physical receiver rails in matched FlowSim runs."""

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
SHARD_BYTES = 2048 * 98_304 // 2
DECODE_RAILS = {3: {24, 28}, 4: {32, 36}}


def main():
    rows = []
    for mode in ("POST_PREFILL", "LAYERWISE"):
        for number in range(8):
            bits = format(number, "03b")
            case = f"{mode.lower()}_{bits}"
            with (RUNS / f"{case}_flows.jsonl").open() as stream:
                flows = [json.loads(line) for line in stream
                         if line.startswith("{")]
            per_request = {request: [] for request in range(3)}
            for flow in flows:
                for request in flow["request_ids"]:
                    per_request[int(request)].append(flow)
            for request, request_flows in per_request.items():
                expected = DECODE_RAILS[3 + int(bits[request])]
                if sum(int(flow["bytes"]) for flow in request_flows) != 2 * SHARD_BYTES:
                    raise RuntimeError(f"{case} request {request}: wrong KV bytes")
                if {int(flow["dst"]) for flow in request_flows} != expected:
                    raise RuntimeError(f"{case} request {request}: wrong receiver rails")
                for flow in request_flows:
                    rows.append({
                        "mode": mode,
                        "assignment": bits,
                        "request_id": request,
                        "decode_instance": 3 + int(bits[request]),
                        "src_endpoint": flow["src"],
                        "dst_receiver_rail": flow["dst"],
                        "bytes": flow["bytes"],
                        "start_ns": flow["start_ns"],
                        "end_ns": flow["end_ns"],
                        "path": "|".join(flow["path"]),
                    })
    out = HERE / "06_FLOW_PATH_AUDIT.csv"
    with out.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"PASS: {len(rows)} model-derived P2D flows across 16 matched runs")


if __name__ == "__main__":
    main()
