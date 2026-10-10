#!/usr/bin/env python3
"""Generate exact-nearest 80/20, 50/50, or 20/80 S16 workload mixes."""

import argparse
import json
import math
from pathlib import Path


PROFILE_FRACTIONS = {
    "small_majority": (0.80, 0.20),
    "mixed": (0.50, 0.50),
    "large_majority": (0.20, 0.80),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--profile", choices=sorted(PROFILE_FRACTIONS), required=True)
    parser.add_argument("--decode-count", type=int, default=256)
    parser.add_argument("--p2d-count", type=int, default=256)
    parser.add_argument("--decode-input", type=int, default=128)
    parser.add_argument("--decode-output", type=int, default=64)
    parser.add_argument("--small-input", type=int, default=2048)
    parser.add_argument("--large-input", type=int, default=8192)
    parser.add_argument("--p2d-arrival-ns", type=int, default=20_000_000)
    args = parser.parse_args()
    if args.decode_count <= 0 or args.p2d_count <= 0:
        parser.error("decode-count and p2d-count must be positive")
    if args.small_input <= 0 or args.large_input <= args.small_input:
        parser.error("large-input must be greater than positive small-input")

    small_fraction, _ = PROFILE_FRACTIONS[args.profile]
    small_count = int(math.floor(args.p2d_count * small_fraction + 0.5))
    large_count = args.p2d_count - small_count
    rows = []
    for index in range(args.decode_count):
        rows.append({
            "request_id": "decode-%d" % index,
            "input_toks": args.decode_input,
            "output_toks": args.decode_output,
            "arrival_time_ns": 0,
            "emit_p2d": False,
            "emit_ep": True,
            "workload_role": "active_decode",
            "kv_size_class": "none",
        })
    for index in range(args.p2d_count):
        size_class = "small" if index < small_count else "large"
        rows.append({
            "request_id": "kv-%s-%d" % (size_class, index),
            "input_toks": args.small_input if size_class == "small" else args.large_input,
            "output_toks": 0,
            "arrival_time_ns": args.p2d_arrival_ns,
            "emit_p2d": True,
            "emit_ep": False,
            "workload_role": "new_p2d",
            "kv_size_class": size_class,
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, separators=(",", ":")) + "\n")
    manifest = {
        "schema_version": 1,
        "profile": args.profile,
        "request_count": len(rows),
        "decode_count": args.decode_count,
        "p2d_count": args.p2d_count,
        "small_p2d_count": small_count,
        "large_p2d_count": large_count,
        "small_input_tokens": args.small_input,
        "large_input_tokens": args.large_input,
        "decode_input_tokens": args.decode_input,
        "decode_output_tokens": args.decode_output,
        "p2d_arrival_ns": args.p2d_arrival_ns,
        "bytes_source": "model-derived from input_toks; no synthetic byte override",
        "synthetic_byte_override": False,
        "output": str(args.output.resolve()),
    }
    with args.manifest.open("w", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2)
        stream.write("\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
