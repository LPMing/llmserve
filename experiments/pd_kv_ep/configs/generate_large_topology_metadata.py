#!/usr/bin/env python3
"""Generate the planned 128-physical-GPU placement ledger.

The ledger is a topology design artifact, not an executed simulator input.  It
keeps physical serving ranks distinct from the current converter's internal
P/D shadow ranks so a later scale-out run cannot silently call those shadows
real GPUs.
"""

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "experiments/pd_kv_ep/configs/large_128_rank_metadata.csv"
FIELDS = (
    "gpu_id", "rank", "server_id", "unit_id", "rack_id", "leaf_id", "role",
    "astra_compute_rank", "astra_shadow_rank", "mapping_status",
)


def add_prefill(rows, unit, physical_rank_start, astra_rank_start, leaf):
    for server in range(4):
        for local_gpu in range(8):
            index = server * 8 + local_gpu
            rows.append({
                "gpu_id": "%s-S%d-G%d" % (unit, server, local_gpu),
                "rank": physical_rank_start + index,
                "server_id": "%s-S%d" % (unit, server),
                "unit_id": unit,
                "rack_id": "R0",
                "leaf_id": "Leaf%d" % leaf,
                "role": "prefill",
                "astra_compute_rank": astra_rank_start + index,
                "astra_shadow_rank": astra_rank_start + 32 + index,
                "mapping_status": "requires co-located/control-only shadow treatment",
            })


def add_decode(rows):
    for server in range(8):
        leaf = 2 if server < 4 else 3
        for local_gpu in range(8):
            index = server * 8 + local_gpu
            rows.append({
                "gpu_id": "D0-S%d-G%d" % (server, local_gpu),
                "rank": 64 + index,
                "server_id": "D0-S%d" % server,
                "unit_id": "D0",
                "rack_id": "R0",
                "leaf_id": "Leaf%d" % leaf,
                "role": "decode",
                "astra_compute_rank": 128 + index,
                "astra_shadow_rank": "",
                "mapping_status": "requires native TP/EP=64 profile before execution",
            })


def main():
    rows = []
    add_prefill(rows, "P0", 0, 0, 0)
    add_prefill(rows, "P1", 32, 64, 1)
    add_decode(rows)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print("wrote", OUTPUT, "with", len(rows), "physical GPU rows")


if __name__ == "__main__":
    main()
