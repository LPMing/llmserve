#!/usr/bin/env python3
"""Build an ns-3 fixed-event ledger from the repository's profiled P2D trace.

This is a network-only projection of a model-derived LAYERWISE Prefill graph.
It preserves the profile's QKV release offsets and per-layer, per-TP-rank KV
bytes, but deliberately does not claim packet-to-serving feedback.
"""

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from serving.core.request import Batch, Request
from serving.core.trace_generator import generate_trace


MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"
LAYERS = 48
INPUT_TOKENS = 4096
TP = 2
P_SERVER_RANK_BASES = (0, 8, 16, 24)
D_SERVER_RANK_BASE = 32


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def trace_for_prefill_chunk(chunk_index):
    chunk_tokens = INPUT_TOKENS // 2
    cached_tokens = chunk_index * chunk_tokens
    request = Request(0, MODEL, INPUT_TOKENS, 1, 0, 0)
    request.num_computed_tokens = cached_tokens
    batch = Batch(
        chunk_index, MODEL, chunk_tokens, cached_tokens,
        [chunk_tokens], [cached_tokens], 1, 0,
        [chunk_tokens], [cached_tokens], [], 0, 0,
        pd_kv_send_tokens=chunk_tokens,
    )
    batch.requests = [request]
    return generate_trace(
        batch, "RTXPRO6000", TP, 1, 1, 1, pd_type="prefill",
        node_id=0, instance_id=0,
        max_num_batched_tokens=2048, max_num_seqs=1,
        fp=16, dtype="bfloat16", kv_cache_dtype="auto",
        placement={
            "default": {"weights": "LOCAL", "kv_loc": "LOCAL",
                        "kv_evict_loc": "LOCAL"},
            "block": [], "layer": {},
        },
        expert_routing_policy="BALANCED", enable_block_copy=True,
        pd_kv_transfer_mode="LAYERWISE",
    )


def extract_release_offsets(rows):
    elapsed_ns = 0
    releases = []
    for row in rows:
        if len(row) < 2:
            continue
        try:
            compute_ns = int(row[1])
        except (TypeError, ValueError):
            continue
        elapsed_ns += compute_ns
        name = str(row[0])
        if name == "qkv_proj":
            layer_id = len(releases)
            if len(row) < 10:
                raise ValueError(f"malformed QKV trace row: {row!r}")
            releases.append({
                "layer_id": layer_id,
                "release_ns": elapsed_ns,
                "bytes_per_tp_rank": int(row[9]),
            })
    if len(releases) != LAYERS:
        qkv_names = [
            row[0] for row in rows if len(row) > 1 and
            str(row[0]).startswith(("qkv", "v_proj"))
        ][:12]
        raise RuntimeError(
            f"expected {LAYERS} LAYERWISE KV release rows, got {len(releases)}; "
            f"trace layer names={qkv_names}")
    if [row["layer_id"] for row in releases] != list(range(LAYERS)):
        raise RuntimeError("QKV layer ids are not the complete ordered 0..47 chain")
    return releases, elapsed_ns


def build_events(releases):
    events = []
    event_id = 0
    for request_id, p_base in enumerate(P_SERVER_RANK_BASES):
        for release in releases:
            for rail, p_gpu, d_gpu in ((0, 0, request_id),
                                       (1, 4, 4 + request_id)):
                events.append({
                    "start_ns": release["release_ns"],
                    "src": p_base + p_gpu,
                    "dst": D_SERVER_RANK_BASE + d_gpu,
                    "bytes": release["bytes_per_tp_rank"],
                    "event_type": 1,
                    "request_id": request_id,
                    "collective_id": 0,
                    "layer_id": release["layer_id"],
                    "tag": event_id,
                    "active_request_ids": str(request_id),
                    "serving_role": "prefill",
                    "rail": rail,
                })
                event_id += 1
    return events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--topology", type=Path, default=ROOT /
                        "research_ns3_incast/fixtures_rankcap200g/fixtures/"
                        "4p1d_unique_spines/topology.txt")
    parser.add_argument("--rank-map", type=Path, default=ROOT /
                        "research_ns3_incast/fixtures_rankcap200g/fixtures/"
                        "4p1d_unique_spines/rank_to_nic.csv")
    args = parser.parse_args()
    for path in (args.topology, args.rank_map):
        if not path.is_file():
            parser.error(f"missing topology input: {path}")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)

    # The serving CLI changes into astra-sim because profiler/perf paths are
    # intentionally relative to that working directory.
    os.chdir(ROOT / "astra-sim")
    releases = []
    chunk_compute_spans = []
    for chunk_index in range(2):
        trace = trace_for_prefill_chunk(chunk_index)
        chunk_releases, chunk_span = extract_release_offsets(trace.rows)
        base_ns = sum(chunk_compute_spans)
        for item in chunk_releases:
            item["chunk_id"] = chunk_index
            item["release_ns"] += base_ns
            item["bytes_per_tp_rank"] = item["bytes_per_tp_rank"]
        releases.extend(chunk_releases)
        chunk_compute_spans.append(chunk_span)
    profiled_prefill_compute_ns = sum(chunk_compute_spans)
    events = build_events(releases)
    event_path = output / "events.csv"
    fields = ["start_ns", "src", "dst", "bytes", "event_type",
              "request_id", "collective_id", "layer_id", "tag",
              "active_request_ids", "serving_role"]
    with event_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: event[key] for key in fields} for event in events)

    per_chunk_bytes = {
        chunk: sum(row["bytes_per_tp_rank"] for row in releases
                   if row["chunk_id"] == chunk)
        for chunk in range(2)
    }
    expected_per_rank = sum(per_chunk_bytes.values())
    if expected_per_rank != 201_326_592:
        raise RuntimeError(
            f"model trace byte invariant failed: shard={expected_per_rank}, "
            "expected 201326592")
    manifest = {
        "case": "LAYERWISE_PROFILED_RELEASE_PACKET_REPLAY",
        "status": "INPUT_READY",
        "model": MODEL,
        "hardware_profile": "RTXPRO6000",
        "profile_variant": "bf16",
        "input_tokens": INPUT_TOKENS,
        "output_tokens": 1,
        "tp_size": TP,
        "num_layers": LAYERS,
        "kv_bytes_per_token_all_layers": 98_304,
        "kv_bytes_per_request": 402_653_184,
        "kv_bytes_per_tp_rank": expected_per_rank,
        "bytes_per_layer_per_tp_rank_by_chunk": {
            str(chunk): per_chunk_bytes[chunk] // LAYERS
            for chunk in range(2)
        },
        "request_count": 4,
        "event_count": len(events),
        "total_event_bytes": sum(row["bytes"] for row in events),
        "profiled_prefill_compute_span_ns": profiled_prefill_compute_ns,
        "release_offsets": releases,
        "ns3_topology": str(args.topology.resolve()),
        "rank_to_nic_map": str(args.rank_map.resolve()),
        "packet_level_only": True,
        "release_semantics": (
            "four identical one-request prefills are phase-aligned and each "
            "uses two 2048-token prefill chunks within the profile's measured "
            "token bound; each layer's two TP shards are released after the "
            "profile-derived QKV compute node; the second chunk starts after "
            "the first chunk's profiled compute graph completes, not after its "
            "P2D network drain"),
        "per_chunk_profiled_compute_span_ns": chunk_compute_spans,
        "limitations": [
            "The replay freezes profile-derived release offsets; ns-3 completion does not feed back into the serving scheduler.",
            "TP/NVSwitch communication time is excluded from the release clock; only profiled compute-node durations are accumulated.",
            "This is controlled synchronized Prefill, not a production-arrival claim.",
            "Decode admission and TTFT/TBT are not simulated.",
        ],
        "events_sha256": sha256(event_path),
        "topology_sha256": sha256(args.topology),
        "rank_map_sha256": sha256(args.rank_map),
        "serving_metrics": "NOT_AVAILABLE: packet replay has no serving feedback",
    }
    (output / "replay_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output), "events": len(events),
        "requests": manifest["request_count"],
        "total_event_bytes": manifest["total_event_bytes"],
        "bytes_per_chunk_per_rank": per_chunk_bytes,
        "profiled_prefill_compute_span_ms": profiled_prefill_compute_ns / 1e6,
        "layer_release_first_last_ms": [
            releases[0]["release_ns"] / 1e6,
            releases[-1]["release_ns"] / 1e6,
        ],
        "events_sha256": manifest["events_sha256"],
    }, indent=2))


if __name__ == "__main__":
    main()
