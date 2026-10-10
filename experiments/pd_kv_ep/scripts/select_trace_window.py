#!/usr/bin/env python3
"""Select an ordered request prefix from a converted real-trace window."""

import argparse
import json
from pathlib import Path


def select(source, output, count):
    rows = []
    with source.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if "arrival_time_ns" not in row:
                raise ValueError("missing arrival_time_ns at line %d" % line_number)
            if "input_toks" not in row or "output_toks" not in row:
                raise ValueError("missing token lengths at line %d" % line_number)
            rows.append(row)
            if len(rows) == count:
                break
    if len(rows) != count:
        raise ValueError("requested %d rows, found %d" % (count, len(rows)))

    first_arrival = int(rows[0]["arrival_time_ns"])
    previous = first_arrival
    for row in rows:
        original_arrival = int(row["arrival_time_ns"])
        if original_arrival < previous:
            raise ValueError("trace arrivals are not monotonic")
        previous = original_arrival
        row["source_arrival_time_ns"] = original_arrival
        row["arrival_time_ns"] = original_arrival - first_arrival

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, separators=(",", ":")) + "\n")

    manifest = {
        "source_trace_window": str(source.resolve()),
        "output_workload": str(output.resolve()),
        "request_count": len(rows),
        "arrival_origin_shift_ns": first_arrival,
        "relative_arrivals_unchanged": True,
        "input_output_lengths_unchanged": True,
        "request_ids_and_provenance_preserved": True,
        "first_arrival_ns": 0,
        "last_arrival_ns": int(rows[-1]["arrival_time_ns"]),
    }
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--count", type=int, required=True)
    args = parser.parse_args()
    if args.count <= 0:
        parser.error("--count must be positive")
    select(args.source, args.output, args.count)


if __name__ == "__main__":
    main()
