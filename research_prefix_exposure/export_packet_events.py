#!/usr/bin/env python3
"""Export matched cache-hit P2D FlowSim releases for fixed ns-3 replay.

The resulting packet replay is network-only: it reuses model-derived FlowSim
release timestamps and bytes, but has no callback into the serving scheduler.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "research_prefix_exposure" / "results"
REQUESTS_BY_COUNT = {1: [1], 2: [1, 3], 4: [1, 3, 5, 7]}
OUTPUT_FIELDS = [
    "start_ns", "src", "dst", "bytes", "event_type", "request_id",
    "collective_id", "layer_id", "tag", "active_request_ids", "serving_role",
]


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, choices=(1, 2, 4), required=True)
    parser.add_argument("--mode", choices=("fair", "paced"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    flow_path = RESULTS / "hit_4_flows.jsonl"
    request_ids = REQUESTS_BY_COUNT[args.count]
    selected = []
    with flow_path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("#"):
                continue
            item = json.loads(line)
            owners = item.get("request_ids") or []
            if item.get("traffic_subtype") == "P2D" and len(owners) == 1 \
                    and owners[0] in request_ids:
                selected.append(item)

    if not selected:
        parser.error("no P2D flows matched the requested cache-hit cohort")
    bytes_by_request = {
        request_id: sum(item["bytes"] for item in selected
                        if item["request_ids"] == [request_id])
        for request_id in request_ids
    }
    if any(value != 403_537_920 for value in bytes_by_request.values()):
        raise RuntimeError(f"per-request KV byte conservation failed: {bytes_by_request}")

    base_by_request = {
        request_id: min(item["requested_start_ns"] for item in selected
                        if item["request_ids"] == [request_id])
        for request_id in request_ids
    }
    origin = min(base_by_request.values())
    sorted_ids = sorted(request_ids)
    # A single full-request, per-rail serialization lower bound: 201,768,960 B
    # divided by one 200-Gbit/s receiver rail (25,000,000,000 B/s).
    rail_bytes = 201_768_960
    rail_rate_bytes_s = 25_000_000_000
    spacing_ns = (rail_bytes * 1_000_000_000 + rail_rate_bytes_s - 1) // rail_rate_bytes_s
    slot = {request_id: index for index, request_id in enumerate(sorted_ids)}

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    events_path = output / "events.csv"
    with events_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for item in sorted(selected, key=lambda row: (
                row["requested_start_ns"], row["request_ids"][0], row["flow_id"])):
            request_id = item["request_ids"][0]
            relative = item["requested_start_ns"] - base_by_request[request_id]
            start_ns = relative + (slot[request_id] * spacing_ns
                                   if args.mode == "paced" else 0)
            writer.writerow({
                "start_ns": start_ns,
                "src": item["src"],
                "dst": item["dst"],
                "bytes": item["bytes"],
                "event_type": item.get("event_type", 1),
                "request_id": request_id,
                "collective_id": item.get("collective_id") or 0,
                "layer_id": item.get("layer_id") or 0,
                "tag": 0,
                "active_request_ids": request_id,
                "serving_role": "prefill",
            })

    total_bytes = sum(bytes_by_request.values())
    manifest = {
        "status": "INPUT_READY",
        "case": "PREFIX_CACHE_HIT_PACKET_REPLAY",
        "mode": args.mode,
        "request_count": args.count,
        "request_ids": request_ids,
        "event_count": len(selected),
        "total_event_bytes": total_bytes,
        "bytes_per_request": bytes_by_request,
        "per_request_flow_count": {
            str(request_id): sum(item["request_ids"] == [request_id]
                                 for item in selected)
            for request_id in request_ids
        },
        "source_flows": str(flow_path),
        "source_flows_sha256": sha256(flow_path),
        "source_timeline": "FlowSim requested_start_ns; normalized to first request flow",
        "pacing": (
            "offline request-bundle release offset equal to 201,768,960 B / "
            "25 GB/s = per-request serialization lower bound on one 200G rail; "
            "preserves each request's internal layerwise release offsets"
            if args.mode == "paced" else "original matched request release timeline"
        ),
        "pacing_spacing_ns": spacing_ns if args.mode == "paced" else 0,
        "serving_metrics": "NOT_AVAILABLE: fixed packet replay has no serving feedback",
    }
    (output / "replay_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "events": str(events_path),
        "mode": args.mode,
        "requests": args.count,
        "events_count": len(selected),
        "bytes": total_bytes,
        "pacing_spacing_ns": manifest["pacing_spacing_ns"],
        "sha256": sha256(events_path),
    }, indent=2))


if __name__ == "__main__":
    main()
