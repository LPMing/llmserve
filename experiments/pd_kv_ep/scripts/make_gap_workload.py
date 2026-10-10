#!/usr/bin/env python3
"""Create a bounded, timestamp-preserving serving gate workload.

This helper changes only the selected request arrival timestamp.  Token
counts, token identities, and source request order remain unchanged, so it is
for control-plane timing gates rather than a synthetic byte generator.
"""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--request-index", type=int, default=1)
    parser.add_argument("--arrival-ns", type=int, required=True)
    args = parser.parse_args()

    rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    if args.request_index < 0 or args.request_index >= len(rows):
        raise SystemExit("request index is outside the input workload")
    rows[args.request_index]["arrival_time_ns"] = args.arrival_ns
    for previous, current in zip(rows, rows[1:]):
        if int(current["arrival_time_ns"]) < int(previous["arrival_time_ns"]):
            raise SystemExit("arrival timestamps must remain nondecreasing")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
