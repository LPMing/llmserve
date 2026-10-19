#!/usr/bin/env python3
"""Measure exact prior-input prefix reuse in pinned Qwen-Bailian traces."""

import json
import math
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "qwen_bailian_raw"
OUTPUT = ROOT / "qwen_bailian_analysis"


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(fraction * len(ordered)) - 1]


class Node:
    __slots__ = ("depth", "representative", "children", "last_seen")

    def __init__(self, depth, representative, last_seen):
        self.depth = depth
        self.representative = representative
        self.children = {}
        self.last_seen = last_seen


class PrefixIndex:
    def __init__(self):
        self.root = Node(0, (), None)
        self.nodes = 1

    def observe(self, sequence, timestamp):
        """Return longest prefix in an earlier input and its latest observation."""
        node = self.root
        depth = 0
        while depth < len(sequence):
            child = node.children.get(sequence[depth])
            if child is None:
                prior_time = node.last_seen
                node.children[sequence[depth]] = Node(len(sequence), sequence, timestamp)
                self.nodes += 1
                node.last_seen = timestamp
                return depth, prior_time
            matched = depth
            limit = min(len(sequence), child.depth)
            while matched < limit and sequence[matched] == child.representative[matched]:
                matched += 1
            if matched < child.depth:
                prior_time = child.last_seen
                split = Node(matched, child.representative, timestamp)
                split.children[child.representative[matched]] = child
                node.children[sequence[depth]] = split
                self.nodes += 1
                if matched < len(sequence):
                    split.children[sequence[matched]] = Node(len(sequence), sequence, timestamp)
                    self.nodes += 1
                node.last_seen = timestamp
                return matched, prior_time
            node.last_seen = timestamp
            node = child
            depth = matched
        prior_time = node.last_seen
        node.last_seen = timestamp
        return depth, prior_time

    def match(self, sequence):
        """Find the longest already indexed prefix without changing the index."""
        node = self.root
        depth = 0
        prior_time = None
        while depth < len(sequence):
            child = node.children.get(sequence[depth])
            if child is None:
                break
            limit = min(len(sequence), child.depth)
            matched = depth
            while matched < limit and sequence[matched] == child.representative[matched]:
                matched += 1
            depth = matched
            prior_time = child.last_seen if matched else None
            if matched < child.depth:
                break
            node = child
        return depth, prior_time


def summarise(path):
    index = PrefixIndex()
    counts = Counter()
    kinds = Counter()
    lengths = []
    outputs = []
    reusable = []
    ratios = []
    ages = []
    parent_lcps = []
    parent_gaps = []
    arrivals = {0.2: Counter(), 1.0: Counter()}
    same_prefix = {0.2: Counter(), 1.0: Counter()}
    parents = {}
    last_timestamp = -math.inf
    time_min = math.inf
    time_max = -math.inf
    for line in path.open():
        row = json.loads(line)
        sequence = tuple(row["hash_ids"])
        tokens = row["input_length"]
        timestamp = row["timestamp"]
        counts["requests"] += 1
        counts["input_tokens"] += tokens
        counts["output_tokens"] += row["output_length"]
        kinds[row["type"]] += 1
        lengths.append(tokens)
        outputs.append(row["output_length"])
        time_min = min(time_min, timestamp)
        time_max = max(time_max, timestamp)
        if timestamp < last_timestamp:
            counts["timestamp_inversions"] += 1
        last_timestamp = timestamp
        if len(sequence) != math.ceil(tokens / 16):
            counts["hash_length_mismatches"] += 1
        if tokens <= 16384:
            counts["input_within_16k"] += 1
        matched, prior_time = index.observe(sequence, timestamp)
        reusable_tokens = min(matched * 16, (tokens // 16) * 16)
        reusable.append(reusable_tokens)
        ratio = reusable_tokens / tokens if tokens else 0
        ratios.append(ratio)
        counts["reusable_input_tokens"] += reusable_tokens
        if ratio >= 0.5:
            counts["requests_reuse_at_least_half"] += 1
        if ratio >= 0.8833:
            counts["requests_reuse_at_least_88pct"] += 1
            if tokens <= 16384:
                counts["high_reuse_within_16k"] += 1
        if reusable_tokens >= 256:
            counts["requests_reuse_256"] += 1
        if reusable_tokens >= 2048:
            counts["requests_reuse_2048"] += 1
        if prior_time is not None and matched:
            age = timestamp - prior_time
            ages.append(age)
            if age < 0:
                counts["negative_prefix_ages"] += 1
            if age <= 1:
                counts["prefix_reuse_within_1s"] += 1
            if age <= 10:
                counts["prefix_reuse_within_10s"] += 1
            if age <= 60:
                counts["prefix_reuse_within_60s"] += 1
        if row["parent_chat_id"] != -1:
            counts["nonroot_requests"] += 1
            parent = parents.get(row["parent_chat_id"])
            if parent is None:
                counts["missing_parent"] += 1
            else:
                parent_sequence, parent_timestamp = parent
                parent_lcp = 0
                for left, right in zip(sequence, parent_sequence):
                    if left != right:
                        break
                    parent_lcp += 1
                parent_lcps.append(min(parent_lcp * 16, (tokens // 16) * 16))
                parent_gaps.append(timestamp - parent_timestamp)
        parents[row["chat_id"]] = sequence, timestamp
        kinds["turn_%s" % row["turn"]] += 1
        for width in arrivals:
            bucket = int(timestamp / width)
            arrivals[width][bucket] += 1
            if len(sequence) >= 16:
                same_prefix[width][bucket, sequence[:16]] += 1
    summary = {
        "source_file": path.name,
        "counts": dict(counts),
        "request_types_and_turns": dict(kinds),
        "time_seconds": {"min": time_min, "max": time_max,
                         "mean_rps": counts["requests"] / (time_max - time_min)},
        "input_tokens_p50_p95_p99": [percentile(lengths, x) for x in (.5, .95, .99)],
        "output_tokens_p50_p95_p99": [percentile(outputs, x) for x in (.5, .95, .99)],
        "prior_input_reusable_tokens_p50_p95_p99":
            [percentile(reusable, x) for x in (.5, .95, .99)],
        "prior_input_reuse_ratio_p50_p95_p99":
            [percentile(ratios, x) for x in (.5, .95, .99)],
        "prior_prefix_age_seconds_p50_p95_p99":
            [percentile(ages, x) for x in (.5, .95, .99)],
        "parent_lcp_tokens_p50_p95_p99":
            [percentile(parent_lcps, x) for x in (.5, .95, .99)],
        "parent_arrival_gap_seconds_p50_p95_p99":
            [percentile(parent_gaps, x) for x in (.5, .95, .99)],
        "compressed_trie_nodes": index.nodes,
        "arrival_buckets": {},
    }
    for width in arrivals:
        burst_sizes = list(arrivals[width].values())
        prefix_groups = list(same_prefix[width].values())
        summary["arrival_buckets"][str(width)] = {
            "nonempty_buckets": len(burst_sizes),
            "requests_per_nonempty_bucket_p50_p95_p99":
                [percentile(burst_sizes, x) for x in (.5, .95, .99)],
            "peak_requests": max(burst_sizes),
            "buckets_with_9_requests": sum(x >= 9 for x in burst_sizes),
            "requests_in_9_request_buckets": sum(x for x in burst_sizes if x >= 9),
            "exact_256_token_prefix_groups_with_2_requests":
                sum(x >= 2 for x in prefix_groups),
            "requests_in_exact_256_token_prefix_groups_with_2":
                sum(x for x in prefix_groups if x >= 2),
            "exact_256_token_prefix_groups_with_4_requests":
                sum(x >= 4 for x in prefix_groups),
            "requests_in_exact_256_token_prefix_groups_with_4":
                sum(x for x in prefix_groups if x >= 4),
        }
    return summary


def main():
    OUTPUT.mkdir(exist_ok=True)
    for path in sorted(RAW.glob("*.jsonl")):
        summary = summarise(path)
        target = OUTPUT / (path.stem + ".json")
        target.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        print(path.name, summary["counts"], summary["arrival_buckets"], flush=True)


if __name__ == "__main__":
    main()
