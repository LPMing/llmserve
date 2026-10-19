#!/usr/bin/env python3
"""Build tiny controlled partial-hit and destination-miss correctness sessions."""

import json
from pathlib import Path


OUT = Path(__file__).resolve().parent / "workloads"


def session(name, warmup_tokens, target_tokens, warmup_prefix,
            target_prefix, target_suffix):
    warmup_ids = list(warmup_prefix[:warmup_tokens])
    target_ids = list(target_prefix[:target_tokens - target_suffix])
    target_ids += list(target_suffix_ids(target_suffix, name))
    return {
        "session_id": name,
        "arrival_time_ns": 0,
        "sub_requests": [
            {
                "input_toks": warmup_tokens,
                "output_toks": 1,
                "input_tok_ids": warmup_ids,
                "output_tok_ids": [990001],
                "tool_duration_ns": 0,
            },
            {
                "input_toks": target_tokens,
                "output_toks": 3,
                "input_tok_ids": target_ids,
                "output_tok_ids": [990002, 990003, 990004],
                "tool_duration_ns": 0,
            },
        ],
    }


def target_suffix_ids(count, name):
    seed = 800000 if name.startswith("partial") else 900000
    return range(seed, seed + count)


def write(name, payload):
    path = OUT / f"{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
    return path


def main():
    shared = list(range(1000, 1000 + 4096))
    partial_prefix = list(range(20000, 20000 + 2048))
    partial = session(
        "partial-hit-control", 2048, 4105, partial_prefix, partial_prefix,
        2057)
    # The target shares exactly the warm-up token/hash prefix. The first 2,048
    # tokens can be resident at both source and destination; the remaining
    # 2,057 tokens are genuine new prompt state.
    partial["sub_requests"][1]["input_tok_ids"] = (
        partial_prefix + list(target_suffix_ids(2057, "partial-hit-control")))
    partial["sub_requests"][1]["input_toks"] = 4105

    miss_prefix = list(range(30000, 30000 + 4096))
    miss = session(
        "destination-miss-control", 4096, 4105, miss_prefix,
        miss_prefix, 9)
    miss["sub_requests"][1]["input_tok_ids"] = (
        shared + list(target_suffix_ids(9, "destination-miss-control")))
    miss["sub_requests"][1]["input_toks"] = 4105

    print(write("partial_hit", partial))
    print(write("destination_miss", miss))


if __name__ == "__main__":
    main()
