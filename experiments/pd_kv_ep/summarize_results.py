#!/usr/bin/env python3
"""Aggregate summary JSON files produced by analyze_results.py."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?", default=Path(__file__).parent / "results")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    summaries = []
    for path in sorted(args.root.rglob("*.summary.json")):
        summaries.append(json.loads(path.read_text(encoding="utf-8")))
    output = args.output or args.root / "summary.json"
    overlap = []
    for summary in summaries:
        communication = summary.get("communication", {})
        overlap.append(communication.get("p2d_ep_overlap_count", 0) > 0)
    result = {
        "root": str(args.root),
        "scenario_count": len(summaries),
        "timed_overlap_verified": any(overlap),
        "contention_slowdown_verified": False,
        "summaries": summaries,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
