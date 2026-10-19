#!/usr/bin/env python3
"""Summarize measured round and tool shapes in the pinned TraceLab release."""

import gzip
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "tracelab_raw/syfi_coding_trace_v0.0.2.jsonl.gz"
EXPECTED_SHA256 = "11ce51ec0a25e3d1d95b025bca2f7d1647e47571eb7cc968acd5fc64d4b4fb65"
OUTPUT = HERE / "tracelab_analysis"


def quantile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def integer(value):
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def main():
    digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError("TraceLab release checksum mismatch")
    counters = Counter()
    models = Counter()
    tools = Counter()
    sessions = Counter()
    by_provider = defaultdict(Counter)
    shape = defaultdict(list)
    with gzip.open(SOURCE, "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            counters["rounds"] += 1
            provider = row.get("provider") or "unknown"
            by_provider[provider]["rounds"] += 1
            models[row.get("model") or "unknown"] += 1
            sessions[row.get("session_id") or "unknown"] += 1
            prompt = integer(row.get("input_tokens_total"))
            prefix = integer(row.get("prefix_tokens"))
            fresh = integer(row.get("newly_append_tokens"))
            output = integer(row.get("output_tokens"))
            shape["prompt_tokens"].append(prompt)
            shape["prefix_tokens"].append(prefix)
            shape["fresh_tokens"].append(fresh)
            shape["output_tokens"].append(output)
            if prompt > 0:
                shape["prefix_fraction"].append(prefix / prompt)
            if prompt != prefix + fresh:
                counters["rounds_token_split_mismatch"] += 1
            if prompt <= 2048:
                counters["rounds_prompt_le_2048"] += 1
            if prompt >= 8192 and output <= 128:
                counters["rounds_long_context_short_output"] += 1
            if prefix >= 8192 and fresh <= 512:
                counters["rounds_large_prefix_small_append"] += 1
            for tool in row.get("tools") or []:
                name = tool.get("tool_name") or "unknown"
                tools[name] += 1
                counters["tools"] += 1
                latency = tool.get("tool_wall_latency_ms")
                if latency is not None:
                    shape["tool_wall_latency_ms"].append(integer(latency))
                if name.lower() in (
                        "task", "taskcreate", "agent", "spawn_agent",
                        "wait_agent", "close_agent"):
                    counters["subagent_related_tool_calls"] += 1
                    by_provider[provider]["subagent_related_tool_calls"] += 1
    OUTPUT.mkdir(exist_ok=True)
    result = {
        "source": "https://github.com/uw-syfi/TraceLab/releases/tag/v0.0.2",
        "license": "CC-BY-4.0",
        "source_sha256": digest,
        "counts": dict(counters),
        "providers": {key: dict(value) for key, value in by_provider.items()},
        "sessions": len(sessions),
        "session_round_count_p50_p95_p99": [
            quantile(list(sessions.values()), fraction)
            for fraction in (0.5, 0.95, 0.99)],
        "top_models": models.most_common(20),
        "top_tools": tools.most_common(30),
        "shape_p50_p95_p99": {
            name: [quantile(values, fraction)
                   for fraction in (0.5, 0.95, 0.99)]
            for name, values in shape.items()
        },
        "subagent_link_caveat": (
            "The public release has no ground-truth parent-child session "
            "link or content block IDs; tool counts cannot establish fork "
            "width, sibling prefix identity, or parent join."),
    }
    (OUTPUT / "summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
