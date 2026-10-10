#!/usr/bin/env python3
"""Create offline EP critical-flow oracle sets from one FAIR FlowSim replay."""
import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--flows", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    groups = defaultdict(list)
    with args.flows.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row.get("traffic_class") != "EP":
                continue
            groups[row.get("collective_id", "")].append(row)
    if not groups:
        raise ValueError("no EP flow rows found")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    modes = {"critical": None, "top_1pct": 0.01, "top_5pct": 0.05, "top_10pct": 0.10}
    summary = {"input": str(args.flows.resolve()), "collective_count": len(groups), "modes": {}}
    for name, fraction in modes.items():
        selected = set()
        protected_bytes = 0
        total_bytes = 0
        protected_counts = []
        for collective_id, rows in groups.items():
            ordered = sorted(rows, key=lambda row: (int(row["end_ns"]), row["flow_id"]))
            total_bytes += sum(int(row["bytes"]) for row in ordered)
            if fraction is None:
                last = max(int(row["end_ns"]) for row in ordered)
                chosen = [row for row in ordered if int(row["end_ns"]) == last]
            else:
                count = max(1, int(math.ceil(len(ordered) * fraction)))
                chosen = ordered[-count:]
            selected.update(row["flow_id"] for row in chosen)
            protected_bytes += sum(int(row["bytes"]) for row in chosen)
            protected_counts.append({"collective_id": collective_id, "flow_count": len(ordered), "protected_flow_count": len(chosen), "protected_bytes": sum(int(row["bytes"]) for row in chosen), "total_bytes": sum(int(row["bytes"]) for row in ordered)})
        path = args.output_dir / ("critical_flow_oracle_%s.txt" % name)
        path.write_text("# Offline EP critical-flow oracle; generated from FAIR completion order\n" + "\n".join(sorted(selected)) + "\n", encoding="utf-8")
        summary["modes"][name] = {"flow_count": len(selected), "protected_bytes": protected_bytes, "total_ep_bytes": total_bytes, "protected_byte_fraction": protected_bytes / float(total_bytes) if total_bytes else 0.0, "rounds": protected_counts}
    (args.output_dir / "oracle_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: {key: value for key, value in data.items() if key != "rounds"} for name, data in summary["modes"].items()}, indent=2))


if __name__ == "__main__":
    main()
