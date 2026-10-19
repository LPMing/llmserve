#!/usr/bin/env python3
"""Measure natural Mooncake arrival buckets and exact released prefix IDs."""

import hashlib
import json
import math
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
RAW = HERE / "mooncake_raw"


def quantile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def main():
    manifest = json.loads((RAW / "manifest.json").read_text())
    result = {"source": manifest["source"], "commit": manifest["commit"]}
    for name, info in manifest["files"].items():
        path = RAW / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != info["sha256"]:
            raise ValueError("Mooncake checksum mismatch: " + name)
        records = [json.loads(line) for line in path.read_text().splitlines()]
        buckets = Counter(row["timestamp"] for row in records)
        timestamps = sorted(buckets)
        gaps = [later - earlier for earlier, later in zip(timestamps,
                                                         timestamps[1:])]
        inputs = [row["input_length"] for row in records]
        outputs = [row["output_length"] for row in records]
        report = {
            "sha256": info["sha256"],
            "requests": len(records),
            "timestamp_span_ms": timestamps[-1] - timestamps[0],
            "distinct_timestamps": len(timestamps),
            "requests_per_timestamp_p50_p95_max": [
                quantile(list(buckets.values()), fraction)
                for fraction in (0.5, 0.95, 1)],
            "positive_timestamp_gap_ms_p50_p95": [
                quantile(gaps, fraction) for fraction in (0.5, 0.95)],
            "top_positive_gaps_ms": Counter(gaps).most_common(5),
            "input_tokens_p50_p95_p99": [
                quantile(inputs, fraction) for fraction in (0.5, 0.95, 0.99)],
            "output_tokens_p50_p95_p99": [
                quantile(outputs, fraction) for fraction in (0.5, 0.95, 0.99)],
            "requests_input_le_2048": sum(value <= 2048 for value in inputs),
            "requests_input_le_16384": sum(value <= 16384 for value in inputs),
            "prefix_block_count_matches_512_tokens": sum(
                len(row["hash_ids"]) == math.ceil(row["input_length"] / 512)
                for row in records),
            "caveat": "Same timestamp does not prove physical simultaneity "
                      "when the published trace has bucketed arrival times; "
                      "model, pool size and NIC mapping are not given.",
        }
        result[name] = report
    output = HERE / "mooncake_analysis"
    output.mkdir(exist_ok=True)
    (output / "summary.json").write_text(json.dumps(result, indent=2,
                                                   sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
