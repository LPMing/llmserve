#!/usr/bin/env python3
"""Audit exact-model SwissAI arrivals, completion, and block-prefix evidence."""

import heapq
import json
import math
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from mine_qwen_bailian import PrefixIndex, percentile


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "swissai_raw/qwen3-32b-buckets.jsonl"
OUTPUT = ROOT / "swissai_analysis/summary.json"


def timestamp_ms(value):
    if not value or value == "\\N":
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp()) * 1000 + parsed.microsecond // 1000


def partition_by_day(directory, raw=RAW):
    handles = {}
    days = Counter()
    models = Counter()
    statuses = Counter()
    differences = Counter()
    counts = Counter()
    with raw.open() as stream:
        for line in stream:
            row = json.loads(line)
            counts["source_rows"] += 1
            if timestamp_ms(row.get("created_at")) is None:
                counts["invalid_created_at"] += 1
                continue
            day = row["created_at"][:10]
            if day not in handles:
                handles[day] = (directory / (day + ".jsonl")).open("w")
            handles[day].write(line)
            days[day] += 1
            models[row.get("model")] += 1
            statuses[row.get("status")] += 1
            counts["rows"] += 1
            token_count = row.get("token_count")
            if token_count is None or token_count < 0:
                counts["invalid_token_count"] += 1
            elif len(row.get("bucket_ids") or []) != math.ceil(token_count / 16):
                counts["bucket_length_mismatch"] += 1
            reported = row.get("reported_token_input", -1)
            if reported is None or reported < 0:
                counts["missing_reported_input"] += 1
            elif token_count is not None and token_count >= 0:
                delta = reported - token_count
                differences[str(delta) if -16 <= delta <= 16 else "outside_±16"] += 1
    for handle in handles.values():
        handle.close()
    return days, models, statuses, differences, counts


def analyze(directory, initial):
    days, models, statuses, differences, counts = initial
    next_event_id = 0
    input_lengths = []
    output_lengths = []
    durations = []
    completed_prefix_tokens = []
    completed_prefix_ratios = []
    arrival_200ms_sizes = []
    arrival_1s_sizes = []
    burst = Counter()
    maximum_1s_arriving_output_tokens = 0
    maximum_1s_arriving_input_tokens = 0
    maximum_200ms_arriving_input_tokens = 0
    maximum_60s_arriving_output_tokens = 0
    maximum_300s_arriving_output_tokens = 0
    total_trie_nodes = 0
    maximum_daily_trie_nodes = 0
    per_day = {}
    first_ms = None
    last_ms = None
    for day in sorted(days):
        index = PrefixIndex()
        pending = []
        arrival_200ms = Counter()
        arrival_1s = Counter()
        arrival_200ms_input = Counter()
        arrival_1s_input = Counter()
        arrival_1s_output = Counter()
        arrival_60s_output = Counter()
        arrival_300s_output = Counter()
        same_prefix_200ms = Counter()
        same_2048_prefix_200ms = Counter()
        daily_rows = []
        with (directory / (day + ".jsonl")).open() as handle:
            for line in handle:
                row = json.loads(line)
                created_ms = timestamp_ms(row["created_at"])
                finished_ms = timestamp_ms(row.get("finished_at"))
                daily_rows.append((created_ms, finished_ms,
                                   row.get("reported_token_input", -1),
                                   row.get("reported_token_output", -1),
                                   row.get("token_count", -1),
                                   tuple(row.get("bucket_ids") or ())))
        daily_rows.sort(key=lambda x: x[0])
        daily = Counter()
        for created_ms, finished_ms, reported_input, reported_output, token_count, sequence in daily_rows:
            first_ms = created_ms if first_ms is None else min(first_ms, created_ms)
            last_ms = created_ms if last_ms is None else max(last_ms, created_ms)
            while pending and pending[0][0] < created_ms:
                finish_time, _, completed_sequence = heapq.heappop(pending)
                index.observe(completed_sequence, finish_time)
            if token_count < 0 or len(sequence) != math.ceil(token_count / 16):
                daily["invalid_bucket_rows"] += 1
                continue
            effective_input = reported_input if reported_input >= 0 else token_count
            input_lengths.append(effective_input)
            counts["effective_input_tokens"] += effective_input
            if reported_output is not None and reported_output >= 0:
                output_lengths.append(reported_output)
                counts["reported_output_tokens"] += reported_output
                counts["valid_reported_output_rows"] += 1
            if token_count <= 16384:
                daily["input_within_profile_16k"] += 1
            depth, completed_time = index.match(sequence)
            matched_tokens = min(depth * 16, (token_count // 16) * 16)
            completed_prefix_tokens.append(matched_tokens)
            ratio = matched_tokens / token_count if token_count else 0.0
            completed_prefix_ratios.append(ratio)
            daily["completed_input_prefix_tokens"] += matched_tokens
            daily["input_tokens"] += token_count
            if ratio >= 0.8833:
                daily["requests_with_completed_prefix_88pct"] += 1
                if token_count <= 16384:
                    daily["profile_16k_completed_prefix_88pct"] += 1
            if matched_tokens >= 2048:
                daily["requests_with_completed_prefix_2048"] += 1
            if completed_time is not None and matched_tokens:
                if created_ms - completed_time <= 1000:
                    daily["completed_prefix_within_1s"] += 1
            bucket_200 = created_ms // 200
            arrival_200ms[bucket_200] += 1
            arrival_200ms_input[bucket_200] += token_count
            bucket_1s = created_ms // 1000
            arrival_1s[bucket_1s] += 1
            arrival_1s_input[bucket_1s] += token_count
            if reported_output is not None and reported_output >= 0:
                arrival_1s_output[bucket_1s] += reported_output
                arrival_60s_output[created_ms // 60000] += reported_output
                arrival_300s_output[created_ms // 300000] += reported_output
            if len(sequence) >= 16:
                same_prefix_200ms[bucket_200, sequence[:16]] += 1
            if len(sequence) >= 128:
                same_2048_prefix_200ms[bucket_200, sequence[:128]] += 1
            if finished_ms is not None and finished_ms >= created_ms:
                durations.append(finished_ms - created_ms)
                counts["total_completion_ms"] += finished_ms - created_ms
                next_event_id += 1
                heapq.heappush(pending, (finished_ms, next_event_id, sequence))
                daily["valid_completion"] += 1
            elif finished_ms is not None:
                daily["negative_completion_duration"] += 1
            else:
                daily["missing_completion"] += 1
            daily["valid_bucket_rows"] += 1
        daily["peak_arrivals_1s"] = max(arrival_1s.values(), default=0)
        daily["peak_arrivals_200ms"] = max(arrival_200ms.values(), default=0)
        daily["peak_arriving_output_tokens_60s"] = max(
            arrival_60s_output.values(), default=0)
        per_day[day] = dict(daily)
        arrival_200ms_sizes.extend(arrival_200ms.values())
        arrival_1s_sizes.extend(arrival_1s.values())
        burst["buckets_200ms_with_9_requests"] += sum(
            x >= 9 for x in arrival_200ms.values())
        burst["requests_in_200ms_9_request_buckets"] += sum(
            x for x in arrival_200ms.values() if x >= 9)
        burst["buckets_1s_with_9_requests"] += sum(
            x >= 9 for x in arrival_1s.values())
        burst["requests_in_1s_9_request_buckets"] += sum(
            x for x in arrival_1s.values() if x >= 9)
        burst["same_256_token_prefix_groups_200ms_with_4_requests"] += sum(
            x >= 4 for x in same_prefix_200ms.values())
        burst["requests_in_same_256_token_prefix_groups_200ms_with_4"] += sum(
            x for x in same_prefix_200ms.values() if x >= 4)
        burst["same_2048_token_prefix_groups_200ms_with_2_requests"] += sum(
            x >= 2 for x in same_2048_prefix_200ms.values())
        burst["requests_in_same_2048_token_prefix_groups_200ms_with_2"] += sum(
            x for x in same_2048_prefix_200ms.values() if x >= 2)
        burst["same_2048_token_prefix_groups_200ms_with_4_requests"] += sum(
            x >= 4 for x in same_2048_prefix_200ms.values())
        burst["requests_in_same_2048_token_prefix_groups_200ms_with_4"] += sum(
            x for x in same_2048_prefix_200ms.values() if x >= 4)
        maximum_daily_trie_nodes = max(maximum_daily_trie_nodes, index.nodes)
        total_trie_nodes += index.nodes
        maximum_1s_arriving_output_tokens = max(
            maximum_1s_arriving_output_tokens,
            max(arrival_1s_output.values(), default=0))
        maximum_1s_arriving_input_tokens = max(
            maximum_1s_arriving_input_tokens,
            max(arrival_1s_input.values(), default=0))
        maximum_200ms_arriving_input_tokens = max(
            maximum_200ms_arriving_input_tokens,
            max(arrival_200ms_input.values(), default=0))
        maximum_60s_arriving_output_tokens = max(
            maximum_60s_arriving_output_tokens,
            max(arrival_60s_output.values(), default=0))
        maximum_300s_arriving_output_tokens = max(
            maximum_300s_arriving_output_tokens,
            max(arrival_300s_output.values(), default=0))
        del daily_rows
    count = counts["rows"]
    peak_200ms = max(arrival_200ms_sizes, default=0)
    return {
        "source": "eth-easl/swissai-serving-trace/qwen3-32b-buckets.jsonl",
        "source_revision": "c3dd66602b564ce189f7db81115620413e646cd5",
        "counts": dict(counts),
        "model_counts": dict(models),
        "status_counts": dict(statuses),
        "reported_input_minus_retained_token_count": dict(differences),
        "first_created_at_ms_utc": first_ms,
        "last_created_at_ms_utc": last_ms,
        "days": len(days),
        "daily_request_counts_top_10": days.most_common(10),
        "input_tokens_p50_p95_p99": [percentile(input_lengths, x) for x in (.5, .95, .99)],
        "output_tokens_p50_p95_p99": [percentile(output_lengths, x) for x in (.5, .95, .99)],
        "completion_ms_p50_p95_p99": [percentile(durations, x) for x in (.5, .95, .99)],
        "same_day_completed_input_prefix_tokens_p50_p95_p99":
            [percentile(completed_prefix_tokens, x) for x in (.5, .95, .99)],
        "same_day_completed_input_prefix_ratio_p50_p95_p99":
            [percentile(completed_prefix_ratios, x) for x in (.5, .95, .99)],
        "maximum_daily_compressed_trie_nodes": maximum_daily_trie_nodes,
        "sum_daily_compressed_trie_nodes": total_trie_nodes,
        "mean_rps_over_observed_span": count / ((last_ms - first_ms) / 1000),
        "arrival_200ms": {
            "nonempty_buckets": len(arrival_200ms_sizes),
            "peak_requests": peak_200ms,
            "peak_arriving_input_tokens": maximum_200ms_arriving_input_tokens,
            "requests_per_nonempty_bucket_p50_p95_p99":
                [percentile(arrival_200ms_sizes, x) for x in (.5, .95, .99)],
            "buckets_with_9_requests": burst["buckets_200ms_with_9_requests"],
            "requests_in_9_request_buckets": burst["requests_in_200ms_9_request_buckets"],
            "same_256_token_prefix_groups_with_4_requests":
                burst["same_256_token_prefix_groups_200ms_with_4_requests"],
            "requests_in_same_256_token_prefix_groups_with_4":
                burst["requests_in_same_256_token_prefix_groups_200ms_with_4"],
            "same_2048_token_prefix_groups_with_2_requests":
                burst["same_2048_token_prefix_groups_200ms_with_2_requests"],
            "requests_in_same_2048_token_prefix_groups_with_2":
                burst["requests_in_same_2048_token_prefix_groups_200ms_with_2"],
            "same_2048_token_prefix_groups_with_4_requests":
                burst["same_2048_token_prefix_groups_200ms_with_4_requests"],
            "requests_in_same_2048_token_prefix_groups_with_4":
                burst["requests_in_same_2048_token_prefix_groups_200ms_with_4"],
        },
        "arrival_1s": {
            "nonempty_buckets": len(arrival_1s_sizes),
            "peak_requests": max(arrival_1s_sizes, default=0),
            "peak_arriving_input_tokens": maximum_1s_arriving_input_tokens,
            "peak_arriving_output_tokens": maximum_1s_arriving_output_tokens,
            "buckets_with_9_requests": burst["buckets_1s_with_9_requests"],
            "requests_in_9_request_buckets":
                burst["requests_in_1s_9_request_buckets"],
        },
        "peak_arriving_output_tokens_60s": maximum_60s_arriving_output_tokens,
        "peak_arriving_output_tokens_300s": maximum_300s_arriving_output_tokens,
        "per_day": per_day,
        "interpretation": (
            "Only full input blocks shared with a request completed earlier "
            "in the same UTC day "
            "are counted. This is not realized cache residency, P/D transfer, "
            "or client TTFT. Generated-output prefixes are unavailable."
        ),
    }


def main():
    OUTPUT.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="swissai_trace_") as dirname:
        directory = Path(dirname)
        initial = partition_by_day(directory)
        print("partitioned", initial[-1], "days", len(initial[0]), flush=True)
        summary = analyze(directory, initial)
    OUTPUT.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    compact = {k: v for k, v in summary.items() if k != "per_day"}
    print(json.dumps(compact, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
