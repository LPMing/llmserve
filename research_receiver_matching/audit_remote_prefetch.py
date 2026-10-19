#!/usr/bin/env python3
"""Screen the bundled agentic trace for real remote-KV prefetch prerequisites."""

import csv
import json
import re
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
TRACE = ROOT / "workloads/swe-bench-qwen3-30b-a3b-50-sps0.2.jsonl"
CAPACITY_LOG = HERE / "runs/post_prefill_000.log"
BLOCK_SIZE = 16
KV_BYTES_PER_TOKEN = 2 * 4 * 128 * 48 * 2
CXL_BW_BYTES_PER_S = 60_000_000_000


def cache_keys(tokens):
    parent = 0
    result = []
    for start in range(0, len(tokens) - BLOCK_SIZE + 1, BLOCK_SIZE):
        parent = hash((parent, tuple(tokens[start:start + BLOCK_SIZE])))
        result.append(parent)
    return result


def common_prefix(a, b):
    length = 0
    for left, right in zip(a, b):
        if left != right:
            break
        length += 1
    return length


def main():
    sessions = [json.loads(line) for line in TRACE.read_text().splitlines()]
    capacity_text = CAPACITY_LOG.read_text()
    match = re.search(r"Instance \[0\]\s+:\s+\d+ tokens / (\d+) blocks",
                      capacity_text)
    if match is None:
        raise RuntimeError("Cannot read the measured fixture's configured KV capacity")
    capacity_blocks = int(match.group(1))
    rows = []
    unique_by_session = []
    max_unhashed_tokens = 0
    for session in sessions:
        turns = session["sub_requests"]
        session_keys = set()
        for turn in turns:
            tokens = turn.get("input_tok_ids", []) + turn.get("output_tok_ids", [])
            session_keys.update(cache_keys(tokens))
            max_unhashed_tokens = max(
                max_unhashed_tokens,
                int(turn["input_toks"]) + int(turn["output_toks"]) - len(tokens))
        unique_by_session.append(session_keys)
        for index, (parent, child) in enumerate(zip(turns, turns[1:])):
            prefix_tokens = common_prefix(parent.get("input_tok_ids", []),
                                          child.get("input_tok_ids", []))
            full_block_tokens = prefix_tokens // BLOCK_SIZE * BLOCK_SIZE
            bytes_to_fetch = full_block_tokens * KV_BYTES_PER_TOKEN
            fetch_ns = round(bytes_to_fetch / CXL_BW_BYTES_PER_S * 1e9)
            gap_ns = int(parent.get("tool_duration_ns", 0))
            rows.append({
                "session_id": session["session_id"],
                "parent_index": index,
                "parent_tool_gap_ns": gap_ns,
                "child_input_toks": int(child["input_toks"]),
                "common_prefix_id_tokens": prefix_tokens,
                "full_block_prefix_tokens": full_block_tokens,
                "conditional_remote_kv_bytes": bytes_to_fetch,
                "conditional_cxl_fetch_ns": fetch_ns,
                "conditional_hideable_ns": min(gap_ns, fetch_ns),
                "observed_remote_miss": "NOT_OBSERVED",
            })
    unique_all = set().union(*unique_by_session)
    # The shipped token-id sidecar is shorter than the declared request shape.
    # Charge every simultaneously active session its largest missing-ID tail
    # plus one partial block, even though chained prefix hashing cannot index
    # those blocks. This is a conservative bound for the provided trace.
    max_unhashed_blocks_per_live_session = (
        (max_unhashed_tokens + BLOCK_SIZE - 1) // BLOCK_SIZE + 1)
    conservative_blocks = (sum(map(len, unique_by_session)) +
                           len(sessions) * max_unhashed_blocks_per_live_session)
    summary = {
        "sessions": len(sessions),
        "child_calls": len(rows),
        "positive_tool_gaps": sum(row["parent_tool_gap_ns"] > 0 for row in rows),
        "median_tool_gap_ms": statistics.median(
            row["parent_tool_gap_ns"] for row in rows) / 1e6,
        "median_conditional_fetch_ms": statistics.median(
            row["conditional_cxl_fetch_ns"] for row in rows) / 1e6,
        "fraction_gaps_cover_conditional_fetch": sum(
            row["parent_tool_gap_ns"] >= row["conditional_cxl_fetch_ns"]
            for row in rows) / len(rows),
        "mean_conditional_hideable_ms": statistics.mean(
            row["conditional_hideable_ns"] for row in rows) / 1e6,
        "unique_full_block_hashes_all_sessions": len(unique_all),
        "max_unhashed_tokens_per_request": max_unhashed_tokens,
        "max_unhashed_blocks_per_live_session": max_unhashed_blocks_per_live_session,
        "conservative_session_distinct_blocks_plus_live_tails": conservative_blocks,
        "configured_kv_capacity_blocks_per_tp2_instance": capacity_blocks,
        "all_session_cache_fits_one_instance": conservative_blocks < capacity_blocks,
        "remote_fetches_measured": None,
        "remote_miss_status": "NOT_MEASURED_AND_NOT_CAPACITY_FORCED",
    }
    output = HERE / "02_REMOTE_PREFETCH_CONDITIONAL.csv"
    with output.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (HERE / "02_REMOTE_PREFETCH_SUMMARY.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
