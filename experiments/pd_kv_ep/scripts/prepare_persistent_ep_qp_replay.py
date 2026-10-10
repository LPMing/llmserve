#!/usr/bin/env python3
"""Prepare a bounded ns-3 replay from model-derived FlowSim event ledgers."""

import argparse
import csv
import gzip
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
POINTS = {
    "D8K1": "full_fair_d8_k1_i8192",
    "D8K2": "full_fair_d8_k2_i8192",
    "D8K4": "full_fair_d8_k4_i8192",
}
TOPOLOGY = "experiments/pd_kv_ep/configs/large_scale/ns3/minimal_1p2d_ep16_2x200g_single_tor.txt"


def read_jsonl_gz(path):
    rows = []
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("{"):
                rows.append(json.loads(line))
    return rows


def csv_text(value):
    return str(value).replace("\r", "").replace("\n", "").replace(",", ";")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--point", choices=tuple(POINTS), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pre-us", type=int, default=500)
    parser.add_argument("--post-us", type=int, default=2500)
    parser.add_argument("--shift-kv-after-ep", action="store_true",
                        help="place the identical P2D burst after the EP observation window")
    parser.add_argument("--align-kv-to-ep-peer", nargs=2, type=int,
                        metavar=("SRC_RANK", "DST_RANK"),
                        help="shift the selected model-derived P2D release so its first "
                             "packet issue coincides with this peer's first selected EP issue")
    args = parser.parse_args()
    if args.pre_us < 0 or args.post_us <= 0:
        parser.error("pre-us must be nonnegative and post-us must be positive")

    point_dir = ROOT / "experiments/pd_kv_ep/results/minimal_ideal_kv_ep/points" / POINTS[args.point]
    source_dir = point_dir / "events"
    ep_path = next(source_dir.glob("*_ep_flows.jsonl.gz"))
    kv_path = next(source_dir.glob("*_kv_events.jsonl.gz"))
    ep_rows = read_jsonl_gz(ep_path)
    kv_rows = read_jsonl_gz(kv_path)

    # Select the model-derived layer-2 release for the new K cohort, not any
    # warm-up P2D traffic at the beginning of the source run.
    kv_candidates = [row for row in kv_rows
                     if row.get("event") == "KV_GENERATED"
                     and row.get("layer_id") == 2
                     and row.get("batch_id") == 1]
    if not kv_candidates:
        raise SystemExit(f"no batch-1, layer-2 KV_GENERATED events in {kv_path}")
    kv_time = min(row["timestamp_ns"] for row in kv_candidates)
    selected_kv = [row for row in kv_candidates if row["timestamp_ns"] == kv_time]
    if not selected_kv:
        raise SystemExit("selected P2D cohort is empty")

    window_start = kv_time - args.pre_us * 1000
    window_end = kv_time + args.post_us * 1000
    ep_groups = defaultdict(list)
    for row in ep_rows:
        if row.get("traffic_class") != "EP":
            continue
        issue_time = row.get("requested_start_ns", row.get("start_ns"))
        group_start = row.get("collective_start_ns", issue_time)
        if window_start <= group_start <= window_end:
            key = (row["collective_id"], row["event_type"])
            ep_groups[key].append(row)
    selected_ep = [row for rows in ep_groups.values() for row in rows]
    if not selected_ep:
        raise SystemExit("no EP collective flows selected in the requested window")

    ep_last_issue = max(row.get("requested_start_ns", row.get("start_ns"))
                        for row in selected_ep)
    if args.shift_kv_after_ep and args.align_kv_to_ep_peer:
        parser.error("--shift-kv-after-ep and --align-kv-to-ep-peer are mutually exclusive")

    shift_ns = 0
    if args.shift_kv_after_ep:
        # This no-overlap control is placed after all selected EP issues. A
        # transfer shifted only into the next nominal round gap would overlap
        # later rounds because a multi-shard P2D burst outlasts that gap.
        shift_ns = ep_last_issue + 500_000 - kv_time
        if shift_ns <= 0:
            raise SystemExit("cannot shift P2D after the selected EP window")
    elif args.align_kv_to_ep_peer:
        src_rank, dst_rank = args.align_kv_to_ep_peer
        peer_issues = [row.get("requested_start_ns", row.get("start_ns"))
                       for row in selected_ep
                       if row.get("src") == src_rank and row.get("dst") == dst_rank]
        if not peer_issues:
            raise SystemExit(
                f"no selected EP event for target rank peer {src_rank}->{dst_rank}")
        shift_ns = min(peer_issues) - kv_time

    events = []
    tag = 1_000_000
    for row in selected_ep:
        issue_time = row.get("requested_start_ns", row.get("start_ns"))
        request_ids = row.get("request_ids") or []
        events.append({
            "start_ns": int(issue_time),
            "src": int(row["src"]),
            "dst": int(row["dst"]),
            "bytes": int(row["bytes"]),
            "event_type": int(row["event_type"]),
            "request_id": int(request_ids[0]) if request_ids else -1,
            "collective_id": int(row["collective_id"]),
            "layer_id": int(row["layer_id"]),
            "tag": tag,
            "active_request_ids": ";".join(str(value) for value in request_ids),
            "serving_role": csv_text(row.get("traffic_subtype") or "EP"),
        })
        tag += 1
    for row in selected_kv:
        request_ids = row.get("request_ids") or []
        events.append({
            "start_ns": int(row["timestamp_ns"] + shift_ns),
            "src": int(row["src"]),
            "dst": int(row["dst"]),
            "bytes": int(row["bytes"]),
            "event_type": int(row["event_type"]),
            "request_id": int(request_ids[0]) if request_ids else -1,
            "collective_id": int(row["collective_id"]),
            "layer_id": int(row["layer_id"]),
            "tag": tag,
            "active_request_ids": ";".join(str(value) for value in request_ids),
            "serving_role": "P2D_KV",
        })
        tag += 1
    events.sort(key=lambda row: (row["start_ns"], row["event_type"], row["tag"]))

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    event_path = output_dir / "events.csv"
    if event_path.exists():
        raise SystemExit(f"refusing to overwrite existing replay input: {event_path}")
    fields = ["start_ns", "src", "dst", "bytes", "event_type", "request_id",
              "collective_id", "layer_id", "tag", "active_request_ids", "serving_role"]
    with event_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(events)

    manifest = {
        "purpose": "persistent EP-QP state micro-replay; network-only, not serving",
        "source_point": args.point,
        "source_ep_ledger": str(ep_path.relative_to(ROOT)),
        "source_kv_ledger": str(kv_path.relative_to(ROOT)),
        "source_model": "Qwen/Qwen3-30B-A3B-Instruct-2507",
        "source_parallelism": "EP16, model-derived routing/bytes",
        "ns3_topology": TOPOLOGY,
        "rank_to_nic_map": (
            "experiments/pd_kv_ep/configs/large_scale/"
            "minimal_1p2d_ep16_rank_to_nic.csv"
        ),
        "link_rate_gbps": 200,
        "p2d_mode": "LAYERWISE",
        "synthetic_byte_override": False,
        "kv_source_release_ns": kv_time,
        "kv_shift_ns": shift_ns,
        "kv_alignment_peer": args.align_kv_to_ep_peer,
        "kv_request_ids": sorted({int(item) for row in selected_kv
                                   for item in row.get("request_ids", [])}),
        "kv_tokens_per_request": 8192,
        "kv_layer_id": 2,
        "kv_flow_count": len(selected_kv),
        "kv_bytes": sum(int(row["bytes"]) for row in selected_kv),
        "ep_collective_count": len(ep_groups),
        "ep_flow_count": len(selected_ep),
        "target_recurrent_ep_peer": "rank16->rank8",
        "ep_window_start_ns": window_start,
        "ep_window_end_ns": window_end,
        "ep_last_issue_ns": ep_last_issue,
        "shifted_control": args.shift_kv_after_ep,
        "request_count": len({int(item) for row in selected_kv
                               for item in row.get("request_ids", [])}) + 8,
        "load_scale": 1.0,
        "arrival_interval_scale": 1.0,
    }
    (output_dir / "replay_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output_dir": str(output_dir), **manifest,
                      "event_count": len(events)}, indent=2))


if __name__ == "__main__":
    main()
