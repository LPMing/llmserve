#!/usr/bin/env python3
"""Convert integrated FlowSim issue-time telemetry into a native ns-3 replay.

The converted event ledger preserves model/serving-generated flow sizes and
release times. ns-3 then recomputes packet-level delivery, queues, ECN/PFC,
and completion times on its own data plane; those results are not fed back into
the serving scheduler by this bridge.
"""

import argparse
import csv
import heapq
import json
import tempfile
from collections import Counter
from pathlib import Path


EVENT_NAMES = {1: "P2D_KV", 2: "EP_DISPATCH", 3: "EP_COMBINE"}
SCALE_EP_DEGREE = {
    "S2P4D_EP32_SHARED_NIC": 32,
    "S2P4D_EP32_DEDICATED_NIC": 32,
    "S8_4P4D_EP32_SHARED_NIC": 32,
}
SCALE_GPU_TO_NIC_MAP = {
    "S8_4P4D_EP32_SHARED_NIC": Path(
        "experiments/pd_kv_ep/configs/large_scale/"
        "s8_4p4d_ep32_gpu_to_nic.csv"),
}
EVENT_HEADER = [
    "start_ns", "src", "dst", "bytes", "event_type", "request_id",
    "collective_id", "layer_id", "tag", "active_request_ids", "serving_role",
]
SORT_CHUNK_ROWS = 50000


def _row_key(row):
    return int(row["start_ns"]), int(row["event_type"]), int(row["tag"])


def _read_event_chunk(path):
    with path.open(encoding="utf-8", newline="") as stream:
        yield from csv.DictReader(stream)


def _write_sorted_chunk(rows, path):
    rows.sort(key=_row_key)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=EVENT_HEADER,
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_rank_to_nic_map(gpu_to_nic_map, output_path):
    """Expand semicolon-separated NIC membership into the ns-3 replay schema."""
    rank_rows = {}
    with gpu_to_nic_map.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            for rank_text in row["rank_ids"].split(";"):
                rank = int(rank_text)
                if rank in rank_rows:
                    raise ValueError("rank %d maps to multiple NICs" % rank)
                rank_rows[rank] = {
                    "astra_rank": rank,
                    "server_id": row["server_id"],
                    "nic_id": int(row["nic_id"]),
                }
    if sorted(rank_rows) != list(range(64)):
        raise ValueError("S8 NIC map must cover logical ranks 0..63 exactly")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=("astra_rank", "server_id", "nic_id"),
            lineterminator="\n")
        writer.writeheader()
        writer.writerows(rank_rows[rank] for rank in sorted(rank_rows))
    return output_path


def convert(flow_telemetry, topology, output_dir, request_count, schedule_source,
            scale_label, gpu_to_nic_map=None):
    class_bytes = Counter()
    class_flows = Counter()
    active_requests = set()
    max_time_ns = 0
    event_count = 0
    output_dir.mkdir(parents=True, exist_ok=True)

    if gpu_to_nic_map is None:
        gpu_to_nic_map = SCALE_GPU_TO_NIC_MAP.get(scale_label)
    if gpu_to_nic_map is not None:
        gpu_to_nic_map = gpu_to_nic_map.resolve()
        rank_to_nic_map = _write_rank_to_nic_map(
            gpu_to_nic_map, output_dir / "rank_to_nic_map.csv")
    else:
        rank_to_nic_map = None

    with tempfile.TemporaryDirectory(prefix="flowsim_replay_sort_",
                                     dir=output_dir) as sort_directory:
        sort_directory = Path(sort_directory)
        chunk_paths = []
        chunk_rows = []
        with flow_telemetry.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                record = json.loads(line)
                if record.get("record_type") == "metadata":
                    continue
                event_type = int(record.get("event_type", -1))
                if event_type not in EVENT_NAMES:
                    raise ValueError(
                        "unsupported event_type %r at line %d" %
                        (event_type, line_number))
                traffic_class = record.get("traffic_class")
                expected_class = "KV_MOVEMENT" if event_type == 1 else "EP"
                if traffic_class != expected_class:
                    raise ValueError(
                        "event/class mismatch at line %d: %r != %r" %
                        (line_number, traffic_class, expected_class))
                if "requested_start_ns" not in record:
                    raise ValueError(
                        "missing issue timestamp at line %d" % line_number)
                start_ns = int(record["requested_start_ns"])
                flow_bytes = int(record["bytes"])
                if start_ns < 0 or flow_bytes <= 0:
                    raise ValueError(
                        "invalid event time/bytes at line %d" % line_number)
                src = int(record["src"])
                dst = int(record["dst"])
                if (rank_to_nic_map is not None and
                        (src not in range(64) or dst not in range(64))):
                    raise ValueError(
                        "event rank outside S8 map at line %d" % line_number)
                request_ids = [str(value) for value in
                               (record.get("request_ids") or [])]
                active_requests.update(request_ids)
                max_time_ns = max(max_time_ns,
                                  int(record.get("end_ns", start_ns)))
                class_bytes[traffic_class] += flow_bytes
                class_flows[traffic_class] += 1
                request_id = request_ids[0] if len(request_ids) == 1 else -1
                chunk_rows.append({
                    "start_ns": start_ns,
                    "src": src,
                    "dst": dst,
                    "bytes": flow_bytes,
                    "event_type": event_type,
                    "request_id": request_id,
                    "collective_id": int(record.get("collective_id", 0) or 0),
                    "layer_id": int(record.get("layer_id", 0) or 0),
                    "tag": event_count,
                    "active_request_ids": ";".join(request_ids),
                    "serving_role": "prefill" if event_type == 1 else "decode",
                })
                event_count += 1
                if len(chunk_rows) >= SORT_CHUNK_ROWS:
                    chunk_path = sort_directory / (
                        "chunk_%06d.csv" % len(chunk_paths))
                    _write_sorted_chunk(chunk_rows, chunk_path)
                    chunk_paths.append(chunk_path)
                    chunk_rows = []

        if chunk_rows:
            chunk_path = sort_directory / ("chunk_%06d.csv" % len(chunk_paths))
            _write_sorted_chunk(chunk_rows, chunk_path)
            chunk_paths.append(chunk_path)
        if not event_count:
            raise ValueError("FlowSim telemetry contains no communication events")

        event_path = output_dir / "events.csv"
        with event_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=EVENT_HEADER,
                                    lineterminator="\n")
            writer.writeheader()
            sorted_rows = heapq.merge(
                *(_read_event_chunk(path) for path in chunk_paths), key=_row_key)
            writer.writerows(sorted_rows)

    if not event_count:
        raise ValueError("FlowSim telemetry contains no communication events")

    summary = {
        "schema_version": 1,
        "scale": scale_label,
        "traffic_class": "FULL",
        "kv_subtype": "P2D",
        "request_count": int(request_count),
        "event_count": event_count,
        "event_counts_by_class": dict(class_flows),
        "bytes_by_class": dict(class_bytes),
        "p2d_bytes": class_bytes["KV_MOVEMENT"],
        "remote_kv_bytes": 0,
        "remote_kv_blocks": 0,
        "ep_bytes": class_bytes["EP"],
        "ep_degree": SCALE_EP_DEGREE[scale_label],
        "model": "Qwen/Qwen3-30B-A3B-Instruct-2507",
        "active_request_ids_seen": sorted(active_requests),
        "max_flowsim_completion_time_ns": max_time_ns,
        "event_timestamp_semantics": "requested_start_ns (serving/network issue time)",
        "schedule_source": str(schedule_source.resolve()),
        "flowsim_telemetry_source": str(flow_telemetry.resolve()),
        "ns3_topology": str(topology.resolve()),
        "rank_to_nic_map": (
            str(rank_to_nic_map.resolve().relative_to(
                Path(__file__).resolve().parents[3]))
            if rank_to_nic_map is not None else None),
        "gpu_to_nic_map_source": (
            str(gpu_to_nic_map) if gpu_to_nic_map is not None else None),
        "load_scale": 1.0,
        "packet_level_completion_is_recomputed_by_ns3": True,
        "serving_metrics_are_not_generated_by_this_replay": True,
        "timing_model": {
            "kind": "integrated_FlowSim_issue_schedule_replayed_in_native_ns3",
            "source_timestamps": "requested_start_ns from integrated FlowSim",
            "ns3_recomputes_packet_delivery_and_completion": True,
            "serving_feedback_from_ns3": False,
        },
        "synthetic_byte_override": False,
    }
    (output_dir / "replay_manifest.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"events": str(event_path), **summary}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flow-telemetry", type=Path, required=True)
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--request-count", type=int, required=True)
    parser.add_argument("--schedule-source", type=Path, required=True,
                        help="integrated request CSV that produced this issue schedule")
    parser.add_argument(
        "--scale-label",
        choices=tuple(SCALE_EP_DEGREE),
        default="S2P4D_EP32_SHARED_NIC",
    )
    parser.add_argument("--gpu-to-nic-map", type=Path, default=None,
                        help="source map with NIC rows and semicolon-separated rank_ids")
    args = parser.parse_args()
    if args.request_count <= 0:
        parser.error("--request-count must be positive")
    convert(args.flow_telemetry.resolve(), args.topology.resolve(),
            args.output_dir.resolve(), args.request_count,
            args.schedule_source.resolve(), args.scale_label,
            args.gpu_to_nic_map)


if __name__ == "__main__":
    main()
