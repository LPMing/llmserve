#!/usr/bin/env python3
"""Generate small integrated EP64 P/D workloads.

Unlike the network-only replay generator, this format deliberately contains
only normal serving requests.  The serving router and schedulers therefore
create both the prefill/P2D and decode/EP phases; no phase is disabled by a
workload-side flag.
"""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--decode-count", type=int, required=True)
    parser.add_argument("--p2d-count", type=int, required=True)
    parser.add_argument("--decode-input", type=int, default=128)
    parser.add_argument("--decode-output", type=int, default=4)
    parser.add_argument("--p2d-input", type=int, default=2048)
    parser.add_argument("--p2d-output", type=int, default=1)
    parser.add_argument("--p2d-arrival-ns", type=int, default=20_000_000)
    args = parser.parse_args()
    if args.decode_count <= 0 or args.p2d_count <= 0:
        parser.error("request counts must be positive")
    rows = []
    for index in range(args.decode_count):
        rows.append({
            "request_id": "decode-%d" % index,
            "input_toks": args.decode_input,
            "output_toks": args.decode_output,
            "arrival_time_ns": 0,
        })
    for index in range(args.p2d_count):
        rows.append({
            "request_id": "p2d-%d" % index,
            "input_toks": args.p2d_input,
            "output_toks": args.p2d_output,
            "arrival_time_ns": args.p2d_arrival_ns,
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, separators=(",", ":")) + "\n")
    print(json.dumps({
        "output": str(args.output),
        "request_count": len(rows),
        "decode_count": args.decode_count,
        "p2d_count": args.p2d_count,
        "synthetic_byte_override": False,
    }, indent=2))


if __name__ == "__main__":
    main()
