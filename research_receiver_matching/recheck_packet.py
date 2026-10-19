#!/usr/bin/env python3
"""Recompute saved ns-3 receiver-incast completion from raw event rows."""

import csv
import json
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
RUNS = {
    "4_to_1_cc0": "RC_N2_cc0",
    "4_to_1_cc1": "RC_N2_cc1",
    "4_to_2_cc0": "RC_N3_cc0",
    "4_to_2_cc1": "RC_N3_FOUR_TO_TWO_RECEIVER_NICS_cc1_local",
    "4_to_4_cc0": "RC_N4_cc0",
}


def main():
    rows = []
    for label, run in RUNS.items():
        folder = ROOT / "research_ns3_incast/results" / run
        with (folder / "comm_events.csv").open(newline="") as stream:
            events = list(csv.DictReader(stream))
        starts = {int(row["event_id"]): row for row in events
                  if row["phase"] == "START"}
        ends = {int(row["event_id"]): row for row in events
                if row["phase"] == "END"}
        if len(starts) != 4 or set(starts) != set(ends):
            raise RuntimeError(f"{run}: expected four matched shard events")
        for event_id, end in sorted(ends.items()):
            start = starts[event_id]
            if int(start["request_id"]) != int(end["request_id"]):
                raise RuntimeError(f"{run}: request ID changed between events")
            issue = int(start["issue_time_ns"])
            finish = int(end["network_end_ns"])
            rows.append({
                "case": label,
                "request_id": start["request_id"],
                "src_rank": start["src_rank"],
                "dst_rank": start["dst_rank"],
                "dst_physical_endpoint": start["dst"],
                "bytes": start["bytes"],
                "issue_ns": issue,
                "finish_ns": finish,
                "fct_ms": (finish - issue) / 1e6,
                "path": start["path"],
            })
        manifest = json.loads((folder / "network_run_manifest.json").read_text())
        if not manifest:
            raise RuntimeError(f"{run}: empty run manifest")
    out = HERE / "03_PACKET_RECHECK.csv"
    with out.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for label in RUNS:
        case_rows = [row for row in rows if row["case"] == label]
        print(label, "mean_fct_ms=%.6f" % statistics.mean(
            row["fct_ms"] for row in case_rows),
            "ready_max_ms=%.6f" % (max(
                row["finish_ns"] for row in case_rows) / 1e6))


if __name__ == "__main__":
    main()
