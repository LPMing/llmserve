#!/usr/bin/env python3
"""Create a deterministic, model-derived controlled batch-miss workload.

R0 seed requests are round-robin distributed over the four paired P/D
instances. The next request is the target, followed by up to three equal-size
KV cross-traffic requests. Arrival times are calibrated from serving events;
this script never writes network-flow issue timestamps.
"""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--target-arrival-ns", type=int, required=True)
    parser.add_argument("--interferer-count", type=int, default=2,
                        choices=(0, 1, 2, 3))
    parser.add_argument("--interferer-offset-ns", type=int, default=0)
    parser.add_argument("--target-input", type=int, default=2048,
                        choices=(128, 512, 2048, 4096))
    parser.add_argument("--interferer-input", type=int, default=2048,
                        choices=(128, 512, 2048, 4096))
    parser.add_argument("--r0-output", type=int, default=64)
    parser.add_argument("--r0-count", type=int, default=24)
    parser.add_argument("--candidate-output", type=int, default=8)
    args = parser.parse_args()

    rows = [{"input_toks": 128, "output_toks": args.r0_output,
             "arrival_time_ns": 0} for _ in range(args.r0_count)]
    rows.append({"input_toks": args.target_input,
                 "output_toks": args.candidate_output,
                 "arrival_time_ns": args.target_arrival_ns})
    interferer_arrival = (
        args.target_arrival_ns + args.interferer_offset_ns)
    for _ in range(args.interferer_count):
        rows.append({"input_toks": args.interferer_input,
                     "output_toks": args.candidate_output,
                     "arrival_time_ns": interferer_arrival})

    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n"
                                  for row in rows), encoding="utf-8")
    print(json.dumps({
        "output": str(path),
        "request_count": len(rows),
        "request_id_plan": {
            "R0_seed": ([0, args.r0_count - 1]
                        if args.r0_count else []),
            "R1_target": args.r0_count,
            "R2_interference": list(range(args.r0_count + 1, len(rows))),
        },
        "target_arrival_ns": args.target_arrival_ns,
        "interferer_arrival_ns": interferer_arrival,
        "interferer_count": args.interferer_count,
        "warning": "arrival offsets must be calibrated from E0 events; no network issue time is overridden",
    }, indent=2))


if __name__ == "__main__":
    main()
