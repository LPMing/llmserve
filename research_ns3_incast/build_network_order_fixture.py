#!/usr/bin/env python3
"""Create a request-bundle release-order counterfactual for packet replay.

The input request set, flow bytes, endpoints, and within-request release offsets
are preserved. Only each request bundle's base release time is shifted. This is
an offline network-scheduling counterfactual, not an online serving policy.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--spacing-ns", required=True, type=int)
    parser.add_argument("--request-order", default="0,1,2,3")
    args = parser.parse_args()
    if args.spacing_ns <= 0:
        parser.error("--spacing-ns must be positive")
    input_dir = args.input.resolve()
    source_path = input_dir / "events.csv"
    source_manifest_path = input_dir / "replay_manifest.json"
    if not source_path.is_file() or not source_manifest_path.is_file():
        parser.error("input must contain events.csv and replay_manifest.json")

    with source_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        rows = list(reader)
    if not rows or "request_id" not in fields or "start_ns" not in fields:
        parser.error("events.csv needs request_id and start_ns columns")
    request_ids = sorted({int(row["request_id"]) for row in rows})
    order = [int(value) for value in args.request_order.split(",") if value]
    if len(order) != len(request_ids) or set(order) != set(request_ids):
        parser.error("request-order must contain each request_id exactly once")

    request_base = {
        request_id: min(int(row["start_ns"]) for row in rows
                        if int(row["request_id"]) == request_id)
        for request_id in request_ids
    }
    slot = {request_id: index for index, request_id in enumerate(order)}
    for row in rows:
        request_id = int(row["request_id"])
        relative = int(row["start_ns"]) - request_base[request_id]
        row["start_ns"] = str(slot[request_id] * args.spacing_ns + relative)

    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    output_path = output_dir / "events.csv"
    with output_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    if sum(int(row["bytes"]) for row in rows) != int(source_manifest["total_event_bytes"]):
        raise RuntimeError("byte conservation failed")
    manifest = dict(source_manifest)
    manifest.update({
        "case": "NETWORK_ONLY_REQUEST_BUNDLE_ORDER",
        "status": "INPUT_READY",
        "source_events": str(source_path),
        "source_events_sha256": sha256(source_path),
        "events_sha256": sha256(output_path),
        "request_order": order,
        "request_bundle_spacing_ns": args.spacing_ns,
        "request_count": len(request_ids),
        "event_count": len(rows),
        "total_event_bytes": sum(int(row["bytes"]) for row in rows),
        "release_pattern": (
            "same request set/bytes/endpoints; per-request bundles shifted "
            "by fixed spacing while preserving within-request release offsets"),
        "serving_metrics": "NOT_AVAILABLE: offline network-only release-order counterfactual",
    })
    (output_dir / "replay_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "events": str(output_path),
        "events_sha256": manifest["events_sha256"],
        "requests": len(request_ids),
        "flows": len(rows),
        "bytes": manifest["total_event_bytes"],
        "order": order,
        "spacing_ns": args.spacing_ns,
    }, indent=2))


if __name__ == "__main__":
    main()
