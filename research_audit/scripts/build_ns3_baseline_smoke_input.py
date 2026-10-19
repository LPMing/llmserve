#!/usr/bin/env python3
"""Extract a bounded, model-derived packet replay slice from FlowSim telemetry.

This is network-only: it preserves issue timestamps and bytes from an
integrated FlowSim ledger, and translates recorded endpoints to the logical
ASTRA ranks used by the matching ns-3 topology. It does not produce serving
metrics or feed packet completions back to the scheduler.
"""

import argparse
import csv
import gzip
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER = ROOT / (
    "research_audit/results/current_baseline_flowsim_handoff_fix.jsonl.gz")
CONFIG_DIR = ROOT / "experiments/pd_kv_ep/configs/large_scale"
KV_REQUEST_ID = 1
EP_REQUEST_ID = 0
EP_COLLECTIVE_ID = 10000303
EXPECTED_KV_FLOWS = 96
EXPECTED_EP_FLOWS = 240

EVENT_FIELDS = (
    "start_ns", "src", "dst", "bytes", "event_type", "request_id",
    "collective_id", "layer_id", "tag", "active_request_ids",
    "serving_role",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--kv-request-id", type=int, default=KV_REQUEST_ID)
    parser.add_argument("--ep-request-id", type=int, default=EP_REQUEST_ID)
    parser.add_argument("--ep-collective-id", type=int,
                        action="append", default=None,
                        help="EP collective id to include; repeat for a full multi-event MoE layer")
    parser.add_argument("--expected-kv-flows", type=int,
                        default=EXPECTED_KV_FLOWS)
    parser.add_argument("--expected-ep-flows", type=int,
                        default=EXPECTED_EP_FLOWS)
    args = parser.parse_args()
    ep_collective_ids = (args.ep_collective_id if args.ep_collective_id
                         else [EP_COLLECTIVE_ID])

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    ledger = args.ledger.resolve()
    logical_map_path = CONFIG_DIR / "minimal_1p2d_ep16_logical_to_physical.json"
    physical_map_path = CONFIG_DIR / "minimal_1p2d_ep16_rank_to_nic.csv"
    topology_path = CONFIG_DIR / "ns3/minimal_1p2d_ep16_logical_ranks_single_tor.txt"

    logical_to_physical = json.loads(
        logical_map_path.read_text(encoding="utf-8"))["logical_to_physical"]
    physical_map = {}
    with physical_map_path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            physical_map[int(row["astra_rank"])] = row
    if len(logical_to_physical) != 32 or len(physical_map) != 24:
        raise ValueError("unexpected 1P2D EP16 logical/physical rank-map size")

    rank_map_path = output_dir / "rank_to_nic_map.csv"
    with rank_map_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=("astra_rank", "server_id", "nic_id"),
            lineterminator="\n")
        writer.writeheader()
        for logical_rank, physical_rank in enumerate(logical_to_physical):
            endpoint = physical_map[int(physical_rank)]
            writer.writerow({
                "astra_rank": logical_rank,
                "server_id": endpoint["server_id"],
                "nic_id": endpoint["nic_id"],
            })

    selected = []
    opener = gzip.open if ledger.suffix == ".gz" else open
    with opener(str(ledger), "rt", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip() or line.startswith("#"):
                continue
            row = json.loads(line)
            request_ids = row.get("request_ids") or []
            is_kv = (row.get("traffic_class") == "KV_MOVEMENT" and
                     args.kv_request_id in request_ids)
            is_ep = (row.get("traffic_class") == "EP" and
                     args.ep_request_id in request_ids and
                     row.get("collective_id") in ep_collective_ids)
            if not (is_kv or is_ep):
                continue
            logical_src = row.get("logical_src")
            logical_dst = row.get("logical_dst")
            if logical_src is None or logical_dst is None:
                raise ValueError("selected event lacks logical ASTRA endpoints")
            event_type = (1 if is_kv else
                          2 if row.get("traffic_subtype") == "EP_DISPATCH" else 3)
            selected.append({
                "start_ns": int(row["requested_start_ns"]),
                "src": int(logical_src),
                "dst": int(logical_dst),
                "bytes": int(row["bytes"]),
                "event_type": event_type,
                "request_id": int(request_ids[0]) if len(request_ids) == 1 else -1,
                "collective_id": int(row.get("collective_id") or 0),
                "layer_id": int(row.get("layer_id") or 0),
                "tag": len(selected),
                "active_request_ids": ";".join(str(value) for value in request_ids),
                "serving_role": "prefill" if is_kv else "decode",
            })

    selected.sort(key=lambda row: (
        row["start_ns"], row["event_type"], row["tag"]))
    kv_events = [row for row in selected if row["event_type"] == 1]
    ep_events = [row for row in selected if row["event_type"] in (2, 3)]
    if (len(kv_events) != args.expected_kv_flows or
            len(ep_events) != args.expected_ep_flows):
        raise ValueError(
            "selected slice changed: KV=%d EP=%d" %
            (len(kv_events), len(ep_events)))

    event_path = output_dir / "events.csv"
    with event_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=EVENT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(selected)

    manifest = {
        "schema_version": 1,
        "scale": "S1P2D_EP16",
        "traffic_class": "FULL",
        "kv_subtype": "P2D",
        "request_count": len({args.kv_request_id, args.ep_request_id}),
        "event_count": len(selected),
        "event_counts_by_class": {
            "KV_MOVEMENT": len(kv_events), "EP": len(ep_events)},
        "bytes_by_class": {
            "KV_MOVEMENT": sum(row["bytes"] for row in kv_events),
            "EP": sum(row["bytes"] for row in ep_events)},
        "ep_degree": 16,
        "model": "Qwen/Qwen3-30B-A3B-Instruct-2507",
        "active_request_ids_seen": [args.ep_request_id, args.kv_request_id],
        "ns3_topology": str(topology_path.resolve()),
        "rank_to_nic_map": str(rank_map_path.resolve()),
        "event_timestamp_semantics": (
            "original requested_start_ns from integrated FlowSim"),
        "packet_level_completion_is_recomputed_by_ns3": True,
        "serving_metrics_are_not_generated_by_this_replay": True,
        "synthetic_byte_override": False,
        "source_flow_ledger": str(ledger),
        "logical_to_physical_map": str(logical_map_path.resolve()),
        "physical_rank_to_nic_map": str(physical_map_path.resolve()),
        "selected_kv_request_id": args.kv_request_id,
        "selected_ep_request_id": args.ep_request_id,
        "selected_ep_collective_ids": ep_collective_ids,
    }
    (output_dir / "replay_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
