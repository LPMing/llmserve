#!/usr/bin/env python3
"""Bound prior-prefix reuse in the committed ordered ShareGPT workload."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
WORKLOADS = (
    "sharegpt-llama-3.1-8b-300-sps10.jsonl",
    "sharegpt-qwen3-30b-a3b-300-sps10.jsonl",
    "sharegpt-qwen3-32b-300-sps10.jsonl",
)
BLOCK_SIZE = 16


def derive(path):
    requests = [json.loads(line) for line in path.open()]
    prior = {}
    prompt_tokens = 0
    max_prior_reuse_tokens = 0
    requests_with_reuse = 0
    for request in requests:
        tokens = request["input_tok_ids"]
        prompt_tokens += len(tokens)
        key = tuple(tokens[:BLOCK_SIZE])
        best = 0
        for old in prior.get(key, ()):
            length = 0
            for lhs, rhs in zip(tokens, old):
                if lhs != rhs:
                    break
                length += 1
            best = max(best, length // BLOCK_SIZE * BLOCK_SIZE)
        max_prior_reuse_tokens += best
        requests_with_reuse += bool(best)
        prior.setdefault(key, []).append(tokens)
    return {
        "workload": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "requests": len(requests),
        "block_size": BLOCK_SIZE,
        "prompt_tokens": prompt_tokens,
        "max_prior_reuse_tokens": max_prior_reuse_tokens,
        "max_prior_reuse_fraction": max_prior_reuse_tokens / prompt_tokens,
        "requests_with_any_prior_reuse": requests_with_reuse,
        "assumption": "Every prior prefix remains resident on the chosen Decode; ignores finite capacity and routing, so this is an optimistic byte-reuse ceiling.",
    }


if __name__ == "__main__":
    print(json.dumps([
        derive(ROOT / "workloads" / name) for name in WORKLOADS
    ], indent=2, sort_keys=True))
