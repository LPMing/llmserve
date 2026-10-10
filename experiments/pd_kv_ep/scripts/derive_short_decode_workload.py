#!/usr/bin/env python3
"""Derive a bounded serving gate without changing request/KV inputs.

This utility only caps output tokens.  It preserves request order, arrival
times, input tokens, request ids, roles, and all source provenance fields.
It is intended for integrated serving gates where the number of repeated
Decode rounds is the cost-control variable; it must not be used for network
traffic-volume characterization.
"""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--max-output-toks", type=int, required=True)
    args = parser.parse_args()
    if args.max_output_toks < 1:
        parser.error("--max-output-toks must be positive")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    changed = 0
    with args.source.open(encoding="utf-8") as source, \
            args.output.open("w", encoding="utf-8") as output:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            old_output = int(row.get("output_toks", 0))
            if old_output > args.max_output_toks:
                row["output_toks"] = args.max_output_toks
                changed += 1
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1

    print(json.dumps({
        "source": str(args.source.resolve()),
        "output": str(args.output.resolve()),
        "request_count": count,
        "capped_requests": changed,
        "max_output_toks": args.max_output_toks,
        "input_tokens_unchanged": True,
        "arrival_times_unchanged": True,
        "model_derived_bytes_unchanged_per_layer": True,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
