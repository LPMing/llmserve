#!/usr/bin/env python3
"""Create offline receiver-fan-in P2D controls.

Only P2D destination instances change.  A source rank's TP shard is mapped to
the same TP rank of a selected Decode instance, so the P/D shard structure,
request timing, layerwise bytes, and EP ledger remain unchanged.  This is a
receiver-incast characterization bound, not a scheduler implementation.
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ledger(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _groups(rows):
    by_instance = defaultdict(list)
    decode = defaultdict(list)
    for row in rows:
        rank = int(row["astra_rank"])
        instance = int(row["instance_id"])
        by_instance[instance].append(row)
        if row["role"] == "decode":
            decode[instance].append(row)
    for values in by_instance.values():
        values.sort(key=lambda row: int(row["tp_rank"]))
    return by_instance, decode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--rank-metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--fan-in-instances", type=int, required=True,
        help="number of Decode instances that receive all source P2D instances")
    args = parser.parse_args()
    rows = _ledger(args.rank_metadata)
    by_instance, decode = _groups(rows)
    prefill_instances = sorted(
        instance for instance, values in by_instance.items()
        if values and values[0]["role"] == "prefill")
    decode_instances = sorted(decode)
    if args.fan_in_instances <= 0 or args.fan_in_instances > len(decode_instances):
        raise ValueError("fan-in instance count must be within Decode instance count")
    targets = decode_instances[:args.fan_in_instances]
    target_rank_by_tp = {}
    for instance in targets:
        for row in decode[instance]:
            target_rank_by_tp[(instance, int(row["tp_rank"]))] = int(row["astra_rank"])
    source_rank_info = {
        int(row["astra_rank"]): (int(row["instance_id"]), int(row["tp_rank"]))
        for row in rows if row["role"] == "prefill"
    }
    source_to_target = {
        instance: targets[index % len(targets)]
        for index, instance in enumerate(prefill_instances)
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    p2d_count = 0
    changed = 0
    with args.events.open(newline="", encoding="utf-8") as source, \
            args.output.open("w", newline="", encoding="utf-8") as target:
        reader = csv.DictReader(source)
        fields = list(reader.fieldnames or [])
        writer = csv.DictWriter(target, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in reader:
            row = dict(row)
            if row.get("event_type") in ("1", "P2D_KV", "REMOTE_KV_FETCH"):
                p2d_count += 1
                source_info = source_rank_info.get(int(row["src"]))
                if source_info is None:
                    raise ValueError("P2D source is not a prefill rank")
                source_instance, tp_rank = source_info
                target_instance = source_to_target[source_instance]
                destination = target_rank_by_tp[(target_instance, tp_rank)]
                if int(row["dst"]) != destination:
                    changed += 1
                row["dst"] = str(destination)
            writer.writerow(row)
    manifest = {
        "source_events": str(args.events.resolve()),
        "output_events": str(args.output.resolve()),
        "rank_metadata": str(args.rank_metadata.resolve()),
        "fan_in_instances": args.fan_in_instances,
        "target_decode_instances": targets,
        "source_to_target_instance": source_to_target,
        "p2d_event_count": p2d_count,
        "changed_destination_count": changed,
        "ep_rows_unchanged": True,
        "bytes_unchanged": True,
        "semantics": "offline receiver-fan-in characterization; TP-shard-preserving P2D remap",
    }
    path = args.output.with_suffix(args.output.suffix + ".json")
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
