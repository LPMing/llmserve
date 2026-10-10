#!/usr/bin/env python3
"""Generate native token workloads for request-composition experiments."""

import argparse
import json
from pathlib import Path


def request(input_tokens, output_tokens, arrival_time_ns, request_id):
    return {
        "request_id": request_id,
        "input_toks": input_tokens,
        "output_toks": output_tokens,
        "arrival_time_ns": arrival_time_ns,
        "input_tok_ids": list(range(1, input_tokens + 1)),
        "output_tok_ids": list(range(input_tokens + 1,
                                     input_tokens + output_tokens + 1)),
    }


def build_time_varying():
    """Return phases with request parameters only; no communication overrides."""
    rows = []
    next_id = 0
    for arrival_ns, count, input_tokens, output_tokens in (
            (0, 2, 8, 32),
            (80_000_000, 4, 64, 4),
            (160_000_000, 2, 8, 32)):
        for offset in range(count):
            rows.append(request(input_tokens, output_tokens,
                                arrival_ns + offset * 1_000_000,
                                "tv-%02d" % next_id))
            next_id += 1
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).parents[1] / "workloads" /
                        "time_varying_mixed.jsonl")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as stream:
        for row in build_time_varying():
            stream.write(json.dumps(row) + "\n")
    print("wrote", args.output)


if __name__ == "__main__":
    main()
