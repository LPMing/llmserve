#!/usr/bin/env python3
"""Screen prior-observed distinct long prefixes in short-output root bursts."""

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "qwen_bailian_raw"
OUT = ROOT / "prefix_burst_screen.json"
PREFIX_BLOCKS = 124
OUTPUT_LIMIT = 128
WINDOWS = (0.1, 1.0)
INPUT_WINDOWS = ((1984, 2304), (1984, 4096))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def screen(path):
    seen = set()
    counts = Counter()
    buckets = {
        (lo, hi, window): defaultdict(set)
        for lo, hi in INPUT_WINDOWS for window in WINDOWS
    }
    for line in path.open():
        row = json.loads(line)
        ids = row["hash_ids"]
        if len(ids) < PREFIX_BLOCKS:
            continue
        key = tuple(ids[:PREFIX_BLOCKS])
        counts["requests_with_1984_token_prefix"] += 1
        prior = key in seen
        if prior:
            counts["prior_observed_1984_token_prefix"] += 1
        if (prior and row["turn"] == 1 and
                row["output_length"] <= OUTPUT_LIMIT):
            for lo, hi in INPUT_WINDOWS:
                if lo <= row["input_length"] <= hi:
                    counts["eligible_root_%d_%d" % (lo, hi)] += 1
                    for window in WINDOWS:
                        bucket = int(row["timestamp"] / window)
                        buckets[(lo, hi, window)][bucket].add(key)
        seen.add(key)
    report = {"source_file": path.name, "sha256": digest(path),
              "counts": dict(counts), "burst_windows": {}}
    for (lo, hi, window), groups in buckets.items():
        sizes = [len(keys) for keys in groups.values()]
        report["burst_windows"]["%d_%d_%.1fs" % (lo, hi, window)] = {
            "eligible_nonempty_buckets": len(sizes),
            "max_distinct_prior_prefixes": max(sizes, default=0),
            "buckets_ge_2": sum(value >= 2 for value in sizes),
            "buckets_ge_4": sum(value >= 4 for value in sizes),
            "buckets_ge_8": sum(value >= 8 for value in sizes),
        }
    return report


def main():
    result = {
        "method": (
            "Exact equality of first 124 released 16-token hash IDs in an "
            "earlier input; root turn; short output; arrival buckets. "
            "Prior occurrence is an optimistic upper bound on cache hit, "
            "not an observed P/D cache state. Qwen traces are not the "
            "Llama-3.1-8B simulator model."),
        "source_manifest": str((RAW / "manifest.json").relative_to(ROOT)),
        "files": {path.name: screen(path)
                  for path in sorted(RAW.glob("*.jsonl"))},
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    for name, item in result["files"].items():
        print(name, item["counts"], item["burst_windows"])


if __name__ == "__main__":
    main()
