#!/usr/bin/env python3
"""Audit whether agentic token-ID sidecars can support exact KV hashes."""

import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
TRACE = ROOT / "workloads/swe-bench-qwen3-30b-a3b-50-sps0.2.jsonl"


def main():
    sessions = [json.loads(line) for line in TRACE.open()]
    turns = [turn for session in sessions for turn in session["sub_requests"]]
    input_delta = Counter(int(turn["input_toks"]) -
                          len(turn.get("input_tok_ids", []))
                          for turn in turns)
    output_delta = Counter(int(turn["output_toks"]) -
                           len(turn.get("output_tok_ids", []))
                           for turn in turns)
    output_missing = [int(turn["output_toks"]) -
                      len(turn.get("output_tok_ids", []))
                      for turn in turns]
    result = {
        "trace": str(TRACE.relative_to(ROOT)),
        "sha256": hashlib.sha256(TRACE.read_bytes()).hexdigest(),
        "sessions": len(sessions),
        "subrequests": len(turns),
        "input_missing_ids_distribution": dict(sorted(input_delta.items())),
        "incomplete_input_requests": sum(count for gap, count in
                                         input_delta.items() if gap != 0),
        "output_missing_ids_min": min(output_missing),
        "output_missing_ids_median": statistics.median(output_missing),
        "output_missing_ids_max": max(output_missing),
        "incomplete_output_requests": sum(count for gap, count in
                                          output_delta.items() if gap != 0),
        "implication": "Unknown location/content of missing prompt IDs prevents valid chained prefix hashes; simulator now disables prefix hashing for these requests.",
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
